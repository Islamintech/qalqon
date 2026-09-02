"""Entry point. Wires the MVC pieces together and starts the bot."""
import logging

from telegram.error import Conflict, NetworkError, TimedOut
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters,
)

from config import settings
from models import (
    KeywordFilter, LLMClient, ProfileAnalyzer, VisionClient, FileScanner,
    ChannelAnalyzer, MTProtoScanner, Policy, Store, LinkAnalyzer,
    BurstDetector, AdminCache, Autonomy, ModerationModel,
)
from views import TelegramView, AlertBatcher, DigestReporter, Heartbeat
from controllers import ModerationController, AdminController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

# httpx logs every request URL at INFO — and the Telegram API puts the BOT
# TOKEN in the path, so that would print the token on every single poll.
# Anyone who can read the logs could then take over the bot.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
# PTB's own polling chatter is not useful once it is working.
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)

# Everything a user can say or send. One handler covers it all, because PTB
# runs only the FIRST matching handler in a group — a captioned .apk split
# across two handlers would get judged on one signal and never the other.
#
#   TEXT      plain messages
#   CAPTION   media captions, invisible to filters.TEXT (was a full bypass)
#   media     any attachment that can carry a payload, not just documents
MODERATED_CONTENT = (
    filters.TEXT
    | filters.CAPTION
    | filters.Document.ALL
    | filters.ANIMATION
    | filters.VIDEO
    | filters.AUDIO
    | filters.VOICE
    | filters.PHOTO
)


async def on_error(update: object, context) -> None:
    """Global error handler.

    Without one, PTB logs a full traceback for every transient network blip,
    and an unrecoverable condition repeats forever at the poll interval until
    the log is unreadable.

    Conflict is special: it means ANOTHER instance is polling this same bot
    token. Two moderators acting on one chat is actively harmful — duplicate
    bans, doubled strikes, two alerts per message — and it cannot resolve
    itself, so we stop rather than fight over the update stream.
    """
    err = context.error
    log = logging.getLogger("qalqon")

    if isinstance(err, Conflict):
        log.critical(
            "ANOTHER INSTANCE of this bot is already running (Conflict). "
            "Two instances would double every ban and strike. Shutting down — "
            "stop the other one, then start a single instance."
        )
        context.application.stop_running()
        return

    if isinstance(err, (NetworkError, TimedOut)):
        # Routine and self-healing; PTB retries on its own.
        log.warning("network issue, will retry: %s", err)
        return

    log.exception("unhandled error while processing an update", exc_info=err)


def main() -> None:
    settings.validate()

    file_scanner = FileScanner()
    store = Store(
        settings.db_path,
        decay_days=settings.strike_decay_days,
        event_retention_days=settings.event_retention_days,
    )

    # Optional profile-photo NSFW screening (needs a free HF token).
    vision = (
        VisionClient(settings.hf_token, nsfw_threshold=settings.nsfw_threshold)
        if settings.hf_token else None
    )

    # Optional MTProto deep channel scanning (phase 2b, needs a user session).
    mtproto = MTProtoScanner(
        settings.mtproto_api_id,
        settings.mtproto_api_hash,
        session=settings.mtproto_session,
        scan_limit=settings.mtproto_scan_limit,
        cache_ttl=settings.mtproto_cache_ttl,
        file_scanner=file_scanner,
    )

    profile_analyzer = ProfileAnalyzer(
        vision=vision,
        channel=ChannelAnalyzer(mtproto=mtproto),
    )
    digest = DigestReporter(interval=settings.digest_interval)
    heartbeat = Heartbeat(store, interval=settings.heartbeat_interval)
    autonomy = Autonomy.parse(settings.autonomy)

    view = TelegramView(
        settings.dry_run,
        settings.admin_chat_id,
        batcher=AlertBatcher(
            threshold=settings.alert_burst_threshold,
            flush_interval=settings.alert_digest_interval,
        ),
        digest=digest,
        autonomy=autonomy,
    )

    # --- MODEL: every rule and all state. Knows nothing about Telegram. ---
    model = ModerationModel(
        store=store,
        policy=Policy(
            require_profile_confirmation=settings.require_profile_confirmation,
            strikes_to_escalate=settings.strikes_to_escalate,
            require_history_to_ban=not settings.ban_on_first_offence,
        ),
        keyword_filter=KeywordFilter(),
        llm_client=LLMClient(
            settings.groq_api_key, settings.groq_model,
            cache_ttl=settings.llm_cache_ttl,
        ),
        profile_analyzer=profile_analyzer,
        link_analyzer=LinkAnalyzer(blocklist=settings.blocked_domains),
        burst_detector=BurstDetector(
            flood_messages=settings.flood_messages,
            flood_window=settings.flood_window,
            raid_users=settings.raid_users,
        ),
        file_scanner=file_scanner,
        autonomy=autonomy,
        trust_after_messages=settings.trust_after_messages,
    )

    # --- VIEW: subscribes to the model. The model never calls it, and the
    # controller never calls it either — that is what makes this MVC rather
    # than three folders with MVC names.
    view.subscribe_to(model)

    # --- CONTROLLER: translates Telegram updates into model calls. Holds no
    # logic, renders nothing.
    controller = ModerationController(
        model,
        admin_cache=AdminCache(ttl=settings.admin_cache_ttl),
        skip_group_admins=settings.skip_group_admins,
    )
    admin = AdminController(
        store, view, settings.admin_chat_id, digest=digest, model=model
    )

    # Open/close the DB and the Telethon client inside PTB's own event loop.
    async def _post_init(app: Application) -> None:
        # Hand the Bot to the adapters once, so nothing downstream has to
        # thread it through as a parameter.
        view.attach(app.bot)
        profile_analyzer.attach(app.bot)
        await store.start()
        # A quiet chat would never hit the opportunistic prune in add_strike.
        pruned = await store.prune_strikes()
        if pruned:
            logging.getLogger("qalqon").info("pruned %s expired strikes", pruned)
        # Retention is enforced on every start, so a long-running deployment
        # cannot quietly accumulate an archive of other people's messages.
        await store.prune_usage()
        forgotten = await store.prune_events()
        if forgotten:
            logging.getLogger("qalqon").info(
                "deleted %s moderation records past the %s-day retention window",
                forgotten, settings.event_retention_days,
            )
        await mtproto.start()

        async def _send_digest(body: str) -> None:
            if settings.admin_chat_id:
                await app.bot.send_message(chat_id=settings.admin_chat_id, text=body)
            else:
                logging.getLogger("qalqon").info("DIGEST:\n%s", body)

        await digest.start(_send_digest)

        if settings.heartbeat_interval:
            await heartbeat.startup(
                _send_digest,
                detail=(
                    f"mode: {'DRY-RUN' if settings.dry_run else 'LIVE'} | "
                    f"autonomy: {autonomy.value} | "
                    f"admins skipped: {'yes' if settings.skip_group_admins else 'no'}"
                ),
            )
            await heartbeat.start(_send_digest)

    async def _post_shutdown(app: Application) -> None:
        # Emit any pending digest before going down, so a raid's last alerts
        # are not lost with the process.
        # Emit a partial digest rather than discarding the period on restart.
        async def _send_digest(body: str) -> None:
            if settings.admin_chat_id:
                await app.bot.send_message(chat_id=settings.admin_chat_id, text=body)

        await heartbeat.stop()
        if settings.heartbeat_interval:
            await heartbeat.shutdown(_send_digest)
        await digest.stop(_send_digest)
        await view.flush_alerts()
        await mtproto.stop()
        await store.stop()

    app = (
        Application.builder()
        .token(settings.telegram_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    # Admin commands first — a /command must never fall through to moderation.
    for name, handler in (
        ("help", admin.help),
        ("stats", admin.stats),
        ("status", admin.status),
        ("whitelist", admin.whitelist),
        ("unwhitelist", admin.unwhitelist),
        ("forgive", admin.forgive),
        ("unban", admin.unban),
        ("dryrun", admin.dryrun),
        ("digest", admin.digest),
    ):
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(CallbackQueryHandler(admin.on_button, pattern=r"^mod\|"))
    app.add_error_handler(on_error)

    # UpdateType.MESSAGES covers both new and EDITED messages. Editing a
    # cleared message into a scam pitch used to walk straight through — the
    # bot was not even subscribed to edits (see allowed_updates below).
    app.add_handler(
        MessageHandler(
            MODERATED_CONTENT
            & ~filters.COMMAND
            & filters.ChatType.GROUPS
            & filters.UpdateType.MESSAGES,
            controller.handle_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS, controller.handle_new_members
        )
    )

    mode = "DRY-RUN (no deletes/bans)" if settings.dry_run else "LIVE"
    logging.getLogger("qalqon").info(
        "starting %s | photo:%s | channel-deep-scan:%s | db:%s | "
        "strikes-to-escalate:%s | trust-after:%s msgs | strike-decay:%s | "
        "first-offence:%s | skip-admins:%s | autonomy:%s | digest:%.0fs",
        mode,
        "on" if settings.hf_token else "off",
        "on" if mtproto.available else "off",
        settings.db_path,
        settings.strikes_to_escalate,
        settings.trust_after_messages,
        f"{settings.strike_decay_days}d" if settings.strike_decay_days else "never",
        # Says what HAPPENS, not which flag is set: "ban_on_first_offence:off"
        # would need the reader to know what the default even is, at the moment
        # they are checking whether a deploy landed.
        "can-ban" if settings.ban_on_first_offence else "delete-only",
        "on" if settings.skip_group_admins else "off",
        autonomy.value,
        settings.digest_interval,
    )
    app.run_polling(
        allowed_updates=["message", "edited_message", "callback_query"]
    )


if __name__ == "__main__":
    main()
