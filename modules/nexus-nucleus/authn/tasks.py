"""
Celery tasks for device activation polling.

poll_device_activation runs in the background after /api/auth/init/ is called.
It hits Supabase device-poll every 3 seconds until:
  - status becomes "active"  → writes user info to DeviceSession
  - status becomes "session_expired" → marks DeviceSession expired
  - 30 minutes elapse → gives up (marks expired)
"""
import logging
import time

import httpx
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

POLL_INTERVAL = 3        # seconds between each Supabase call
MAX_WAIT = 30 * 60       # 30 minutes total maximum


@shared_task(bind=True, queue="neuralops", name="authn.tasks.poll_device_activation")
def poll_device_activation(self, device_id: str) -> str:
    """
    Long-running Celery task that polls Supabase device-poll until activation.

    Args:
        device_id: UUID string matching the device_id in Supabase.

    Returns:
        One of: "active", "expired", "timeout", "error"
    """
    # Import here to avoid app-not-ready issues at module level
    from .models import DeviceSession

    logger.info("[poll_device_activation] Starting poll for device_id=%s", device_id)

    elapsed = 0

    while elapsed < MAX_WAIT:
        try:
            response = httpx.get(
                settings.SUPABASE_DEVICE_POLL_URL,
                params={"device_id": device_id},
                headers={
                    # Supabase edge function needs the anon key as Bearer token
                    "Authorization": f"Bearer {settings.SUPABASE_ANON_KEY}",
                    # Our install token for extra verification in the edge function
                    "X-NeuralOps-Token": settings.NEURALOPS_INSTALL_TOKEN,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            logger.debug("[poll_device_activation] device_id=%s status=%s", device_id, status)

            if status == "active":
                session_expires_at = None
                raw_expires = data.get("session_expires_at")
                if raw_expires:
                    session_expires_at = parse_datetime(raw_expires)

                DeviceSession.objects.filter(device_id=device_id).update(
                    status=DeviceSession.STATUS_ACTIVE,
                    user_id=data.get("user_id"),
                    email=data.get("email"),
                    session_expires_at=session_expires_at,
                    celery_task_id=None,  # clear — task done
                )
                logger.info(
                    "[poll_device_activation] Device activated. email=%s device_id=%s",
                    data.get("email"),
                    device_id,
                )
                return "active"

            elif status == "session_expired":
                DeviceSession.objects.filter(device_id=device_id).update(
                    status=DeviceSession.STATUS_EXPIRED,
                    celery_task_id=None,
                )
                logger.info("[poll_device_activation] Session expired. device_id=%s", device_id)
                return "expired"

            # status == "pending" → keep waiting
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[poll_device_activation] HTTP %s from Supabase: %s",
                exc.response.status_code,
                exc.response.text,
            )
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

        except Exception as exc:
            logger.warning("[poll_device_activation] Network error: %s", exc)
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

    # 30 minutes elapsed — give up
    DeviceSession.objects.filter(device_id=device_id).update(
        status=DeviceSession.STATUS_EXPIRED,
        celery_task_id=None,
    )
    logger.warning("[poll_device_activation] Timed out after 30 min. device_id=%s", device_id)
    return "timeout"
