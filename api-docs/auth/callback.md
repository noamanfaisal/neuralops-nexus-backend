# Authentication — AUTH-SIGNIN

**Task ID:** `e7b3a912-5f4d-4c8a-b061-2d9e0f1a8c47`
**Assigned to:** —

---

## GET api/v1/auth/callback

**Description**
Browser-facing callback endpoint. The hosted login page redirects here after
Supabase authentication completes, passing the access token as a query param.
Verifies the JWT, syncs User + Human, creates a UserSession, then determines
where to send the user based on their access level. For the personal edition,
the first user to ever sign in automatically becomes the company owner.
Everyone after must be an invitee or they are denied access.

**Flow**
1. Hosted page redirects browser to `{app_host}/auth/callback?access_token=xxx`
2. Extract `access_token` from query params — return error if missing
3. Verify JWT via Supabase JWKS (PyJWKClient)
4. Extract claims: `sub`, `email`, `email_verified`, `user_metadata`
5. If no Company exists in system → create User, create Company, assign as owner → redirect to dashboard
   If User is an invitee (CompanyAccess / ProjectMember / TopicParticipant exists) → create/sync User → redirect to appropriate view
   If User already exists with no ownership or invitee record → redirect to no-access page
6. Create UserSession (IP, user agent, provider session ID)

**Request**
```
GET /auth/callback?access_token=eyJhbGci...
```
No request body. Token arrives as a query param from the browser redirect.
`app_host` can be localhost, Tailscale IP, LAN IP, or any address the app runs on.

**Response**
```
302 → /dashboard             (company owner or company member)
302 → /projects/{id}         (project-level invitee)
302 → /topics/{id}           (topic-level invitee)
302 → /all_allowed_settings
302 → /all_permissions
```

**Models Involved**
- `User`
- `Human`
- `UserSession`
- `Company`
- `CompanyAccess`
- `ProjectMember`
- `TopicParticipant`

**ORM Query**
```python
```

**Discussion**

**Grey Area**
Model involved could be more, when starts working
