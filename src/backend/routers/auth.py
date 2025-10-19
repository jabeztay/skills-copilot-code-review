"""
Authentication endpoints for the High School Management System API
"""

from fastapi import APIRouter, HTTPException, Header, Query, Depends, Form
from typing import Dict, Any, Optional
import secrets
from datetime import datetime, timedelta

from ..database import teachers_collection, verify_password

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

# Simple in-memory session store: token -> {username, created_at}
# NOTE: This is intentionally minimal for the sample app. For production use a persistent store.
_sessions: Dict[str, Dict[str, Any]] = {}

# Session configuration
SESSION_TTL_SECONDS = 24 * 3600  # sessions valid for 24 hours

# Basic login rate-limiting (per username)
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 5 * 60  # 5 minutes

# Track failed login attempts: username -> {count:int, first_failure: datetime}
_login_attempts: Dict[str, Dict[str, Any]] = {}


def _create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(seconds=SESSION_TTL_SECONDS),
    }
    return token


def _revoke_sessions_for_username(username: str) -> None:
    # remove any existing sessions for a username (simple rotation / single-session policy)
    for t, sess in list(_sessions.items()):
        if sess.get("username") == username:
            del _sessions[t]


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
        # enforce expiration
        expires_at = sess.get("expires_at")
        if expires_at and datetime.utcnow() > expires_at:
            # session expired; remove it
            del _sessions[token]
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
def login(username: str = Form(...), password: str = Form(...)) -> Dict[str, Any]:
    """Login a teacher account and return a session token. Accepts form-encoded data."""
    # rate-limiting / lockout per username
    attempts = _login_attempts.get(username)
    now = datetime.utcnow()
    if attempts:
        # reset window
        if (now - attempts["first_failure"]).total_seconds() > LOCKOUT_WINDOW_SECONDS:
            attempts = None
            _login_attempts.pop(username, None)
    if attempts and attempts["count"] >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")

    teacher = teachers_collection.find_one({"_id": username})

    if not teacher or not verify_password(teacher.get("password", ""), password):
        # record failed attempt
        if not attempts:
            _login_attempts[username] = {"count": 1, "first_failure": now}
        else:
            attempts["count"] += 1
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # successful login: clear any failed attempts
    _login_attempts.pop(username, None)

    # rotate sessions (revoke old tokens) — simple single-session policy
    _revoke_sessions_for_username(username)

    token = _create_session(username)

    return {
        "username": teacher["username"],
        "display_name": teacher["display_name"],
        "role": teacher["role"],
        "token": token,
        "expires_at": _sessions[token]["expires_at"].isoformat() + "Z",
    }


@router.post('/logout')
def logout(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Logout and revoke the current session token (Authorization: Bearer <token>)"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    token = authorization.split(" ", 1)[1]
    if token in _sessions:
        del _sessions[token]
    return {"message": "Logged out"}


@router.get("/check-session")
def check_session(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Check if a session is valid (resolved via token or legacy username query)"""
    return current_user
