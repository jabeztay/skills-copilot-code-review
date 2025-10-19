"""
Authentication endpoints for the High School Management System API
"""

from fastapi import APIRouter, HTTPException, Header, Query, Depends
from typing import Dict, Any, Optional
import secrets
from datetime import datetime

from ..database import teachers_collection, verify_password

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

# Simple in-memory session store: token -> {username, created_at}
# NOTE: This is intentionally minimal for the sample app. For production use a persistent store.
_sessions: Dict[str, Dict[str, Any]] = {}


def _create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"username": username, "created_at": datetime.utcnow()}
    return token


def get_current_user(authorization: Optional[str] = Header(None), username: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Resolve current teacher from Authorization header (Bearer token) or fallback to username query (legacy).

    Prefer token-based lookup. Raises 401 if not authenticated.
    """
    resolved_username = None

    # Authorization: Bearer <token>
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        sess = _sessions.get(token)
        if not sess:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        resolved_username = sess["username"]
    elif username:
        # Legacy fallback (still supported for compatibility)
        resolved_username = username
    else:
        raise HTTPException(status_code=401, detail="Authentication required")

    teacher = teachers_collection.find_one({"_id": resolved_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return {"username": teacher["username"], "display_name": teacher["display_name"], "role": teacher["role"]}


@router.post("/login")
def login(username: str, password: str) -> Dict[str, Any]:
    """Login a teacher account and return a session token"""
    teacher = teachers_collection.find_one({"_id": username})

    if not teacher or not verify_password(teacher.get("password", ""), password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = _create_session(username)

    return {
        "username": teacher["username"],
        "display_name": teacher["display_name"],
        "role": teacher["role"],
        "token": token,
    }


@router.get("/check-session")
def check_session(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Check if a session is valid (resolved via token or legacy username query)"""
    return current_user
