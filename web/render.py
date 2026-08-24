"""Presentation layer for the dashboard: styles, chart, and page chrome.

Kept apart from app.py so routing and authentication stay readable next to
each other, and so the visual language lives in one file.

COLOR
The three action series are a validated categorical palette, not a taste
decision — checked with the data-viz validator against this dashboard's own
dark surface (#171a21), all pairs:

    review  #3987e5  blue
    delete  #c98500  amber
    ban     #d55181  crimson

    lightness band PASS · chroma floor PASS · CVD separation PASS
    (deutan ΔE 13.2, tritan 8.7) · normal-vision ΔE 19.3 · contrast PASS

Two semantically tidier options were rejected because they failed: the
status trio (warning/serious/critical) puts amber beside orange at ΔE 13.6,
below the 15 normal-vision floor; blue/amber/red fails the same pair at 13.0.
Red and yellow cannot both appear in a three-series set at this size.

Colour carries identity only. Severity is carried by the legend order, the
labels and the stack order — never by hue alone.

DARK ONLY, deliberately. The product's surfaces are its identity and every
value here was validated against them; a light mode would need its own
validated steps rather than an inverted flip, and there is no use case for it
(this is an operations console, read at night as often as not).
"""

# --- palette ---------------------------------------------------------------
SURFACE = "#171a21"      # chart surface
PLANE = "#0f1115"        # page plane
RAISED = "#1c2029"
INK = "#e9ecf2"          # primary
INK_2 = "#a2a9b8"        # secondary
INK_MUTED = "#6f7688"    # axis / labels
HAIRLINE = "#242936"
GRID = "#20242f"

SERIES = {
    "REVIEW": "#3987e5",
    "DELETE": "#c98500",
    "BAN": "#d55181",
}
SERIES_ORDER = ["BAN", "DELETE", "REVIEW"]  # most severe first, in legend
ADMIN_TINT = "#9085e9"
GOOD = "#0ca30c"

CSS = f"""
*,*::before,*::after{{box-sizing:border-box}}
:root{{color-scheme:dark}}
body{{
  margin:0;background:{PLANE};color:{INK};
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}}
a{{color:#8ab4ff;text-decoration:none}}
a:hover{{text-decoration:underline}}

/* ---------- chrome ---------- */
header{{
  position:sticky;top:0;z-index:5;background:rgba(15,17,21,.88);
  backdrop-filter:blur(10px);border-bottom:1px solid {HAIRLINE};
  padding:14px 22px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;
}}
.brand{{display:flex;align-items:center;gap:9px;font-weight:640;font-size:15px;
  letter-spacing:-.01em}}
.brand svg{{display:block}}
.badge{{padding:3px 9px;border-radius:6px;font-size:11px;font-weight:650;
  letter-spacing:.03em;text-transform:uppercase}}
.badge.live{{background:#3a1c22;color:#f2a0ad;box-shadow:inset 0 0 0 1px #5b2a33}}
.badge.dry{{background:#16281d;color:#84d9a4;box-shadow:inset 0 0 0 1px #23412f}}
.spacer{{flex:1}}
.who{{font-size:13px;color:{INK_2}}}

main{{padding:26px 22px 60px;max-width:1180px;margin:0 auto}}
section{{margin-bottom:38px}}
.head{{display:flex;align-items:baseline;gap:12px;margin:0 0 14px;flex-wrap:wrap}}
h2{{font-size:12px;text-transform:uppercase;letter-spacing:.09em;
  color:{INK_MUTED};margin:0;font-weight:660}}
.sub{{font-size:12.5px;color:{INK_MUTED}}}

/* ---------- filters ---------- */
.filters{{display:flex;gap:18px;flex-wrap:wrap;align-items:center;
  padding-bottom:20px;margin-bottom:24px;border-bottom:1px solid {HAIRLINE}}}
.fgroup{{display:flex;align-items:center;gap:7px;flex-wrap:wrap}}
.flabel{{font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:{INK_MUTED};font-weight:640}}
.chip{{padding:5px 11px;border-radius:7px;font-size:12.5px;color:{INK_2};
  background:{RAISED};box-shadow:inset 0 0 0 1px {HAIRLINE};white-space:nowrap}}
.chip:hover{{color:{INK};text-decoration:none;background:#222736}}
.chip[aria-current="true"]{{background:#25406e;color:#dce8ff;
  box-shadow:inset 0 0 0 1px #35538a;font-weight:620}}

/* ---------- tiles ---------- */
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));
  gap:12px}}
.tile{{background:{SURFACE};border:1px solid {HAIRLINE};border-radius:12px;
  padding:15px 17px}}
.tile .v{{font-size:27px;font-weight:660;letter-spacing:-.025em;line-height:1.1}}
.tile .k{{font-size:12px;color:{INK_MUTED};margin-top:3px}}
.hero{{background:{SURFACE};border:1px solid {HAIRLINE};border-radius:14px;
  padding:22px 24px;display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}}
.hero .v{{font-size:52px;font-weight:680;letter-spacing:-.04em;line-height:1}}
.hero .k{{font-size:13.5px;color:{INK_2}}}

/* ---------- chart ---------- */
.card{{background:{SURFACE};border:1px solid {HAIRLINE};border-radius:14px;
  padding:18px 20px 14px}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px}}
.lg{{display:flex;align-items:center;gap:7px;font-size:12.5px;color:{INK_2}}}
.sw{{width:10px;height:10px;border-radius:3px;flex:none}}
.chart{{width:100%;height:auto;display:block;overflow:visible}}
.chart text{{font:11px system-ui,-apple-system,"Segoe UI",sans-serif;
  fill:{INK_MUTED};font-variant-numeric:tabular-nums}}
.chart .seg:hover{{opacity:.82}}

/* ---------- tables ---------- */
.wrap{{overflow-x:auto;border:1px solid {HAIRLINE};border-radius:12px;
  background:{SURFACE}}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:{INK_MUTED};font-weight:640;padding:11px 14px;
  border-bottom:1px solid {HAIRLINE};font-size:11px;text-transform:uppercase;
  letter-spacing:.06em;white-space:nowrap}}
td{{padding:10px 14px;border-bottom:1px solid {GRID};vertical-align:top}}
tr:last-child td{{border-bottom:0}}
tbody tr:hover td{{background:#1b1f29}}
.num{{font-variant-numeric:tabular-nums}}
.tag{{padding:2px 8px;border-radius:5px;font-size:11px;font-weight:650;
  white-space:nowrap;display:inline-block;letter-spacing:.02em}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
  color:{INK_MUTED}}}
.msg{{color:{INK_2};font-size:12.5px;max-width:400px;overflow-wrap:anywhere}}
.dim{{color:{INK_MUTED}}}

/* ---------- notes & empties ---------- */
.note{{background:#1b1a16;border-left:3px solid #8a6a1e;padding:11px 15px;
  border-radius:0 9px 9px 0;font-size:12.5px;color:#cfc6ae;margin-top:12px}}
.empty{{padding:36px 20px;text-align:center;color:{INK_MUTED};font-size:13.5px}}
details{{margin-top:12px}}
summary{{cursor:pointer;font-size:12px;color:{INK_MUTED};
  list-style:none;display:inline-flex;align-items:center;gap:6px}}
summary::-webkit-details-marker{{display:none}}
summary:hover{{color:{INK_2}}}

/* ---------- login ---------- */
.login{{max-width:390px;margin:12vh auto;text-align:center;padding:0 20px}}
.login h2{{font-size:19px;text-transform:none;letter-spacing:-.01em;
  color:{INK};margin-bottom:8px}}
.login p{{color:{INK_MUTED};font-size:13.5px;margin-top:0}}
.field{{width:100%;padding:11px 13px;border-radius:9px;
  border:1px solid {HAIRLINE};background:{SURFACE};color:{INK};font-size:14px}}
.field:focus{{outline:2px solid #35538a;outline-offset:1px}}
.btn{{margin-top:10px;width:100%;padding:11px;border-radius:9px;border:0;
  background:#2f5399;color:#fff;font-size:14px;font-weight:640;cursor:pointer}}
.btn:hover{{background:#37609f}}
code{{background:{RAISED};padding:2px 6px;border-radius:5px;font-size:12px}}

@media (max-width:640px){{
  main{{padding:20px 14px 48px}}
  header{{padding:12px 14px;gap:10px}}
  .hero .v{{font-size:40px}}
  .tile .v{{font-size:23px}}
  .msg{{max-width:200px}}
}}
"""

LOGO = (
    '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" '
    'aria-hidden="true"><path d="M10 1 18.2 4v7.1c0 4.6-3.3 8.2-8.2 9.9'
    '-4.9-1.7-8.2-5.3-8.2-9.9V4L10 1Z" fill="#3987e5"/>'
    '<path d="m6.4 10.9 2.5 2.5 4.9-4.9" stroke="#0f1115" stroke-width="2.1" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def bar_chart(daily: list[dict], height: int = 190) -> str:
    """Stacked daily activity.

    Mark specs from the data-viz method: 2px surface gap between stacked
    segments (never a border around marks), 4px rounded data-end on the top
    segment only, hairline recessive grid, no value printed on every bar.
    Each segment carries a <title> so the exact number is reachable on hover
    without JavaScript, and a table view sits below for the WCAG-clean path.
    """
    n = len(daily)
    if not n:
        return '<div class="empty">No activity recorded yet.</div>'

    totals = [d["REVIEW"] + d["DELETE"] + d["BAN"] for d in daily]
    peak = max(totals) or 1
    # Round the axis up to something readable rather than to the raw peak.
    step = 1 if peak <= 4 else (2 if peak <= 10 else 5 if peak <= 25 else 10)
    top = ((peak + step - 1) // step) * step

    pad_l, pad_r, pad_t, pad_b = 30, 4, 8, 22
    w = 720
    plot_w = w - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    band = plot_w / n
    bar_w = min(band * 0.62, 26)

    out = [
        f'<svg class="chart" viewBox="0 0 {w} {height}" '
        # Default (uniform) aspect ratio: preserveAspectRatio="none" would
        # stretch the axis text horizontally when the card is wide.
        f'role="img" '
        f'aria-label="Moderation actions per day">'
    ]

    # Recessive solid hairline grid — never dashed.
    ticks = [0, top // 2, top] if top >= 2 else [0, top]
    for t in sorted(set(ticks)):
        y = pad_t + plot_h - (t / top) * plot_h
        out.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{pad_l - 8}" y="{y + 3.5:.1f}" text-anchor="end">{t}</text>'
        )

    for i, d in enumerate(daily):
        x = pad_l + i * band + (band - bar_w) / 2
        y = pad_t + plot_h
        stack = [(k, d[k]) for k in ("REVIEW", "DELETE", "BAN") if d[k]]
        for j, (key, value) in enumerate(stack):
            h = (value / top) * plot_h
            # 2px surface gap between segments, not a stroke.
            gap = 2 if j < len(stack) - 1 else 0
            seg_h = max(h - gap, 1.5)
            y -= h
            topmost = j == len(stack) - 1
            radius = 'rx="3"' if topmost else ""
            out.append(
                f'<rect class="seg" x="{x:.1f}" y="{y + gap:.1f}" '
                f'width="{bar_w:.1f}" height="{seg_h:.1f}" {radius} '
                f'fill="{SERIES[key]}"><title>{d["day"]} — {value} '
                f'{key.lower()}</title></rect>'
            )
        if not stack:
            # A flat tick so an empty day reads as "zero", not "missing".
            out.append(
                f'<rect x="{x:.1f}" y="{pad_t + plot_h - 1.5:.1f}" '
                f'width="{bar_w:.1f}" height="1.5" fill="{HAIRLINE}"/>'
            )

    # Axis baseline, and labels only where they will not collide.
    out.append(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{w - pad_r}" '
        f'y2="{pad_t + plot_h}" stroke="{HAIRLINE}" stroke-width="1"/>'
    )
    every = 1 if n <= 8 else (2 if n <= 16 else 5)
    for i, d in enumerate(daily):
        if i % every and i != n - 1:
            continue
        cx = pad_l + i * band + band / 2
        out.append(
            f'<text x="{cx:.1f}" y="{height - 6}" text-anchor="middle">'
            f'{d["day"][5:]}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def legend(keys=None) -> str:
    keys = keys or SERIES_ORDER
    items = "".join(
        f'<span class="lg"><span class="sw" style="background:{SERIES[k]}">'
        f'</span>{k.title()}</span>'
        for k in keys
    )
    return f'<div class="legend">{items}</div>'
