"""The privacy notice.

This page has a reader the rest of web/ does not: an ordinary group member who
followed a link from the bot's Telegram profile, has no account here, and wants
one question answered — *what does this thing know about me?*

So it is built around a ledger rather than prose. Six paragraphs of policy text
are technically complete and practically unread; two facing columns saying
KEPT and NEVER KEPT answer the question at a glance, and the prose underneath
is there for the reader who wants the detail.

Every number on the page is read from the live configuration and passed in,
never typed into the copy. A notice that promises 90 days while the bot keeps
forever is worse than no notice at all.

The page is Uzbek first, because the communities being moderated are, with a
full English translation below it rather than the four-line summary it used to
carry — a translation that drops half the content is not a translation.
"""

from . import landing, render

# Bumped by hand when the substance changes, not on every deploy: a date that
# moves when a typo is fixed teaches the reader to ignore it.
UPDATED = "2026-09-02"

CSS = """
.pv{--max:840px}

/* ---------- head ---------- */
.pv-head{border-bottom:1px solid var(--line);
  background:radial-gradient(700px 320px at 50% -20%,
    color-mix(in srgb, var(--accent) 11%, transparent), transparent 70%)}
.pv-head .in{max-width:var(--max);margin:0 auto;padding:72px 28px 56px;
  text-align:center}
.pv h1{font-size:clamp(30px,4.6vw,42px);font-weight:720;letter-spacing:-.035em;
  line-height:1.1;margin:0}
.pv .lede{margin:20px auto 0;max-width:52ch;font-size:17px;line-height:1.65;
  color:var(--ink-2)}
.stamp{display:inline-flex;align-items:center;gap:8px;margin-top:26px;
  padding:6px 14px;border-radius:999px;background:var(--card);
  border:1px solid var(--line);font-size:12.5px;color:var(--muted)}
.stamp .ic{color:var(--accent)}

/* ---------- body ---------- */
.pv main{max-width:var(--max);margin:0 auto;padding:52px 28px 20px}
/* landing.CSS is on this page too for the header and footer, and its
   `.lp section{max-width:1100px;padding:90px 28px}` would otherwise apply to
   every section here — 90px of its padding on top of the 52px below, so the
   page read as six blocks marooned in whitespace. Reset, don't inherit. */
.pv section{max-width:none;padding:0;margin:0 0 52px}
.pv h2{font-size:21px;font-weight:680;letter-spacing:-.022em;margin:0 0 8px;
  display:flex;align-items:center;gap:10px}
.pv h2 .ic{color:var(--accent);flex:none}
.pv .sub{margin:0 0 20px;color:var(--muted);font-size:14px;line-height:1.6}
.pv p{margin:0 0 14px;font-size:15px;line-height:1.75;color:var(--ink-2)}
.pv p:last-child{margin-bottom:0}
.pv strong{color:var(--ink);font-weight:640}

/* ---------- the numbers, stated once and up front ---------- */
.pv-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;
  margin-bottom:52px}
.pv-fact{background:var(--card);border:1px solid var(--line);border-radius:13px;
  padding:18px 18px 16px;box-shadow:var(--shadow)}
.pv-fact b{display:block;font-size:26px;font-weight:700;letter-spacing:-.03em;
  line-height:1.15;color:var(--accent-ink)}
.pv-fact span{display:block;margin-top:5px;font-size:12.5px;color:var(--muted);
  line-height:1.5}

/* ---------- the ledger: the whole point of the page ----------
   Two facing columns, tinted with the good/ban roles so the answer is legible
   before a word is read. The tint is a background wash, never the only signal:
   each row carries its own check or cross glyph. */
.ledger{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.led{border-radius:15px;border:1px solid var(--line);overflow:hidden;
  background:var(--card);box-shadow:var(--shadow)}
.led .cap{display:flex;align-items:center;gap:9px;padding:15px 20px;
  font-size:13px;font-weight:680;letter-spacing:.01em;
  border-bottom:1px solid var(--line)}
.led.keep .cap{background:var(--delete-bg);color:var(--delete)}
.led.never .cap{background:var(--good-bg);color:var(--good)}
.led ul{margin:0;padding:8px 0;list-style:none}
.led li{display:flex;gap:11px;padding:9px 20px;font-size:14px;line-height:1.6;
  color:var(--ink-2)}
.led li .ic{flex:none;margin-top:3px}
.led.keep li .ic{color:var(--delete)}
.led.never li .ic{color:var(--good)}

/* ---------- who sees it ---------- */
.rows{border:1px solid var(--line);border-radius:15px;overflow:hidden;
  background:var(--card);box-shadow:var(--shadow)}
.row{display:flex;gap:14px;padding:16px 20px;
  border-bottom:1px solid var(--line-soft)}
.row:last-child{border-bottom:0}
.row .ic{flex:none;margin-top:2px;color:var(--muted)}
.row b{display:block;font-size:14.5px;font-weight:620;color:var(--ink);
  margin-bottom:3px}
.row span{font-size:13.5px;line-height:1.6;color:var(--ink-2)}
.row .tag{margin-left:auto;flex:none;align-self:center;padding:4px 10px;
  border-radius:999px;font-size:11.5px;font-weight:640;white-space:nowrap;
  background:var(--raised);color:var(--muted)}

/* ---------- external services ---------- */
.svc{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.svc .box{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:20px;box-shadow:var(--shadow)}
.svc .box h3{margin:0 0 4px;font-size:15px;font-weight:660}
.svc .box .what{font-size:12.5px;color:var(--accent-ink);margin-bottom:9px}
.svc .box p{margin:0;font-size:13.5px;line-height:1.62}

/* ---------- contact ---------- */
.pv-cta{background:var(--card);border:1px solid var(--line);border-radius:15px;
  padding:26px;box-shadow:var(--shadow);text-align:center}
.pv-cta p{max-width:46ch;margin:0 auto 18px}

/* ---------- the English half ----------
   A <details>, not a second page: one URL to give people, and the reader who
   needs English is one click from all of it rather than a four-line gist. */
.pv details{border:1px solid var(--line);border-radius:15px;
  background:var(--card);box-shadow:var(--shadow);margin-bottom:52px}
.pv summary{list-style:none;display:flex;align-items:center;gap:11px;
  padding:18px 22px;cursor:pointer;font-size:15px;font-weight:620;
  color:var(--ink);background:none;border-radius:15px}
.pv summary::-webkit-details-marker{display:none}
.pv summary::before{content:"";width:0;height:0;flex:none;
  border:5px solid transparent;border-left:6px solid var(--muted)}
.pv details[open] summary::before{border:5px solid transparent;
  border-top:6px solid var(--muted);margin-top:5px}
.pv summary:hover{color:var(--accent-ink)}
.pv summary .hint{margin-left:auto;font-size:12.5px;font-weight:500;
  color:var(--muted)}
.pv details[open] summary{border-bottom:1px solid var(--line);
  border-radius:15px 15px 0 0}
.pv .en{padding:22px}
.pv .en h3{font-size:14px;font-weight:660;margin:22px 0 8px;color:var(--ink)}
.pv .en h3:first-child{margin-top:0}
.pv .en p{font-size:14px}
.pv .en ul{margin:0 0 14px;padding-left:20px;color:var(--ink-2);font-size:14px;
  line-height:1.7}

@media (max-width:760px){
  .pv-facts{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:620px){
  .pv-head .in{padding:50px 20px 40px}
  .pv main{padding:38px 20px 12px}
  .pv section{margin-bottom:40px}
  .ledger,.svc{grid-template-columns:minmax(0,1fr)}
  .row{flex-wrap:wrap}
  .row .tag{margin-left:0;width:100%;text-align:center}
}
"""


def _ledger(chars: int) -> str:
    """What is kept, and what is not, side by side.

    Deliberately the first thing under the numbers: it is the question the
    reader actually arrived with, and it answers in about four seconds.
    """
    keep = [
        ("groups", "Guruh identifikatori va nomi"),
        ("member", "Foydalanuvchi identifikatori va useri"),
        ("shield", "Qaror: o'chirildi / bloklandi / ko'rib chiqilsin"),
        ("warn", "Qaror sababi"),
        ("broom", f"O'sha xabarning dastlabki {chars} belgisi"),
        ("bars", "Xabarlar soni, ogohlantirishlar soni va holat"),
    ]
    never = [
        ("quiet", "Oddiy suhbat — chora ko'rilmagan xabar matni"),
        ("lock", "Shaxsiy xabarlar (bot ularni umuman ko'rmaydi)"),
        ("member", "Telefon raqami, manzil, elektron pochta"),
        ("bars", "To'lov yoki karta ma'lumotlari"),
        ("context", "Joylashuv, qurilma yoki brauzer izlari"),
        ("link", "Reklama identifikatorlari va kuzatuv cookie'lari"),
    ]

    def items(rows: list[tuple[str, str]], glyph: str) -> str:
        return "".join(
            f"<li>{render.icon(glyph, 15)}<span>{text}</span></li>"
            for _, text in rows
        )

    return (
        f'<div class="ledger">'
        f'<div class="led keep"><div class="cap">{render.icon("broom", 15)}'
        f"SAQLANADI</div><ul>{items(keep, 'warn')}</ul></div>"
        f'<div class="led never"><div class="cap">{render.icon("quiet", 15)}'
        f"HECH QACHON SAQLANMAYDI</div><ul>{items(never, 'check')}</ul></div>"
        f"</div>"
    )


def page(logo: str, signed_in: bool, theme: str, here: str,
         retention_days: int, strike_days: int, snippet_chars: int) -> str:
    """The notice.

    Every figure is a parameter. If someone sets EVENT_RETENTION_DAYS=0 the
    page says "muddatsiz" in the prose *and* in the number tile — there is no
    path by which the copy and the configuration can disagree.
    """
    if retention_days:
        keep_tile = (f'<b>{retention_days}</b><span>kun saqlanadi, keyin '
                     f"o'chiriladi</span>")
        keep_uz = (f"Yozuvlar <strong>{retention_days} kundan</strong> keyin "
                   f"avtomatik va butunlay o'chiriladi. Buning uchun hech kim "
                   f"hech narsa qilishi shart emas — o'chirish har kecha o'zi "
                   f"ishlaydi.")
        keep_en = (f"Records are deleted automatically and permanently after "
                   f"<strong>{retention_days} days</strong>. Nobody has to "
                   f"request it; the sweep runs nightly on its own.")
    else:
        keep_tile = "<b>∞</b><span>muddatsiz saqlanmoqda</span>"
        keep_uz = ("Hozircha bu yozuvlar <strong>muddatsiz</strong> saqlanmoqda "
                   "(<code>EVENT_RETENTION_DAYS=0</code>). Bu sozlama, va bu "
                   "sahifa uni yashirmaydi.")
        keep_en = ("These records are currently kept <strong>indefinitely</strong> "
                   "(<code>EVENT_RETENTION_DAYS=0</code>). That is a setting, "
                   "and this page will not hide it.")

    nav = ('<a href="/#how">How it works</a>'
           '<a href="/#safety">Safety</a>'
           '<a href="/privacy" aria-current="page">Privacy</a>')

    return f"""
<div class="lp pv">
{landing.header(logo, signed_in, theme, here, nav)}

<div class="pv-head"><div class="in">
  <div class="eyebrow">Maxfiylik</div>
  <h1>Qalqon siz haqingizda nimani biladi.</h1>
  <p class="lede">Qisqa javob: deyarli hech narsa. Bot faqat o'zi chora ko'rgan
  holatlarni yozib qo'yadi — qolgan hamma narsa yozilmasdan o'tib ketadi.</p>
  <span class="stamp">{render.icon("clock", 13)}Oxirgi yangilanish:
  {UPDATED}</span>
</div></div>

<main>

<div class="pv-facts">
  <div class="pv-fact">{keep_tile}</div>
  <div class="pv-fact"><b>{strike_days}</b><span>kundan keyin ogohlantirish
    kuchini yo'qotadi</span></div>
  <div class="pv-fact"><b>{snippet_chars}</b><span>belgi — saqlanadigan matnning
    eng ko'p uzunligi</span></div>
  <div class="pv-fact"><b>0</b><span>ma'lumot sotiladi yoki reklamaga
    beriladi</span></div>
</div>

<section>
  <h2>{render.icon("bars", 19)}Nima saqlanadi, nima yo'q</h2>
  <p class="sub">Bot guruhdagi har bir xabarni ko'radi, lekin ularning deyarli
  barchasini o'qib, hech narsa yozmasdan unutadi. Yozuv faqat chora ko'rilganda
  paydo bo'ladi.</p>
  {_ledger(snippet_chars)}
</section>

<section>
  <h2>{render.icon("clock", 19)}Qancha vaqt saqlanadi</h2>
  <p>{keep_uz}</p>
  <p>Ogohlantirishlar alohida ishlaydi: ular
  <strong>{strike_days} kundan</strong> keyin kuchini yo'qotadi, ya'ni bir marta
  xato qilgan odam buni abadiy ko'tarib yurmaydi. Uzoq vaqtdan beri guruhda
  bo'lgan a'zolarni bot umuman avtomatik bloklamaydi.</p>
</section>

<section>
  <h2>{render.icon("people", 19)}Kim ko'ra oladi</h2>
  <p class="sub">Yozuvlarga kirish uch kishi bilan cheklangan, va ro'yxat
  shundan iborat.</p>
  <div class="rows">
    <div class="row">{render.icon("shield", 16)}<div><b>Guruh adminlari</b>
      <span>O'z guruhlaridagi qarorlarni ko'radi va ularni bekor qila
      oladi.</span></div><span class="tag">o'z guruhi</span></div>
    <div class="row">{render.icon("member", 16)}<div><b>Bot egasi</b>
      <span>Botni ishlatayotgan operator — texnik nosozliklarni tuzatish
      uchun.</span></div><span class="tag">to'liq</span></div>
    <div class="row">{render.icon("ban", 16)}<div><b>Boshqa hech kim</b>
      <span>Ma'lumot sotilmaydi, ijaraga berilmaydi, reklama tarmoqlariga
      uzatilmaydi va boshqa guruhlarga ko'rsatilmaydi.</span></div>
      <span class="tag">hech qachon</span></div>
  </div>
</section>

<section>
  <h2>{render.icon("link", 19)}Tashqi xizmatlar</h2>
  <p class="sub">Bot ikkita tashqi xizmatdan foydalanadi. Ular ma'lumotni faqat
  javob qaytarish uchun ishlatadi va uni saqlab qolmaydi.</p>
  <div class="svc">
    <div class="box"><h3><a href="https://groq.com">Groq</a></h3>
      <div class="what">Shubhali xabar matni</div>
      <p>Xabar firibgarlikmi yoki yo'qmi — buni til modeli hal qiladi. Faqat
      dastlabki tekshiruvdan o'tgan xabarlar yuboriladi, hammasi emas.</p></div>
    <div class="box"><h3><a href="https://huggingface.co">Hugging Face</a></h3>
      <div class="what">Profil rasmi</div>
      <p>Yangi a'zoning avatari soxta yoki generatsiya qilinganini aniqlash
      uchun. Rasm tahlildan keyin saqlanmaydi.</p></div>
  </div>
</section>

<section>
  <h2>{render.icon("undo", 19)}O'chirish va tuzatish</h2>
  <div class="pv-cta">
    <p>O'zingiz haqingizdagi yozuvni o'chirishni yoki noto'g'ri qarorni
    tuzatishni so'rash uchun guruh admini bilan bog'laning — u buni bir tugma
    bilan bajara oladi, va bekor qilingan qaror ortidagi ogohlantirish ham
    o'chadi.</p>
    <a class="lp-btn" href="https://t.me/QalqonSafeBot">@QalqonSafeBot</a>
  </div>
</section>

<details>
  <summary>{render.icon("context", 16)}English
    <span class="hint">Full translation</span></summary>
  <div class="en">
    <p>Qalqon is an anti-scam moderation bot for Telegram communities. This
    page explains what it stores about you. The short answer is: almost
    nothing. It sees every message in a group and forgets nearly all of them
    without writing anything down.</p>

    <h3>What is recorded</h3>
    <p>Only cases the bot actually acted on:</p>
    <ul>
      <li>The group id and name</li>
      <li>The user id and username</li>
      <li>The decision — deleted, banned, or flagged for review</li>
      <li>The reason for that decision</li>
      <li>The first {snippet_chars} characters of the triggering message</li>
      <li>Per member: message count, strike count, and status</li>
    </ul>

    <h3>What is never recorded</h3>
    <ul>
      <li>Ordinary conversation. If a message is not flagged, its text is
      written nowhere.</li>
      <li>Private messages — the bot never sees them at all</li>
      <li>Phone numbers, addresses, email</li>
      <li>Payment or card details</li>
      <li>Location, device or browser fingerprints</li>
      <li>Advertising identifiers and tracking cookies</li>
    </ul>

    <h3>How long</h3>
    <p>{keep_en} Strikes expire separately, after
    <strong>{strike_days} days</strong>, so one bad week does not follow
    someone forever. Long-standing members are never banned automatically.</p>

    <h3>Who can see it</h3>
    <p>Group admins see the decisions in their own groups and can reverse them.
    The operator running the bot has full access for troubleshooting. Nobody
    else: the data is never sold, rented, passed to ad networks, or shown to
    other groups.</p>

    <h3>External services</h3>
    <p>Suspicious message text is sent to <a href="https://groq.com">Groq</a>
    for language-model analysis, and profile photos to
    <a href="https://huggingface.co">Hugging Face</a> to detect generated
    avatars. Both use the data only to return an answer and do not retain it.
    Only messages that already passed a first check are sent — not everything.</p>

    <h3>Deletion and correction</h3>
    <p>To have a record deleted, or a wrong decision corrected, contact your
    group admin. They can do it with one tap, and reversing a decision also
    clears the strike behind it.</p>
  </div>
</details>

</main>

{landing.footer(logo)}
</div>
"""
