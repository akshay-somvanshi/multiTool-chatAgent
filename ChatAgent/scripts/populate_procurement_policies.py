"""
Populates the BigQuery `procurement_policies` table with industry-specific procurement
policies sourced from Google Search results and extracted via Gemini.

Usage:
    python populate_procurement_policies.py [--industries "Retail,Manufacturing"] [--dry-run]

Run once per industry (or re-run to refresh). The script is idempotent: it upserts by
(industry, policy_name) so re-running won't create duplicates.
"""

import argparse
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

import dotenv
import requests
from google import genai
from google.cloud import bigquery
from google.genai.types import GenerateContentConfig

dotenv.load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "dash-beta-e61d0")
DATASET_ID = "dash_beta_database"
TABLE_ID = "procurement_policies"
GEMINI_MODEL = "gemini-3.1-pro-preview"
GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_SEARCH_CX = os.getenv("GOOGLE_CSE_ID")

DEFAULT_INDUSTRIES = [
    "Retail",
    "Manufacturing",
    "Construction",
    "Financial Services",
    "Healthcare",
    "Technology",
    "Food & Beverage",
    "Logistics & Transport",
    "Energy & Utilities",
    "Professional Services",
]

POLICY_SCHEMA = [
    bigquery.SchemaField("policy_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("industry", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("policy_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("policy_source", "STRING"),
    bigquery.SchemaField("policy_description", "STRING"),
    bigquery.SchemaField("category", "STRING"),
    bigquery.SchemaField("last_updated", "TIMESTAMP"),
]


def ensure_table(bq_client: bigquery.Client) -> None:
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    try:
        bq_client.get_table(table_ref)
        print(f"Table {table_ref} already exists.")
    except Exception:
        table = bigquery.Table(table_ref, schema=POLICY_SCHEMA)
        bq_client.create_table(table)
        print(f"Created table {table_ref}.")


def search_policy_sources(industry: str) -> list[dict]:
    """Return a list of {title, snippet, url} from Google Search for procurement policies."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_CX:
        print(f"  [search] No Google Search credentials — skipping web search for {industry}")
        return []

    queries = [
        f"{industry} industry procurement sustainability requirements UK",
        f"{industry} supplier sustainability procurement policy criteria",
    ]
    results = []
    for q in queries:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": GOOGLE_SEARCH_API_KEY, "cx": GOOGLE_SEARCH_CX, "q": q, "num": 5},
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "url": item.get("link", ""),
                })
        except Exception as e:
            print(f"  [search] Query failed ({q!r}): {e}")
        time.sleep(0.5)
    return results


def extract_policies_with_llm(
    industry: str,
    search_results: list[dict],
    gemini_client: genai.Client,
) -> list[dict]:
    """Use Gemini to extract structured procurement policy criteria."""
    search_context = ""
    if search_results:
        snippets = "\n".join(
            f"- [{r['title']}] ({r['url']}): {r['snippet']}" for r in search_results[:8]
        )
        search_context = f"\nWeb search results to ground your response:\n{snippets}\n"

    prompt = f"""You are an expert in sustainability procurement standards.

Generate a comprehensive list of procurement policy requirements for the {industry} industry.
These are the criteria that large buyers and public sector organisations use when evaluating
supplier sustainability performance.{search_context}

For each policy, provide:
- policy_name: short name (e.g. "Carbon Reduction Target")
- policy_description: 1-2 sentence description of the requirement
- category: one of [environmental, social, governance, supply_chain, reporting, certification]
- policy_source: the standard, framework, or regulation it comes from (e.g. "ISO 14001", "PPN 06/21", "CDP")

Return 15-25 distinct, specific policies that are realistically used in {industry} procurement.

Return ONLY a valid JSON object:
{{
  "policies": [
    {{
      "policy_name": "...",
      "policy_description": "...",
      "category": "...",
      "policy_source": "..."
    }}
  ]
}}"""

    for attempt in range(3):
        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GenerateContentConfig(response_mime_type="application/json"),
            )
            data = json.loads(response.text)
            return data.get("policies", [])
        except Exception as e:
            print(f"  [llm] Attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                return []
            time.sleep(2 ** attempt)
    return []


def get_existing_policy_names(bq_client: bigquery.Client, industry: str) -> set[str]:
    query = f"""
        SELECT LOWER(policy_name) as pname
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE LOWER(industry) = @industry
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("industry", "STRING", industry.lower())]
    )
    try:
        results = bq_client.query(query, job_config=job_config).result()
        return {row.pname for row in results}
    except Exception:
        return set()


def insert_policies(
    bq_client: bigquery.Client,
    industry: str,
    policies: list[dict],
    dry_run: bool,
) -> int:
    existing = get_existing_policy_names(bq_client, industry)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for p in policies:
        name = p.get("policy_name", "").strip()
        if not name or name.lower() in existing:
            continue
        rows.append({
            "policy_id": str(uuid.uuid4()),
            "industry": industry,
            "policy_name": name,
            "policy_source": p.get("policy_source", ""),
            "policy_description": p.get("policy_description", ""),
            "category": p.get("category", ""),
            "last_updated": now,
        })

    if not rows:
        print(f"  No new policies to insert for {industry} (all already present).")
        return 0

    if dry_run:
        print(f"  [dry-run] Would insert {len(rows)} policies for {industry}:")
        for r in rows:
            print(f"    - [{r['category']}] {r['policy_name']}")
        return len(rows)

    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    errors = bq_client.insert_rows_json(bq_client.get_table(table_ref), rows)
    if errors:
        print(f"  BigQuery insert errors for {industry}: {errors}")
        return 0

    print(f"  Inserted {len(rows)} new policies for {industry}.")
    return len(rows)


def populate_industry(
    industry: str,
    bq_client: bigquery.Client,
    gemini_client: genai.Client,
    dry_run: bool,
) -> None:
    print(f"\nProcessing: {industry}")
    search_results = search_policy_sources(industry)
    print(f"  Found {len(search_results)} search results.")
    policies = extract_policies_with_llm(industry, search_results, gemini_client)
    print(f"  Extracted {len(policies)} policies from LLM.")
    insert_policies(bq_client, industry, policies, dry_run)


def main():
    parser = argparse.ArgumentParser(description="Populate procurement_policies BigQuery table.")
    parser.add_argument(
        "--industries",
        type=str,
        default=None,
        help="Comma-separated list of industries (default: all default industries)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be inserted without writing to BigQuery",
    )
    args = parser.parse_args()

    industries = (
        [i.strip() for i in args.industries.split(",")]
        if args.industries
        else DEFAULT_INDUSTRIES
    )

    bq_client = bigquery.Client(project=PROJECT_ID)
    gemini_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")

    if not args.dry_run:
        ensure_table(bq_client)

    total_inserted = 0
    for industry in industries:
        populate_industry(industry, bq_client, gemini_client, args.dry_run)

    print(f"\nDone. Total policies inserted: {total_inserted}")


if __name__ == "__main__":
    main()
