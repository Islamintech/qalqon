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

# What each action is called in the interface, and which icon draws it.
#
# These were emoji. Emoji are a different typeface on every platform — the same
# chip rendered as a flat glyph here and a colour cartoon there, at a size the
# CSS could not control — and they carry no stroke, so they never matched the
# weight of the text beside them. Drawn icons scale and recolour with the chip.
LABEL = {
    "BAN": ("Member removed", "ban"),
    "DELETE": ("Message deleted", "broom"),
    "REVIEW": ("Needs review", "warn"),
    "ADMIN_BAN": ("You banned", "ban"),
    "ADMIN_UNBAN": ("You unbanned", "undo"),
    "ADMIN_IGNORE": ("You marked it a mistake", "undo"),
    "ADMIN_WHITELIST": ("You trusted", "check"),
}

# One stroke style throughout: 16-unit box, 1.4 stroke, round caps, no fills,
# so every icon inherits the colour and optical weight of its context.
PATHS = {
    "grid": '<rect x="2" y="2" width="5" height="5" rx="1"/>'
            '<rect x="9" y="2" width="5" height="5" rx="1"/>'
            '<rect x="2" y="9" width="5" height="5" rx="1"/>'
            '<rect x="9" y="9" width="5" height="5" rx="1"/>',
    "groups": '<circle cx="6" cy="6" r="2.6"/><circle cx="11" cy="10" r="2.6"/>'
              '<path d="M7.7 7.9 9.3 8.6"/>',
    "member": '<circle cx="8" cy="5.5" r="2.6"/>'
              '<path d="M3 13.2c.7-2.3 2.6-3.5 5-3.5s4.3 1.2 5 3.5"/>',
    "clock": '<circle cx="8" cy="8" r="5.8"/><path d="M8 4.6V8l2.4 1.6"/>',
    "bars": '<path d="M2.5 13V7.5M6.2 13V3.5M9.8 13V9.5M13.5 13V6"/>',
    "ban": '<circle cx="8" cy="8" r="5.6"/><path d="M4 4l8 8"/>',
    "broom": '<path d="M3 13h10M5 4h6M5.6 4l-.8 9M10.4 4l.8 9"/>',
    "warn": '<path d="M8 2.6 14.2 13H1.8L8 2.6Z"/><path d="M8 6.6v2.6M8 11h.01"/>',
    "check": '<path d="M3.4 8.4 6.6 11.6l6-6.4"/>',
    "undo": '<path d="M3 8a5 5 0 1 0 1.6-3.7"/><path d="M2.6 3v3.2h3.2"/>',
    "shield": '<path d="M8 2 13 3.9v4.4c0 2.9-2 5.1-5 6.2-3-1.1-5-3.3-5-6.2V3.9L8 2Z"/>'
              '<path d="M5.9 8.1 7.4 9.6l3-3"/>',
    "quiet": '<circle cx="8" cy="8" r="5.8"/><path d="M5.4 8h5.2"/>',
    # --- landing page ------------------------------------------------------
    "context": '<path d="M8 3.2a2.4 2.4 0 0 0-4.3 1.4A2.2 2.2 0 0 0 3 8.4'
               'a2.2 2.2 0 0 0 1.4 2.9A2.3 2.3 0 0 0 8 12.8Z"/>'
               '<path d="M8 3.2a2.4 2.4 0 0 1 4.3 1.4A2.2 2.2 0 0 1 13 8.4'
               'a2.2 2.2 0 0 1-1.4 2.9A2.3 2.3 0 0 1 8 12.8Z"/>',
    "link": '<path d="M8.6 11.4a3.2 3.2 0 0 0 4.6 0l1.2-1.2a3.2 3.2 0 0 0-4.6-4.6'
            'l-.7.7"/><path d="M7.4 4.6a3.2 3.2 0 0 0-4.6 0L1.6 5.8a3.2 3.2 0 0 0 '
            '4.6 4.6l.7-.7"/>',
    "people": '<circle cx="6" cy="5.6" r="2.3"/>'
              '<path d="M1.8 13c.6-2 2.2-3.1 4.2-3.1s3.6 1.1 4.2 3.1"/>'
              '<path d="M10.6 3.6a2.3 2.3 0 0 1 0 4"/>'
              '<path d="M11.6 9.4c1.5.3 2.4 1.3 2.8 2.8"/>',
    "buoy": '<circle cx="8" cy="8" r="6"/><circle cx="8" cy="8" r="2.4"/>'
            '<path d="M3.8 3.8 6.3 6.3M9.7 9.7l2.5 2.5M12.2 3.8 9.7 6.3'
            'M6.3 9.7l-2.5 2.5"/>',
    "megaphone": '<path d="M2.4 6.6v2.8h2.2L9.6 12V4L4.6 6.6Z"/>'
                 '<path d="M11.6 5.8a3 3 0 0 1 0 4.4"/>'
                 '<path d="M4.6 9.4v2.8h2v-2"/>',
    "lock": '<rect x="3" y="7" width="10" height="6.4" rx="1.6"/>'
            '<path d="M5.4 7V5.2a2.6 2.6 0 0 1 5.2 0V7"/>',
    # --- theme switch ------------------------------------------------------
    "sun": '<circle cx="8" cy="8" r="2.9"/>'
           '<path d="M8 1.6v1.5M8 12.9v1.5M14.4 8h-1.5M3.1 8H1.6'
           'M12.5 3.5l-1 1M4.5 11.5l-1 1M12.5 12.5l-1-1M4.5 4.5l-1-1"/>',
    "moon": '<path d="M13 9.4A5.6 5.6 0 0 1 6.6 3a5.8 5.8 0 1 0 6.4 6.4Z"/>',
}


PLURAL = {"BAN": "removed", "DELETE": "deleted", "REVIEW": "to review"}

NAV = [
    ("/app", "Overview", "grid"),
    ("/groups", "Groups", "groups"),
    ("/members", "Members", "member"),
    ("/activity", "Activity", "clock"),
    ("/usage", "Usage", "bars"),
]


def icon(name: str, size: float = 14) -> str:
    """An inline SVG icon. Unknown names draw nothing rather than a tofu box."""
    path = PATHS.get(name)
    if not path:
        return ""
    return (
        f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 16 16" '
        f'fill="none" stroke="currentColor" stroke-width="1.4" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{path}</svg>"
    )


# The two palettes, defined once and emitted three times below: for the
# default, for the OS preference, and for an explicit choice.
LIGHT = """
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
"""

DARK = """
  color-scheme:dark;
  --page:#0f1115; --card:#171a21; --raised:#1c2029;
  --line:#242936; --line-soft:#1e222c;
  --ink:#e9ecf2; --ink-2:#a2a9b8; --muted:#767d8d;
  --accent:#3987e5; --accent-soft:#17253b; --accent-ink:#8ab4ff;
  --review:#3987e5; --delete:#c98500; --ban:#d55181;
  --review-bg:#152435; --delete-bg:#2d2510; --ban-bg:#33202a;
  --good:#3fbe6b; --good-bg:#152a1c;
  --shadow:none; --shadow-lg:none;
"""

CSS = f"""
*,*::before,*::after{{box-sizing:border-box}}

/* Light is the default. The OS preference applies unless the reader has
   explicitly asked for light, and an explicit choice beats both — which is
   why the dark block appears twice rather than being written as one rule. */
:root{{{LIGHT}}}
@media (prefers-color-scheme:dark){{
  :root:not([data-theme="light"]){{{DARK}}}
}}
:root[data-theme="dark"]{{{DARK}}}
""" + """
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
nav a .ic{opacity:.75;flex:none}
.act .ic,.empty .ic{flex:none}
.bar-end{margin-left:auto;display:flex;align-items:center;gap:14px;flex:none}
.bar-end .who{font-size:12.5px;color:var(--muted);white-space:nowrap}
.theme{display:flex;gap:1px;padding:2px;border-radius:9px;background:var(--raised);
  border:1px solid var(--line);flex:none}
.theme .seg{display:flex;align-items:center;justify-content:center;
  width:27px;height:22px;border-radius:7px;color:var(--muted);line-height:0}
.theme .seg:hover{color:var(--ink);text-decoration:none}
/* The selected segment is tinted, not merely a different surface: against the
   dark track, --card is DARKER than --raised, so a surface swap read as an
   inset hole rather than a selection. */
.theme .seg.on,
.theme.auto .seg.light,
.theme.auto .seg.dark{background:var(--accent-soft);color:var(--accent-ink)}
/* Nothing chosen yet: the OS decides which one is actually showing, so let the
   same media query that picks the palette pick the highlight. */
.theme.auto .seg.dark{background:none;color:var(--muted)}
@media (prefers-color-scheme:dark){
  .theme.auto .seg.light{background:none;color:var(--muted)}
  .theme.auto .seg.dark{background:var(--accent-soft);color:var(--accent-ink)}
}
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
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;
  margin-bottom:20px}
/* period and group are different questions; without a divider the five
   chips read as one set and the current selection looks ambiguous. */
.fsep{width:1px;align-self:stretch;background:var(--line);margin:2px 7px}
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
/* the hero is full-bleed, so without something on the right it was a
   metre of empty card. The obvious next step lives there. */
.hero .go{margin-left:auto;font-size:13.5px;font-weight:600;
  padding:9px 15px;border-radius:9px;background:var(--raised);
  border:1px solid var(--line);color:var(--ink-2);white-space:nowrap}
.hero .go:hover{border-color:var(--accent);color:var(--accent-ink);
  text-decoration:none}

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
  overflow-wrap:anywhere;border-left:2px solid var(--line);max-width:78ch}
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
.empty .icon{color:var(--muted);opacity:.75;line-height:0}
.empty h3{font-size:16px;font-weight:620;margin:14px 0 6px}
.empty p{margin:0 auto;max-width:430px;color:var(--muted);font-size:13.5px;
  line-height:1.6}
.empty .hint{margin-top:18px;display:inline-block;text-align:left;
  background:var(--raised);border-radius:10px;padding:13px 17px;
  font-size:13px;color:var(--ink-2);line-height:1.8}

.note{background:var(--delete-bg);border-radius:11px;padding:13px 17px;
  font-size:13px;color:var(--ink-2);line-height:1.55;margin-top:14px}
details{margin-top:9px}
summary{display:inline-flex;align-items:center;gap:5px;
  padding:3px 9px;border-radius:7px;background:var(--raised)}
/* A glyph triangle renders as a smudge at this size and sits off the
   baseline; borders draw a crisp one that inherits the text colour. */
summary::before{content:"";width:0;height:0;border:4px solid transparent;
  border-left:5px solid currentColor;opacity:.75}
details[open] summary::before{border:4px solid transparent;
  border-top:5px solid currentColor;margin-top:4px}
summary{cursor:pointer;font-size:12.5px;color:var(--muted);list-style:none}
summary::-webkit-details-marker{display:none}
summary:hover{color:var(--ink-2)}

/* ---------- login ---------- */
.login{max-width:400px;margin:13vh auto;text-align:center;padding:0 20px}
.login .card{padding:32px 28px}
.login h1{font-size:21px;margin-bottom:6px}
.login p{color:var(--muted);font-size:13.5px;margin:0 0 20px}
.login .foot{margin:18px 0 0;font-size:12.5px;line-height:1.65}
.or{display:flex;align-items:center;gap:12px;margin:22px 0 18px}
.or::before,.or::after{content:"";flex:1;height:1px;background:var(--line)}
.or span{font-size:12px;color:var(--muted)}
.lbl{display:block;text-align:left;font-size:12.5px;color:var(--ink-2);
  margin-bottom:7px}
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


def topbar(active: str, dry_run: bool, user_label: str,
           theme: str = "", here: str = "/app") -> str:
    """Horizontal navigation.

    Five destinations do not justify a fixed column stealing a fifth of the
    width on every page — and the pages that matter most (Activity, Usage) are
    the widest, so they were the ones paying for it.
    """
    links = "".join(
        f'<a href="{href}" aria-current="{"page" if href == active else "false"}">'
        f"{icon(key)}<span>{name}</span></a>"
        for href, name, key in NAV
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
        f"{theme_switch(theme, here)}"
        f'<span class="who">{user_label}</span>'
        f'<a href="/logout">Sign out</a></div>'
        f"</div></header>"
    )


THEMES = [("light", "sun", "Light"), ("dark", "moon", "Dark")]


def theme_switch(current: str, here: str) -> str:
    """Light or dark.

    Until the reader picks one, the page still follows the operating system —
    and the server cannot read a media query, so it does not know which of the
    two is on screen. When nothing has been chosen the switch is marked `auto`
    and the CSS highlights whichever segment matches the OS, which keeps the
    control honest on a first visit without any script.
    """
    auto = "" if current else " auto"
    links = "".join(
        f'<a href="/theme?v={value}&amp;next={here}" '
        f'class="seg {value}{" on" if value == current else ""}" '
        f'title="{title}" aria-label="{title}" '
        f'aria-current="{"true" if value == current else "false"}">'
        f"{icon(key, 13)}</a>"
        for value, key, title in THEMES
    )
    return (
        f'<div class="theme{auto}" role="group" aria-label="Colour theme">'
        f"{links}</div>"
    )


def empty(glyph: str, title: str, body: str, hint: str = "") -> str:
    """An empty state should say what to DO, not just that there is nothing.

    With three events the old page looked broken rather than quiet, and gave a
    reader no way to tell "working, nothing to report" from "misconfigured".
    """
    hint_html = f'<div class="hint">{hint}</div>' if hint else ""
    return (
        f'<div class="card"><div class="empty">'
        f'<div class="icon">{icon(glyph, 30)}</div>'
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


def bar_chart(daily: list[dict], height: int = 232) -> str:
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

    # Drawn at close to its rendered width: an SVG stretched from a small
    # viewBox scales its TEXT and hairlines with it, so the axis labels came
    # out larger than the body copy and the gridlines looked like borders.
    pad_l, pad_r, pad_t, pad_b = 40, 8, 12, 28
    w = 1150
    plot_w, plot_h = w - pad_l - pad_r, height - pad_t - pad_b
    band = plot_w / n
    bar_w = min(band * 0.62, 44)

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
    bar_w = min(band * 0.62, 44)

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
