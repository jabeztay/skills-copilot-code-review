"""
Announcements management endpoints
"""

from fastapi import APIRouter, HTTPException, Query, Form, Depends
from typing import Optional, Dict, Any
from datetime import datetime

from ..database import announcements_collection, teachers_collection
from .auth import get_current_user

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


def _is_authenticated_teacher(username: Optional[str]) -> bool:
    # keep for compatibility with other code paths that may still call it directly
    if not username:
        return False
    teacher = teachers_collection.find_one({"_id": username})
    return teacher is not None


@router.get("/active", response_model=Dict[str, Any])
def get_active_announcements() -> Dict[str, Any]:
    """Return announcements that are currently active (start_date <= now < expires_at)"""
    now = datetime.utcnow()
    query = {
        "$and": [
            {
                "$or": [
                    {"start_date": {"$eq": None}},
                    {"start_date": {"$lte": now}}
                ]
            },
            {"expires_at": {"$gt": now}}
        ]
    }

    anns = []
    for a in announcements_collection.find(query).sort([("expires_at", 1)]):
        ann = {
            "id": str(a.get("_id")),
            "message": a.get("message"),
            "start_date": a.get("start_date").isoformat() if a.get("start_date") else None,
            "expires_at": a.get("expires_at").isoformat() if a.get("expires_at") else None,
        }
        anns.append(ann)

    return {"announcements": anns}


@router.get("", response_model=Dict[str, Any])
def list_announcements(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """List all announcements (management view). Requires authentication via dependency."""

    anns = []
    for a in announcements_collection.find().sort([("expires_at", 1)]):
        a["id"] = str(a.get("_id"))
        a.pop("_id", None)
        if a.get("start_date"):
            a["start_date"] = a["start_date"].isoformat()
        if a.get("expires_at"):
            a["expires_at"] = a["expires_at"].isoformat()
        if a.get("created_at"):
            a["created_at"] = a["created_at"].isoformat()
        anns.append(a)

    return {"announcements": anns}


@router.post("/create")
def create_announcement(
    message: str = Form(...),
    expires_at: str = Form(...),
    start_date: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a new announcement. expires_at required (ISO format)."""
    # current_user was already validated by the dependency

    try:
        exp = datetime.fromisoformat(expires_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid expires_at format; use ISO datetime")

    if start_date:
        try:
            start = datetime.fromisoformat(start_date)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid start_date format; use ISO datetime")
    else:
        start = None

    doc = {
        "message": message,
        "start_date": start,
        "expires_at": exp,
    "created_by": current_user["username"],
        "created_at": datetime.utcnow()
    }

    result = announcements_collection.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "Announcement created"}


@router.post("/update/{announcement_id}")
def update_announcement(
    announcement_id: str,
    message: Optional[str] = Form(None),
    expires_at: Optional[str] = Form(None),
    start_date: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update an existing announcement by id. Authentication is handled by dependency."""

    from bson import ObjectId

    try:
        _id = ObjectId(announcement_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid announcement id")

    update = {}
    if message is not None:
        update["message"] = message
    if expires_at is not None:
        try:
            update["expires_at"] = datetime.fromisoformat(expires_at)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid expires_at format")
    if start_date is not None:
        if start_date == "":
            update["start_date"] = None
        else:
            try:
                update["start_date"] = datetime.fromisoformat(start_date)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid start_date format")

    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = announcements_collection.update_one({"_id": _id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement updated"}


@router.delete("/{announcement_id}")
def delete_announcement(announcement_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Delete an announcement by id. Authentication via dependency."""

    from bson import ObjectId

    try:
        _id = ObjectId(announcement_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid announcement id")

    result = announcements_collection.delete_one({"_id": _id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}


# Some clients (the frontend) POST to /announcements/delete/{id} using form-encoded requests.
# Provide a POST wrapper that calls the same logic so both DELETE and POST are supported.
@router.post("/delete/{announcement_id}")
def delete_announcement_post(announcement_id: str, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Delete an announcement by id (POST wrapper for form clients)."""
    return delete_announcement(announcement_id, current_user)
