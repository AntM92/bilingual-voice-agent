# Webhook tool configuration (dashboard)

Create these three tools in the dashboard under Agent → Tools → Add tool →
**Webhook**. Replace `https://YOUR-SERVER-URL` with your hosted backend's base
URL (the live demo uses PythonAnywhere); for local testing, any HTTPS tunnel
URL works the same way.

For **every** tool, add a header under Secrets:
`X-Workspace-Token: <the same value as WORKSPACE_TOKEN in your .env>`.
That's what stops strangers from calling your protected endpoints.

All parameters use the **LLM Prompt** value type — the agent fills them from
the conversation. The parameter *descriptions* below matter: they are how
the model knows what to collect before calling the tool. Write them carefully
and tune them if the agent calls tools too early or with missing data.

> **Terminology:** the `service` field used by the booking tools represents an
> **appointment type**, not one of Zafira AI's business services. Zafira AI's
> business services are Workflow Automation, Intelligent AI Systems, Systems
> Integration, and Conversational AI. The booking appointment types are
> `consultation`, `site-visit`, and `follow-up`.

---

## 1. check_availability

- **Description:** "Check available Zafira AI appointment slots. The `service`
  parameter is an appointment type, not a Zafira AI business service. Always
  call this before offering or confirming an appointment time. Never invent
  availability."
- **Method:** POST
- **URL:** `https://YOUR-SERVER-URL/tools/check-availability`
- **Body parameters:**
  - `service` (string, required) — "Appointment type: one of `consultation`,
    `site-visit`, or `follow-up`. Use `consultation` for a general discussion
    about a business problem, automation opportunity, AI project, or Zafira AI
    service."
  - `preferred_day` (string, optional) — "Weekday the caller mentioned, if any,
    e.g. `Monday`."

The backend is the source of truth for appointment availability. It filters
out already-booked slots, so the agent must only offer slots returned by this
tool.

## 2. book_appointment

- **Description:** "Book a confirmed Zafira AI appointment. The `service`
  parameter is the appointment type: `consultation`, `site-visit`, or
  `follow-up`. Only call after the caller has selected a valid slot returned by
  `check_availability` and their name and phone number have been collected and
  confirmed."
- **Method:** POST
- **URL:** `https://YOUR-SERVER-URL/tools/book-appointment`
- **Body parameters:**
  - `name` (string, required) — "Caller's name, as confirmed back to them."
  - `phone` (string, required) — "Caller's phone number, confirmed digit by
    digit."
  - `service` (string, required) — "Appointment type: `consultation`,
    `site-visit`, or `follow-up`."
  - `slot` (string, required) — "The chosen slot, exactly as returned by
    `check_availability`."
  - `language` (string, required) — "`en` or `ar` — the language the caller is
    currently speaking."
  - `notes` (string, optional) — "Anything else relevant the caller said, such
    as the business problem or Zafira AI capability they want to discuss."

The backend independently enforces booking invariants. It rejects unknown
appointment types, invalid or hallucinated slots, and slots that have already
been booked. The model is not trusted to enforce these business rules by
itself.

## 3. request_handoff

- **Description:** "Request a human callback from the Zafira AI team. Use this
  when the caller explicitly asks for a person, needs a project-specific quote
  or specialist answer, has a complaint, raises a legal or contractual issue,
  asks something the knowledge base cannot answer reliably, or when another
  tool fails. Collect and confirm a callback number first."
- **Method:** POST
- **URL:** `https://YOUR-SERVER-URL/tools/request-handoff`
- **Body parameters:**
  - `name` (string, optional) — "Caller's name if given."
  - `phone` (string, required) — "Callback number, confirmed digit by digit."
  - `reason` (string, required) — "One-line summary of why a human is needed."
  - `preferred_time` (string, optional) — "When the caller would prefer the
    callback."
  - `language` (string, required) — "`en` or `ar` — the language for the
    callback."

A successful handoff request is saved by the backend and triggers an email
notification to the configured human recipient. Do not tell the caller that a
handoff was created until the tool returns success.

---

## Business hours

Zafira AI's human team operating hours are **Monday through Friday, 9:00 AM to
6:00 PM Gulf Standard Time (UTC+4)**.

Automated AI systems may operate outside those hours, but the agent must not
claim that the human team is available 24/7.

---

## System tool to enable

- **language_detection** — Agent → Tools → Add tool → System → Language
  detection. Also add **Arabic** under Voice & language → Additional languages,
  and choose an Arabic voice that sounds natural for Gulf customers.

---

## Why webhook handoff instead of transfer_to_number

`transfer_to_number` is appropriate for telephony deployments where the agent
has a live phone leg that can be transferred through SIP/Twilio or another
telephony provider.

This prototype runs through the browser widget, so escalation is implemented
as a structured callback workflow instead: the agent captures the caller's
context, the backend stores the request, and the configured human recipient is
notified by email.

---

## Tool safety principles

- Never invent availability.
- Never promise a slot before `check_availability` confirms it.
- Never claim a booking succeeded before `book_appointment` returns success.
- Never claim a handoff was created before `request_handoff` returns success.
- Confirm phone numbers digit by digit before saving them.
- If a tool fails, explain briefly and offer a human follow-up.
- Never collect payment-card or banking information.
- Treat the backend as the source of truth for appointment validity and
  duplicate-booking prevention.
