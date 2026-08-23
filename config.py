"""Central configuration. All secrets come from environment variables."""
import os
from dataclasses import dataclass, field
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
    mtproto_session: str = os.getenv("MTPROTO_SESSION", "scamguard_user")
    mtproto_scan_limit: int = int(os.getenv("MTPROTO_SCAN_LIMIT", "40"))
    mtproto_cache_ttl: int = int(os.getenv("MTPROTO_CACHE_TTL", "21600"))

    # Phase 3 — memory, strikes and trust.
    db_path: str = os.getenv("DB_PATH", "scamguard.db")
    # How many strikes before the response escalates one step (REVIEW->DELETE
    # ->BAN). Lower = harsher on repeat offenders.
    strikes_to_escalate: int = int(os.getenv("STRIKES_TO_ESCALATE", "2"))
    # Messages a member must post, strike-free, before they are "established"
    # and can no longer be auto-banned over a single message.
    trust_after_messages: int = int(os.getenv("TRUST_AFTER_MESSAGES", "25"))
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
