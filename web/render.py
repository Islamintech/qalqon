"""Design system for the dashboard: tokens, chrome, and chart rendering.

LIGHT BY DEFAULT, dark when the viewer's OS asks. Both are *selected* palettes
validated against their own surface, not one flipped into the other:

    role     light      dark
    review   #2a78d6    #3987e5     blue
    delete   #eda100    #c98500     amber
    ban      #e34948    #d55181     red / rose

Light passes every separation gate (CVD ΔE 15.3, normal-vision 20.8) with a
contrast WARN on the amber, which the relief rule covers — the legend and the
table view are both present, so colour never carries a value alone.

Dark could not keep the same red: against the dark surface, amber and red land
at normal-vision ΔE 13.0, below the 15 floor. The rose step is the nearest
passing red. This is exactly why per-mode steps are chosen rather than one
palette inverted into the other.

Colour carries identity only; severity comes from the wording, the order and
the icons.

PLAIN LANGUAGE. The first version showed BAN / DELETE / REVIEW, raw chat ids,
and reason strings like "content=RED_FLAG(llm); profile=CLEAN". That reads as a
database dump. An operator wants to know what happened to whom — "member
removed", "message deleted" — with the machine detail available but out of the
way.
"""

# --- tokens ----------------------------------------------------------------
SERIES = {"REVIEW": "#2a78d6", "DELETE": "#eda100", "BAN": "#e34948"}
SERIES_DARK = {"REVIEW": "#3987e5", "DELETE": "#c98500", "BAN": "#d55181"}
SERIES_ORDER = ["BAN", "DELETE", "REVIEW"]

# What each action is called in the interface, and its icon.
LABEL = {
    "BAN": ("Member removed", "🚫"),
    "DELETE": ("Message deleted", "🧹"),
    "REVIEW": ("Needs review", "⚠️"),
    "ADMIN_BAN": ("You banned", "🚫"),
    "ADMIN_UNBAN": ("You unbanned", "♻️"),
    "ADMIN_IGNORE": ("You marked it a mistake", "👌"),
    "ADMIN_WHITELIST": ("You trusted", "✅"),
}
PLURAL = {"BAN": "removed", "DELETE": "deleted", "REVIEW": "to review"}

NAV = [
    ("/app", "Overview", "▦"),
    ("/groups", "Groups", "◍"),
    ("/members", "Members", "◎"),
    ("/activity", "Activity", "◔"),
    ("/usage", "Usage", "◑"),
]

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --page:#f6f7f9; --card:#ffffff; --raised:#f2f4f7;
  --line:#e4e7ec; --line-soft:#eef1f4;
  --ink:#101418; --ink-2:#4a5260; --muted:#79808f;
  --accent:#2a78d6; --accent-soft:#eaf2fd; --accent-ink:#1b5fae;
  --review:#2a78d6; --delete:#eda100; --ban:#e34948;
  --review-bg:#eaf2fd; --delete-bg:#fdf3dd; --ban-bg:#fdecec;
  --good:#0f8a3d; --good-bg:#e7f6ec;
  --shadow:0 1px 2px rgba(16,20,24,.05),0 1px 3px rgba(16,20,24,.04);
  --shadow-lg:0 2px 4px rgba(16,20,24,.05),0 8px 24px rgba(16,20,24,.07);
}
@media (prefers-color-scheme:dark){
  :root{
    color-scheme:dark;
    --page:#0f1115; --card:#171a21; --raised:#1c2029;
    --line:#242936; --line-soft:#1e222c;
    --ink:#e9ecf2; --ink-2:#a2a9b8; --muted:#767d8d;
    --accent:#3987e5; --accent-soft:#17253b; --accent-ink:#8ab4ff;
    --review:#3987e5; --delete:#c98500; --ban:#d55181;
    --review-bg:#152435; --delete-bg:#2d2510; --ban-bg:#33202a;
    --good:#3fbe6b; --good-bg:#152a1c;
    --shadow:none; --shadow-lg:none;
  }
}
body{margin:0;background:var(--page);color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:var(--accent-ink);text-decoration:none}
a:hover{text-decoration:underline}
h1,h2,h3{margin:0}

/* ---------- shell: a horizontal bar, not a sidebar ----------
   Five destinations do not need a 216px column taking a fifth of the width
   from the content on every page. */
.shell{min-height:100vh;display:flex;flex-direction:column}
.topbar{position:sticky;top:0;z-index:20;background:var(--card);
  border-bottom:1px solid var(--line);
  backdrop-filter:saturate(180%) blur(14px)}
.topbar .in{max-width:1240px;margin:0 auto;padding:0 26px;height:60px;
  display:flex;align-items:center;gap:20px}
.brand{display:flex;align-items:center;gap:9px;font-weight:700;font-size:16.5px;
  letter-spacing:-.022em;color:var(--ink);flex:none}
.brand svg{width:20px;height:22px;flex:none}
nav{display:flex;gap:3px;align-items:center;overflow-x:auto;
  scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav a{display:flex;align-items:center;gap:7px;padding:8px 13px;border-radius:8px;
  color:var(--ink-2);font-size:14px;font-weight:540;white-space:nowrap;
  line-height:1}
nav a:hover{background:var(--raised);color:var(--ink);text-decoration:none}
nav a[aria-current="page"]{background:var(--accent-soft);color:var(--accent-ink);
  font-weight:640}
nav a i{font-style:normal;opacity:.7;font-size:12.5px}
.bar-end{margin-left:auto;display:flex;align-items:center;gap:14px;flex:none}
.bar-end .who{font-size:12.5px;color:var(--muted);white-space:nowrap}
.bar-end a{font-size:12.5px;color:var(--ink-2)}
.bar-end a:hover{color:var(--accent-ink)}
main{flex:1;width:100%;max-width:1240px;margin:0 auto;padding:28px 26px 64px}

/* ---------- page head ---------- */
.phead{display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap;
  margin-bottom:22px}
.phead h1{font-size:clamp(19px,3.2vw,22px);font-weight:660;letter-spacing:-.02em}
.phead p{margin:3px 0 0;color:var(--muted);font-size:13.5px}
.pill{padding:4px 10px;border-radius:999px;font-size:11.5px;font-weight:640;
  letter-spacing:.02em;display:inline-block}
.pill.dry{background:var(--good-bg);color:var(--good)}
.pill.live{background:var(--ban-bg);color:var(--ban)}
.grow{flex:1}

/* ---------- filters ---------- */
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.chip{padding:6px 13px;border-radius:8px;font-size:13px;color:var(--ink-2);
  background:var(--card);border:1px solid var(--line);white-space:nowrap}
.chip:hover{text-decoration:none;border-color:var(--accent);color:var(--ink)}
.chip[aria-current="true"]{background:var(--accent);border-color:var(--accent);
  color:#fff;font-weight:600}

/* ---------- cards & tiles ---------- */
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  box-shadow:var(--shadow)}
.pad{padding:20px 22px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));
  gap:14px;margin-bottom:26px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:17px 19px;box-shadow:var(--shadow)}
.tile .v{font-size:clamp(23px,4.4vw,28px);font-weight:680;letter-spacing:-.03em;line-height:1.1}
.tile .k{font-size:12.5px;color:var(--muted);margin-top:4px}
.hero{display:flex;align-items:center;gap:22px;flex-wrap:wrap;
  padding:24px 26px;margin-bottom:14px}
.hero .v{font-size:clamp(34px,7vw,54px);font-weight:700;letter-spacing:-.045em;line-height:1;
  color:var(--accent-ink)}
.hero .k{font-size:14px;color:var(--ink-2);line-height:1.5}

/* ---------- action chips ---------- */
.act{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;
  border-radius:7px;font-size:12px;font-weight:620;white-space:nowrap}
.act.BAN,.act.ADMIN_BAN{background:var(--ban-bg);color:var(--ban)}
.act.DELETE{background:var(--delete-bg);color:var(--delete)}
.act.REVIEW{background:var(--review-bg);color:var(--review)}
.act.ADMIN_IGNORE,.act.ADMIN_UNBAN,.act.ADMIN_WHITELIST{
  background:var(--raised);color:var(--ink-2)}

/* ---------- group cards ---------- */
.gcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(272px,1fr));
  gap:14px}
.gcard{display:block;background:var(--card);border:1px solid var(--line);
  border-radius:14px;padding:18px 20px;color:inherit;box-shadow:var(--shadow)}
.gcard:hover{text-decoration:none;border-color:var(--accent);
  box-shadow:var(--shadow-lg)}
.gname{font-size:16px;font-weight:640;letter-spacing:-.01em;overflow-wrap:anywhere}
.gsub{font-size:12px;color:var(--muted);margin-top:2px}
.gnums{display:flex;gap:20px;margin:15px 0 12px}
.gnum b{display:block;font-size:23px;font-weight:680;letter-spacing:-.02em;
  line-height:1.15}
.gnum span{font-size:11.5px;color:var(--muted)}
.gfoot{font-size:12px;color:var(--ink-2);border-top:1px solid var(--line-soft);
  padding-top:11px}

/* ---------- feed ---------- */
.feed{display:flex;flex-direction:column}
.item{display:flex;gap:14px;padding:16px 22px;
  border-bottom:1px solid var(--line-soft)}
.item:last-child{border-bottom:0}
.item .who{font-weight:600;font-size:14px;display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.item .meta{font-size:12px;color:var(--muted);margin-top:3px}
.item .said{font-size:13.5px;color:var(--ink-2);margin-top:9px;
  background:var(--raised);border-radius:9px;padding:9px 12px;
  overflow-wrap:anywhere;border-left:2px solid var(--line)}
.item .when{margin-left:auto;font-size:12px;color:var(--muted);
  white-space:nowrap;padding-left:10px}

/* ---------- tables ---------- */
.wrap{overflow-x:auto;border-radius:14px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;color:var(--muted);font-weight:620;padding:12px 18px;
  border-bottom:1px solid var(--line);font-size:11.5px;text-transform:uppercase;
  letter-spacing:.05em;white-space:nowrap}
td{padding:13px 18px;border-bottom:1px solid var(--line-soft)}
tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--raised)}
.num{font-variant-numeric:tabular-nums}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
  color:var(--muted)}
.dim{color:var(--muted)}

/* ---------- chart ---------- */
.legend{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:16px}
.lg{display:flex;align-items:center;gap:7px;font-size:13px;color:var(--ink-2)}
.sw{width:11px;height:11px;border-radius:3px;flex:none}
.chart{width:100%;height:auto;display:block}
.chart text{font:11px system-ui,-apple-system,sans-serif;fill:var(--muted);
  font-variant-numeric:tabular-nums}
.chart .seg:hover{opacity:.8}

/* ---------- empty states ---------- */
.empty{padding:54px 28px;text-align:center}
.empty .icon{font-size:30px;opacity:.5}
.empty h3{font-size:16px;font-weight:620;margin:14px 0 6px}
.empty p{margin:0 auto;max-width:430px;color:var(--muted);font-size:13.5px;
  line-height:1.6}
.empty .hint{margin-top:18px;display:inline-block;text-align:left;
  background:var(--raised);border-radius:10px;padding:13px 17px;
  font-size:13px;color:var(--ink-2);line-height:1.8}

.note{background:var(--delete-bg);border-radius:11px;padding:13px 17px;
  font-size:13px;color:var(--ink-2);line-height:1.55;margin-top:14px}
details{margin-top:10px}
summary{cursor:pointer;font-size:12.5px;color:var(--muted);list-style:none}
summary::-webkit-details-marker{display:none}
summary:hover{color:var(--ink-2)}

/* ---------- login ---------- */
.login{max-width:400px;margin:13vh auto;text-align:center;padding:0 20px}
.login .card{padding:32px 28px}
.login h1{font-size:21px;margin-bottom:6px}
.login p{color:var(--muted);font-size:13.5px;margin:0 0 20px}
.field{width:100%;padding:11px 13px;border-radius:10px;
  border:1px solid var(--line);background:var(--page);color:var(--ink);
  font-size:14px}
.field:focus{outline:2px solid var(--accent);outline-offset:1px}
.btn{margin-top:10px;width:100%;padding:11px;border-radius:10px;border:0;
  background:var(--accent);color:#fff;font-size:14px;font-weight:620;
  cursor:pointer}
code{background:var(--raised);padding:2px 6px;border-radius:5px;font-size:12.5px}

@media (max-width:1080px){
  .topbar .in,main{padding-left:20px;padding-right:20px}
}
@media (max-width:880px){
  .topbar .in{height:auto;padding:11px 20px;flex-wrap:wrap;row-gap:9px}
  .bar-end{margin-left:auto}
  /* the nav takes the full second row and scrolls, instead of collapsing to
     icons nobody can identify */
  nav{order:3;width:100%;padding-bottom:1px}
  main{padding:22px 20px 52px}
}

/* Below this the layout stops being a scaled-down desktop: the grids re-flow
   to two columns rather than one tall stack, and the chart starts to scroll.
   An SVG with a fixed viewBox shrinks its TEXT along with its bars, so a chart
   that merely fits a phone has axis labels around 5px tall. Better to keep the
   type legible and let the plot scroll under the finger. */
@media (max-width:720px){
  .tiles{grid-template-columns:repeat(auto-fit,minmax(136px,1fr));gap:10px;
    margin-bottom:20px}
  .tile{padding:14px 15px;border-radius:12px}
  .gcards{grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
  .gcard{padding:15px 16px}
  .gnums{gap:16px;margin:12px 0 10px}
  .hero{padding:18px 20px;gap:16px}
  .pad{padding:16px 17px;overflow-x:auto}
  .chart{min-width:520px}
  .legend{gap:14px;margin-bottom:13px}
  th{padding:10px 13px}
  td{padding:11px 13px}
  .empty{padding:40px 20px}
}

/* Phones. The feed row is the piece that genuinely breaks: a timestamp pinned
   right by margin-left:auto squeezes the message it belongs to down to a few
   characters per line, so it drops to its own line instead. */
@media (max-width:560px){
  .topbar .in,main{padding-left:14px;padding-right:14px}
  main{padding-bottom:44px}
  .item{padding:14px 16px;flex-wrap:wrap}
  .item .when{margin-left:0;padding-left:0;width:100%;margin-top:9px}
  .filters{gap:6px;margin-bottom:16px}
  .chip{padding:5px 11px;font-size:12.5px}
  .phead{gap:10px;margin-bottom:18px}
  .login{margin:7vh auto}
  .login .card{padding:26px 20px}
}
@media (max-width:430px){
  .bar-end .who{display:none}
  .tiles{grid-template-columns:1fr 1fr}
  .brand{font-size:15.5px}
  nav a{padding:7px 11px}
}
"""

LOGO = (
    '<svg width="21" height="23" viewBox="0 0 20 22" fill="none" '
    'aria-hidden="true"><path d="M10 1 18.2 4v7.1c0 4.6-3.3 8.2-8.2 9.9'
    '-4.9-1.7-8.2-5.3-8.2-9.9V4L10 1Z" fill="currentColor"/>'
    '<path d="m6.4 10.9 2.5 2.5 4.9-4.9" stroke="var(--card)" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def topbar(active: str, dry_run: bool, user_label: str) -> str:
    """Horizontal navigation.

    Five destinations do not justify a fixed column stealing a fifth of the
    width on every page — and the pages that matter most (Activity, Usage) are
    the widest, so they were the ones paying for it.
    """
    links = "".join(
        f'<a href="{href}" aria-current="{"page" if href == active else "false"}">'
        f"<i>{icon}</i><span>{name}</span></a>"
        for href, name, icon in NAV
    )
    mode = (
        '<span class="pill dry">Dry run</span>' if dry_run
        else '<span class="pill live">Live</span>'
    )
    return (
        f'<header class="topbar"><div class="in">'
        f'<a class="brand" href="/"><span style="color:var(--accent)">{LOGO}</span>'
        f'<span>Qalqon</span></a>'
        f"<nav>{links}</nav>"
        f'<div class="bar-end">{mode}'
        f'<span class="who">{user_label}</span>'
        f'<a href="/logout">Sign out</a></div>'
        f"</div></header>"
    )


def empty(icon: str, title: str, body: str, hint: str = "") -> str:
    """An empty state should say what to DO, not just that there is nothing.

    With three events the old page looked broken rather than quiet, and gave a
    reader no way to tell "working, nothing to report" from "misconfigured".
    """
    hint_html = f'<div class="hint">{hint}</div>' if hint else ""
    return (
        f'<div class="card"><div class="empty"><div class="icon">{icon}</div>'
        f"<h3>{title}</h3><p>{body}</p>{hint_html}</div></div>"
    )


def legend(keys=None) -> str:
    keys = keys or SERIES_ORDER
    items = "".join(
        f'<span class="lg"><span class="sw" style="background:var(--{k.lower()})">'
        f"</span>{LABEL[k][0]}</span>"
        for k in keys
    )
    return f'<div class="legend">{items}</div>'


def bar_chart(daily: list[dict], height: int = 210) -> str:
    """Stacked daily activity.

    2px surface gap between stacked segments rather than a border, rounded
    data-end on the top segment only, solid hairline grid, no value printed on
    every bar. Each segment carries a <title> so the exact number is reachable
    on hover without JavaScript; the table view below is the WCAG-clean twin.
    """
    n = len(daily)
    if not n:
        return ""

    totals = [d["REVIEW"] + d["DELETE"] + d["BAN"] for d in daily]
    peak = max(totals) or 1
    step = 1 if peak <= 4 else (2 if peak <= 10 else 5 if peak <= 25 else 10)
    top = ((peak + step - 1) // step) * step

    pad_l, pad_r, pad_t, pad_b = 34, 6, 10, 26
    w = 760
    plot_w, plot_h = w - pad_l - pad_r, height - pad_t - pad_b
    band = plot_w / n
    bar_w = min(band * 0.6, 30)

    out = [
        f'<svg class="chart" viewBox="0 0 {w} {height}" role="img" '
        f'aria-label="Moderation actions per day">'
    ]
    for t in sorted({0, top // 2, top}):
        y = pad_t + plot_h - (t / top) * plot_h
        out.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
            f'stroke="var(--line-soft)" stroke-width="1"/>'
            f'<text x="{pad_l - 9}" y="{y + 3.5:.1f}" text-anchor="end">{t}</text>'
        )

    for i, d in enumerate(daily):
        x = pad_l + i * band + (band - bar_w) / 2
        y = pad_t + plot_h
        stack = [(k, d[k]) for k in ("REVIEW", "DELETE", "BAN") if d[k]]
        for j, (key, value) in enumerate(stack):
            h = (value / top) * plot_h
            gap = 2 if j < len(stack) - 1 else 0
            y -= h
            radius = 'rx="4"' if j == len(stack) - 1 else ""
            out.append(
                f'<rect class="seg" x="{x:.1f}" y="{y + gap:.1f}" '
                f'width="{bar_w:.1f}" height="{max(h - gap, 2):.1f}" {radius} '
                f'fill="var(--{key.lower()})"><title>{d["day"]}: {value} '
                f"{PLURAL[key]}</title></rect>"
            )
        if not stack:
            # A flat tick, so an empty day reads as zero rather than missing.
            out.append(
                f'<rect x="{x:.1f}" y="{pad_t + plot_h - 2:.1f}" '
                f'width="{bar_w:.1f}" height="2" rx="1" fill="var(--line)"/>'
            )

    out.append(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{w - pad_r}" '
        f'y2="{pad_t + plot_h}" stroke="var(--line)" stroke-width="1"/>'
    )
    every = 1 if n <= 8 else (2 if n <= 16 else 5)
    for i, d in enumerate(daily):
        if i % every and i != n - 1:
            continue
        cx = pad_l + i * band + band / 2
        out.append(
            f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="middle">'
            f'{d["day"][5:]}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def tokens_chart(daily: list[dict], height: int = 180) -> str:
    """Tokens per day, with the cached share shown beneath.

    One series with a second stacked underneath rather than two charts: the
    question is "how much did we use, and how much of it did the cache save",
    and those only mean anything side by side.
    """
    n = len(daily)
    if not n:
        return ""
    peak = max(d["tokens"] for d in daily) or 1
    # Round up to something readable rather than to the raw peak.
    mag = 10 ** max(len(str(int(peak))) - 2, 0)
    top = ((int(peak) // mag) + 1) * mag

    pad_l, pad_r, pad_t, pad_b = 48, 6, 10, 26
    w = 760
    plot_w, plot_h = w - pad_l - pad_r, height - pad_t - pad_b
    band = plot_w / n
    bar_w = min(band * 0.6, 30)

    def fmt(v: int) -> str:
        return f"{v // 1000}k" if v >= 1000 else str(v)

    out = [
        f'<svg class="chart" viewBox="0 0 {w} {height}" role="img" '
        f'aria-label="Tokens used per day">'
    ]
    for t in sorted({0, top // 2, top}):
        y = pad_t + plot_h - (t / top) * plot_h
        out.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
            f'stroke="var(--line-soft)" stroke-width="1"/>'
            f'<text x="{pad_l - 9}" y="{y + 3.5:.1f}" text-anchor="end">'
            f"{fmt(t)}</text>"
        )
    for i, d in enumerate(daily):
        x = pad_l + i * band + (band - bar_w) / 2
        h = (d["tokens"] / top) * plot_h
        y = pad_t + plot_h - h
        out.append(
            f'<rect class="seg" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{max(h, 2):.1f}" rx="4" fill="var(--accent)">'
            f'<title>{d["day"]}: {d["tokens"]:,} tokens over {d["calls"]} '
            f'calls ({d["cached"]} from cache)</title></rect>'
        )
    out.append(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{w - pad_r}" '
        f'y2="{pad_t + plot_h}" stroke="var(--line)" stroke-width="1"/>'
    )
    every = 1 if n <= 8 else (2 if n <= 16 else 5)
    for i, d in enumerate(daily):
        if i % every and i != n - 1:
            continue
        cx = pad_l + i * band + band / 2
        out.append(
            f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="middle">'
            f'{d["day"][5:]}</text>'
        )
    out.append("</svg>")
    return "".join(out)
