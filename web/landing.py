"""The public face of the project.

Everything else in web/ is an operations console for one person. This is the
page a stranger lands on, so it has a different job: explain what the thing is,
why it exists, and how it works, to someone who has never heard of it and will
give it about twenty seconds.

It shows NO live data. Group names, member ids and message text are private to
the communities being moderated, and a portfolio page is the last place they
should appear. Every number here is a property of the software, not of anyone's
conversation.
"""

from . import render

CSS = """
.lp{--max:1100px}
.lp a{text-decoration:none}

/* ---------- header: three zones, so the nav is centred in the bar rather
   than crowding the logo and leaving the right half empty ---------- */
.lp-head{position:sticky;top:0;z-index:20;backdrop-filter:saturate(180%) blur(14px);
  background:color-mix(in srgb, var(--page) 80%, transparent);
  border-bottom:1px solid var(--line)}
.lp-head .in{max-width:var(--max);margin:0 auto;padding:0 28px;height:66px;
  display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px}
.lp-brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:18px;
  letter-spacing:-.025em;color:var(--ink);justify-self:start}
.lp-brand .mark{height:24px;width:auto;flex:none;color:var(--accent)}
.lp-nav{display:flex;gap:4px;align-items:center;justify-self:center}
.lp-nav a{color:var(--ink-2);font-size:14px;font-weight:540;padding:8px 14px;
  border-radius:8px;line-height:1;white-space:nowrap}
.lp-nav a:hover{color:var(--ink);background:var(--raised)}
.lp-cta{justify-self:end;display:flex;gap:10px;align-items:center}
.lp-btn{padding:10px 18px;border-radius:10px;font-size:14px;font-weight:620;
  background:var(--accent);color:#fff;white-space:nowrap;line-height:1;
  box-shadow:0 1px 2px rgba(16,20,24,.12)}
.lp-btn:hover{filter:brightness(1.07)}
.lp-btn.ghost{background:transparent;color:var(--ink-2);
  box-shadow:inset 0 0 0 1px var(--line)}
.lp-btn.ghost:hover{color:var(--ink);box-shadow:inset 0 0 0 1px var(--accent)}

/* ---------- sections: one centred column, so no section is left-packed
   with dead space beside it ---------- */
.lp section{max-width:var(--max);margin:0 auto;padding:90px 28px}
.sec-head{max-width:660px;margin:0 auto 40px;text-align:center}
.lp h2{font-size:clamp(25px,3.2vw,33px);font-weight:690;letter-spacing:-.03em;
  margin-bottom:14px;line-height:1.15}
.lp .lead{color:var(--ink-2);font-size:16.5px;line-height:1.7;margin:0}
.eyebrow{font-size:11.5px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:var(--accent);margin-bottom:14px}

/* ---------- hero: centred, so the headline is not marooned on the left ---
   Named lp-hero, not hero: render.CSS ships a .hero for the dashboard's hero
   CARD (display:flex; align-items:center), and both stylesheets are on every
   page. Under that rule the eyebrow, headline, paragraph, buttons and stats
   became five flex items in one vertically-centred row. */
.hero-wrap{position:relative;overflow:hidden;border-bottom:1px solid var(--line);
  background:
    radial-gradient(880px 420px at 50% -12%,
      color-mix(in srgb, var(--accent) 14%, transparent), transparent 72%),
    radial-gradient(620px 300px at 88% 8%,
      color-mix(in srgb, var(--review) 8%, transparent), transparent 68%)}
.hero-in{max-width:820px;margin:0 auto;padding:104px 28px 92px;text-align:center}
.lp-hero h1{font-size:clamp(35px,5.6vw,58px);font-weight:730;letter-spacing:-.042em;
  line-height:1.05;margin:0 auto;max-width:17ch}
.lp-hero h1 em{font-style:normal;color:var(--accent)}
.lp-hero p{margin:24px auto 0;font-size:18px;line-height:1.62;color:var(--ink-2);
  max-width:54ch}
.lp-hero .row{display:flex;gap:12px;margin-top:34px;flex-wrap:wrap;
  justify-content:center}
.lp-hero .facts{display:flex;justify-content:center;margin-top:58px;flex-wrap:wrap}
.fact{padding:0 30px;border-left:1px solid var(--line);text-align:center}
.fact:first-child{border-left:0}
.fact b{display:block;font-size:27px;font-weight:710;letter-spacing:-.03em;
  line-height:1.15}
.fact span{font-size:12.5px;color:var(--muted)}

/* ---------- grids: explicit columns, so six cards never leave two orphans
   on a row of four ---------- */
.grid{display:grid;gap:16px}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.box{background:var(--card);border:1px solid var(--line);border-radius:15px;
  padding:26px;box-shadow:var(--shadow);display:flex;flex-direction:column}
.box h3{font-size:16px;font-weight:660;margin-bottom:9px;letter-spacing:-.012em}
.box p{margin:0;font-size:14px;line-height:1.68;color:var(--ink-2)}
.box .ico{display:block;margin-bottom:15px;line-height:0;color:var(--accent)}

/* ---------- the two example messages ---------- */
.msg{border-radius:14px;padding:20px 22px;border:1px solid var(--line);
  background:var(--card);box-shadow:var(--shadow);display:flex;
  flex-direction:column}
.msg .tag{display:inline-flex;align-items:center;gap:7px;font-size:11px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;display:block;margin-bottom:12px}
.msg.ok .tag{color:var(--good)}
.msg.bad .tag{color:var(--ban)}
.msg .txt{color:var(--ink);font-size:15px;line-height:1.6}
.msg .cap{margin-top:auto;padding-top:14px;font-size:12.5px;color:var(--muted);
  border-top:1px solid var(--line-soft);line-height:1.6}
.punch{max-width:660px;margin:28px auto 0;text-align:center;font-size:16px;
  line-height:1.7;color:var(--ink-2)}

/* ---------- pipeline ---------- */
.pipe{background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:30px 26px;margin-bottom:36px;overflow-x:auto;box-shadow:var(--shadow)}
.pipe svg{display:block;min-width:620px;width:100%;height:auto}

/* ---------- stack ---------- */
.stack{display:flex;flex-wrap:wrap;gap:9px;justify-content:center;
  max-width:720px;margin:0 auto 38px}
.tech{padding:8px 14px;border-radius:9px;font-size:13px;color:var(--ink-2);
  background:var(--card);border:1px solid var(--line)}

/* ---------- footer: a grid, so the columns space evenly instead of
   bunching to the left ---------- */
.lp-foot{border-top:1px solid var(--line);background:var(--card)}
.lp-foot .in{max-width:var(--max);margin:0 auto;padding:52px 28px 40px;
  display:grid;grid-template-columns:1.6fr 1fr 1fr 1fr;gap:40px}
.lp-foot h4{font-size:11.5px;text-transform:uppercase;letter-spacing:.1em;
  color:var(--muted);margin:0 0 14px;font-weight:680}
.lp-foot a,.lp-foot p{display:block;color:var(--ink-2);font-size:13.5px;
  margin:0 0 9px;line-height:1.6}
.lp-foot a:hover{color:var(--accent-ink)}
.lp-foot .bottom{max-width:var(--max);margin:0 auto;padding:22px 28px 40px;
  color:var(--muted);font-size:12.5px;border-top:1px solid var(--line-soft)}

@media (max-width:900px){
  .lp-head .in{height:auto;grid-template-columns:auto 1fr;padding:12px 20px;
    row-gap:10px}
  .lp-cta{grid-column:2;justify-self:end}
  /* the nav takes its own scrollable row rather than vanishing — a header
     with no navigation is a dead end, and most visitors arrive on a phone */
  .lp-nav{grid-column:1 / -1;grid-row:2;justify-self:stretch;overflow-x:auto;
    gap:2px;scrollbar-width:none}
  .lp-nav::-webkit-scrollbar{display:none}
  .lp-nav a{padding:7px 11px;font-size:13.5px}
  .g3{grid-template-columns:repeat(2,minmax(0,1fr))}
  .lp-foot .in{grid-template-columns:1fr 1fr;gap:30px}
  .fact{padding:0 20px}
}
@media (max-width:620px){
  .lp section{padding:60px 20px}
  .hero-in{padding:64px 20px 56px}
  .g2,.g3{grid-template-columns:minmax(0,1fr)}
  .lp-foot .in{grid-template-columns:1fr;gap:26px;padding:38px 20px 30px}
  .lp-hero .facts{gap:22px 0}
  .fact{flex:1 0 45%;border-left:0;padding:0}
}
"""


def _pipeline() -> str:
    """How a message is judged, as a diagram rather than a paragraph.

    The six detectors sit in two rows, so the connectors fan out from a rail
    rather than running straight across — an arrow drawn to the middle points
    at the gap between the rows and connects nothing.

    Real SVG text rather than an image: it stays sharp at any size, follows the
    theme through CSS variables, and a screen reader can read it.
    """
    W, H = 980, 226
    ROW_Y = (46, 128)          # top edge of each detector row
    BOX_W, BOX_H, GAP_X = 158, 62, 172
    COL_X = 214                # left edge of the first detector column
    RAIL_IN, RAIL_OUT = 178, 726
    MID = H / 2

    line = ('<path d="{d}" fill="none" stroke="var(--line)" '
            'stroke-width="1.5" stroke-linecap="round"/>')
    box = ('<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
           'fill="var(--raised)" stroke="var(--line)"/>')

    out = [
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="A message is '
        'checked by six independent detectors — keywords, links, files, pace, '
        'sender profile and a language model. Their verdicts feed one policy, '
        'which decides between allow, review, delete and remove.">'
        '<style>.t{font:13.5px system-ui;fill:var(--ink)}'
        '.s{font:11px system-ui;fill:var(--muted)}'
        '.h{font:10.5px system-ui;font-weight:700;fill:var(--accent);'
        'letter-spacing:.09em}</style>'
    ]

    # --- incoming ---------------------------------------------------------
    out.append(box.format(x=0, y=MID - 33, w=128, h=66))
    out.append(f'<text class="t" x="64" y="{MID - 4}" text-anchor="middle">Message</text>')
    out.append(f'<text class="s" x="64" y="{MID + 15}" text-anchor="middle">'
               "text · file · edit</text>")

    row_mid = [y + BOX_H / 2 for y in ROW_Y]
    # message -> vertical rail -> each row
    out.append(line.format(d=f"M128 {MID} H{RAIL_IN}"))
    out.append(line.format(d=f"M{RAIL_IN} {row_mid[0]} V{row_mid[1]}"))
    for y in row_mid:
        out.append(line.format(d=f"M{RAIL_IN} {y} H{COL_X - 8}"))
        out.append(f'<path d="M{COL_X - 10} {y - 4} L{COL_X - 3} {y} '
                   f'L{COL_X - 10} {y + 4}" fill="var(--muted)"/>')

    # --- detectors --------------------------------------------------------
    out.append(f'<text class="h" x="{COL_X}" y="28">SIGNALS</text>')
    names = [
        ("Keywords", "multilingual"), ("Links", "typosquats"),
        ("Files", "disguised"), ("Pace", "flood · raid"),
        ("Profile", "photo · bio"), ("Model", "context-aware"),
    ]
    right = COL_X + 2 * GAP_X + BOX_W
    for i, (name, sub) in enumerate(names):
        x, y = COL_X + (i % 3) * GAP_X, ROW_Y[i // 3]
        out.append(box.format(x=x, y=y, w=BOX_W, h=BOX_H))
        out.append(f'<text class="t" x="{x + 15}" y="{y + 26}">{name}</text>')
        out.append(f'<text class="s" x="{x + 15}" y="{y + 45}">{sub}</text>')

    # each row -> rail -> policy
    for y in row_mid:
        out.append(line.format(d=f"M{right} {y} H{RAIL_OUT}"))
    out.append(line.format(d=f"M{RAIL_OUT} {row_mid[0]} V{row_mid[1]}"))
    out.append(line.format(d=f"M{RAIL_OUT} {MID} H{RAIL_OUT + 34}"))
    out.append(f'<path d="M{RAIL_OUT + 32} {MID - 4} L{RAIL_OUT + 39} {MID} '
               f'L{RAIL_OUT + 32} {MID + 4}" fill="var(--muted)"/>')

    # --- policy + outcomes ------------------------------------------------
    px = RAIL_OUT + 42
    out.append(box.format(x=px, y=ROW_Y[0], w=112, h=ROW_Y[1] + BOX_H - ROW_Y[0]))
    out.append(f'<text class="t" x="{px + 56}" y="{MID - 4}" text-anchor="middle">'
               "Policy</text>")
    out.append(f'<text class="s" x="{px + 56}" y="{MID + 15}" text-anchor="middle">'
               "pure rules</text>")

    ox = px + 112
    out.append(line.format(d=f"M{ox} {MID} H{ox + 28}"))
    out.append(f'<path d="M{ox + 26} {MID - 4} L{ox + 33} {MID} '
               f'L{ox + 26} {MID + 4}" fill="var(--muted)"/>')
    outcomes = [("Allow", "var(--good)"), ("Review", "var(--review)"),
                ("Delete", "var(--delete)"), ("Remove", "var(--ban)")]
    oy = ROW_Y[0] + 6
    for i, (label, colour) in enumerate(outcomes):
        y = oy + i * 26
        out.append(f'<circle cx="{ox + 44}" cy="{y - 4}" r="4" fill="{colour}"/>')
        out.append(f'<text class="s" x="{ox + 56}" y="{y}">{label}</text>')
    out.append("</svg>")
    return "".join(out)


def header(logo: str, signed_in: bool, theme: str = "", here: str = "/",
           nav: str = "") -> str:
    """The public site header, shared by the landing page and the notice.

    `nav` is passed in rather than fixed: the landing page's links are anchors
    into its own sections, which point nowhere from any other page.
    """
    cta = (
        '<a class="lp-btn" href="/app">Open dashboard</a>' if signed_in
        else '<a class="lp-btn" href="/login">Admin sign in</a>'
    )
    if not nav:
        nav = (
            '<a href="/#problem">The problem</a>'
            '<a href="/#how">How it works</a>'
            '<a href="/#safety">Safety</a>'
            '<a href="/#stack">Built with</a>'
        )
    return (
        f'<header class="lp-head"><div class="in">'
        f'<a class="lp-brand" href="/">{logo}Qalqon</a>'
        f'<nav class="lp-nav">{nav}</nav>'
        f'<div class="lp-cta">{render.theme_switch(theme, here)}{cta}</div>'
        f"</div></header>"
    )


def footer(logo: str) -> str:
    """The public site footer, shared by the landing page and the notice."""
    return f"""
<footer class="lp-foot">
  <div class="in">
    <div class="col">
      <a class="lp-brand" href="/" style="margin-bottom:12px">{logo}Qalqon</a>
      <p style="color:var(--muted)">Anti-scam moderation for Telegram
      communities.</p>
    </div>
    <div class="col"><h4>Product</h4>
      <a href="/#how">How it works</a><a href="/#safety">Safety</a>
      <a href="/privacy">Privacy notice</a></div>
    <div class="col"><h4>Admins</h4>
      <a href="/login">Sign in</a>
      <a href="https://t.me/QalqonSafeBot">@QalqonSafeBot</a></div>
    <div class="col"><h4>Author</h4>
      <a href="https://github.com/Islamintech">Islombek Ergashev</a>
      <p style="color:var(--muted)">Built 2026</p></div>
  </div>
  <div class="bottom">© 2026 Qalqon. Anti-scam moderation for Telegram
  communities.</div>
</footer>"""


def page(logo: str, signed_in: bool, theme: str = "",
         here: str = "/") -> str:
    nav = ('<a href="#problem">The problem</a>'
           '<a href="#how">How it works</a>'
           '<a href="#safety">Safety</a>'
           '<a href="#stack">Built with</a>')
    return f"""
<div class="lp">
{header(logo, signed_in, theme, here, nav)}

<div class="hero-wrap"><div class="hero-in lp-hero">
  <div class="eyebrow">Telegram moderation</div>
  <h1>Scammers move faster than <em>moderators</em>.</h1>
  <p>Qalqon watches Telegram groups for fraud — advance-fee scams, fake
  offers, phishing links and disguised malware — across languages. It removes
  what is clearly an attack, and asks a human about everything else.</p>
  <div class="row">
    <a class="lp-btn" href="#how">See how it works</a>
    <a class="lp-btn ghost" href="#problem">Why it was built</a>
  </div>
  <div class="facts">
    <div class="fact"><b>6</b><span>independent signals</span></div>
    <div class="fact"><b>∞</b><span>languages</span></div>
    <div class="fact"><b>369</b><span>automated tests</span></div>
    <div class="fact"><b>&lt;1s</b><span>typical decision</span></div>
  </div>
</div></div>

<section id="problem">
  <div class="sec-head">
    <div class="eyebrow">The problem</div>
    <h2>The scam and the honest post look identical.</h2>
    <p class="lead">Real communities talk about money constantly — job offers,
    buying and selling, splitting bills, exchanging currency. A filter tuned to
    flag those buries the group's purpose in false alarms, and eventually
    removes the members who post most usefully. Measured against real traffic,
    a generic ruleset flagged four of every fifteen legitimate posts, and
    banned two of them outright.</p>
  </div>
  <div class="grid g2">
    <div class="msg ok"><span class="tag">{render.icon("check", 12)}Left alone</span>
      <div class="txt">“Anyone got a spare shift tomorrow? Happy to cover it —
      message me”</div>
      <div class="cap">Every keyword here appears in scams too. Nothing is
      being asked of anyone, so nothing happens.</div></div>
    <div class="msg bad"><span class="tag">{render.icon("ban", 12)}Removed</span>
      <div class="txt">“I can get you the job — just send the 300 deposit
      first and I'll confirm today”</div>
      <div class="cap">Same subject, same tone. But money is demanded before
      anything is delivered.</div></div>
  </div>
  <p class="punch"><b>The topic is never the signal.</b> What separates the two
  is whether someone is asked to part with money or credentials before
  receiving anything. Qalqon is built around that distinction rather than
  around keywords about money — which is also why it works the same way in a
  language it has never been tuned for.</p>
</section>

<section id="how">
  <div class="sec-head">
    <div class="eyebrow">How it works</div>
    <h2>Six signals, one decision.</h2>
    <p class="lead">Cheap detectors run first; the language model only when it
    can still change the outcome. The signals are combined, never averaged —
    and the rules that decide what happens are a pure function with no network
    and no database, so every case can be tested.</p>
  </div>
  <div class="pipe">{_pipeline()}</div>
  <div class="grid g3">
    <div class="box"><span class="ico">{render.icon("context", 21)}</span><h3>Context-aware</h3>
      <p>The model is told what is normal for the community it guards, so a
      job post quoting a daily rate reads as recruitment rather than an
      earnings promise.</p></div>
    <div class="box"><span class="ico">{render.icon("link", 21)}</span><h3>Structural link checks</h3>
      <p>Homographs, typosquats, credentials-in-URL and buried double
      extensions. Nothing is ever fetched — following a stranger's link would
      hand them an SSRF probe.</p></div>
    <div class="box"><span class="ico">{render.icon("clock", 21)}</span><h3>Memory that forgives</h3>
      <p>Repeat offenders escalate; strikes expire, so one bad week does not
      follow someone forever. Long-standing members can never be banned
      automatically.</p></div>
  </div>
</section>

<section id="safety">
  <div class="sec-head">
    <div class="eyebrow">Safety</div>
    <h2>Built to be wrong safely.</h2>
    <p class="lead">A moderation bot's worst failure is not missing a scam. It
    is removing a real member — and doing it invisibly.</p>
  </div>
  <div class="grid g3">
    <div class="box"><span class="ico">{render.icon("people", 21)}</span><h3>Two signals to act</h3>
      <p>A suspicious message alone is not enough. The sender's profile has to
      agree before anyone is removed; a lone red flag goes to a human
      instead.</p></div>
    <div class="box"><span class="ico">{render.icon("buoy", 21)}</span><h3>Dry run by default</h3>
      <p>New deployments report what they would do without touching anything,
      so the thresholds can be judged against real traffic before they are
      trusted.</p></div>
    <div class="box"><span class="ico">{render.icon("megaphone", 21)}</span><h3>Failure is loud</h3>
      <p>If a detector cannot run, the verdict is marked degraded and admins
      are told. A screening step that quietly stops working is worse than one
      switched off.</p></div>
    <div class="box"><span class="ico">{render.icon("undo", 21)}</span><h3>One-tap reversal</h3>
      <p>Every alert carries Ban, Ignore and Trust buttons. Marking a decision
      wrong clears the strike behind it, so a mistake cannot compound.</p></div>
    <div class="box"><span class="ico">{render.icon("lock", 21)}</span><h3>Privacy by retention</h3>
      <p>Ordinary conversation is never stored. Only messages that were acted
      on are kept, and only for 90 days.</p></div>
    <div class="box"><span class="ico">{render.icon("bars", 21)}</span><h3>Measured, not assumed</h3>
      <p>Admin decisions are recorded as ground truth, so the false-positive
      rate is a number on a dashboard rather than a feeling.</p></div>
  </div>
</section>

<section id="stack">
  <div class="sec-head">
    <div class="eyebrow">Built with</div>
    <h2>Plain Python, tested hard.</h2>
    <p class="lead">Event-driven Model–View–Controller: the controller
    translates Telegram updates, the model holds every rule and all state, and
    views subscribe to what it announces. The model imports no Telegram code at
    all, which is what makes the whole decision path testable without a
    network.</p>
  </div>
  <div class="stack">
    <span class="tech">Python 3.12</span>
    <span class="tech">python-telegram-bot</span>
    <span class="tech">Groq · gpt-oss-safeguard</span>
    <span class="tech">Hugging Face</span>
    <span class="tech">FastAPI</span>
    <span class="tech">SQLite · WAL</span>
    <span class="tech">Docker</span>
    <span class="tech">pytest · 369 tests</span>
    <span class="tech">nginx · Let's Encrypt</span>
  </div>
  <div class="grid g3">
    <div class="box"><h3>No network in the tests</h3>
      <p>Telegram, Groq and Hugging Face are all substituted, so the full
      escalation matrix runs in seconds on every change.</p></div>
    <div class="box"><h3>Read-only dashboard</h3>
      <p>The web process opens the database read-only and mounts it read-only.
      A bug here cannot alter moderation state.</p></div>
    <div class="box"><h3>Deploys as one container</h3>
      <p>No published ports — the bot polls outbound and listens on nothing, so
      it adds no attack surface to the host.</p></div>
  </div>
</section>

{footer(logo)}
</div>
"""
