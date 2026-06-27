from typing import Literal, Optional

from ninja import Schema


# ── Existing: Supabase JWT sign-in ─────────────────────────────────────────

class SignInRequest(Schema):
    access_token: str


class LocalUserOut(Schema):
    id: str
    email: str
    username: str
    is_new_user: bool


class ExternalIdentityOut(Schema):
    provider: str
    provider_user_id: str
    email: str
    email_verified: bool


class SignInResponse(Schema):
    user: LocalUserOut
    external_identity: ExternalIdentityOut


# ── New: Device activation flow ─────────────────────────────────────────────

class AuthInitResponse(Schema):
    """Response from GET /api/auth/init/"""
    status: Literal["authenticated", "unauthenticated"]
    # Populated when status == "authenticated"
    email: Optional[str] = None
    user_id: Optional[str] = None
    session_expires_at: Optional[str] = None
    # Populated when status == "unauthenticated"
    login_url: Optional[str] = None


class AuthStatusResponse(Schema):
    """Response from GET /api/auth/status/"""
    status: Literal["pending", "active", "session_expired"]
    # Populated when status == "active"
    email: Optional[str] = None
    user_id: Optional[str] = None
    session_expires_at: Optional[str] = None
