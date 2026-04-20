"""Multi-tenant organization management.

Each organization is an isolated data silo — documents, threads, and
audit logs are scoped by org_id. Users belong to exactly one org.

For the demo, the seed creates a default "TechNova" org. New orgs
can be created by executives via POST /api/orgs.
"""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Field, Session, SQLModel, select

from src.auth.dependencies import CurrentUser, get_current_user
from src.core.store import _get_engine

router = APIRouter(prefix="/api/orgs", tags=["organizations"])


# ── Organization model ────────────────────────────────────────────────────

class Organization(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    slug: str = Field(index=True, unique=True)  # URL-safe identifier
    plan: str = "free"  # free | pro | enterprise
    max_docs: int = 50
    max_users: int = 10
    max_queries_per_day: int = 500
    created_at: datetime = Field(default_factory=datetime.utcnow)
    settings_json: str = ""  # JSON blob for org-specific config


# ── CRUD helpers ──────────────────────────────────────────────────────────

def get_org(org_id: int) -> Optional[Organization]:
    with Session(_get_engine()) as s:
        return s.get(Organization, org_id)


def get_org_by_slug(slug: str) -> Optional[Organization]:
    with Session(_get_engine()) as s:
        return s.exec(select(Organization).where(Organization.slug == slug)).first()


def list_orgs() -> list[Organization]:
    with Session(_get_engine()) as s:
        return list(s.exec(select(Organization).order_by(Organization.created_at.desc())))


def create_org(name: str, slug: str, plan: str = "free") -> Organization:
    org = Organization(name=name, slug=slug, plan=plan)
    with Session(_get_engine()) as s:
        s.add(org)
        s.commit()
        s.refresh(org)
    return org


def update_org(org_id: int, **kwargs) -> Optional[Organization]:
    with Session(_get_engine()) as s:
        org = s.get(Organization, org_id)
        if not org:
            return None
        for k, v in kwargs.items():
            if hasattr(org, k):
                setattr(org, k, v)
        s.add(org)
        s.commit()
        s.refresh(org)
        return org


# ── Seed default org ──────────────────────────────────────────────────────

def ensure_default_org() -> Organization:
    """Create the default TechNova org if it doesn't exist."""
    existing = get_org_by_slug("technova")
    if existing:
        return existing
    return create_org(
        name="TechNova Inc.",
        slug="technova",
        plan="enterprise",
    )


# ── API endpoints ─────────────────────────────────────────────────────────

class OrgResponse(BaseModel):
    id: int
    name: str
    slug: str
    plan: str
    max_docs: int
    max_users: int
    max_queries_per_day: int
    created_at: datetime


class CreateOrgRequest(BaseModel):
    name: str
    slug: str
    plan: str = "free"


class OrgUsage(BaseModel):
    org_id: int
    org_name: str
    plan: str
    docs_count: int
    users_count: int
    queries_today: int
    limits: dict


@router.get("", response_model=list[OrgResponse])
def list_organizations(user: CurrentUser = Depends(get_current_user)):
    """List all organizations. Visible to all users for demo."""
    return [
        OrgResponse(
            id=o.id, name=o.name, slug=o.slug, plan=o.plan,
            max_docs=o.max_docs, max_users=o.max_users,
            max_queries_per_day=o.max_queries_per_day,
            created_at=o.created_at,
        )
        for o in list_orgs()
    ]


@router.post("", response_model=OrgResponse)
def create_organization(
    req: CreateOrgRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Create a new organization. Executive only."""
    if user.role != "executive":
        raise HTTPException(status_code=403, detail="Executive access required")
    slug = req.slug.lower().strip().replace(" ", "-")[:30]
    if get_org_by_slug(slug):
        raise HTTPException(status_code=409, detail=f"Organization '{slug}' already exists")
    org = create_org(name=req.name, slug=slug, plan=req.plan)
    return OrgResponse(
        id=org.id, name=org.name, slug=org.slug, plan=org.plan,
        max_docs=org.max_docs, max_users=org.max_users,
        max_queries_per_day=org.max_queries_per_day,
        created_at=org.created_at,
    )


@router.get("/current", response_model=OrgResponse)
def get_current_org(user: CurrentUser = Depends(get_current_user)):
    """Get the current user's organization."""
    # For demo, all users belong to the default org
    org = ensure_default_org()
    return OrgResponse(
        id=org.id, name=org.name, slug=org.slug, plan=org.plan,
        max_docs=org.max_docs, max_users=org.max_users,
        max_queries_per_day=org.max_queries_per_day,
        created_at=org.created_at,
    )


@router.get("/usage", response_model=OrgUsage)
def get_org_usage(user: CurrentUser = Depends(get_current_user)):
    """Get usage stats for the current org."""
    from src.core import models as m, store as st

    org = ensure_default_org()
    docs = st.list_documents()
    users = m.list_users()

    # Count today's queries
    from datetime import date
    today = date.today()
    all_audit = m.list_audit(limit=5000)
    today_queries = sum(
        1 for a in all_audit
        if hasattr(a.ts, 'date') and a.ts.date() == today
    )

    return OrgUsage(
        org_id=org.id,
        org_name=org.name,
        plan=org.plan,
        docs_count=len(docs),
        users_count=len(users),
        queries_today=today_queries,
        limits={
            "max_docs": org.max_docs,
            "max_users": org.max_users,
            "max_queries_per_day": org.max_queries_per_day,
            "docs_remaining": max(0, org.max_docs - len(docs)),
            "users_remaining": max(0, org.max_users - len(users)),
            "queries_remaining": max(0, org.max_queries_per_day - today_queries),
        },
    )
