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
   Conversational model output streams into phrase-buffered TTS, so speech can
   begin while the remainder of the answer is still being generated.
5. Conversations, decisions, tasks, goals, and selected memories persist in
   `agent/entity_memory.db`.

`agent.lifecycle.Lifecycle` publishes renderer-neutral state events for visual
clients. Current states include booting, wake detection, listening, transcribing,
thinking, tool activity, speaking, errors, idle, and shutdown. During speech,
the audio player also publishes a normalized output envelope so the 2D and 3D
orbs react to the voice actually reaching the speakers.

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

Direct questions such as “How long is the drive to the airport?” use the
configured home address and routing provider. “From A to B” requests use both
explicit locations. Route questions never fall back to an LLM-generated time;
if the provider cannot verify the route, Entity says so instead of guessing.

Weather uses Open-Meteo's current, hourly, and daily forecasts. Configure exact
coordinates when Entity has a usual home location; they avoid ambiguous place
names, while explicit requests such as “weather in Raleigh” still use ranked
geocoding results. Outfit questions are deterministic weather requests and
include apparent temperature range, rain probability and timing, wind and gusts,
UV exposure, and practical clothing guidance.

```dotenv
ENTITY_WEATHER_LOCATION=Marvin, North Carolina
ENTITY_WEATHER_LATITUDE=34.99182
ENTITY_WEATHER_LONGITUDE=-80.81479
```

Current-location detection can recognize explicitly mapped Wi-Fi connection
profiles locally. Entity compares only the active NetworkManager connection name
against `.env`; it does not scan, retain, or upload nearby access-point BSSIDs.
“Where am I?” reports both the estimate and its method. An optional public-IP
fallback provides only city-level accuracy and is disabled by default because it
sends a request to a third-party service.

“Give me my briefing,” “morning update,” and similar requests build a briefing
immediately. The same briefing can be delivered once each morning through speech
and the configured notification provider. It combines weather and clothing
advice, calendar events, reminders, the latest world-model summary, direct news
headlines, and explicitly labeled non-factual prediction-market signals.

Future requests compose the alarm and briefing as one persisted task. For
example, “Wake me at 6 AM tomorrow and deliver the daily intelligence briefing”
builds the briefing at 6 AM from then-current information instead of delivering
it when the request is made. The task survives an Entity restart.

For reliable alarms, run Entity as the supervised user service in
`deploy/entity.service`, enable it for the user default target, and enable user
lingering. The service restarts after failures and starts without requiring an
open terminal. A computer that is powered off cannot synthesize speech; after a
long outage Entity sends the overdue briefing as a notification rather than
speaking unexpectedly hours late.

```dotenv
ENTITY_DAILY_BRIEFING_ENABLED=true
ENTITY_DAILY_BRIEFING_HOUR=7
ENTITY_DAILY_BRIEFING_MINUTE=30
ENTITY_DAILY_BRIEFING_GRACE_HOURS=4
```

“What have you learned?” reads Entity's actual durable memory and public
world-model stores instead of asking the language model to improvise an answer.
Add “about …” to filter it, for example “What have you learned about Iran?”
Entity labels uncorroborated evidence and describes world-model conclusions as
provisional.

Ordinary planning and conversation also receive concise relevant world-model
evidence and recent runtime observations. External material is explicitly
labeled as data rather than instructions, and low-level intelligence collection
activity remains silent unless a validated delivery policy calls for a user
notification.

Keep `.env`, OAuth credentials, tokens, and `agent/entity_memory.db` private. They
are ignored by Git.

Entity can run with one of three live visual interfaces. The 2D and 3D modes
start a private localhost server, open the interface in a browser, and stream
lifecycle events to it. Unreal sends the same events to an Unreal Remote Control
Preset without blocking Entity's runtime.

```bash
.venv/bin/python main.py 2d
.venv/bin/python main.py 3d
.venv/bin/python main.py unreal
```

The 2D interface has no build dependencies. The 3D interface requires Node.js
18 or newer. Entity installs the locked dependencies when they change and
builds the interface when 3D mode starts. The default balanced renderer caps
pixel density, uses a single shadow source, and avoids screen-space transmission
passes that can create rectangular artifacts. Append `?quality=low` to the 3D
URL on a software-rendered machine or `?quality=high` when extra GPU headroom is
available. Set the default and browser behavior in `.env`:

```dotenv
ENTITY_VISUAL_MODE=2d
ENTITY_VISUAL_HOST=127.0.0.1
ENTITY_VISUAL_PORT=8765
ENTITY_VISUAL_OPEN_BROWSER=true
```

Entity also has an optional, read-only world-intelligence foundation. It runs
independently from conversational research, collects normalized public evidence
from configured authoritative sources, keeps immutable document versions and
an access audit, and serves a localhost dashboard. A deterministic understanding
layer clusters related reports into evolving situations, extracts structured
claims, tracks source-weighted confidence, preserves contradictions, supersedes
outdated single-source claims without deleting them, and writes immutable model
snapshots and rolling briefings. Optional read-only Gmail and Outlook connectors
can add private mail after explicit OAuth authorization. Social sources remain
low-confidence discovery signals. Entity may create explicitly labeled,
evidence-linked experimental forecasts; it never treats a forecast as a fact
or issues a forecast as an autonomous alert.

```dotenv
ENTITY_INTELLIGENCE_ENABLED=true
ENTITY_INTELLIGENCE_DASHBOARD_HOST=127.0.0.1
ENTITY_INTELLIGENCE_DASHBOARD_PORT=8770
ENTITY_FORECAST_MAX_ACTIVE=12
ENTITY_FORECAST_PER_CYCLE=2
ENTITY_USGS_ENABLED=true
ENTITY_EONET_ENABLED=true
ENTITY_RELIEFWEB_ENABLED=true
ENTITY_RELIEFWEB_APPNAME=
ENTITY_GDACS_ENABLED=true
ENTITY_WHO_OUTBREAKS_ENABLED=true
ENTITY_NWS_ALERTS_ENABLED=true
ENTITY_CISA_KEV_ENABLED=true
ENTITY_GITHUB_ADVISORIES_ENABLED=true
ENTITY_NOAA_SPACE_WEATHER_ENABLED=true
# NASA FIRMS is opt-in and requires a free MAP_KEY.
ENTITY_FIRMS_ENABLED=false
ENTITY_FIRMS_MAP_KEY=
ENTITY_WORLD_BANK_ENABLED=true
ENTITY_WORLD_BANK_COUNTRIES=WLD
ENTITY_WORLD_BANK_INDICATORS=FP.CPI.TOTL.ZG,NY.GDP.MKTP.KD.ZG,SL.UEM.TOTL.ZS
ENTITY_FRED_ENABLED=false
ENTITY_FRED_API_KEY=
ENTITY_FRED_SERIES=
ENTITY_NEWS_ENABLED=true
ENTITY_NEWS_RSS_FEEDS=BBC News - World|https://feeds.bbci.co.uk/news/world/rss.xml|0.85||NPR - World|https://feeds.npr.org/1004/rss.xml|0.85||UN News|https://news.un.org/feed/subscribe/en/news/all/rss.xml|0.90||Deutsche Welle - World|https://rss.dw.com/rdf/rss-en-all|0.82||Al Jazeera|https://www.aljazeera.com/xml/rss/all.xml|0.78||France 24|https://www.france24.com/en/rss|0.80||The Guardian - World|https://www.theguardian.com/world/rss|0.80
ENTITY_POLYMARKET_ENABLED=true
# Optional lower-trust global news discovery; separate queries with ||.
ENTITY_GDELT_ENABLED=false
ENTITY_GDELT_QUERIES=earthquake OR tsunami||outbreak OR epidemic||coup OR sanctions
```

When Entity starts, the dashboard is available at
`http://127.0.0.1:8770/`. The intelligence service can also run without the
voice runtime:

```bash
.venv/bin/python -m agent.intelligence
```

ReliefWeb requires an approved application name. When none is configured, its
connector remains registered but disabled. USGS, NASA EONET, GDACS, WHO Disease
Outbreak News, U.S. NWS, CISA KEV, GitHub Security Advisories, NOAA Space
Weather alerts, and selected World Bank indicators require no API key. NASA
FIRMS and FRED require operator-provided keys and are disabled until supplied.
GDELT is also free and global, but its results inherit the varying reliability
of the publishers it indexes. The dashboard binds only to localhost by default.

Direct news collection uses publisher-supplied RSS or Atom metadata rather than
scraping full articles. `ENTITY_NEWS_RSS_FEEDS` entries use
`Publisher name|feed URL|baseline credibility`, separated by `||`; an explicitly
empty value disables all default feeds. BBC World, NPR World, UN News, Deutsche
Welle, Al Jazeera, France 24, and The Guardian World are configured by default,
and each document retains its publisher, domain, feed URL, article link, byline,
and feed categories.

Polymarket collection uses its public Gamma market-data API and needs no account,
API key, wallet, or trading permissions. Entity polls active markets by 24-hour
volume and retains outcome probabilities, resolution metadata, liquidity, and
volume. It contains no order or wallet code.

The dashboard separates observations from interpretation. Each situation shows
its linked evidence and source count, provisional confidence, active or contested
claims, geographic position when supplied by the source, and confidence history.
Confidence means support within the evidence
Entity has collected; it is not a declaration that a claim is true. Polymarket
prices appear as separately labeled forecast signals: they are versioned when
probabilities change, but never create factual claims, corroborate a report, or
change publisher reputation. The initial analyzer is deliberately deterministic
(`deterministic-v1`) so every model change
can be reproduced and traced to an immutable source-document version.

Experimental forecasts run continuously with the intelligence worker. The
thinking model proposes a bounded, falsifiable outcome, probability, deadline,
and resolution criterion from source-linked evidence. Once due, later evidence
is used to resolve it as yes or no; the system records a Brier score and feeds
aggregate calibration back into subsequent forecasts. Forecasts remain separate
from factual claims and are shown in the dashboard as experimental.

Collection and analysis run continuously in the background whenever the service
is enabled. While the conversational interface is otherwise idle, both web
visuals show gold `intelligence_collecting` activity during source polling and
purple `world_model_updating` activity while evidence is clustered into
situations and claims. Foreground listening, thinking, acting, and speaking
always take precedence; completion only returns the visual to idle if the
intelligence cycle still owns the display.

Publisher reputation is calibrated separately from connector provenance. Public
Telegram channels and X accounts receive their own identities. After a maturity
delay, later independent high-baseline evidence may confirm an earlier report;
robustly superseded claims or deleted reports without corroboration may count
against it. Unconfirmed reports remain unresolved rather than being labeled
false. Scores use a conservative prior, can move only within a configured bound,
and every outcome and score change is retained in an audit history. Private mail
never participates. Inspect current results at
`/api/intelligence/reputations` on the localhost intelligence dashboard.

### Read-only Gmail and Outlook setup

Entity can ingest one Gmail account and one Outlook/Microsoft 365 account through
delegated OAuth. It never requests mail write/send permissions and does not accept
account passwords. OAuth credentials and revocable token caches stay local, use
private file permissions, and are ignored by Git. Private mail also forces the
intelligence dashboard to remain on a loopback address.

Install the current locked dependencies first:

```bash
.venv/bin/pip install -r requirements.txt
```

For Gmail, create a Google Cloud project, enable the Gmail API, configure its
OAuth consent screen, and create an OAuth client of type **Desktop app**. Download
the client JSON to `agent/google_gmail_credentials.json`. If the consent screen is
in testing mode, add your Gmail address as a test user. Then configure:

```dotenv
ENTITY_GMAIL_ENABLED=true
ENTITY_GMAIL_CREDENTIALS_PATH=agent/google_gmail_credentials.json
ENTITY_GMAIL_TOKEN_PATH=agent/google_gmail_token.json
ENTITY_GMAIL_QUERY=newer_than:7d -in:spam -in:trash
```

For Outlook, register an application in Microsoft Entra ID. Select the supported
account types you intend to use, add a **Mobile and desktop application** redirect
URI of `http://localhost`, and grant the delegated Microsoft Graph permission
`Mail.Read`. Do not create a client secret. Copy its Application (client) ID:

```dotenv
ENTITY_OUTLOOK_ENABLED=true
ENTITY_OUTLOOK_CLIENT_ID=your-application-client-id
ENTITY_OUTLOOK_TENANT=common
ENTITY_OUTLOOK_TOKEN_CACHE_PATH=agent/outlook_mail_token_cache.json
ENTITY_OUTLOOK_FOLDER=inbox
```

Choose how much mail content is retained locally:

```dotenv
# Safer default: subject, sender, provider preview, and metadata only.
ENTITY_MAIL_STORE_BODY=false
```

Setting `ENTITY_MAIL_STORE_BODY=true` additionally stores a normalized body copy,
capped at 20,000 characters per message. Attachments are never downloaded. After
the provider registrations and environment values are ready, authorize both:

```bash
.venv/bin/python -m agent.intelligence.mail_auth both
```

Each provider opens its official consent page in the system browser. Restart
Entity after authorization. To revoke access, revoke Entity in the corresponding
Google or Microsoft account security page and remove its local token file.

### Read-only X public-signal setup

Entity can collect public posts from an explicit account allowlist and X recent
search queries using application-only authentication. This connector contains no
write endpoints and cannot post, like, follow, bookmark, read direct messages, or
access a private home timeline. X data is treated as a low-confidence social
signal; repetition across X posts does not become independent corroboration.

The X API is pay-per-use. Before enabling it, create an app in the X Developer
Console, purchase only the credits you intend to use, and configure a spending
limit. Generate the app's Bearer Token and configure:

```dotenv
ENTITY_X_ENABLED=true
ENTITY_X_BEARER_TOKEN=your-app-only-bearer-token
ENTITY_X_USERNAMES=Reuters,AP,NOAA,NHC_Atlantic
ENTITY_X_SEARCH_QUERIES=(earthquake OR tsunami) lang:en -is:retweet||(wildfire OR evacuation) lang:en -is:retweet
ENTITY_X_POLL_SECONDS=900
ENTITY_X_MAX_RESULTS=25
```

Handles are comma-separated; recent-search queries are separated with `||`.
Entity combines configured handles and topics into cost-bounded recent searches,
requests only posts newer than its saved cursor, and deduplicates posts before
storage. The result cap is per collection cycle. Keep the Bearer Token only in
`.env`; it is a secret even though the connector can access public data only.

### Read-only Telegram public-channel setup

Telegram is a useful worldwide early-signal source, but it is not evidence of
truth by itself. Entity uses an explicit allowlist, accepts public broadcast
channels only, stores text and captions without downloading media, preserves
captured revisions and detected deletion tombstones, and assigns the source a
low initial credibility requiring independent corroboration. Private chats,
private channels, groups, contacts, and saved messages are rejected.

Install the locked dependencies, then place the `api_id` and `api_hash` obtained
from `my.telegram.org` in `.env`. Do not enable collection yet:

```dotenv
ENTITY_TELEGRAM_ENABLED=false
ENTITY_TELEGRAM_API_ID=your-numeric-api-id
ENTITY_TELEGRAM_API_HASH=your-api-hash
ENTITY_TELEGRAM_SESSION_PATH=agent/private/telegram_entity
ENTITY_TELEGRAM_CHANNELS=
ENTITY_TELEGRAM_POLL_SECONDS=120
ENTITY_TELEGRAM_MESSAGES_PER_CHANNEL=50
ENTITY_TELEGRAM_DELETION_SCAN_SIZE=100
```

Authorize locally. The phone number, one-time code, and optional two-step
password are requested interactively and must never be placed in `.env`:

```bash
.venv/bin/python -m agent.intelligence.telegram_auth authorize
```

The local Telethon session contains an account authorization key. It is excluded
from Git and restricted to the local user, but it is not inherently encrypted at
rest; full-disk encryption provides stronger protection. Telegram does not offer
a public-channels-only or read-only scope for user sessions: Entity's connector
contains no write operations and rejects non-public targets, but the session key
itself represents the account more broadly. A dedicated account with no private
conversations is strongly recommended. Revoking that Telegram session invalidates
it.

After authorization, list only eligible public channels already followed by the
account:

```bash
.venv/bin/python -m agent.intelligence.telegram_auth channels
```

Review the result, add selected usernames without `@` to the comma-separated
`ENTITY_TELEGRAM_CHANNELS` value, then set `ENTITY_TELEGRAM_ENABLED=true` and
restart Entity. Entity rescans recent messages for edits and checks a rolling ID
window for deletions. Increasing `ENTITY_TELEGRAM_DELETION_SCAN_SIZE` improves
coverage at the cost of more API reads. Captured originals remain in immutable
document versions when a deletion is detected.

Every Telegram item retains `translation_status=pending`; automatic multilingual
translation is the next processing-stage integration rather than part of the
collector. Private mail is excluded from public understanding and source scoring.

For Unreal mode, enable Remote Control and configure:

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
.venv/bin/python main.py 2d
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
- `agent/intelligence/`: evidence storage, situation analysis, worker, and dashboard
- `agent/connectors/`: read-only public-source adapters
- `agent/observers/`: background event producers
- `agent/actuators/`: controlled external actions
- `agent/routes.py`, `agent/weather.py`, `agent/research.py`: network tools
- `agent/identity.md`: assistant identity and capability contract
