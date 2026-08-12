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
import sqlite3
import requests
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from threading import Lock

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from elevenlabs.client import ElevenLabs
from elevenlabs.errors import BadRequestError

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voice-agent")

WORKSPACE_TOKEN = os.getenv("WORKSPACE_TOKEN", "")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_FILE = DATA_DIR / "agent.db"
LEADS_FILE = DATA_DIR / "leads.jsonl"
POSTCALL_FILE = DATA_DIR / "post_call_log.jsonl"
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
POSTCALL_WEBHOOK_SECRET = os.getenv("POSTCALL_WEBHOOK_SECRET", "")

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

elevenlabs = ElevenLabs(
    api_key=ELEVENLABS_API_KEY,
)

BOOKING_LOCK = Lock()

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

def require_workspace_auth(
    x_workspace_token: Optional[str] = Header(
        default=None,
        alias="X-Workspace-Token",
    ),
) -> None:
    require_token(x_workspace_token)

def save_record(path: Path, record: dict) -> None:
    """Append one JSON record per line. Swap this function to push to a CRM."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    record["saved_at"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def new_ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"

def get_booked_slots(service: str) -> set[str]:
    """Return already-booked slots for a service."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT slot
            FROM bookings
            WHERE service = ?
            """,
            (service,),
        ).fetchall()

    return {row["slot"] for row in rows}

def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ref TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                service TEXT NOT NULL,
                slot TEXT NOT NULL,
                language TEXT NOT NULL,
                notes TEXT,
                saved_at TEXT NOT NULL,
                UNIQUE(service, slot)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS handoffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ref TEXT NOT NULL UNIQUE,
                name TEXT,
                phone TEXT NOT NULL,
                reason TEXT NOT NULL,
                preferred_time TEXT,
                language TEXT NOT NULL,
                saved_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS post_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL UNIQUE,
                agent_id TEXT,
                agent_name TEXT,
                event_timestamp INTEGER,
                status TEXT,
                call_duration_secs INTEGER,
                termination_reason TEXT,
                call_successful TEXT,
                transcript_summary TEXT,
                transcript_json TEXT NOT NULL,
                analysis_json TEXT,
                metadata_json TEXT,
                received_at TEXT NOT NULL,
                language TEXT,
                outcome TEXT,
                booking_reference TEXT,
                handoff_reference TEXT,
                clean_transcript TEXT
            )
            """
        )

        # Upgrade existing databases that were created before the
        # analytics columns existed.
        post_call_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(post_calls)"
            ).fetchall()
        }

        new_columns = {
            "language": "TEXT",
            "outcome": "TEXT",
            "booking_reference": "TEXT",
            "handoff_reference": "TEXT",
            "clean_transcript": "TEXT",
        }

        for column_name, column_type in new_columns.items():
            if column_name not in post_call_columns:
                conn.execute(
                    f"""
                    ALTER TABLE post_calls
                    ADD COLUMN {column_name} {column_type}
                    """
                )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_post_calls_outcome
            ON post_calls(outcome)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_post_calls_language
            ON post_calls(language)
            """
        )

def send_handoff_email(
    ref: str,
    name: Optional[str],
    phone: str,
    reason: str,
    preferred_time: Optional[str],
    language: str,
) -> bool:
    api_key = os.getenv("BREVO_API_KEY", "")
    notify_email = os.getenv("HANDOFF_NOTIFY_EMAIL", "")
    from_email = os.getenv("BREVO_FROM_EMAIL", "")
    from_name = os.getenv("BREVO_FROM_NAME", "Zafira Voice Agent")

    if not api_key or not notify_email or not from_email:
        log.warning("Handoff email notification is not configured.")
        return False

    payload = {
        "sender": {
            "name": from_name,
            "email": from_email,
        },
        "to": [
            {
                "email": notify_email,
            }
        ],
        "subject": f"Human callback requested — {ref}",
        "textContent": (
            f"Reference: {ref}\n"
            f"Name: {name or 'Not provided'}\n"
            f"Phone: {phone}\n"
            f"Reason: {reason}\n"
            f"Preferred callback time: {preferred_time or 'Not specified'}\n"
            f"Language: {'Arabic' if language == 'ar' else 'English'}\n"
        ),
    }

    # PythonAnywhere free accounts require outbound HTTPS traffic
    # to use their proxy. Locally this can remain unset.
    proxy_url = os.getenv("OUTBOUND_PROXY", "")

    proxies = None
    if proxy_url:
        proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }

    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
            },
            json=payload,
            proxies=proxies,
            timeout=10,
        )

        response.raise_for_status()

        log.info(
            "handoff notification sent for %s (HTTP %s)",
            ref,
            response.status_code,
        )

        return True

    except requests.RequestException as exc:
        response_text = ""

        if exc.response is not None:
            response_text = exc.response.text

        log.error(
            "Brevo notification failed for %s: %s %s",
            ref,
            exc,
            response_text,
        )

        return False

def build_clean_transcript(transcript: list[dict]) -> str:
    """Return a readable transcript containing only spoken user/agent messages."""
    lines: list[str] = []

    for turn in transcript:
        role = turn.get("role")
        message = turn.get("message")

        if role not in {"agent", "user"}:
            continue

        if not message:
            continue

        lines.append(f"{role}: {message}")

    return "\n".join(lines)


def detect_conversation_language(transcript: list[dict]) -> str:
    """Detect English vs Arabic from user messages."""
    user_text = " ".join(
        str(turn.get("message") or "")
        for turn in transcript
        if turn.get("role") == "user"
    )

    arabic_chars = len(
        re.findall(r"[\u0600-\u06FF]", user_text)
    )
    latin_chars = len(
        re.findall(r"[A-Za-z]", user_text)
    )

    if arabic_chars > latin_chars:
        return "ar"

    return "en"


def find_reference(text: str, prefix: str) -> Optional[str]:
    """Extract references such as BK-ABC123 or HND-ABC123."""
    match = re.search(
        rf"\b{re.escape(prefix)}-[A-F0-9]{{6}}\b",
        text.upper(),
    )

    return match.group(0) if match else None


def derive_post_call_outcome(
    transcript: list[dict],
    summary: Optional[str],
    call_successful: object,
) -> tuple[str, Optional[str], Optional[str]]:
    """Derive business outcome and associated references."""
    transcript_json = json.dumps(
        transcript,
        ensure_ascii=False,
    )

    search_text = (
        transcript_json
        + "\n"
        + (summary or "")
    )

    booking_reference = find_reference(
        search_text,
        "BK",
    )

    handoff_reference = find_reference(
        search_text,
        "HND",
    )

    normalized = search_text.lower()

    if handoff_reference or "request_handoff" in normalized:
        outcome = "handoff"

    elif booking_reference or "book_appointment" in normalized:
        outcome = "booking"

    elif str(call_successful).lower() in {
        "failure",
        "failed",
        "false",
    }:
        outcome = "unsuccessful"

    else:
        outcome = "information"

    return (
        outcome,
        booking_reference,
        handoff_reference,
    )
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

@app.on_event("startup")
def startup() -> None:
    init_db()

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
            "service": service,
            "slots": [],
        }

    booked_slots = get_booked_slots(service)

    slots = [
        slot
        for slot in DEMO_SLOTS[service]
        if slot not in booked_slots
    ]

    if body.preferred_day:
        preferred_day = body.preferred_day.strip().lower()
        slots = [
            slot
            for slot in slots
            if slot.lower().startswith(preferred_day)
        ]

    return {
        "found": bool(slots),
        "service": service,
        "slots": slots,
    }


@app.post("/tools/book-appointment")
def book_appointment(
    body: BookingRequest,
    x_workspace_token: Optional[str] = Header(default=None),
) -> dict:
    require_token(x_workspace_token)

    service = body.service.strip().lower()
    slot = body.slot.strip()

    # Reject unknown services.
    if service not in DEMO_SLOTS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unknown_service",
                "message": f"Unknown service '{body.service}'.",
                "valid_services": list(DEMO_SLOTS.keys()),
            },
        )

    # Reject slots that are not part of the configured schedule.
    if slot not in DEMO_SLOTS[service]:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_slot",
                "message": (
                    f"'{slot}' is not an available slot for {service}. "
                    "Call check_availability again before booking."
                ),
                "available_slots": DEMO_SLOTS[service],
            },
        )

    # Prevent two bookings from claiming the same slot.
    with BOOKING_LOCK:
        ref = new_ref("BK")
        saved_at = datetime.now(timezone.utc).isoformat()

        try:
            with get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO bookings (
                        ref,
                        name,
                        phone,
                        service,
                        slot,
                        language,
                        notes,
                        saved_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ref,
                        body.name,
                        body.phone,
                        service,
                        slot,
                        body.language,
                        body.notes,
                        saved_at,
                    ),
                )

        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "slot_already_booked",
                    "message": (
                        f"'{slot}' has already been booked. "
                        "Call check_availability again and choose another slot."
                    ),
                },
            )

    log.info("booking saved: %s (%s, %s)", ref, service, slot)

    return {
        "confirmed": True,
        "reference": ref,
        "message": f"Booked {service} at {slot} for {body.name}. Reference {ref}.",
    }


@app.post("/tools/request-handoff")
def request_handoff(
    body: HandoffRequest,
    x_workspace_token: Optional[str] = Header(default=None),
) -> dict:
    require_token(x_workspace_token)

    ref = new_ref("HND")
    saved_at = datetime.now(timezone.utc).isoformat()

    # Always save the handoff first.
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO handoffs (
                ref,
                name,
                phone,
                reason,
                preferred_time,
                language,
                saved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref,
                body.name,
                body.phone,
                body.reason,
                body.preferred_time,
                body.language,
                saved_at,
            ),
        )

    # Notify a human by email through Brevo.
    notification_sent = send_handoff_email(
        ref=ref,
        name=body.name,
        phone=body.phone,
        reason=body.reason,
        preferred_time=body.preferred_time,
        language=body.language,
    )

    if not notification_sent:
        log.warning(
            "Handoff %s was saved but the email notification was not sent.",
            ref,
        )

    log.info("handoff requested: %s (%s)", ref, body.reason)

    return {
        "confirmed": True,
        "reference": ref,
        "message": (
            "A colleague will call back "
            + (
                f"around {body.preferred_time} "
                if body.preferred_time
                else "shortly "
            )
            + f"in {'Arabic' if body.language == 'ar' else 'English'}. "
            + f"Reference {ref}."
        ),
    }

@app.get(
    "/analytics/summary",
    dependencies=[Depends(require_workspace_auth)],
)
def analytics_summary() -> dict:
    with get_db() as conn:
        total_calls = conn.execute(
            "SELECT COUNT(*) FROM post_calls"
        ).fetchone()[0]

        bookings = conn.execute(
            """
            SELECT COUNT(*)
            FROM post_calls
            WHERE outcome = 'booking'
            """
        ).fetchone()[0]

        handoffs = conn.execute(
            """
            SELECT COUNT(*)
            FROM post_calls
            WHERE outcome = 'handoff'
            """
        ).fetchone()[0]

        information = conn.execute(
            """
            SELECT COUNT(*)
            FROM post_calls
            WHERE outcome = 'information'
            """
        ).fetchone()[0]

        unsuccessful = conn.execute(
            """
            SELECT COUNT(*)
            FROM post_calls
            WHERE outcome = 'unsuccessful'
            """
        ).fetchone()[0]

        english_calls = conn.execute(
            """
            SELECT COUNT(*)
            FROM post_calls
            WHERE language = 'en'
            """
        ).fetchone()[0]

        arabic_calls = conn.execute(
            """
            SELECT COUNT(*)
            FROM post_calls
            WHERE language = 'ar'
            """
        ).fetchone()[0]

        average_duration = conn.execute(
            """
            SELECT AVG(call_duration_secs)
            FROM post_calls
            WHERE call_duration_secs IS NOT NULL
            """
        ).fetchone()[0]

    conversion_rate = (
        round((bookings / total_calls) * 100, 1)
        if total_calls
        else 0.0
    )

    return {
        "total_calls": total_calls,
        "outcomes": {
            "bookings": bookings,
            "handoffs": handoffs,
            "information": information,
            "unsuccessful": unsuccessful,
        },
        "languages": {
            "english": english_calls,
            "arabic": arabic_calls,
        },
        "average_duration_secs": (
            round(average_duration, 1)
            if average_duration is not None
            else 0
        ),
        "booking_conversion_rate_percent": conversion_rate,
    }

@app.get(
    "/analytics/recent",
    dependencies=[Depends(require_workspace_auth)],
)
def analytics_recent(limit: int = 10) -> dict:
    # Keep the endpoint lightweight even if a large limit is requested.
    limit = max(1, min(limit, 50))

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                conversation_id,
                agent_name,
                language,
                outcome,
                booking_reference,
                handoff_reference,
                call_duration_secs,
                call_successful,
                termination_reason,
                transcript_summary,
                received_at
            FROM post_calls
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return {
        "count": len(rows),
        "calls": [dict(row) for row in rows],
    }

@app.get(
    "/analytics/calls/{conversation_id}",
    dependencies=[Depends(require_workspace_auth)],
)
def analytics_call_detail(conversation_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                conversation_id,
                agent_name,
                language,
                outcome,
                booking_reference,
                handoff_reference,
                call_duration_secs,
                call_successful,
                termination_reason,
                transcript_summary,
                clean_transcript,
                received_at
            FROM post_calls
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    return dict(row)

@app.post("/webhooks/post-call")
async def post_call(request: Request) -> dict:
    if not POSTCALL_WEBHOOK_SECRET:
        log.error("POSTCALL_WEBHOOK_SECRET is not configured.")
        raise HTTPException(
            status_code=503,
            detail="Post-call webhook is not configured.",
        )

    raw_body = await request.body()
    signature = request.headers.get("elevenlabs-signature")

    if not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing ElevenLabs-Signature header.",
        )

    try:
        event = elevenlabs.webhooks.construct_event(
            rawBody=raw_body.decode("utf-8"),
            sig_header=signature,
            secret=POSTCALL_WEBHOOK_SECRET,
        )
    except BadRequestError:
        log.warning("Rejected post-call webhook with invalid signature.")
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature.",
        )

    event_type = event.get("type")

    # For now, we only persist transcription/analysis events.
    if event_type != "post_call_transcription":
        return {
            "received": True,
            "ignored": True,
            "type": event_type,
        }

    data = event.get("data", {})
    metadata = data.get("metadata") or {}
    analysis = data.get("analysis") or {}
    transcript = data.get("transcript") or []
    transcript_summary = analysis.get("transcript_summary")
    call_successful = analysis.get("call_successful")

    clean_transcript = build_clean_transcript(
        transcript
    )

    language = detect_conversation_language(
        transcript
    )

    (
        outcome,
        booking_reference,
        handoff_reference,
    ) = derive_post_call_outcome(
        transcript=transcript,
        summary=transcript_summary,
        call_successful=call_successful,
    )

    conversation_id = data.get("conversation_id")

    if not conversation_id:
        raise HTTPException(
            status_code=400,
            detail="Missing conversation_id.",
        )

    received_at = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO post_calls (
                conversation_id,
                agent_id,
                agent_name,
                event_timestamp,
                status,
                call_duration_secs,
                termination_reason,
                call_successful,
                transcript_summary,
                transcript_json,
                analysis_json,
                metadata_json,
                received_at,
                language,
                outcome,
                booking_reference,
                handoff_reference,
                clean_transcript
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(conversation_id) DO UPDATE SET
                agent_id = excluded.agent_id,
                agent_name = excluded.agent_name,
                event_timestamp = excluded.event_timestamp,
                status = excluded.status,
                call_duration_secs = excluded.call_duration_secs,
                termination_reason = excluded.termination_reason,
                call_successful = excluded.call_successful,
                transcript_summary = excluded.transcript_summary,
                transcript_json = excluded.transcript_json,
                analysis_json = excluded.analysis_json,
                metadata_json = excluded.metadata_json,
                received_at = excluded.received_at,
                language = excluded.language,
                outcome = excluded.outcome,
                booking_reference = excluded.booking_reference,
                handoff_reference = excluded.handoff_reference,
                clean_transcript = excluded.clean_transcript
            """,
            (
                conversation_id,
                data.get("agent_id"),
                data.get("agent_name"),
                event.get("event_timestamp"),
                data.get("status"),
                metadata.get("call_duration_secs"),
                metadata.get("termination_reason"),
                call_successful,
                transcript_summary,
                json.dumps(
                    transcript,
                    ensure_ascii=False,
                ),
                json.dumps(
                    analysis,
                    ensure_ascii=False,
                ),
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                ),
                received_at,
                language,
                outcome,
                booking_reference,
                handoff_reference,
                clean_transcript,
            ),
        )

    log.info(
        "post-call transcription stored: %s",
        conversation_id,
    )

    return {
        "received": True,
        "conversation_id": conversation_id,
    }
