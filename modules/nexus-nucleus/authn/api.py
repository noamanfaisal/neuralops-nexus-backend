from ninja import Router
from ninja.errors import HttpError

from .schema import AuthInitResponse, AuthStatusResponse, SignInRequest, SignInResponse
from .services import DeviceAuthError, SignInError, auth_init, auth_status, signin_with_supabase_token
from .supabase import SupabaseTokenError


router = Router(tags=["Authentication"])


# ── Supabase JWT sign-in ─────────────────────────────────────────────────────

@router.post("/signin", response=SignInResponse)
def signin(request, payload: SignInRequest):
    try:
        return signin_with_supabase_token(payload.access_token)
    except (SignInError, SupabaseTokenError) as exc:
        raise HttpError(401, str(exc))


# ── Device activation flow ───────────────────────────────────────────────────

@router.get("/init/", response=AuthInitResponse)
def init(request):
    """
    Called once on app start.
    Returns authenticated (go to /app) or unauthenticated (show activation screen + login_url).
    """
    try:
        return auth_init()
    except DeviceAuthError as exc:
        raise HttpError(502, f"Could not reach activation service: {exc}")


@router.get("/status/", response=AuthStatusResponse)
def status(request):
    """
    Polled every 3 seconds by the frontend while waiting for activation.
    Reads from DB only — no Supabase call.
    """
    return auth_status()
