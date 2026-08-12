"""
Tool server for the bilingual EN/AR customer-response voice agent.

ElevenLabs Agents calls these endpoints as *webhook tools* during a live
conversation. The agent decides when to call them (based on the tool
descriptions configured in the dashboard — see agent/tools.md); this server
just does the work and returns JSON the agent can speak from.

Endpoints
---------
GET  /health                   Liveness check.
POST /tools/check-availability Return open appointment slots for a service.
POST /tools/book-appointment   Book a slot and persist the lead.
POST /tools/request-handoff    Capture a human-callback request (handoff).
POST /webhooks/post-call       Receive the ElevenLabs post-call payload.

Design notes
------------
- Storage is a JSON-lines file (data/leads.jsonl). Deliberately simple: the
  point of the prototype is the conversation design and the integration
  seam, not the database. Swapping this for Supabase/a CRM is a small,
  isolated change (see save_record()).
- Every tool endpoint requires the X-Workspace-Token header to match
  WORKSPACE_TOKEN from .env. Configure the same value as a secret header in
  the dashboard tool settings, so only your ElevenLabs workspace can call
  these endpoints.
- Human handoff here is *webhook-based* (capture a callback, notify a
  human). On a phone deployment you would use the built-in
  transfer_to_number system tool instead; see README "Design decisions".

Run locally:
    uvicorn server.main:app --reload --port 8000
Expose to ElevenLabs while testing:
    ngrok http 8000
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voice-agent")

WORKSPACE_TOKEN = os.getenv("WORKSPACE_TOKEN", "")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEADS_FILE = DATA_DIR / "leads.jsonl"
POSTCALL_FILE = DATA_DIR / "post_call_log.jsonl"

app = FastAPI(title="Bilingual Voice Agent — Tool Server", version="0.1.0")

# ---------------------------------------------------------------------------
# Demo schedule. In a real deployment this would query a calendar/booking
# system; for the prototype a static-but-plausible schedule keeps the demo
# deterministic and the conversation realistic.
# ---------------------------------------------------------------------------
SERVICES = {
    "consultation": {"en": "General consultation", "ar": "استشارة عامة"},
    "site-visit": {"en": "On-site visit", "ar": "زيارة ميدانية"},
    "follow-up": {"en": "Follow-up call", "ar": "مكالمة متابعة"},
}

DEMO_SLOTS = {
    "consultation": ["Sunday 10:00", "Sunday 16:30", "Tuesday 11:00", "Wednesday 14:00"],
    "site-visit": ["Monday 09:30", "Thursday 13:00"],
    "follow-up": ["Sunday 12:00", "Tuesday 17:00", "Thursday 10:30"],
}


# ---------------------------------------------------------------------------
# Auth + persistence helpers
# ---------------------------------------------------------------------------
def require_token(x_workspace_token: Optional[str]) -> None:
    """Reject tool calls that don't carry the shared secret header."""
    if not WORKSPACE_TOKEN:
        # Fail loudly in logs but allow local testing without a token.
        log.warning("WORKSPACE_TOKEN is not set — running with auth DISABLED (dev only).")
        return
    if x_workspace_token != WORKSPACE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Workspace-Token")


def save_record(path: Path, record: dict) -> None:
    """Append one JSON record per line. Swap this function to push to a CRM."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    record["saved_at"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def new_ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Request models — field descriptions double as documentation for what the
# agent should have collected before calling the tool.
# ---------------------------------------------------------------------------
class AvailabilityRequest(BaseModel):
    service: str = Field(description="One of: consultation, site-visit, follow-up")
    preferred_day: Optional[str] = Field(default=None, description="Optional day the caller mentioned")


class BookingRequest(BaseModel):
    name: str = Field(description="Caller's name as confirmed back to them")
    phone: str = Field(description="Caller's phone number, confirmed digit by digit")
    service: str = Field(description="One of: consultation, site-visit, follow-up")
    slot: str = Field(description="A slot string exactly as returned by check-availability")
    language: str = Field(description="Conversation language at booking time: 'en' or 'ar'")
    notes: Optional[str] = Field(default=None, description="Anything else the caller mentioned")


class HandoffRequest(BaseModel):
    name: Optional[str] = Field(default=None, description="Caller's name if given")
    phone: str = Field(description="Callback number, confirmed digit by digit")
    reason: str = Field(description="Short summary of why a human is needed")
    preferred_time: Optional[str] = Field(default=None, description="When the caller wants the callback")
    language: str = Field(description="'en' or 'ar' — the human should call back in this language")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "auth_enabled": bool(WORKSPACE_TOKEN)}


@app.post("/tools/check-availability")
def check_availability(
    body: AvailabilityRequest,
    x_workspace_token: Optional[str] = Header(default=None),
) -> dict:
    require_token(x_workspace_token)
    service = body.service.strip().lower()
    if service not in DEMO_SLOTS:
        return {
            "found": False,
            "message": f"Unknown service '{body.service}'. Valid services: {', '.join(DEMO_SLOTS)}.",
        }
    slots = DEMO_SLOTS[service]
    if body.preferred_day:
        day = body.preferred_day.strip().lower()
        filtered = [s for s in slots if s.lower().startswith(day)]
        slots = filtered or slots  # fall back to all slots so the agent can offer alternatives
    log.info("availability: service=%s day=%s -> %d slots", service, body.preferred_day, len(slots))
    return {"found": True, "service": service, "slots": slots}


@app.post("/tools/book-appointment")
def book_appointment(
    body: BookingRequest,
    x_workspace_token: Optional[str] = Header(default=None),
) -> dict:
    require_token(x_workspace_token)
    ref = new_ref("BK")
    save_record(LEADS_FILE, {"type": "booking", "ref": ref, **body.model_dump()})
    log.info("booking saved: %s (%s, %s)", ref, body.service, body.slot)
    return {
        "confirmed": True,
        "reference": ref,
        "message": f"Booked {body.service} at {body.slot} for {body.name}. Reference {ref}.",
    }


@app.post("/tools/request-handoff")
def request_handoff(
    body: HandoffRequest,
    x_workspace_token: Optional[str] = Header(default=None),
) -> dict:
    require_token(x_workspace_token)
    ref = new_ref("HND")
    save_record(LEADS_FILE, {"type": "handoff", "ref": ref, **body.model_dump()})
    # TODO(production): notify a human immediately — WhatsApp Business API,
    # Slack webhook, or email — instead of only persisting the request.
    log.info("handoff requested: %s (%s)", ref, body.reason)
    return {
        "confirmed": True,
        "reference": ref,
        "message": (
            "A colleague will call back "
            + (f"around {body.preferred_time} " if body.preferred_time else "shortly ")
            + f"in {'Arabic' if body.language == 'ar' else 'English'}. Reference {ref}."
        ),
    }


@app.post("/webhooks/post-call")
async def post_call(request: Request) -> dict:
    """
    Receives the ElevenLabs post-call payload (transcript + analysis) after a
    conversation ends. Enable it in the ElevenLabs settings under post-call
    webhooks and point it at this endpoint.

    NOTE: ElevenLabs signs post-call webhooks with a shared secret. Before
    production use, verify the signature header against
    POSTCALL_WEBHOOK_SECRET per the current docs — the exact header/scheme is
    documented on the post-call webhooks page.
    """
    payload = await request.json()
    # Store a compact record; full payloads are large.
    save_record(
        POSTCALL_FILE,
        {
            "conversation_id": payload.get("conversation_id") or payload.get("data", {}).get("conversation_id"),
            "received_keys": sorted(payload.keys()),
        },
    )
    log.info("post-call payload received")
    return {"received": True}
