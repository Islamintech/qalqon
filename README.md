# ScamGuard — Telegram anti-scam moderation bot (Phase 1)

Python + Groq (free LLM) + keyword matching, in an MVC layout.

## Structure

```
scam_guard_bot/
├── main.py                     # entry point — wires everything, starts polling
├── config.py                   # settings from .env
├── models/                     # the "M": data + detection logic
│   ├── verdict.py              #   shared Risk/Verdict types
│   ├── keyword_filter.py       #   fast regex first pass
│   ├── llm_client.py           #   Groq wrapper (returns a Verdict)
│   └── profile_analyzer.py     #   sender profile checks (+phase-2 hooks)
├── views/
│   └── telegram_view.py        # the "V": delete / ban / alert admins
└── controllers/
    └── moderation_controller.py# the "C": escalation brain
```

## Flow per message

1. **Keyword filter** (cheap) → may raise suspicion to FIFTY_FIFTY
2. **Groq LLM** → CLEAN / FIFTY_FIFTY / RED_FLAG
3. Combine (take the worst). CLEAN messages exit here — no profile call, no cost.
4. If suspicious → **check the sender's profile** (bio + photo).
5. **Act only when both message AND profile look bad.** A lone red flag goes to
   the admins for review instead of an auto-ban. This is what keeps real users
   from getting banned by mistake.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in your tokens
python main.py
```

Get the bot token from **@BotFather**, and a free key from
**console.groq.com**. In your group: add the bot, then promote it to admin with
"delete messages" and "ban users" rights — without admin it can't act.

## Important: DRY_RUN

`DRY_RUN=true` (the default) means the bot only logs what it *would* do — no real
deletes or bans. Run it like this for a few days, read the logs, tune the
keywords and the LLM prompt, and only flip it to `false` once the decisions look
right. Auto-banning on day one will catch innocent people.

## Phase 2 (later)

- Download the profile photo → free vision model (HF NSFW/deepfake classifier).
- Read the user's linked channel → scan pinned files for unvalidated `.apk`s and
  suspicious links. Hooks are marked `PHASE 2` in `profile_analyzer.py`.

---

## Phase 2 (added)

Three new signals, wired into the same escalation flow:

**Profile-photo NSFW screening** — `models/vision_client.py`
Downloads the sender's profile photo and runs a free Hugging Face classifier
(`Falconsai/nsfw_image_detection`). Set `HF_TOKEN` in `.env` to turn it on;
leave it empty to skip photo analysis. Verify the model is served on HF's free
tier at build time — their provider setup shifts.

**In-group file scanning** — `models/file_scanner.py`
Catches fake `wallet.apk` / `.exe` files dropped in the chat. A dangerous file
type is removed immediately (no profile confirmation) because the file *is* the
attack. Decides on declared name/type/size only — it never opens the file.

**Linked-channel detection** — `models/channel_analyzer.py`
Reads `chat.personal_chat` to find the channel a user pinned to their profile
and checks its public description for scam terms. Having a linked channel is
normal on its own, so only a scammy description raises risk.

### Phase 2b — deep channel scanning (BUILT, opt-in)

`models/mtproto_scanner.py` reads the recent files inside a user's linked
channel via Telethon and runs each through the file scanner — catching the fake
`.apk` a scammer hosts in their channel rather than posts in chat.

It needs a **user session** (the Bot API can't do this):

1. Get `api_id` / `api_hash` from https://my.telegram.org (use a DEDICATED
   account — automating your main account risks a ban).
2. Put them in `.env` as `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`.
3. Create the session once, interactively:
   ```bash
   python scripts/telethon_login.py
   ```
4. Restart the bot. It connects non-interactively from then on.

Leave the api creds empty and this stays off — everything else runs unchanged.

**Safety by design:** the deep scan only runs for users who are *already*
suspicious (the profile check only fires on non-clean messages), handles
Telegram's FloodWait, and caches each channel's result for `MTPROTO_CACHE_TTL`
seconds so a repeat scammer is never rescanned.

### New env vars

```
TELEGRAM_API_ID=            # from my.telegram.org
TELEGRAM_API_HASH=
MTPROTO_SESSION=scamguard_user
MTPROTO_SCAN_LIMIT=40       # messages to check per channel
MTPROTO_CACHE_TTL=21600     # 6h — don't rescan the same channel
```

---

## Phase 3 — memory, escalation and admin control

Phases 1–2 judged every message in isolation: a serial scammer on their fifth
attempt looked exactly like a first-time poster, and the "⚠️ Review" alerts went
to admins who had no way to act on them. Phase 3 fixes both.

### The decision is now a separate, pure layer

`models/policy.py` holds the whole escalation matrix as a function of
`(content, profile, strikes, trusted)` with no Telegram and no I/O in it. This
is the safety-critical part of the bot, so it is exhaustively unit-tested.

```
content \ profile | CLEAN      FIFTY_FIFTY   RED_FLAG
------------------+------------------------------------
CLEAN             | NONE       NONE          NONE      <- profile alone is never an offence
FIFTY_FIFTY       | REVIEW     REVIEW        DELETE
RED_FLAG          | DELETE     BAN           BAN
```

Then two adjustments, **in this order**:

1. **Strikes** — every `STRIKES_TO_ESCALATE` *active* strikes moves the response
   one step up the ladder (`REVIEW → DELETE → BAN`). Only actions that removed
   a message earn a strike; a REVIEW alone never snowballs into a ban. Strikes
   expire — see below.
2. **Trust** — a member who has posted `TRUST_AFTER_MESSAGES` times without ever
   earning a strike is capped at REVIEW. The cap is applied *after* escalation
   on purpose, so old strikes can't auto-ban someone who has since settled.

### Memory (`models/store.py`)

SQLite via the stdlib, off the event loop with `asyncio.to_thread` — no new
dependency. Per `(chat, user)` it remembers messages seen, strikes, and status
(`normal` / `whitelisted` / `banned`), plus an event log for `/status`.

Tenure and strike counts are also passed to the LLM as a short sender prior — a
brand-new account posting an investment pitch is treated differently from a
long-standing member using the same words. The prompt forbids raising risk on
context alone; the message still has to justify the verdict.

### Strike decay

A strike stops counting toward escalation after `STRIKE_DECAY_DAYS` (default 30).
Two reasons this matters:

- One bad week two years ago should not still be pushing someone toward a ban.
- Without decay the count only ratchets upward, so *every* long-lived member
  eventually accumulates enough noise that one borderline message auto-bans them.

Strikes are therefore stored as timestamped rows, not a bare counter. Each user
has two numbers:

| | decays | used for |
|---|---|---|
| **active strikes** | yes | escalation, and the trust check |
| **lifetime strikes** | never | admin context in `/status` |

`/status` shows both, plus when the oldest active strike drops off:

```
👤 user 12345 (@someone) in -1001234567890
messages seen: 84
strikes: 2 active / 5 lifetime (oldest expires in 25.0d)
status: normal
```

Decay is what makes forgiveness possible: once a user's strikes age out, a clean
run of `TRUST_AFTER_MESSAGES` messages earns them established-member status
again, capping them back at REVIEW. `/forgive` does the same thing immediately,
and deliberately keeps the lifetime total so an admin can still see the history.
Set `STRIKE_DECAY_DAYS=0` to disable ageing entirely.

Expired rows are deleted opportunistically on each new strike, and once at
startup (`prune_strikes`) since a quiet chat would never trigger the former.

**Upgrading an existing database:** the schema is versioned and migrates itself
on first start. A pre-decay DB's counter is backfilled as timestamped rows dated
to each user's `last_seen` — erring recent, so shipping this doesn't silently
forgive everyone you had already flagged.

### Admin control

Every alert now carries **🚫 Ban / 👌 Ignore / ✅ Whitelist** buttons (and
♻️ Unban on an alert for someone already banned). Tapping one edits the alert to
record who resolved it and removes the buttons, so two admins can't act twice on
the same case. **Ignore clears the user's strikes** — a false positive must not
leave a mark that escalates the next message.

Commands (in the group, or from `ADMIN_CHAT_ID`):

```
/stats                 totals for this chat
/status <user_id>      one user's record + recent events
/whitelist <user_id>   trust a user, clears their strikes
/unwhitelist <user_id> remove that trust
/forgive <user_id>     reset strikes only
/unban <user_id>       lift a ban
/dryrun [on|off]       show or flip the safety switch, no restart needed
```

Authorization is checked on **every** entry point, buttons included — the bot
holds ban rights, so an unguarded command would hand that power to anyone who
can type. A caller qualifies by writing from `ADMIN_CHAT_ID`, or by actually
being an admin/owner of the group (verified live via `get_chat_member`).

### Cost and coverage fixes

- **Keyword filter runs before the LLM**, as phase 1 intended.
- **Identical text is cached** for `LLM_CACHE_TTL` seconds, so a spammer posting
  the same line 30 times costs one call. Context-flavoured calls aren't cached —
  one user's history must not colour another's verdict.
- **Short chatter skips the model.** Under 12 characters with no link, mention
  or keyword hit ("ok", "thanks", "👍") cannot carry a scam pitch. Anything with
  a link goes to the model however short it is.
- **All attachment types are scanned**, not just documents — a fake APK sent as
  a video was previously walking straight through.
- **New joiners are screened.** A red-flag profile earns a heads-up to admins,
  never a ban: a profile is not an offence.
- `Verdict.worst()` no longer raises on an empty call.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

193 tests, no network and no real Telegram — `tests/conftest.py` has the fakes.
Coverage is deliberately weighted toward the parts that can hurt someone: the
full escalation matrix, trust-vs-strike ordering, strike decay (including the
window boundary and the v1 migration), admin authorization, the dry-run
guarantee, and — for the link checker — as many false-positive cases as
detection cases, since a link checker that flags ordinary URLs is worse than
none at all.

`tests/test_bypasses.py` is a regression suite: one test per hole that was once
open, each naming the bypass it closes.

### New env vars

```
DB_PATH=scamguard.db
STRIKES_TO_ESCALATE=2      # strikes per escalation step
TRUST_AFTER_MESSAGES=25    # clean messages before a member is "established"
LLM_CACHE_TTL=900          # seconds to reuse a verdict for identical text
STRIKE_DECAY_DAYS=30       # a strike stops counting after this long (0 = never)
```

---

## Phase 4 — closing the bypasses, links, raids

### Three ways in that are now shut

**Edited messages.** The bot was not subscribed to edit updates at all, so
posting "hi", letting it clear, then editing in the pitch was a complete
bypass. Edits are now moderated like any other message — and deliberately do
*not* increment the sender's message count, or editing one message repeatedly
would farm tenure toward the trust threshold.

**Captions.** `filters.TEXT` does not match captions, so a photo carrying the
scam pitch in its caption reached only the attachment handler, which judged the
(perfectly clean) `.jpg` and never read a word.

**Failing open under load.** `LLMClient` turned every exception into a CLEAN
verdict. A 20-account raid fired 20 simultaneous Groq calls, hit the free-tier
rate limit, and every 429 became "this message is fine" — the bot went blind
during exactly the attack it exists to stop, and the logs looked calm. Now:

- a semaphore caps in-flight calls so we stop rate-limiting ourselves
- 429s and 5xx are retried with jittered exponential backoff
- when the model truly cannot be reached the verdict is marked `degraded`

`degraded` is the important part. It keeps "the model said clean" distinct from
"we never got an answer", so the bot can keep moderating on keywords, mark the
alert as impaired, and warn admins **once per 30 minutes** rather than either
staying silent or flooding the queue with one notice per message.

### One handler, not several

Text, captions and attachments are now a single entry point. PTB runs only the
*first* matching handler in a group, so splitting them meant a captioned `.apk`
got judged on one signal and never the other. Both are gathered; the harsher
outcome wins.

### Link analysis (`models/link_analyzer.py`)

Scam links are the actual payload of most Telegram scams and nothing was looking
at them. The design constraint: **sharing links is normal**. "Contains a URL" is
not a signal, so what this looks for is *structural deception*:

| pattern | example | risk |
|---|---|---|
| credentials-in-URL | `binance.com@evil.xyz` | RED |
| punycode / homograph | `xn--binnce-mva.com` | RED |
| typosquat (≤1 edit) | `binanace.com` | RED |
| visual look-alike | `metarnask.io` (`rn`→`m`) | RED |
| brand as decoration | `binance.security-verify.top` | RED |
| shortener | `bit.ly/…` | 50/50 |
| raw IP | `http://51.20.3.4/wallet` | 50/50 |

Nothing is ever fetched: making the bot follow user-supplied links would hand
anyone in the group an SSRF primitive and a way to confirm the bot is watching.
The extracted hosts are also handed to the LLM so it need not parse URLs out of
prose. Extra domains can be banned outright via `BLOCKED_DOMAINS`.

### Raid defence (`models/burst_detector.py`, `views/alert_batcher.py`)

**Flood** — one account posting `FLOOD_MESSAGES` in `FLOOD_WINDOW` seconds.
Content-blind, so no rewording evades it, and free.

**Raid** — `RAID_USERS` *different* new accounts posting within a minute. One
chatty newcomer is not a raid; fifteen at once is.

Two deliberate restraints here:

- **Pace never bans.** A burst is capped at DELETE and earns no strike. Someone
  splitting one thought across ten lines is not a scammer, and an innocent fast
  poster must not accumulate strikes that escalate a later message. Content
  evidence can still ban them; typing speed cannot.
- **A raid does not tighten punishment.** A raid is when false positives are
  most likely (a lively argument looks like a burst), and mass-banning real
  members is worse than a slow queue. Raid state changes how alerts are
  *delivered*, not how users are judged.

**Alert coalescing.** Past `ALERT_BURST_THRESHOLD` alerts in 30s the batcher
switches to one digest per `ALERT_DIGEST_INTERVAL`. A digest carries no buttons
— thirty button sets is not a renderable message, and a bulk "ban all" control
is the last thing that should exist during a raid. The digest names the users so
an admin can act deliberately with `/status`. Pending digests are flushed at
shutdown so a raid's last alerts are not lost with the process.

### Preflight — the part fakes cannot test

Everything else is tested against fakes, which cannot tell you whether your
token is valid or whether Telegram will actually let the bot delete anything.

```bash
python scripts/preflight.py                 # credentials only
python scripts/preflight.py -1001234567890  # also verify a specific group
```

It checks the token, the admin chat is reachable, that the bot is an admin with
delete + ban rights, that **privacy mode is off** (with privacy mode on a bot
sees only commands, so it would sit there moderating nothing — the most commonly
missed setup step), that Groq answers, and the optional HF / MTProto pieces. It
is read-only apart from one test message, and exits non-zero on any blocker.

### New env vars

```
AUTONOMY=assisted          # report | assisted | autonomous
DIGEST_INTERVAL=21600      # seconds between digest summaries (6h)
BLOCKED_DOMAINS=           # comma-separated, always red-flagged
FLOOD_MESSAGES=5           # messages per user...
FLOOD_WINDOW=8             # ...within this many seconds = a flood
RAID_USERS=5               # distinct new accounts in 60s = a raid
ALERT_BURST_THRESHOLD=5    # alerts in 30s before digesting
ALERT_DIGEST_INTERVAL=60   # seconds between digests
```

---

## Runtime requirements

**python-telegram-bot 22.8+ is required on Python 3.14.** Version 21.x calls
`asyncio.get_event_loop()` inside `run_polling()`, which raises
`RuntimeError: There is no current event loop` on 3.14 — the bot imports fine
and then dies on start. This is pinned in requirements.txt.

**httpx request logging is silenced** in `main.py`. Telegram puts the bot token
in the URL path, and httpx logs every request URL at INFO — so the default
configuration printed the bot token on every poll. Anyone reading the logs could
take over the bot.

## Only ever run ONE instance

Telegram allows a single `getUpdates` poller per bot token. A second instance
causes `telegram.error.Conflict`, and the two fight over the update stream —
each seeing only some messages, and both acting on the ones they do see:
duplicate bans, doubled strikes, two alerts per message.

`main.py` registers a global error handler that treats Conflict as fatal and
shuts down rather than looping. Without an error handler at all, PTB logs a
full traceback for every transient network blip and repeats it at the poll
interval until the log is unusable — routine `NetworkError`/`TimedOut` are now
logged as one-line warnings, since PTB retries those itself.

## Setup checklist

Three credentials, four settings. Work top to bottom.

**1. Bot token** — @BotFather → `/newbot`. Then, in @BotFather:
`/setprivacy` → your bot → **Disable**. With privacy mode ON the bot receives
only commands, so it would sit in the group moderating nothing. This is the most
commonly missed step.

**2. Groq key** — console.groq.com, free. Model `llama-3.3-70b-versatile`
(current, and the documented replacement for several retired models).

**3. HF token** *(optional — profile-photo screening)* — must be a
**fine-grained** token with the **"Make calls to Inference Providers"**
permission. A plain read token returns 401.

**4. Two chats:**
- the group you want moderated — add the bot, then promote it to admin with
  **delete messages** and **ban users**
- a separate private group for alerts — add the bot

**5. Their ids:**
```bash
python scripts/chat_id.py     # post in each chat; it prints the ids
```
Put the ALERT group's id in `ADMIN_CHAT_ID`. Without it every alert degrades to
a log line and the inline buttons never reach a human.

**6. Verify before trusting it:**
```bash
python scripts/preflight.py <moderated_group_id>
```
Checks the token, privacy mode, admin rights, the alert chat, Groq, and — by
actually classifying a test image — photo screening. Exits non-zero on any
blocker.

**7. Leave `DRY_RUN=true`** for a few days and read the logs before going live.

## A note on the two providers

They do different jobs and do not overlap:

| provider | model | judges |
|---|---|---|
| Groq | `llama-3.3-70b-versatile` | message **text** |
| HF | `Falconsai/nsfw_image_detection` | the **profile photo** |

`Falconsai/nsfw_image_detection` is HF's own documented example model for
image-classification, and returns a calibrated 0–1 score — which is what
`NSFW_THRESHOLD` and the borderline band depend on. A general vision LLM would
have to self-report that number, which is far less reliable, so the split is
deliberate rather than accidental.

**Endpoint history worth knowing:** HF folded serverless inference into
Inference Providers, and the old `api-inference.huggingface.co` host no longer
resolves *at all*. Any code still pointing there fails DNS on every single call.
Requests now go to `https://router.huggingface.co/hf-inference/models/<model>`.
Because that moved once it can move again, so a vision failure is now reported
as `degraded` and warned to admins rather than silently returning CLEAN — a
screening step that is quietly dead is worse than one switched off, because it
still looks like it is working.

## Alerts show every signal

`Verdict.worst()` collapses several detectors into one verdict, so only the
winner's reason used to reach the admin. That hid whether a single detector
fired or three agreed independently — which is the difference between a guess
and a confirmation, and only the reviewer can weigh it.

Composite verdicts now carry their inputs in `components`, and alerts print the
full breakdown:

```
content=RED_FLAG
  llm      RED_FLAG     crypto airdrop pitch with suspicious link
  keyword  CLEAN        no pattern matched
  link     RED_FLAG     'binanace.com' is 1 character from 'binance'
profile=CLEAN
  profile  CLEAN        no suspicious bio terms
  vision   CLEAN        photo ok score=0.00
  channel  CLEAN        no linked channel
decision=DELETE — content=RED_FLAG(llm); profile=CLEAN
```

A detector that ran and found nothing is listed too — that it ran is itself
information. A signal that could not run is marked `CLEAN?`, so a missing
detector never reads as a clean result. Components are flattened one level
(profile → vision → … would otherwise nest without limit) and excluded from
equality, so verdicts still compare on their substance.

## Group admins are skipped

Telegram does not let a bot delete or ban a chat admin. Moderating them
therefore produced alerts nobody could act on — and unactionable alerts are
worse than none, because they train whoever reads the queue to ignore it.

The check runs before any analysis, so a skipped admin costs no LLM call. The
admin **list** is fetched once per chat and cached (`ADMIN_CACHE_TTL`, default
300s) — checking per user would mean an API round-trip on every message in the
group.

Anonymous admins and channel posts (`sender_chat` set) are skipped too: there is
no user account to judge or act on.

Two deliberate choices in `AdminCache`:

- **A failed lookup reports "not an admin"**, so the message is moderated
  normally. Failing the other way would silently switch moderation off for the
  whole group whenever Telegram hiccups.
- **Failures are not cached**, or one blip would disable the exemption for a
  full TTL.

Set `SKIP_GROUP_ADMINS=false` to moderate everyone — useful when testing with
your own admin account, which is otherwise skipped.

## Running across many groups

Phase 1 assumed a person reads every borderline case. That holds for one group
and quietly fails for twenty: nobody empties a queue that never empties, so
"route it to a human" becomes "ignore it" — while the scam message stays up the
whole time. Worse, a wall of unread alerts *looks* like oversight is happening.

So the question stops being "should a human approve this?" and becomes **"is
this worth interrupting a human for?"** — which depends on whether the decision
is already made, reversible, and costly if wrong:

| decision | already done? | interrupts a human? | why |
|---|---|---|---|
| `REVIEW` | no | **yes** | ambiguous; somebody actually has to decide |
| `BAN` | yes | **yes** | reversible in one tap — but only if seen |
| `DELETE` | yes | no → digest | message gone, user stays; low stakes |

### Autonomy levels (`AUTONOMY`)

- **`report`** — never act, alert everything. Safe, and useless at scale: the
  scam stays up until someone reads the alert.
- **`assisted`** *(default)* — act as the policy decided; interrupt for REVIEW
  and BAN, digest the rest.
- **`autonomous`** — act as the policy decided; interrupt for nothing, digest
  everything.

Autonomy governs **notification**, not judgement — the escalation matrix stays
the single place where severity is decided. The one exception is `report`,
which downgrades anything that would touch the chat to REVIEW.

### Digests (`DIGEST_INTERVAL`, default 6h)

Routine handled actions accumulate and go out as one message, **grouped by
chat** — with twenty groups a flat timeline tells you nothing about *which*
community has a problem:

```
📋 ScamGuard digest — last 6.0h

"Crypto Signals" (-1001)
  6× BAN, 9× DELETE
  • BAN @scammer0 — content=RED_FLAG(llm); profile=RED_FLAG
  …and 12 more

"Book Club" (-1002)
  1× DELETE
  • DELETE @someone — link: typosquat 'binanace.com'
```

A quiet period sends **nothing** — a digest that says "nothing happened" every
six hours is training you to ignore it. Pending entries are flushed on shutdown
so a restart never silently discards a partial period, and `/digest` forces one
early.

Note this is separate from `AlertBatcher`, which is a pressure valve for when
*live* alerts arrive faster than a human can read them. The digest is the normal
path for things nobody needs to see immediately.

### Still worth doing

- A `/queue` command to re-list unresolved review alerts after a restart.
