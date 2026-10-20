"""POST /v1/waitlist, GET /v1/waitlist/stats — pre-launch demand signups for a
future self-serve Cloud tier. No payments, no checkout — signup only."""
from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from cloud import db, rate_limit
from cloud.auth import require_setup_token
from openosint.regexes import EMAIL_RE

router = APIRouter()

_SUCCESS_MESSAGE = "You're on the list. We'll email you when OpenOSINT Cloud opens up."


class WaitlistRole(str, Enum):
    soc_analyst = "soc_analyst"
    threat_intel = "threat_intel"
    pentester_bug_bounty = "pentester_bug_bounty"
    journalist_researcher = "journalist_researcher"
    msp_it = "msp_it"
    developer = "developer"
    other = "other"


class WaitlistPlanInterest(str, Enum):
    pro = "pro"
    team = "team"


class WaitlistRequest(BaseModel):
    email: str
    role: WaitlistRole | None = None
    use_case: str | None = Field(default=None, max_length=500)
    plan_interest: WaitlistPlanInterest | None = None
    consent: bool
    source: str | None = Field(default=None, max_length=200)
    # Hidden form field — bots fill it, real visitors never see it (see
    # docs/cloud/waitlist/index.html). Non-empty means drop the signup.
    website: str = ""

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("use_case", "source")
    @classmethod
    def _strip_or_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class WaitlistResponse(BaseModel):
    status: str
    message: str


class WaitlistStatsResponse(BaseModel):
    total: int
    by_role: dict[str, int]
    by_plan_interest: dict[str, int]
    by_source: dict[str, int]


@router.post("/waitlist", response_model=WaitlistResponse)
async def join_waitlist(body: WaitlistRequest, request: Request) -> WaitlistResponse:
    success = WaitlistResponse(status="ok", message=_SUCCESS_MESSAGE)

    if body.website:
        # ponytail: honeypot tripped — pretend success, store nothing
        return success

    if not body.consent:
        raise HTTPException(status_code=400, detail="consent is required")

    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit.waitlist_limiter.allow(client_ip):
        raise HTTPException(
            status_code=429, detail="Too many requests. Please try again shortly."
        )

    await db.add_waitlist_signup(
        email=body.email,
        role=body.role.value if body.role else None,
        use_case=body.use_case,
        plan_interest=body.plan_interest.value if body.plan_interest else None,
        source=body.source,
    )
    return success


@router.get("/waitlist/stats", response_model=WaitlistStatsResponse)
async def waitlist_stats(_: None = Depends(require_setup_token)) -> WaitlistStatsResponse:
    stats = await db.get_waitlist_stats()
    return WaitlistStatsResponse(**stats)
