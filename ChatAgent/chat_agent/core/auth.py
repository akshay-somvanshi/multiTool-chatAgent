from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import firebase_admin
from firebase_admin import auth, credentials
import os

try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()

security = HTTPBearer()

async def get_user_id(res: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    FastAPI dependency to verify a Firebase ID token.
    Extracts the 'Authorization: Bearer <token>' header and returns the 'uid'.
    """
    token = res.credentials
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token["uid"]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )