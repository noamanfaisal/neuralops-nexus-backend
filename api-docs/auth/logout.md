# Authentication — AUTH-LOGOUT

**Task ID:** `b2f7e491-6a3c-4d17-9e85-1c0b3f2a7d64`
**Assigned to:** —
**Status:** Draft

---

## POST /api/v1/auth/logout

**Description**
Logs the user out of the local system. Verifies the Bearer token to identify
the caller, marks their active UserSession as inactive, and returns 200.
Django does not call Supabase signOut — this is a local logout only.
The frontend is responsible for discarding the token from memory after
this call returns.

**Flow**
1. Client sends request with `Authorization: Bearer <token>`
2. Auth guard verifies JWT via Supabase JWKS, resolves local User
3. Mark active UserSession as inactive (`is_current=False`, `ended_at=now()`)
4. Return 200

**Request**
```
POST /api/v1/auth/logout
Authorization: Bearer <supabase_access_token>
```
No request body.

**Response**
```json
{
  "detail": "Logged out successfully."
}
```

**Error Responses**
```
401 — missing or invalid token
```

**Models Involved**
- `UserSession` — active session for this user is marked inactive on logout

**ORM Query**
```python
from django.utils.timezone import now

UserSession.objects.filter(
    user=request.user,
    is_current=True,
).update(
    is_current=False,
    ended_at=now(),
)
```

**Discussion**
- No Supabase signOut call needed. This is personal edition — the token lives
  in app memory and the user is the only one running the instance. The JWT
  expires on its own (typically 1 hour).
- If the user has multiple active sessions (multiple devices), this only
  marks the session tied to the current token. A "logout all devices" feature
  would require filtering without `provider_session_id` — out of scope for now.
- The auth guard (HttpBearer) must be implemented before this endpoint,
  as it is the first endpoint that requires Bearer token verification.
- Future: if a security revocation flow is ever needed, Supabase signOut
  can be added here at that point.