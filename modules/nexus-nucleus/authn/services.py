import logging

import httpx
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .supabase import verify_supabase_token

logger = logging.getLogger(__name__)

User = get_user_model()


# =========================================================
# Existing: Supabase JWT sign-in (portal / web flow)
# =========================================================

class SignInError(Exception):
    pass


@transaction.atomic
def signin_with_supabase_token(access_token: str) -> dict:
    if not access_token:
        raise SignInError("access_token is required.")

    claims = verify_supabase_token(access_token)

    email = claims.get("email")
    supabase_user_id = claims.get("sub")
    email_verified = claims.get("email_verified", False)

    if not email:
        raise SignInError("Email is missing from Supabase token.")

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "username": email,
            "is_active": True,
        },
    )

    changed_fields = []

    if not user.username:
        user.username = email
        changed_fields.append("username")

    if not user.is_active:
        user.is_active = True
        changed_fields.append("is_active")

    if changed_fields:
        user.save(update_fields=changed_fields)

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_new_user": created,
        },
        "external_identity": {
            "provider": "supabase",
            "provider_user_id": supabase_user_id,
            "email": email,
            "email_verified": email_verified,
        },
    }


# =========================================================
# New: Device activation flow
# =========================================================

class DeviceAuthError(Exception):
    pass


def _register_device_in_supabase(device_id: str) -> None:
    """
    Call Supabase device-request edge function to register / re-register this device.
    Raises DeviceAuthError on failure.
    """
    try:
        response = httpx.post(
            settings.SUPABASE_DEVICE_REQUEST_URL,
            json={
                "device_id": device_id,
                "device_name": "NeuralOps Desktop",
            },
            headers={
                "Authorization": f"Bearer {settings.SUPABASE_ANON_KEY}",
                "X-NeuralOps-Token": settings.NEURALOPS_INSTALL_TOKEN,
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        response.raise_for_status()
        logger.info("[device_auth] Registered device_id=%s with Supabase", device_id)
    except httpx.HTTPStatusError as exc:
        raise DeviceAuthError(
            f"Supabase device-request returned {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except Exception as exc:
        raise DeviceAuthError(f"Failed to reach Supabase: {exc}") from exc


def auth_init() -> dict:
    """
    Entry point called by GET /api/auth/init/

    Flow:
    1. If DeviceSession exists and is active + not expired → return "authenticated"
    2. If DeviceSession is already pending → return existing login_url (don't re-register)
    3. Otherwise → register with Supabase, kick off polling task, return "unauthenticated" + login_url
    """
    from .models import DeviceSession
    from .tasks import poll_device_activation

    session = DeviceSession.objects.first()

    # ── Already authenticated ────────────────────────────────────────────────
    if session and session.status == DeviceSession.STATUS_ACTIVE:
        if session.session_expires_at and session.session_expires_at > timezone.now():
            return {
                "status": "authenticated",
                "email": session.email,
                "user_id": session.user_id,
                "session_expires_at": session.session_expires_at.isoformat(),
            }
        else:
            # Session expired — mark it and fall through to re-register
            session.status = DeviceSession.STATUS_EXPIRED
            session.save(update_fields=["status", "updated_at"])

    # ── Already waiting (pending) ────────────────────────────────────────────
    if session and session.status == DeviceSession.STATUS_PENDING:
        login_url = f"{settings.NEURALOPS_PORTAL_URL}/login?device_id={session.device_id}"
        logger.info("[device_auth] Returning existing pending session device_id=%s", session.device_id)
        return {"status": "unauthenticated", "login_url": login_url}

    # ── New or expired — register fresh ─────────────────────────────────────
    device_id = str(session.device_id) if session else None

    if session:
        # Reuse same device_id — Supabase upserts on conflict so this resets it to pending
        device_id = str(session.device_id)
        _register_device_in_supabase(device_id)
        session.status = DeviceSession.STATUS_PENDING
        session.user_id = None
        session.email = None
        session.session_expires_at = None
        session.celery_task_id = None
        session.save()
    else:
        # First time — create new session (device_id auto-generated by model)
        session = DeviceSession.objects.create()
        device_id = str(session.device_id)
        _register_device_in_supabase(device_id)

    # Start Celery polling task
    task = poll_device_activation.delay(device_id)
    session.celery_task_id = task.id
    session.save(update_fields=["celery_task_id", "updated_at"])
    logger.info("[device_auth] Started polling task %s for device_id=%s", task.id, device_id)

    login_url = f"{settings.NEURALOPS_PORTAL_URL}/login?device_id={device_id}"
    return {"status": "unauthenticated", "login_url": login_url}


def auth_status() -> dict:
    """
    Called by GET /api/auth/status/ — reads current state from DB only (no Supabase call).

    Returns one of:
      { status: "pending" }
      { status: "active", email, user_id, session_expires_at }
      { status: "session_expired" }
    """
    from .models import DeviceSession

    session = DeviceSession.objects.first()

    if not session:
        return {"status": "pending"}

    if session.status == DeviceSession.STATUS_ACTIVE:
        if session.session_expires_at and session.session_expires_at > timezone.now():
            return {
                "status": "active",
                "email": session.email,
                "user_id": session.user_id,
                "session_expires_at": session.session_expires_at.isoformat(),
            }
        else:
            session.status = DeviceSession.STATUS_EXPIRED
            session.save(update_fields=["status", "updated_at"])
            return {"status": "session_expired"}

    if session.status == DeviceSession.STATUS_EXPIRED:
        return {"status": "session_expired"}

    # pending
    return {"status": "pending"}
