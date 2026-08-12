# Zafira AI Bilingual Voice Agent

A working bilingual **English/Arabic customer-response voice agent** for Zafira AI, built with **ElevenLabs Agents** and a **FastAPI** backend.

The agent can answer questions about Zafira AI, switch naturally between English and Arabic, check demo appointment availability, book appointments, capture human escalation requests, notify a human by email, and process signed post-call webhooks for analytics.

> **Live voice demo:** https://antm92.github.io/bilingual-voice-agent/  
> **Private operator dashboard:** hosted on the PythonAnywhere backend and protected by `X-Workspace-Token`  
> **Demo video:** coming soon

---

## What this project demonstrates

### Bilingual voice UX

The agent supports English and Arabic and uses ElevenLabs language detection so it can follow the caller when they switch languages mid-conversation.

The voice experience is designed for short, natural spoken turns rather than long chatbot-style responses.

### Zafira AI company knowledge

The agent is grounded in a Zafira AI knowledge base and can answer questions about:

- Workflow Automation
- Intelligent AI Systems
- Systems Integration
- Conversational AI
- pricing and engagement options
- business use cases
- integrations
- selected work
- contact information
- operating hours

The system prompt explicitly separates **Zafira AI's business services** from the booking system's **appointment types**.

### Webhook tools

The ElevenLabs agent calls three FastAPI webhook tools:

- `check_availability`
- `book_appointment`
- `request_handoff`

The model proposes intent, but the backend enforces business rules.

For example, the backend validates that:

1. the appointment type exists,
2. the requested slot exists for that appointment type,
3. the slot has not already been booked,
4. only then can the booking be created.

A hallucinated or duplicated slot is rejected server-side.

### Human escalation

When a caller asks for a person, needs specialist help, or reaches a tool failure, the agent can create a structured callback request containing:

- name
- phone number
- reason
- preferred callback time
- conversation language

The handoff is stored in SQLite and triggers an email notification through Brevo.

### Signed post-call processing

After a conversation finishes, ElevenLabs sends a post-call transcription webhook to the backend.

The backend:

- validates the `ElevenLabs-Signature` HMAC signature,
- stores the call idempotently by `conversation_id`,
- stores transcript, metadata, analysis and summary,
- derives conversation language,
- derives business outcome,
- extracts booking or handoff references,
- creates a clean transcript containing only spoken user/agent messages.

### Operator analytics

The backend exposes protected analytics endpoints and a private operator dashboard.

Available analytics include:

- total calls
- bookings
- handoffs
- booking conversion rate
- English vs Arabic usage
- average call duration
- daily performance
- bookings by appointment type
- recent calls
- per-call summaries and clean transcripts

---

## Live architecture

```text
Public visitor
    |
    v
GitHub Pages
ElevenLabs web widget
    |
    v
ElevenLabs Agents
ASR + LLM + TTS + turn-taking + language detection
    |
    | HTTPS webhook tools
    | X-Workspace-Token
    v
FastAPI backend
PythonAnywhere
    |
    +-- /tools/check-availability
    |       -> deterministic demo schedule
    |       -> filters already-booked SQLite slots
    |
    +-- /tools/book-appointment
    |       -> server-side slot validation
    |       -> duplicate protection
    |       -> SQLite bookings
    |
    +-- /tools/request-handoff
    |       -> SQLite handoffs
    |       -> Brevo email notification
    |
    +-- /webhooks/post-call
    |       -> ElevenLabs HMAC verification
    |       -> idempotent SQLite storage
    |       -> transcript + analysis + derived outcome
    |
    +-- /analytics/summary
    +-- /analytics/recent
    +-- /analytics/daily
    +-- /analytics/calls/{conversation_id}
    |
    +-- /dashboard
            -> private operator dashboard
            -> protected by X-Workspace-Token
```

---

## Important design principle

> **The LLM proposes intent. The backend enforces business truth.**

The system prompt tells the agent not to invent availability, but the backend does not rely on the prompt for booking correctness.

`book_appointment` independently validates the appointment type and slot, while SQLite prevents two bookings from claiming the same `(service, slot)` pair.

This means an invalid tool call cannot create a valid booking simply because the language model requested it.

---

## Appointment availability

The current demo uses a **deterministic demo schedule**, not a production calendar integration.

That is intentional for this prototype.

Example appointment types:

- `consultation`
- `site-visit`
- `follow-up`

Zafira AI human-team operating hours are:

**Monday through Friday, 9:00 AM to 6:00 PM Gulf Standard Time (UTC+4).**

A future production deployment could replace the demo schedule with a real calendar, CRM, booking system or scheduling API without changing the agent/tool interaction model.

---

## Repository structure

```text
agent/
    system_prompt.md
    first_message.md
    tools.md
    ...

server/
    main.py
    dashboard.html

docs/
    index.html

data/
    runtime SQLite database is created here and ignored by Git

requirements.txt
.env.example
README.md
```

### `agent/`

Contains the conversation design and tool configuration used to reproduce the ElevenLabs agent.

### `server/`

Contains the FastAPI backend and operator dashboard.

### `docs/`

Contains the public GitHub Pages live-demo page with the ElevenLabs widget.

---

## Run locally

### 1. Create a virtual environment

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example file:

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Configure the required values in `.env`.

Do not commit `.env`.

### 4. Start FastAPI

```bash
uvicorn server.main:app --reload --port 8000
```

If a local environment blocks a specific port, use another available port.

### 5. Expose the backend to ElevenLabs

For local testing, expose the FastAPI server over HTTPS using a tunnel and configure the three ElevenLabs webhook tools to use that HTTPS base URL.

The hosted demo uses PythonAnywhere instead of a development tunnel.

---

## Environment variables

The project uses environment variables rather than hard-coded credentials.

Typical configuration:

```text
WORKSPACE_TOKEN=
ELEVENLABS_API_KEY=
POSTCALL_WEBHOOK_SECRET=

BREVO_API_KEY=
HANDOFF_NOTIFY_EMAIL=
BREVO_FROM_EMAIL=
BREVO_FROM_NAME=

OUTBOUND_PROXY=
PORT=8000
```

### `WORKSPACE_TOKEN`

Shared secret required by protected tool and analytics endpoints.

Authentication fails closed: if `WORKSPACE_TOKEN` is not configured, protected requests are rejected rather than silently becoming public.

### `POSTCALL_WEBHOOK_SECRET`

Shared HMAC secret used to validate ElevenLabs post-call webhook signatures.

### `ELEVENLABS_API_KEY`

Used by the ElevenLabs SDK integration.

### Brevo variables

Used to send human-handoff notification emails.

`OUTBOUND_PROXY` is optional and is used by the hosted PythonAnywhere deployment because its outbound network path requires a proxy for the Brevo API.

---

## ElevenLabs agent setup

### Languages

- English as the default language
- Arabic as an additional language
- Language Detection system tool enabled
- separate English/Arabic voices can be configured

### Prompt

Use:

```text
agent/system_prompt.md
```

The prompt defines:

- bilingual behavior
- short voice-first responses
- Zafira AI service positioning
- knowledge-base grounding
- appointment workflow
- pricing boundaries
- human escalation behavior
- tool-use rules
- safety guardrails

### First message

Use:

```text
agent/first_message.md
```

### Webhook tools

Configure the three tools documented in:

```text
agent/tools.md
```

Each protected tool uses:

```text
X-Workspace-Token: <secret>
```

The `service` tool field means **appointment type**, not Zafira AI's business service.

---

## Tool behavior

### `check_availability`

Returns open demo appointment slots and excludes slots already present in the bookings table.

### `book_appointment`

Creates a booking only when:

- the appointment type is known,
- the slot belongs to that appointment type,
- the slot is still available.

Invalid slots and duplicate bookings are rejected by the backend.

### `request_handoff`

Stores a human callback request and sends an email notification to the configured recipient.

For the browser-widget demo this is a callback workflow, not a live telephone transfer.

A telephony version could use ElevenLabs' transfer tooling with SIP/Twilio.

---

## Persistence

Runtime data is stored in SQLite:

```text
data/agent.db
```

The database contains:

- bookings
- handoffs
- post-call records

The runtime database is ignored by Git.

SQLite is deliberately sufficient for this single-instance prototype. A larger deployment could replace it with a managed relational database or CRM.

---

## Post-call workflow

The backend receives ElevenLabs post-call transcription events at:

```text
POST /webhooks/post-call
```

Processing includes:

1. read the raw request body,
2. require the `ElevenLabs-Signature` header,
3. validate the event using the configured webhook secret,
4. accept `post_call_transcription`,
5. upsert by `conversation_id`,
6. persist transcript, metadata and analysis,
7. generate a clean spoken transcript,
8. detect English/Arabic from user speech,
9. derive call outcome,
10. extract `BK-...` or `HND-...` references where present.

The unique `conversation_id` makes repeated webhook delivery idempotent.

---

## Analytics API

Analytics endpoints are protected by `X-Workspace-Token`.

### Summary

```text
GET /analytics/summary
```

Returns overall KPIs such as total calls, bookings, handoffs, language split, average duration and booking conversion rate.

### Recent calls

```text
GET /analytics/recent?limit=10
```

Returns recent conversation metadata without returning the full raw transcript.

### Daily analytics

```text
GET /analytics/daily?days=7
```

Returns daily performance and bookings by appointment type using Gulf time.

### Call detail

```text
GET /analytics/calls/{conversation_id}
```

Returns one call's summary and clean transcript.

---

## Operator dashboard

The private operator dashboard is served from:

```text
/dashboard
```

It provides:

- KPI cards
- daily performance
- booking breakdown
- recent calls
- outcome/language indicators
- call summaries
- clean transcripts
- date-range controls
- optional auto-refresh

The dashboard does not hard-code the workspace secret. The operator enters the token in the browser, and API requests include it in the `X-Workspace-Token` header.

---

## Public live demo

The public demo is hosted with GitHub Pages:

**https://antm92.github.io/bilingual-voice-agent/**

It embeds the ElevenLabs conversation widget and does not expose the private analytics dashboard or workspace token.

Suggested demo flow:

1. Ask: "What does Zafira AI do?"
2. Ask about one of Zafira AI's services.
3. Switch from English to Arabic during the conversation.
4. Ask to book a consultation.
5. Try requesting an invalid/non-working day.
6. Request a human callback.
7. End the call and inspect the post-call record in the private dashboard.

---

## Security and reliability choices

### Fail-closed API authentication

Protected endpoints reject requests if server authentication is not configured.

### Server-side booking validation

The backend validates booking invariants independently of the LLM.

### Duplicate-booking protection

SQLite enforces a unique `(service, slot)` constraint in addition to application-level checks.

### Signed webhooks

Post-call events require a valid ElevenLabs HMAC signature.

### Idempotent post-call processing

Repeated webhook deliveries update the same `conversation_id` record instead of creating duplicates.

### Secret management

Secrets are stored in `.env`/host environment configuration and are excluded from Git.

### Minimal public exposure

The GitHub Pages site contains only the public voice widget. Operator analytics remain protected on the backend.

---

## Deployment

The live backend is deployed on PythonAnywhere over HTTPS.

Typical deployment flow:

```text
local repository
    ->
GitHub main branch
    ->
git pull on PythonAnywhere
    ->
install requirements when needed
    ->
reload web application
```

The PythonAnywhere deployment keeps its own `.env` and runtime SQLite database; neither is pulled from Git.

---

## Current limitations

This is a portfolio/demo deployment, not a production scheduling platform.

Current limitations include:

- appointment availability is a deterministic demo schedule rather than a real calendar,
- SQLite is appropriate for the current single-instance deployment but not intended as a horizontally scaled database,
- browser handoff creates a callback/email workflow rather than a live telephone transfer,
- production CRM/calendar integrations are intentionally outside the prototype's current scope.

These boundaries are deliberate and documented rather than hidden behind broader claims.

---

## Next steps

Useful future extensions include:

- real Google/Microsoft calendar or booking-system integration,
- CRM lead creation,
- telephony deployment with live transfer,
- automated ElevenLabs Agent Testing scenarios,
- conventional FastAPI unit/integration tests,
- demo video showing English → Arabic switching and a complete booking/handoff flow.

---

## License

MIT — see [LICENSE](LICENSE).
