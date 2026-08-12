# Bilingual EN/AR Customer-Response Voice Agent

A working prototype of a customer-response voice agent for Gulf service
businesses, built on **ElevenLabs Agents**. It books appointments against
live availability, switches between **English and Arabic mid-conversation**,
and hands off to a human when the conversation needs one.

> **Live demo:** _coming — link will go here once the widget is deployed via
> GitHub Pages_
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
FastAPI tool server (server/main.py)
        │
        ├── /tools/check-availability   → demo schedule (swap: calendar API)
        ├── /tools/book-appointment     → data/leads.jsonl (swap: CRM/Supabase)
        ├── /tools/request-handoff      → data/leads.jsonl + notify (TODO)
        └── /webhooks/post-call         → data/post_call_log.jsonl
```

The conversation brain (ASR, LLM, TTS, turn-taking) is fully hosted by
ElevenLabs; this repo owns the **agent design** (prompt, tools, guardrails)
and the **integration seam** (the tool server).

## Repo layout

```
agent/    system_prompt.md, first_message.md, tools.md  ← conversation design
server/   main.py                                       ← FastAPI tool server
docs/     index.html                                    ← demo page (GitHub Pages)
data/     runtime output (leads, post-call log) — gitignored
```

## Run it

1. **Server**

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env        # set WORKSPACE_TOKEN to a random string
   uvicorn server.main:app --reload --port 8000
   ```

2. **Expose it** (while testing): `ngrok http 8000` and note the HTTPS URL.

3. **Create the agent** in the ElevenLabs dashboard:
   - System prompt: `agent/system_prompt.md` · First message:
     `agent/first_message.md`
   - Voice & language: add **Arabic** as an additional language and pick an
     Arabic voice from the Voice Library.
   - Tools: add the three webhook tools exactly as specified in
     `agent/tools.md` (with the `X-Workspace-Token` secret header), plus the
     **Language detection** system tool.

4. **Test** in the dashboard or on `docs/index.html` (paste your widget
   embed snippet from the agent's Widget tab). Try: book in English; switch
   to Arabic mid-call; ask for a human; ask for a slot that doesn't exist.

5. **Check the output**: bookings and handoffs land in `data/leads.jsonl`.

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
