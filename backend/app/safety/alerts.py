"""Real-time admin alerts for crisis and abuse turns.

Posts a minimal, privacy-preserving notice (no message text; a link to the
admin crisis queue) to ``ADMIN_ALERT_WEBHOOK_URL``. Awaited with a short
timeout inside the request so serverless runtimes don't drop it.
"""

import logging

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


async def send_admin_alert(kind: str, flags: list[str], conversation_id: str | None, is_guest: bool) -> bool:
    settings = get_settings()
    url = settings.admin_alert_webhook_url
    if not url:
        return False
    who = "guest visitor" if is_guest else "signed-in user"
    text = (
        f":rotating_light: rebbe.dev {kind} turn ({who}). Flags: {', '.join(flags) or 'none'}. "
        f"Review: {settings.public_base_url}/admin#flagged"
        + (f" (conversation {conversation_id})" if conversation_id else "")
    )
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.post(url, json={"text": text, "content": text})
            return r.status_code < 400
    except Exception as e:
        logger.warning("Admin alert failed: %s", e)
        return False
