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

`agent.lifecycle.Lifecycle` publishes renderer-neutral state events for visual
clients. Current states include booting, wake detection, listening, transcribing,
thinking, tool activity, speaking, errors, idle, and shutdown.

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

For a visual interface, keep Entity in its own process. The optional Unreal proof
of concept sends lifecycle states to an Unreal Remote Control Preset without
blocking Entity's runtime. Enable it with:

```dotenv
ENTITY_UNREAL_ENABLED=true
ENTITY_PREFER_CLOUD_WHEN_UNREAL=true
ENTITY_UNREAL_REMOTE_URL=http://127.0.0.1:30010
ENTITY_UNREAL_PRESET=EntityOrb
ENTITY_UNREAL_TARGET=component_scalar
ENTITY_UNREAL_COMPONENT_PATH=/Game/Maps/UEDPIE_0_EntityRoomTest.EntityRoomTest:PersistentLevel.BP_EntityOrb_C_0.Shell
```

The proof-of-concept bridge calls the running orb shell's native material
functions. It maps each lifecycle state to emission strength, breathing speed,
breathing expansion, and a distinct color. The main visual language is cyan idle,
blue listening, indigo transcription, purple thinking, green speaking, orange
tool use, gold autonomous activity, orange-red service trouble, and crimson
runtime errors. It sends only the newest state and discards stale visual updates
if Unreal is unavailable. Test the connection without starting Entity's audio and
model stack using:

```bash
.venv/bin/python -m agent.visual.unreal thinking
```

The `UEDPIE_0` component path exists only while the first Play In Editor session
is running. Restart Entity after entering Play, and update the path if Unreal uses
a different PIE instance number. Unreal Remote Control is intended only for the
editor proof of concept. A packaged interface should use a dedicated runtime
transport and a stable actor lookup instead of an editor object path.

When `ENTITY_PREFER_CLOUD_WHEN_UNREAL=true`, a reachable Unreal Remote Control
server also makes the configured cloud model Entity's first choice. This avoids
competing with Unreal for GPU memory. Closing Unreal automatically restores the
normal local-first order, and local Ollama remains the fallback if cloud inference
fails.

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

Behavioral integration experiments use `tests/entity_sandbox.py`. The sandbox
keeps tasks, conversations, decisions, and learned memories in a temporary
SQLite database. Its recording actuator replaces Calendar, ntfy, speech, and
diagnostic side effects with in-memory records, while still allowing the real
planner, conversation model, and read-only internet research path to be tested.
Do not replace the recording actuator with production actuators in automated
scenario runs.

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
