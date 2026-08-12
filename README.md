# Bilingual EN/AR Customer-Response Voice Agent

A working prototype of a customer-response voice agent for Gulf service
businesses, built on **ElevenLabs Agents**. It books appointments against
live availability, switches between **English and Arabic mid-conversation**,
and hands off to a human when the conversation needs one.

> **Live demo:** https://antm92.github.io/bilingual-voice-agent/
> **Demo video:** _coming — 90-second EN→AR walkthrough_

## What it demonstrates

- **Bilingual voice UX** — Arabic configured as an additional language with
  the `language_detection` system tool, so the agent follows the caller's
  language switch without being asked.
- **Webhook (server) tools** — the agent calls a FastAPI backend for real
  availability, bookings and handoff requests instead of hallucinating
  answers: `check_availability`, `book_appointment`, `request_handoff`.
- **Human handoff** — an explicit escalation path: frustrated caller,
  out-of-scope request, or "I want to talk to a person" → callback captured
  with number, reason, preferred time and **callback language**.
- **Guarded conversation design** — the system prompt forbids invented
  availability and prices, requires digit-by-digit phone confirmation, and
  keeps replies breath-length for voice.
- **Post-call hook** — an endpoint ready to receive ElevenLabs post-call
  payloads (transcript + analysis) for QA and follow-up automation.

## Architecture

```
Caller (web widget, EN/AR speech)
        │
        ▼
ElevenLabs Agents  ── ASR → LLM → TTS, turn-taking, language detection
        │
        │  webhook tools (HTTPS + X-Workspace-Token)
        ▼
FastAPI tool server (server/main.py) — hosted on PythonAnywhere
        │
        ├── /tools/check-availability   → demo schedule (swap: calendar API)
        ├── /tools/book-appointment     → data/leads.jsonl (swap: CRM/Supabase)
        ├── /tools/request-handoff      → data/leads.jsonl + notify (TODO)
        └── /webhooks/post-call         → data/post_call_log.jsonl
```

The conversation brain (ASR, LLM, TTS, turn-taking) is fully hosted by
ElevenLabs; this repo owns the **agent design** (prompt, tools, guardrails)
and the **integration seam** (the tool server). The live demo's tool server
runs on PythonAnywhere at a stable HTTPS URL; for local development it runs
with uvicorn.

## Run it locally

1. **Server**

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env        # set WORKSPACE_TOKEN to a random string
   uvicorn server.main:app --reload --port 8000
   ```

2. **Point the agent at your server.** The tools in the ElevenLabs
   dashboard call whatever base URL you configure (see `agent/tools.md`).
   The live demo points at the hosted PythonAnywhere backend; for local
   testing, expose your dev server with any HTTPS tunnel and use that URL
   instead.

3. **Create the agent** in the ElevenLabs dashboard:
   - System prompt: `agent/system_prompt.md` · First message:
     `agent/first_message.md`
   - Voice & language: add **Arabic** as an additional language and pick an
     Arabic voice from the Voice Library.
   - Tools: add the three webhook tools exactly as specified in
     `agent/tools.md` (with the `X-Workspace-Token` secret header), plus the
     **Language detection** system tool.

4. **Test** in the dashboard or on the live demo page. Try: book in
   English; switch to Arabic mid-call; ask for a human; ask for a slot that
   doesn't exist.

5. **Check the output**: bookings and handoffs land in `data/leads.jsonl`
   on the server.

## Deployment

The demo backend is deployed on PythonAnywhere:

- `server/main.py` served over HTTPS at a stable subdomain — no dev tunnel
  in the loop, so the public demo works without a laptop running.
- `WORKSPACE_TOKEN` set as a server-side environment variable; the same
  value is configured as a secret header on each tool in the ElevenLabs
  dashboard, so only the workspace's agents can call the endpoints.
- The three tool URLs in the dashboard point at the hosted base URL.

Any always-on HTTPS host works the same way (Render, Railway, Fly, a VPS);
only the base URL in the tool configuration changes.

## Design decisions

- **Webhook handoff, not `transfer_to_number`.** The built-in
  `transfer_to_number` system tool does a live warm transfer — the right
  answer on a phone deployment (Twilio/SIP). In a browser widget there is no
  phone leg, so handoff is modelled as *callback capture + human
  notification*, which also fits how Gulf service businesses actually
  operate on WhatsApp.
- **LLM-filled tool parameters.** All tool parameters use the dashboard's
  "LLM Prompt" value type with carefully written descriptions — the
  descriptions, not the code, are what make the agent collect a confirmed
  phone number before booking.
- **Stable hosted backend over a dev tunnel.** The public demo's tools
  point at a persistent HTTPS host rather than a rotating tunnel URL, so
  the demo stays up on its own and the dashboard configuration never goes
  stale.
- **Boring storage on purpose.** JSON-lines files keep the integration seam
  obvious. `save_record()` is the single function to replace for
  Supabase/CRM.

## Roadmap

- Telephony deployment (Twilio/SIP) with `transfer_to_number` warm handoff
- WhatsApp notification to staff on `request_handoff`
- Post-call webhook signature verification + automated QA summaries
- Supabase persistence and a small staff dashboard for leads

## License

MIT — see [LICENSE](LICENSE).
