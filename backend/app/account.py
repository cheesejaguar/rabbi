"""Account self-service: data export and account deletion."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from . import database as db
from .auth import get_current_user
from .config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/account", tags=["account"])


class DeleteAccountRequest(BaseModel):
    confirm: str


def _require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not get_settings().db_url:
        raise HTTPException(status_code=503, detail="Database not configured")
    return user


@router.get("/export")
async def export_account(request: Request):
    user = _require_user(request)
    data = await db.export_user_data(user["id"])
    data["exported_at"] = datetime.now(timezone.utc).isoformat()
    body = json.dumps(data, default=str, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="rebbe-dev-export.json"'},
    )


@router.delete("")
async def delete_account(request: Request, body: DeleteAccountRequest):
    user = _require_user(request)
    if body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail='Type "DELETE" to confirm.')
    deleted = await db.delete_user_account(user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")
    logger.info("Account deleted by user request")
    response = JSONResponse({"deleted": True})
    response.delete_cookie("session", path="/")
    return response
