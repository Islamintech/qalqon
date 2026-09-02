"""Central configuration. All secrets come from environment variables."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")

    # Groq model. Model strings change and the docs lag behind the API — the
    # authoritative list is GET https://api.groq.com/openai/v1/models with your
    # own key, because availability differs per account.
    #
    # gpt-oss-safeguard-20b is purpose-built for safety classification and is
    # the best-calibrated of the available models on AMBIGUOUS messages, which
    # is what decides the false-positive rate: it returns FIFTY_FIFTY (-> human
    # review) where the general models jump to RED_FLAG (-> action).
    # openai/gpt-oss-120b is the stronger general alternative.
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-safeguard-20b")

    # Free Hugging Face token for profile-photo NSFW screening (phase 2).
    # Leave empty to skip photo analysis entirely.
    hf_token: str = os.getenv("HF_TOKEN", "")
    nsfw_threshold: float = float(os.getenv("NSFW_THRESHOLD", "0.75"))

    # Where to send moderation alerts (an admin-only channel or group id).
    admin_chat_id: str = os.getenv("ADMIN_CHAT_ID", "")

    # Phase 2b — MTProto deep channel scanning (Telethon, user session).
    # Leave the api creds empty to keep this off; the bot runs fine without it.
    mtproto_api_id: str = os.getenv("TELEGRAM_API_ID", "")
    mtproto_api_hash: str = os.getenv("TELEGRAM_API_HASH", "")
    mtproto_session: str = os.getenv("MTPROTO_SESSION", "qalqon_user")
    mtproto_scan_limit: int = int(os.getenv("MTPROTO_SCAN_LIMIT", "40"))
    mtproto_cache_ttl: int = int(os.getenv("MTPROTO_CACHE_TTL", "21600"))

    # Phase 3 — memory, strikes and trust.
    db_path: str = os.getenv("DB_PATH", "qalqon.db")
    # How many strikes before the response escalates one step (REVIEW->DELETE
    # ->BAN). Lower = harsher on repeat offenders.
    strikes_to_escalate: int = int(os.getenv("STRIKES_TO_ESCALATE", "2"))
    # Messages a member must post, strike-free, before they are "established"
    # and can no longer be auto-banned over a single message.
    trust_after_messages: int = int(os.getenv("TRUST_AFTER_MESSAGES", "25"))
    # Whether a member with NO prior strikes can be banned outright. Off by
    # default: the commonest way to score FIFTY_FIFTY on a profile is "no
    # profile photo", which describes most newcomers, so one LLM misfire could
    # remove a genuine new member before any human saw it. With this off they
    # lose the message and the admin is alerted; a ban needs either a prior
    # strike or BOTH the message and the profile at RED_FLAG. Set to true to
    # restore the old behaviour.
    ban_on_first_offence: bool = (
        os.getenv("BAN_ON_FIRST_OFFENCE", "false").lower() == "true"
    )
    # A strike stops counting toward escalation after this many days. One bad
    # week should not still be pushing someone toward a ban a year later.
    # Set to 0 to disable decay and keep strikes forever.
    strike_decay_days: int = int(os.getenv("STRIKE_DECAY_DAYS", "30"))
    # Identical text is answered from cache for this long (seconds).
    llm_cache_ttl: int = int(os.getenv("LLM_CACHE_TTL", "900"))

    # Extra domains to treat as an automatic red flag, comma-separated.
    # The structural checks in LinkAnalyzer run regardless of this list.
    blocked_domains: frozenset = frozenset(
        d.strip().lower().lstrip(".")
        for d in os.getenv("BLOCKED_DOMAINS", "").split(",")
        if d.strip()
    )

    # Raid / flood detection. Pace is judged content-blind; nobody is banned
    # on pace alone, it only feeds the normal escalation path.
    flood_messages: int = int(os.getenv("FLOOD_MESSAGES", "5"))
    flood_window: float = float(os.getenv("FLOOD_WINDOW", "8"))
    raid_users: int = int(os.getenv("RAID_USERS", "5"))
    # Once alerts exceed this many in 30s they are folded into a periodic
    # digest, so a raid cannot bury the review queue.
    alert_burst_threshold: int = int(os.getenv("ALERT_BURST_THRESHOLD", "5"))
    alert_digest_interval: float = float(os.getenv("ALERT_DIGEST_INTERVAL", "60"))

    # Skip group admins. Telegram will not let a bot delete or ban an admin,
    # so moderating them only fills the review queue with alerts nobody can
    # act on. Set false to moderate everyone (useful while testing with your
    # own admin account).
    skip_group_admins: bool = os.getenv("SKIP_GROUP_ADMINS", "true").lower() == "true"
    admin_cache_ttl: float = float(os.getenv("ADMIN_CACHE_TTL", "300"))

    # How much the bot does on its own, and what it interrupts a human for:
    #   report      never act, alert everything (safe, useless at scale)
    #   assisted    act; interrupt for REVIEW + BAN, digest the rest (default)
    #   autonomous  act; interrupt for nothing, digest everything
    autonomy: str = os.getenv("AUTONOMY", "assisted")
    # Seconds between digest summaries of routine, already-handled actions.
    digest_interval: float = float(os.getenv("DIGEST_INTERVAL", "21600"))

    # Proof of life. The signal you act on is the ABSENCE of the daily ping,
    # so it is sent on a schedule regardless of activity. 0 disables it.
    heartbeat_interval: float = float(os.getenv("HEARTBEAT_INTERVAL", "86400"))

    # --- read-only web dashboard (optional, separate process) ------------
    # Telegram user ids allowed to view it. EMPTY DENIES EVERYONE — defaulting
    # to open would mean a forgotten value silently publishes every moderation
    # record, including users' message text.
    web_admin_ids: frozenset = frozenset(
        int(v) for v in os.getenv("WEB_ADMIN_IDS", "").replace(" ", "").split(",")
        if v.strip().lstrip("-").isdigit()
    )
    # Your bot's @username, needed by the Telegram login widget.
    web_bot_username: str = os.getenv("WEB_BOT_USERNAME", "")
    # Public URL of the panel; must match the domain set via /setdomain.
    web_base_url: str = os.getenv("WEB_BASE_URL", "http://localhost:8080")
    # Leave empty to derive one from the bot token (rotating the token then
    # invalidates every session).
    web_session_secret: str = os.getenv("WEB_SESSION_SECRET", "")
    # Alternative sign-in for reaching the panel without a domain (Telegram's
    # widget requires one). Empty disables it — a default-on second credential
    # is how panels end up unintentionally reachable. Must be 32+ chars.
    web_access_token: str = os.getenv("WEB_ACCESS_TOKEN", "")

    # How long a moderation record — including up to 500 characters of the
    # message that triggered it — is kept. This is other people's private
    # conversation; the audit value decays fast, the privacy cost does not.
    # 0 keeps everything forever.
    event_retention_days: int = int(os.getenv("EVENT_RETENTION_DAYS", "90"))

    # Your account's tokens-per-minute ceiling for the Groq model. This is the
    # limit that actually bites — it is per MINUTE, so a quiet week with one
    # busy minute still gets rate-limited. Read it from the
    # x-ratelimit-limit-tokens header on any API response.
    groq_token_limit_per_minute: int = int(
        os.getenv("GROQ_TOKEN_LIMIT_PER_MINUTE", "8000")
    )
    # Whether this key is actually billed. Groq exposes no billing endpoint, so
    # this cannot be detected — and a dashboard that prints a dollar figure for
    # a free-tier key is inventing a bill. Default "free": the cost column then
    # reads as a list-price equivalent for planning, not as money owed.
    # Check console.groq.com and set "paid" if you are on a paid plan.
    groq_plan: str = os.getenv("GROQ_PLAN", "free").strip().lower()

    # Safety switch. When True the bot only REPORTS what it would do and never
    # actually deletes or bans. Keep this on until you trust the detection.
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"

    # A message is acted on only if BOTH its content and the sender's profile
    # look bad. This is the escalation rule that keeps false positives down.
    require_profile_confirmation: bool = True

    def validate(self) -> None:
        missing = [
            name
            for name, val in (
                ("TELEGRAM_BOT_TOKEN", self.telegram_token),
                ("GROQ_API_KEY", self.groq_api_key),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


settings = Settings()
