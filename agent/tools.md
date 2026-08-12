# Webhook tool configuration (dashboard)

Create these three tools in the dashboard under Agent → Tools → Add tool →
**Webhook**. Replace https://YOUR-SERVER-URL with your hosted backend's base URL (the live demo uses PythonAnywhere); for local testing, any HTTPS tunnel URL works the same way.

For **every** tool, add a header under Secrets:
`X-Workspace-Token: <the same value as WORKSPACE_TOKEN in your .env>`.
That's what stops strangers from calling your endpoints.

All parameters use the **LLM Prompt** value type — the agent fills them from
the conversation. The parameter *descriptions* below matter: they are how
the model knows what to collect before calling the tool. Write them
carefully and tune them if the agent calls tools too early or with missing
data.

---

## 1. check_availability

- **Description:** "Fetch open appointment slots for a service. Call this
  before offering any times to the caller. Never invent availability."
- **Method:** POST
- **URL:** `https://YOUR-SERVER-URL/tools/check-availability`
- **Body parameters:**
  - `service` (string, required) — "The service the caller wants: one of
    'consultation', 'site-visit', 'follow-up'."
  - `preferred_day` (string, optional) — "Day the caller mentioned, if any,
    e.g. 'Sunday'."

## 2. book_appointment

- **Description:** "Save a confirmed booking. Only call after the caller has
  chosen a slot returned by check_availability and has confirmed their name
  and phone number."
- **Method:** POST
- **URL:** `https://YOUR-SERVER-URL/tools/book-appointment`
- **Body parameters:**
  - `name` (string, required) — "Caller's name, as confirmed back to them."
  - `phone` (string, required) — "Caller's phone number, confirmed digit by
    digit."
  - `service` (string, required) — "'consultation', 'site-visit' or
    'follow-up'."
  - `slot` (string, required) — "The chosen slot, exactly as returned by
    check_availability."
  - `language` (string, required) — "'en' or 'ar' — the language the caller
    is currently speaking."
  - `notes` (string, optional) — "Anything else relevant the caller said."

## 3. request_handoff

- **Description:** "Save a request for a human callback. Call this when the
  caller asks for a person, sounds frustrated, or asks something outside
  your scope. Collect a callback number first."
- **Method:** POST
- **URL:** `https://YOUR-SERVER-URL/tools/request-handoff`
- **Body parameters:**
  - `name` (string, optional) — "Caller's name if given."
  - `phone` (string, required) — "Callback number, confirmed digit by
    digit."
  - `reason` (string, required) — "One-line summary of why a human is
    needed."
  - `preferred_time` (string, optional) — "When the caller wants the
    callback."
  - `language` (string, required) — "'en' or 'ar' — the language for the
    callback."

---

## System tool to enable

- **language_detection** — Agent → Tools → Add tool → System →
  Language detection. Also add **Arabic** under Voice & language →
  Additional languages, and pick a good Arabic voice from the Voice Library
  (audition a few — you're the native speaker, your ear is the QA here).

## Why webhook handoff instead of transfer_to_number

`transfer_to_number` (a built-in system tool) does a live warm transfer to a
human phone line — the right choice for telephony deployments with
Twilio/SIP. This prototype runs in the browser widget, where there is no
phone leg to transfer, so handoff is modelled as "capture a callback and
notify a human" via webhook. The README's roadmap covers the telephony
upgrade path.
