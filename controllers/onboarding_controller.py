"""What an admin sees before Qalqon has done anything.

Every other surface in this bot assumes it is already installed correctly, and
that assumption is where installs die. A bot that was added but never promoted
sits in the group reading nothing, while the group believes it is protected —
and the failure is silent by construction, because the thing that would report
it is the thing that has no rights. From the outside, "quiet because nothing
bad happened" and "quiet because I cannot see anything" look identical.

So setup is not a welcome message, it is a diagnosis. Three entry points, each
answering the one question that is live at that moment:

  /start in private   how do I install this? — with a button that asks for the
                      two rights in the SAME dialog as the invite, because a
                      separate "now go promote it" step is the one people skip
  added to a group    what is missing HERE — sent unprompted, since this is the
                      one moment the admin is certainly looking
  /start in a group   the same check again, on demand, after they fix something

The rights check mirrors scripts/preflight.py deliberately. Preflight is run
once by whoever deploys the bot; this is run by every group admin who installs
it, and neither audience can be asked to trust the other's setup.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

log = logging.getLogger("qalqon.onboarding")

# Requested in the invite dialog itself. `restrict_members` is what Telegram
# calls the right to ban; there is no separate ban permission.
INVITE_RIGHTS = "delete_messages+restrict_members"

WELCOME = """🛡 Qalqon

I remove scam messages from Telegram groups — fake job offers, advance-fee \
"visa" deals, and currency-exchange traps — reading Uzbek, Russian, Korean and \
English to the same standard.

To put me to work:

1. Tap "Add to a group" below and choose your group.
2. Leave both rights ticked — delete messages and ban users. Without them I \
can recognise a scam and do nothing about it.
3. I'll report what's still missing as soon as I arrive.

What I do there:

• A clear scam is removed, and the admins are told afterwards.
• Anything borderline goes to an admin with Ban / Ignore / Whitelist buttons. \
The decision stays with a person.
• Ordinary chat is left alone. Posting a shift, a wage, a district or an \
exchange rate is normal here and is never treated as a signal on its own.

I keep no record of ordinary messages — only of the ones I acted on."""

# What each missing right actually costs, in the group's terms rather than the
# API's. "can_restrict_members: false" tells an admin nothing they can act on.
RIGHTS = (
    ("can_delete_messages", "Delete messages", "scam posts would stay up"),
    ("can_restrict_members", "Ban users", "a scammer could not be removed"),
)


def invite_markup(username: str, privacy_url: str = "") -> InlineKeyboardMarkup | None:
    """The add-to-group button, pre-ticking the rights it needs.

    Returns None when the bot's username is not known yet, so a missing
    username costs the button and not the whole message.
    """
    if not username:
        return None
    rows = [[InlineKeyboardButton(
        "➕ Add to a group",
        url=f"https://t.me/{username}?startgroup=true&admin={INVITE_RIGHTS}",
    )]]
    if privacy_url:
        rows.append([InlineKeyboardButton("Privacy", url=privacy_url)])
    return InlineKeyboardMarkup(rows)


class OnboardingController:
    def __init__(
        self, view=None, web_base_url: str = "", admin_chat_id: str = ""
    ) -> None:
        self._view = view
        self._admin_chat_id = admin_chat_id
        self._privacy_url = f"{web_base_url.rstrip('/')}/privacy" if web_base_url else ""

    # --- entry points ----------------------------------------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/start — a pitch in private, a diagnosis in a group."""
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return
        if getattr(chat, "type", "private") == "private":
            await msg.reply_text(
                WELCOME,
                reply_markup=invite_markup(
                    getattr(context.bot, "username", "") or "", self._privacy_url
                ),
                disable_web_page_preview=True,
            )
            return
        await msg.reply_text(await self._readiness(context.bot, chat))

    async def on_added(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Sent when Qalqon itself is the new member.

        Unprompted on purpose: a bot that was added but cannot act looks
        exactly like a bot with nothing to do, so someone must be told now.
        But told in the ADMIN chat, not the group: members should not watch
        a permissions checklist scroll past. An admin who wants it in the
        group can still ask with /start.
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat or not msg.new_chat_members:
            return
        me = getattr(context.bot, "id", None)
        if not any(getattr(m, "id", None) == me for m in msg.new_chat_members):
            return
        card = await self._readiness(context.bot, chat)
        if not self._admin_chat_id:
            log.info("added to %s; no ADMIN_CHAT_ID for the setup card:\n%s", chat.id, card)
            return
        try:
            await context.bot.send_message(
                chat_id=self._admin_chat_id, text=f"{card}\n\nGroup id: {chat.id}"
            )
        except Exception as exc:
            log.warning("setup card for %s not delivered: %s", chat.id, exc)

    # --- the check -------------------------------------------------------
    async def _readiness(self, bot, chat) -> str:
        """Ask Telegram what this bot may actually do in this chat.

        Asked live rather than remembered: rights are changed in Telegram's own
        UI, which sends us nothing, so any cached answer is a guess about the
        present built from the past.
        """
        title = getattr(chat, "title", "") or "this group"
        lines = [f"🛡 Qalqon setup — {title}", ""]
        blockers = []

        try:
            member = await bot.get_chat_member(chat.id, bot.id)
        except Exception as exc:  # network, or removed mid-check
            log.warning("rights check failed in %s: %s", chat.id, exc)
            return (
                f"🛡 Qalqon setup — {title}\n\n"
                "I could not read my own permissions just now. Run /start "
                "again in a moment."
            )

        if getattr(member, "status", "") != "administrator":
            lines.append("❌ Not an administrator")
            lines.append("")
            lines.append(
                "Promote me in Group settings → Administrators, with "
                "\"Delete messages\" and \"Ban users\" ticked. Until then I "
                "can read this group but cannot act in it."
            )
            return "\n".join(lines)

        lines.append("✅ Administrator")
        for attr, label, cost in RIGHTS:
            if getattr(member, attr, False):
                lines.append(f"✅ {label}")
            else:
                lines.append(f"❌ {label} — {cost}")
                blockers.append(label)

        # Privacy mode is set by whoever owns the bot, not by this group's
        # admins — but it is checked here anyway, because its symptom is the
        # bot doing nothing, which is exactly what they would blame on rights.
        try:
            me = await bot.get_me()
            if not getattr(me, "can_read_all_group_messages", False):
                lines.append("❌ Cannot read group messages — privacy mode is on")
                blockers.append("privacy mode")
        except Exception as exc:
            log.warning("get_me failed during setup check: %s", exc)

        lines.append("")
        if blockers:
            lines.append(
                "Fix: " + ", ".join(blockers) + ". Then send /start again."
            )
            if "privacy mode" in blockers:
                lines.append(
                    "Privacy mode is turned off by the bot's owner in "
                    "@BotFather → /setprivacy → Disable."
                )
            return "\n".join(lines)

        if self._view is not None and getattr(self._view, "dry_run", False):
            lines.append(
                "Ready — but running in dry-run: I will report what I would "
                "have done and change nothing. An admin can flip that with "
                "/dryrun off."
            )
        else:
            lines.append("Ready. I'm watching this group.")
        lines.append("Admins: /help for the full command list.")
        return "\n".join(lines)
