# Entity

Entity is a local-first, voice-operated personal assistant. It combines wake-word
detection, speech recognition, local or cloud language models, deterministic tool
execution, persistent SQLite memory, reminders, calendar monitoring, weather,
research, traffic-aware departure advice, and optional ntfy messaging.

## Runtime flow

1. Observers publish microphone, reminder, calendar, autonomy, or ntfy events.
2. `EntityRuntime` records the event and asks the planner for a validated tool plan.
3. Deterministic Python handlers execute allowed actions and request confirmation
   for uncertain or sensitive work.
4. Actuators speak, notify, inspect diagnostics, or write calendar events.
5. Conversations, decisions, tasks, goals, and selected memories persist in
   `agent/entity_memory.db`.

The language model selects intent; it does not directly call external services.

## Setup

Python 3.12 is the currently tested interpreter.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Configure at least one language-model route in `.env`. The normal local setup is
Ollama with `ENTITY_LOCAL_LLM_PROVIDER=ollama` and
`ENTITY_LOCAL_LLM_MODEL=<installed-model>`. Cloud fallback remains opt-in.

Audio also requires a working PortAudio input and an output backend. Kokoro is the
default voice. Google Calendar, ntfy, research, and route providers are optional
and become active only when their corresponding settings are enabled.

For live traffic departure estimates, set:

```dotenv
ENTITY_ROUTES_PROVIDER=tomtom
ENTITY_TOMTOM_API_KEY=
ENTITY_HOME_ADDRESS=
```

Keep `.env`, OAuth credentials, tokens, and `agent/entity_memory.db` private. They
are ignored by Git.

## Run

```bash
.venv/bin/python main.py
```

Entity announces startup, begins listening for the wake word, and starts enabled
background observers. Stop it with `Ctrl-C`.

## Verify

The deterministic regression suite uses only the standard library and does not
contact live services:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q main.py vad.py speech.py agent tts tests
.venv/bin/python -m pip check
```

Ask Entity for a `system status` to inspect configured runtime services. Live
integration checks can consume API quota or produce external effects, so test
calendar writes and ntfy delivery intentionally.

## Main modules

- `agent/runtime.py`: event dispatch, tool execution, confirmations, and replies
- `agent/models/`: Ollama/OpenAI providers and escalation routing
- `agent/audio/`: wake word, VAD, microphone capture, and transcription
- `agent/memory/`: SQLite schema, durable state, and semantic memory
- `agent/observers/`: background event producers
- `agent/actuators/`: controlled external actions
- `agent/routes.py`, `agent/weather.py`, `agent/research.py`: network tools
- `agent/identity.md`: assistant identity and capability contract
