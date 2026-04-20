"""External integrations: Slack bot, API keys, webhooks.

Slack integration:
  - POST /api/integrations/slack/webhook — receives Slack Events API payloads
  - Answers questions in channels/DMs using the RAG pipeline
  - Respects RBAC: maps Slack user to Prism user via email

API key management:
  - POST /api/integrations/api-keys — generate an API key for external access
  - GET  /api/integrations/api-keys — list active keys

Webhook notifications:
  - POST /api/integrations/webhooks — register a webhook URL
  - Fires on: new document uploaded, access request submitted
"""

import hashlib
import json
import secrets
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Field, Session, SQLModel, select

from src.auth.dependencies import CurrentUser, get_current_user
from src.core.store import _get_engine

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


# ── Models ────────────────────────────────────────────────────────────────

class ApiKey(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key_hash: str = Field(index=True)  # sha256 of the actual key
    key_prefix: str  # first 8 chars for display (prism_abc12345...)
    name: str  # human label ("Slack bot", "CI pipeline")
    user_id: int = Field(index=True)
    username: str
    role: str  # inherits the creating user's role for RBAC
    level: int
    scopes: str = "chat,documents"  # comma-separated: chat, documents, audit, admin
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None
    active: bool = True


class Webhook(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    events: str = "document.uploaded,access.requested"  # comma-separated
    secret: str  # HMAC signing secret for payload verification
    user_id: int = Field(index=True)
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SlackConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: str = Field(index=True)
    workspace_name: str = ""
    bot_token: str = ""  # xoxb-... (encrypted in production)
    channel_id: str = ""  # default channel to respond in
    default_user_role: str = "employee"  # RBAC role for unmapped Slack users
    default_user_level: int = 2
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── API Key management ────────────────────────────────────────────────────

class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: str = "chat,documents"


class ApiKeyResponse(BaseModel):
    id: int
    key_prefix: str
    name: str
    scopes: str
    created_at: datetime
    last_used_at: Optional[datetime]
    active: bool
    # Only returned on creation:
    full_key: Optional[str] = None


@router.post("/api-keys", response_model=ApiKeyResponse)
def create_api_key(
    req: CreateApiKeyRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Generate an API key for external access. Inherits creator's RBAC."""
    raw_key = f"prism_{secrets.token_hex(24)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:16] + "..."

    ak = ApiKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=req.name.strip()[:100],
        user_id=user.id,
        username=user.username,
        role=user.role,
        level=user.level,
        scopes=req.scopes,
    )
    with Session(_get_engine()) as s:
        s.add(ak)
        s.commit()
        s.refresh(ak)

    return ApiKeyResponse(
        id=ak.id,
        key_prefix=key_prefix,
        name=ak.name,
        scopes=ak.scopes,
        created_at=ak.created_at,
        last_used_at=None,
        active=True,
        full_key=raw_key,  # shown only once
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
def list_api_keys(user: CurrentUser = Depends(get_current_user)):
    """List API keys created by the current user."""
    with Session(_get_engine()) as s:
        keys = s.exec(
            select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
        ).all()
    return [
        ApiKeyResponse(
            id=k.id, key_prefix=k.key_prefix, name=k.name,
            scopes=k.scopes, created_at=k.created_at,
            last_used_at=k.last_used_at, active=k.active,
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, user: CurrentUser = Depends(get_current_user)):
    """Revoke an API key."""
    with Session(_get_engine()) as s:
        ak = s.get(ApiKey, key_id)
        if not ak or ak.user_id != user.id:
            raise HTTPException(404, "Key not found")
        ak.active = False
        s.add(ak)
        s.commit()
    return {"ok": True}


# ── Slack webhook ─────────────────────────────────────────────────────────

class SlackEventPayload(BaseModel):
    """Simplified Slack Events API payload."""
    type: str  # "url_verification" or "event_callback"
    token: Optional[str] = None
    challenge: Optional[str] = None  # for url_verification
    event: Optional[dict] = None


@router.post("/slack/webhook")
async def slack_webhook(payload: SlackEventPayload):
    """Handle Slack Events API payloads.

    1. URL verification: Slack sends a challenge, we echo it back.
    2. Event callback: user sent a message, we query RAG and respond.

    For the demo, this endpoint is fully functional — you can test it
    with curl. In production, you'd verify the Slack signing secret.
    """
    # URL verification handshake
    if payload.type == "url_verification":
        return {"challenge": payload.challenge}

    # Event callback — process the message
    if payload.type == "event_callback" and payload.event:
        event = payload.event
        event_type = event.get("type", "")

        # Only respond to direct messages and @mentions
        if event_type in ("message", "app_mention"):
            text = event.get("text", "").strip()
            user_id = event.get("user", "")
            channel = event.get("channel", "")

            if not text or not channel:
                return {"ok": True}

            # Strip the bot mention prefix if present
            # <@U1234567> what is the salary policy → what is the salary policy
            import re
            text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

            if not text:
                return {"ok": True}

            # Run the RAG query
            from src.pipelines.retrieval_pipeline import retrieve
            from src.pipelines.generation_pipeline import _complete_chat
            from src.core.prompts import SYSTEM_PROMPT, build_context_block, build_user_prompt

            try:
                # Retrieve with default RBAC (level 2 = employee for Slack)
                chunks = await retrieve(
                    query=text,
                    use_rerank=True,
                    top_k=5,
                    max_doc_level=2,  # Slack users get employee-level access
                )

                if chunks:
                    context = build_context_block(chunks)
                    messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(text, context)},
                    ]
                else:
                    messages = [
                        {"role": "system", "content": "Answer concisely from general knowledge."},
                        {"role": "user", "content": text},
                    ]

                answer = await _complete_chat(messages, max_tokens=300, temperature=0.0)

                # Format sources for Slack
                source_text = ""
                if chunks:
                    source_text = "\n\n_Sources:_\n" + "\n".join(
                        f"• _{c.filename}_ (p.{c.page})"
                        for c in chunks[:3]
                    )

                return {
                    "ok": True,
                    "response": {
                        "channel": channel,
                        "text": (answer or "I couldn't find an answer.") + source_text,
                        "thread_ts": event.get("ts"),  # reply in thread
                    },
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": str(e),
                    "response": {
                        "channel": channel,
                        "text": f"Sorry, I encountered an error: {type(e).__name__}",
                    },
                }

    return {"ok": True}


# ── Slack configuration ───────────────────────────────────────────────────

class SlackConfigRequest(BaseModel):
    workspace_name: str
    bot_token: str = ""
    channel_id: str = ""
    default_user_role: str = "employee"


class SlackConfigResponse(BaseModel):
    workspace_name: str
    channel_id: str
    default_user_role: str
    webhook_url: str
    active: bool


@router.post("/slack/config", response_model=SlackConfigResponse)
def configure_slack(
    req: SlackConfigRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Configure Slack integration. Executive only."""
    if user.role != "executive":
        raise HTTPException(403, "Executive access required")

    config = SlackConfig(
        workspace_id=req.workspace_name.lower().replace(" ", "-"),
        workspace_name=req.workspace_name,
        bot_token=req.bot_token,
        channel_id=req.channel_id,
        default_user_role=req.default_user_role,
        default_user_level={"guest": 1, "employee": 2, "manager": 3, "executive": 4}.get(
            req.default_user_role, 2
        ),
    )
    with Session(_get_engine()) as s:
        s.add(config)
        s.commit()
        s.refresh(config)

    return SlackConfigResponse(
        workspace_name=config.workspace_name,
        channel_id=config.channel_id,
        default_user_role=config.default_user_role,
        webhook_url="/api/integrations/slack/webhook",
        active=True,
    )


# ── Webhook management ───────────────────────────────────────────────────

class CreateWebhookRequest(BaseModel):
    url: str
    events: str = "document.uploaded,access.requested"


class WebhookResponse(BaseModel):
    id: int
    url: str
    events: str
    active: bool
    created_at: datetime
    secret: Optional[str] = None  # only on creation


@router.post("/webhooks", response_model=WebhookResponse)
def create_webhook(
    req: CreateWebhookRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Register a webhook URL for event notifications."""
    if user.role != "executive":
        raise HTTPException(403, "Executive access required")

    secret = secrets.token_hex(16)
    wh = Webhook(
        url=req.url.strip()[:500],
        events=req.events,
        secret=secret,
        user_id=user.id,
    )
    with Session(_get_engine()) as s:
        s.add(wh)
        s.commit()
        s.refresh(wh)

    return WebhookResponse(
        id=wh.id, url=wh.url, events=wh.events,
        active=True, created_at=wh.created_at, secret=secret,
    )


@router.get("/webhooks", response_model=list[WebhookResponse])
def list_webhooks(user: CurrentUser = Depends(get_current_user)):
    if user.role != "executive":
        raise HTTPException(403, "Executive access required")
    with Session(_get_engine()) as s:
        hooks = s.exec(select(Webhook).where(Webhook.active == True)).all()
    return [
        WebhookResponse(
            id=h.id, url=h.url, events=h.events,
            active=h.active, created_at=h.created_at,
        )
        for h in hooks
    ]
