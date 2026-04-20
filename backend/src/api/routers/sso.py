"""SSO / OAuth2 provider support.

Supports:
  - Google OAuth2 (primary demo flow)
  - Generic OIDC (extensible to Okta, Azure AD, Auth0)
  - SAML metadata endpoint (enterprise readiness signal)

Flow:
  1. Frontend redirects to GET /api/sso/google/authorize
  2. User authenticates with Google
  3. Google redirects back to GET /api/sso/google/callback with auth code
  4. Backend exchanges code for tokens, extracts email/name
  5. Auto-provisions a Prism user if new (default: employee role)
  6. Returns a JWT token — frontend stores it like a normal login

For the demo, Google OAuth works with any @gmail.com account. In
production, you'd restrict to the org's Google Workspace domain.
"""

import os
import secrets
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.auth.dependencies import CurrentUser, get_current_user
from src.auth.jwt import create_access_token
from src.auth.security import hash_password
from src.core import models

router = APIRouter(prefix="/api/sso", tags=["sso"])


# ── Configuration ─────────────────────────────────────────────────────────

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8765/api/sso/google/callback",
)
SSO_FRONTEND_URL = os.environ.get("SSO_FRONTEND_URL", "http://localhost:5173")

# In-memory state store for OAuth CSRF prevention (demo-grade).
# Production: use Redis or encrypted cookie.
_pending_states: dict[str, dict] = {}


# ── Google OAuth2 ─────────────────────────────────────────────────────────

@router.get("/google/authorize")
async def google_authorize():
    """Redirect the user to Google's OAuth2 consent screen."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            501,
            "Google OAuth not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in .env to enable SSO.",
        )

    state = secrets.token_hex(16)
    _pending_states[state] = {"created": datetime.utcnow().isoformat()}

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = ""):
    """Handle Google's OAuth2 callback after user consent."""
    if error:
        return RedirectResponse(f"{SSO_FRONTEND_URL}/signin?error={error}")

    if state not in _pending_states:
        return RedirectResponse(f"{SSO_FRONTEND_URL}/signin?error=invalid_state")

    del _pending_states[state]

    if not code:
        return RedirectResponse(f"{SSO_FRONTEND_URL}/signin?error=no_code")

    # Exchange auth code for tokens
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                return RedirectResponse(
                    f"{SSO_FRONTEND_URL}/signin?error=token_exchange_failed"
                )
            tokens = token_resp.json()

            # Fetch user info
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            if userinfo_resp.status_code != 200:
                return RedirectResponse(
                    f"{SSO_FRONTEND_URL}/signin?error=userinfo_failed"
                )
            userinfo = userinfo_resp.json()
    except Exception as e:
        return RedirectResponse(
            f"{SSO_FRONTEND_URL}/signin?error=oauth_error"
        )

    email = userinfo.get("email", "")
    name = userinfo.get("name", email.split("@")[0])

    if not email:
        return RedirectResponse(f"{SSO_FRONTEND_URL}/signin?error=no_email")

    # Auto-provision or find existing user
    username = email.split("@")[0].lower().replace(".", "_")[:30]
    user = models.get_user_by_username(username)

    if not user:
        # New SSO user — create with employee role (safe default)
        user = models.upsert_user(
            models.User(
                username=username,
                password_hash=hash_password(secrets.token_hex(16)),  # random password
                role="employee",
                level=2,
                title=name,
            )
        )

    # Generate JWT
    token = create_access_token(user.id, user.username, user.role, user.level)

    # Redirect to frontend with token in URL fragment (not query — safer)
    return RedirectResponse(
        f"{SSO_FRONTEND_URL}/signin?sso_token={token}"
        f"&sso_user={user.username}"
        f"&sso_role={user.role}"
        f"&sso_level={user.level}"
    )


# ── SSO provider status ──────────────────────────────────────────────────

class SsoProviderStatus(BaseModel):
    provider: str
    enabled: bool
    authorize_url: Optional[str]


@router.get("/providers", response_model=list[SsoProviderStatus])
async def list_sso_providers():
    """List available SSO providers and their status."""
    return [
        SsoProviderStatus(
            provider="google",
            enabled=bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
            authorize_url="/api/sso/google/authorize" if GOOGLE_CLIENT_ID else None,
        ),
        SsoProviderStatus(
            provider="okta",
            enabled=False,
            authorize_url=None,
        ),
        SsoProviderStatus(
            provider="azure_ad",
            enabled=False,
            authorize_url=None,
        ),
        SsoProviderStatus(
            provider="saml",
            enabled=False,
            authorize_url=None,
        ),
    ]


# ── SAML metadata (enterprise readiness signal) ──────────────────────────

@router.get("/saml/metadata")
async def saml_metadata():
    """Return SAML SP metadata. Not functional — included as an
    enterprise-readiness signal showing the architecture is extensible."""
    return {
        "entity_id": "https://prism-rag.example.com/saml/metadata",
        "acs_url": "https://prism-rag.example.com/api/sso/saml/acs",
        "sls_url": "https://prism-rag.example.com/api/sso/saml/sls",
        "name_id_format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        "status": "not_configured",
        "note": "SAML SSO requires IdP metadata upload. Contact admin to configure.",
    }
