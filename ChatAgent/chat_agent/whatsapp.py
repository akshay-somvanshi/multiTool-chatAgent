"""WhatsApp Cloud API channel for the Dash agent.

Phase 2 (this file currently): INBOUND webhook only.
- GET  /webhook/whatsapp  -> Meta verification challenge (hub.challenge).
- POST /webhook/whatsapp  -> verify X-Hub-Signature-256 on the RAW body, guard
  status callbacks, de-dup on wamid, schedule a background task, return 200 fast.

The background handler currently parses + logs the inbound message. Phases 3-5
fill in: outbound send, identity (phone -> user_id) lookup, the agent call
(classifier.ainvoke(..., text_only=True)), and media/document download.

Config via env vars (Phase 6 will move these to Google Secret Manager):
  WA_VERIFY_TOKEN     - token you choose; must match the webhook config in Meta.
  WA_APP_SECRET       - Meta App secret; used for X-Hub-Signature-256 HMAC.
  WA_ACCESS_TOKEN     - long-lived System User token (used for sending, Phase 3).
  WA_PHONE_NUMBER_ID  - the WhatsApp phone number id (used for sending, Phase 3).
  WA_GRAPH_VERSION    - Graph API version (default v21.0).
"""

import os
import json
import hmac
import hashlib
from collections import deque

from fastapi import APIRouter, Request, Response, BackgroundTasks, HTTPException

# --- Config -----------------------------------------------------------------
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN")
WA_APP_SECRET = os.getenv("WA_APP_SECRET")
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID")
WA_GRAPH_VERSION = os.getenv("WA_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{WA_GRAPH_VERSION}"

router = APIRouter()

# --- Classifier injection (set from app.py after the singleton is built) -----
# Avoids a circular import (app.py imports this module; this module must not
# import app.py). Used by the background handler from Phase 3 onwards.
_classifier = None


def set_classifier(classifier) -> None:
    """Wire the shared classifier singleton into this module (called by app.py)."""
    global _classifier
    _classifier = classifier


# --- In-memory wamid de-dup -------------------------------------------------
# Meta retries the same message (same wamid) for up to 7 days on a slow/failed
# webhook. We must not double-process. NOTE: this is per-instance and best-effort
# only — Cloud Run scales to N instances, so Phase 3+ should move to a durable
# store (Redis) keyed on wamid for true idempotency.
_SEEN_MAX = 2000
_seen_wamids: set = set()
_seen_order: deque = deque()


def _already_processed(wamid: str) -> bool:
    """Return True if this wamid was already seen; otherwise record and return False."""
    if not wamid:
        return False
    if wamid in _seen_wamids:
        return True
    _seen_wamids.add(wamid)
    _seen_order.append(wamid)
    if len(_seen_order) > _SEEN_MAX:
        evicted = _seen_order.popleft()
        _seen_wamids.discard(evicted)
    return False


# --- Signature verification -------------------------------------------------
def _verify_signature(raw_body: bytes, header: str) -> bool:
    """Verify Meta's X-Hub-Signature-256 over the RAW request body.

    Must run on the raw bytes before any JSON parse/re-serialize (re-serializing
    changes the bytes and breaks the HMAC). Constant-time compare to avoid leaks.
    """
    if not WA_APP_SECRET:
        # Dev affordance: no secret configured -> cannot verify. Allow but warn
        # loudly. In production WA_APP_SECRET MUST be set so this never triggers.
        print("[WhatsApp] WARNING: WA_APP_SECRET not set — skipping signature "
              "verification (DEV ONLY; set it before production).", flush=True)
        return True
    if not header:
        return False
    expected = "sha256=" + hmac.new(WA_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


# --- Inbound payload parsing ------------------------------------------------
def _iter_messages(data: dict):
    """Yield (message, contact) tuples from a webhook payload.

    Skips status callbacks (delivered/read/sent) and any non-message events —
    those reuse the same envelope but have no `value.messages`.
    """
    if data.get("object") != "whatsapp_business_account":
        return
    for entry in data.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            messages = value.get("messages")
            if not messages:
                if value.get("statuses"):
                    print(f"[WhatsApp] Status callback ({len(value['statuses'])}) — ignored", flush=True)
                continue
            contacts = value.get("contacts", []) or []
            contact = contacts[0] if contacts else {}
            for msg in messages:
                yield msg, contact


# --- Routes -----------------------------------------------------------------
@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    """Meta webhook verification handshake (GET)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token and token == WA_VERIFY_TOKEN:
        print("[WhatsApp] Webhook verification OK", flush=True)
        # Must echo the raw challenge as text/plain.
        return Response(content=challenge or "", media_type="text/plain")

    print(f"[WhatsApp] Webhook verification FAILED (mode={mode}, token_match={token == WA_VERIFY_TOKEN})", flush=True)
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhook/whatsapp")
async def inbound_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive inbound WhatsApp messages. Acknowledge fast (200); process async."""
    raw_body = await request.body()

    if not _verify_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        print("[WhatsApp] Invalid X-Hub-Signature-256 — rejecting", flush=True)
        raise HTTPException(status_code=403, detail="invalid signature")

    try:
        data = json.loads(raw_body)
    except Exception:
        # Not JSON — ack so Meta doesn't retry.
        return Response(status_code=200)

    for msg, contact in _iter_messages(data):
        wamid = msg.get("id")
        if _already_processed(wamid):
            print(f"[WhatsApp] Duplicate message {wamid} — skipping", flush=True)
            continue
        background_tasks.add_task(handle_message, msg, contact)

    # Always 200 quickly; the agent reply (Phase 3) is sent out-of-band.
    return Response(status_code=200)


# --- Background message handler ---------------------------------------------
async def handle_message(msg: dict, contact: dict) -> None:
    """Process one inbound message off the request path.

    Phase 2: parse + log. Phase 3 adds: mark-read+typing, identity lookup,
    classifier.ainvoke(text, user_id, text_only=True), and send_text reply.
    Phase 5 adds document/media download.
    """
    sender = msg.get("from")
    msg_type = msg.get("type")
    profile_name = ((contact.get("profile") or {}).get("name")) if contact else None
    print(f"[WhatsApp] Inbound from {sender} ({profile_name!r}) type={msg_type} wamid={msg.get('id')}", flush=True)

    if msg_type == "text":
        text = (msg.get("text") or {}).get("body", "")
        print(f"[WhatsApp] Text body: {text!r}", flush=True)
        # TODO Phase 3+4: identity lookup -> classifier.ainvoke(text, user_id,
        #                 text_only=True) -> send_text(sender, reply)
    elif msg_type in ("document", "image"):
        print(f"[WhatsApp] Media message (type={msg_type}) — download deferred to Phase 5", flush=True)
        # TODO Phase 5: resolve media id -> download -> stage to GCS -> agent
    else:
        print(f"[WhatsApp] Unsupported message type: {msg_type}", flush=True)
