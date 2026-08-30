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

CSS = """
.lp{--max:1080px}
.lp a{text-decoration:none}

/* header */
.lp-head{position:sticky;top:0;z-index:20;backdrop-filter:blur(12px);
  background:color-mix(in srgb, var(--page) 82%, transparent);
  border-bottom:1px solid var(--line)}
.lp-head .in{max-width:var(--max);margin:0 auto;padding:14px 24px;
  display:flex;align-items:center;gap:26px}
.lp-brand{display:flex;align-items:center;gap:9px;font-weight:680;font-size:17px;
  letter-spacing:-.02em;color:var(--ink)}
.lp-nav{display:flex;gap:22px;margin-left:12px}
.lp-nav a{color:var(--ink-2);font-size:14px;font-weight:520}
.lp-nav a:hover{color:var(--ink)}
.lp-cta{margin-left:auto;display:flex;gap:10px;align-items:center}
.lp-btn{padding:9px 17px;border-radius:9px;font-size:14px;font-weight:600;
  background:var(--accent);color:#fff;white-space:nowrap}
.lp-btn:hover{filter:brightness(1.08)}
.lp-btn.ghost{background:transparent;color:var(--ink-2);
  box-shadow:inset 0 0 0 1px var(--line)}
.lp-btn.ghost:hover{color:var(--ink);box-shadow:inset 0 0 0 1px var(--accent)}

/* sections */
.lp section{max-width:var(--max);margin:0 auto;padding:84px 24px}
.lp h2{font-size:30px;font-weight:680;letter-spacing:-.028em;margin-bottom:12px}
.lp .lead{color:var(--ink-2);font-size:16px;max-width:620px;line-height:1.65}
.eyebrow{font-size:12px;font-weight:680;letter-spacing:.1em;
  text-transform:uppercase;color:var(--accent);margin-bottom:12px}

/* hero */
.hero-wrap{position:relative;overflow:hidden;
  border-bottom:1px solid var(--line);
  background:
    radial-gradient(900px 380px at 15% -10%,
      color-mix(in srgb, var(--accent) 13%, transparent), transparent 70%),
    radial-gradient(700px 340px at 88% 0%,
      color-mix(in srgb, var(--review) 9%, transparent), transparent 65%)}
.hero-in{max-width:var(--max);margin:0 auto;padding:96px 24px 84px}
.hero h1{font-size:clamp(34px,5.4vw,56px);font-weight:720;letter-spacing:-.04em;
  line-height:1.06;max-width:15ch}
.hero h1 em{font-style:normal;color:var(--accent)}
.hero p{margin:22px 0 0;font-size:18px;line-height:1.62;color:var(--ink-2);
  max-width:56ch}
.hero .row{display:flex;gap:12px;margin-top:32px;flex-wrap:wrap}
.hero .facts{display:flex;gap:34px;margin-top:52px;flex-wrap:wrap}
.fact b{display:block;font-size:25px;font-weight:700;letter-spacing:-.025em}
.fact span{font-size:12.5px;color:var(--muted)}

/* generic grid */
.grid{display:grid;gap:16px;margin-top:36px}
.g2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(248px,1fr))}
.box{background:var(--card);border:1px solid var(--line);border-radius:15px;
  padding:24px;box-shadow:var(--shadow)}
.box h3{font-size:16px;font-weight:650;margin-bottom:8px;letter-spacing:-.01em}
.box p{margin:0;font-size:14px;line-height:1.65;color:var(--ink-2)}
.box .ico{font-size:20px;margin-bottom:14px;display:block}

/* the problem: side-by-side messages */
.msg{border-radius:13px;padding:15px 17px;font-size:14px;line-height:1.6;
  border:1px solid var(--line);background:var(--card)}
.msg .tag{font-size:11px;font-weight:680;letter-spacing:.05em;
  text-transform:uppercase;display:block;margin-bottom:9px}
.msg.ok .tag{color:var(--good)}
.msg.bad .tag{color:var(--ban)}
.msg .txt{color:var(--ink);font-size:14.5px}
.msg .note{margin-top:11px;font-size:12.5px;color:var(--muted);
  padding-top:11px;border-top:1px solid var(--line-soft)}

/* pipeline */
.pipe{background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:30px 26px;margin-top:36px;overflow-x:auto;box-shadow:var(--shadow)}
.pipe svg{display:block;min-width:660px;width:100%;height:auto}

/* stack */
.stack{display:flex;flex-wrap:wrap;gap:9px;margin-top:26px}
.tech{padding:7px 13px;border-radius:8px;font-size:13px;color:var(--ink-2);
  background:var(--card);border:1px solid var(--line)}

/* footer */
.lp-foot{border-top:1px solid var(--line);background:var(--card);margin-top:40px}
.lp-foot .in{max-width:var(--max);margin:0 auto;padding:44px 24px;
  display:flex;gap:34px;flex-wrap:wrap;align-items:flex-start}
.lp-foot .col{min-width:170px}
.lp-foot h4{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted);margin:0 0 12px;font-weight:660}
.lp-foot a,.lp-foot p{display:block;color:var(--ink-2);font-size:13.5px;
  margin:0 0 8px;line-height:1.6}
.lp-foot a:hover{color:var(--accent-ink)}
.lp-foot .bottom{max-width:var(--max);margin:0 auto;padding:0 24px 40px;
  color:var(--muted);font-size:12.5px}

@media (max-width:760px){
  .lp-nav{display:none}
  .lp section{padding:60px 20px}
  .hero-in{padding:64px 20px 56px}
  .lp h2{font-size:24px}
}
"""


def _pipeline() -> str:
    """How a message is judged, as a diagram rather than a paragraph.

    Drawn in SVG with currentColor-driven tokens so it follows the theme, and
    with real text rather than an image, so it stays legible when scaled and
    readable to a screen reader.
    """
    box = (
        '<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" '
        'fill="var(--raised)" stroke="var(--line)"/>'
    )
    out = ['<svg viewBox="0 0 980 210" role="img" aria-label="How a message is '
           'judged: six detectors feed one policy, which decides.">'
           '<style>.t{font:13px system-ui;fill:var(--ink)}'
           '.s{font:11px system-ui;fill:var(--muted)}'
           '.h{font:11px system-ui;font-weight:700;fill:var(--accent);'
           'letter-spacing:.08em}</style>']
    # incoming
    out.append(box.format(x=0, y=72, w=132, h=62))
    out.append('<text class="t" x="66" y="98" text-anchor="middle">Message</text>')
    out.append('<text class="s" x="66" y="116" text-anchor="middle">text · file · edit</text>')

    # detectors
    out.append('<text class="h" x="196" y="26">SIGNALS</text>')
    names = [
        ("Keywords", "multilingual"), ("Links", "typosquats"),
        ("Files", "fake .apk"), ("Pace", "flood / raid"),
        ("Profile", "photo · bio"), ("Language model", "context-aware"),
    ]
    for i, (name, sub) in enumerate(names):
        x, y = 196 + (i % 3) * 176, 40 + (i // 3) * 74
        out.append(box.format(x=x, y=y, w=162, h=58))
        out.append(f'<text class="t" x="{x + 14}" y="{y + 24}">{name}</text>')
        out.append(f'<text class="s" x="{x + 14}" y="{y + 42}">{sub}</text>')

    # policy + outcome
    out.append(box.format(x=736, y=40, w=110, h=126))
    out.append('<text class="t" x="791" y="92" text-anchor="middle">Policy</text>')
    out.append('<text class="s" x="791" y="110" text-anchor="middle">pure rules</text>')
    out.append(box.format(x=872, y=40, w=108, h=126))
    out.append('<text class="s" x="926" y="76" text-anchor="middle">Allow</text>')
    out.append('<text class="s" x="926" y="100" text-anchor="middle">Review</text>')
    out.append('<text class="s" x="926" y="124" text-anchor="middle">Delete</text>')
    out.append('<text class="s" x="926" y="148" text-anchor="middle">Remove</text>')

    for x1, x2, y in ((132, 196, 103), (712, 736, 103), (846, 872, 103)):
        out.append(
            f'<line x1="{x1}" y1="{y}" x2="{x2 - 6}" y2="{y}" '
            f'stroke="var(--line)" stroke-width="1.5"/>'
            f'<path d="M{x2 - 8} {y - 4} L{x2 - 2} {y} L{x2 - 8} {y + 4}" '
            f'fill="var(--muted)"/>'
        )
    out.append("</svg>")
    return "".join(out)


def page(logo: str, signed_in: bool) -> str:
    cta = (
        '<a class="lp-btn" href="/app">Open dashboard</a>' if signed_in
        else '<a class="lp-btn" href="/login">Admin sign in</a>'
    )
    return f"""
<div class="lp">
<header class="lp-head"><div class="in">
  <a class="lp-brand" href="/"><span style="color:var(--accent)">{logo}</span>Qalqon</a>
  <nav class="lp-nav">
    <a href="#problem">The problem</a>
    <a href="#how">How it works</a>
    <a href="#safety">Safety</a>
    <a href="#stack">Built with</a>
  </nav>
  <div class="lp-cta">{cta}</div>
</div></header>

<div class="hero-wrap"><div class="hero-in hero">
  <div class="eyebrow">Telegram moderation</div>
  <h1>Scammers move faster than <em>moderators</em>.</h1>
  <p>Qalqon watches Telegram groups for fraud — fake job offers, advance-fee
  scams, phishing links and disguised malware — in Uzbek, Russian and English.
  It removes what is clearly an attack, and asks a human about everything
  else.</p>
  <div class="row">
    <a class="lp-btn" href="#how">See how it works</a>
    <a class="lp-btn ghost" href="#problem">Why it was built</a>
  </div>
  <div class="facts">
    <div class="fact"><b>6</b><span>independent signals</span></div>
    <div class="fact"><b>3</b><span>languages</span></div>
    <div class="fact"><b>336</b><span>automated tests</span></div>
    <div class="fact"><b>&lt;1s</b><span>typical decision</span></div>
  </div>
</div></div>

<section id="problem">
  <div class="eyebrow">The problem</div>
  <h2>The scam and the honest post look identical.</h2>
  <p class="lead">Qalqon was built for groups of Uzbek workers in South Korea.
  Their two most common messages — daily shift announcements, and swapping
  Korean won for Uzbek so'm — read exactly like fraud to a naive filter.
  An off-the-shelf ruleset flagged four of every fifteen legitimate posts,
  and banned two of them outright.</p>
  <div class="grid g2">
    <div class="msg ok"><span class="tag">✓ Left alone</span>
      <div class="txt">“So'm kerak edi, kimda bor? Karta orqali o'tkazaman”</div>
      <div class="note">A currency exchange offer. Ordinary business in these
      groups — and the message an earlier version banned on sight.</div></div>
    <div class="msg bad"><span class="tag">✕ Removed</span>
      <div class="txt">“Avval siz pul o'tkazing, keyin men won yuboraman”</div>
      <div class="note">“You transfer first, then I'll send.” Same topic, same
      language — but payment is demanded up front.</div></div>
  </div>
  <p class="lead" style="margin-top:26px"><b>The topic is never the signal.</b>
  What separates the two is whether someone is asked to part with money before
  receiving anything. Qalqon is built around that distinction, not around
  keywords about money.</p>
</section>

<section id="how">
  <div class="eyebrow">How it works</div>
  <h2>Six signals, one decision.</h2>
  <p class="lead">Every message is checked by cheap detectors first and the
  language model only when it can still change the outcome. The signals are
  combined, never averaged — and the rules that decide what happens are a pure
  function with no network and no database, so every case can be tested.</p>
  <div class="pipe">{_pipeline()}</div>
  <div class="grid g3">
    <div class="box"><span class="ico">🧠</span><h3>Context-aware</h3>
      <p>The model is told what is normal in these communities, so a shift
      announcement with a daily wage reads as recruitment rather than an
      earnings promise.</p></div>
    <div class="box"><span class="ico">🔗</span><h3>Structural link checks</h3>
      <p>Homographs, typosquats, credentials-in-URL and buried double
      extensions. Nothing is ever fetched — following a stranger's link would
      hand them an SSRF probe.</p></div>
    <div class="box"><span class="ico">⏱️</span><h3>Memory that forgives</h3>
      <p>Repeat offenders escalate; strikes expire, so one bad week does not
      follow someone forever. Long-standing members can never be banned
      automatically.</p></div>
  </div>
</section>

<section id="safety">
  <div class="eyebrow">Safety</div>
  <h2>Built to be wrong safely.</h2>
  <p class="lead">A moderation bot's worst failure is not missing a scam. It is
  removing a real member — and doing it invisibly.</p>
  <div class="grid g3">
    <div class="box"><span class="ico">👥</span><h3>Two signals to act</h3>
      <p>A suspicious message alone is not enough. The sender's profile has to
      agree before anyone is removed; a lone red flag goes to a human
      instead.</p></div>
    <div class="box"><span class="ico">🛟</span><h3>Dry run by default</h3>
      <p>New deployments report what they would do without touching anything,
      so the thresholds can be judged against real traffic before they are
      trusted.</p></div>
    <div class="box"><span class="ico">📣</span><h3>Failure is loud</h3>
      <p>If a detector cannot run, the verdict is marked degraded and admins
      are told. A screening step that quietly stops working is worse than one
      switched off.</p></div>
    <div class="box"><span class="ico">↩️</span><h3>One-tap reversal</h3>
      <p>Every alert carries Ban, Ignore and Trust buttons. Marking a decision
      wrong clears the strike behind it, so a mistake cannot compound.</p></div>
    <div class="box"><span class="ico">🔒</span><h3>Privacy by retention</h3>
      <p>Ordinary conversation is never stored. Only messages that were acted
      on are kept, and only for 90 days.</p></div>
    <div class="box"><span class="ico">📊</span><h3>Measured, not assumed</h3>
      <p>Admin decisions are recorded as ground truth, so the false-positive
      rate is a number on a dashboard rather than a feeling.</p></div>
  </div>
</section>

<section id="stack">
  <div class="eyebrow">Built with</div>
  <h2>Plain Python, tested hard.</h2>
  <p class="lead">Event-driven Model–View–Controller: the controller translates
  Telegram updates, the model holds every rule and all state, and views
  subscribe to what it announces. The model imports no Telegram code at all,
  which is what makes the whole decision path testable without a network.</p>
  <div class="stack">
    <span class="tech">Python 3.12</span>
    <span class="tech">python-telegram-bot</span>
    <span class="tech">Groq · gpt-oss-safeguard</span>
    <span class="tech">Hugging Face</span>
    <span class="tech">FastAPI</span>
    <span class="tech">SQLite · WAL</span>
    <span class="tech">Docker</span>
    <span class="tech">pytest · 336 tests</span>
    <span class="tech">nginx · Let's Encrypt</span>
  </div>
  <div class="grid g3" style="margin-top:30px">
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

<footer class="lp-foot">
  <div class="in">
    <div class="col">
      <a class="lp-brand" href="/" style="margin-bottom:12px">
        <span style="color:var(--accent)">{logo}</span>Qalqon</a>
      <p style="color:var(--muted)">Anti-scam moderation for Telegram
      communities.</p>
    </div>
    <div class="col"><h4>Product</h4>
      <a href="#how">How it works</a><a href="#safety">Safety</a>
      <a href="/privacy">Privacy notice</a></div>
    <div class="col"><h4>Admins</h4>
      <a href="/login">Sign in</a>
      <a href="https://t.me/QalqonSafeBot">@QalqonSafeBot</a></div>
    <div class="col"><h4>Author</h4>
      <a href="https://github.com/Islamintech">Islombek Ergashev</a>
      <p style="color:var(--muted)">Built 2026</p></div>
  </div>
  <div class="bottom">© 2026 Qalqon. Serving Uzbek communities in South Korea.</div>
</footer>
</div>
"""
