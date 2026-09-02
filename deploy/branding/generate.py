"""Regenerate the Telegram bot profile images.

    pip install playwright && playwright install chromium
    python deploy/branding/generate.py

Drawn from `web.render.SHIELD` rather than from a copy of the path data, so
the bot's avatar, the favicon and the site header can never drift into three
slightly different shields. Playwright is NOT a project dependency -- this is
run by hand when the mark or the wording changes, not on every build, so it
does not belong in requirements-dev.txt.

Telegram crops the avatar to a CIRCLE. That is why it is a separate square
image with the mark well inside the safe area, instead of the 640x360 one
scaled down: the wide image centre-crops to a slice of the wordmark.
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from playwright.sync_api import sync_playwright  # noqa: E402

from web import render  # noqa: E402

OUT = pathlib.Path(__file__).parent

# Literal colours, not theme tokens: a bot profile never sees the stylesheet.
INK, DIM, GROUND, BLUE = "#e9ecf2", "#a2a9b8", "#0f1115", "#3987e5"

TAGLINES = {
    "uz": "Guruhingizni firibgarlik va spamdan himoya qiladi",
    "en": "Anti-scam moderation for Telegram communities",
}


def _start_page(tagline: str) -> str:
    """640x360 — the image above the Start button, with the wordmark."""
    shield = render.SHIELD.format(knockout=GROUND)
    return f"""<style>
*{{margin:0;box-sizing:border-box}}
body{{width:640px;height:360px;display:flex;flex-direction:column;
 align-items:center;justify-content:center;gap:22px;
 background:radial-gradient(520px 300px at 50% -18%,#1c3a63,transparent 70%),
 {GROUND};
 font:400 15px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:{INK}}}
svg{{width:74px;height:auto;color:{BLUE}}}
h1{{font-size:44px;font-weight:730;letter-spacing:-.035em;line-height:1}}
p{{font-size:16.5px;color:{DIM};line-height:1.5;text-align:center;max-width:34ch}}
.rule{{width:52px;height:2px;border-radius:2px;background:{BLUE};opacity:.85}}
</style>
<svg viewBox="0 0 20 22" fill="none">{shield}</svg>
<h1>Qalqon</h1><div class="rule"></div><p>{tagline}</p>"""


def _avatar() -> str:
    """512x512 — cropped to a circle by Telegram, so no text and wide margins."""
    shield = (render.SHIELD.format(knockout="#ffffff")
              .replace('fill="currentColor"', 'fill="#ffffff"')
              .replace('stroke="#ffffff"', 'stroke="#2a6ec2"'))
    return f"""<style>
*{{margin:0;box-sizing:border-box}}
body{{width:512px;height:512px;display:flex;align-items:center;
 justify-content:center;
 background:radial-gradient(420px 420px at 50% 22%,#4b95ee,#2a6ec2 62%,#1d5299)}}
svg{{width:268px;height:auto}}
</style>
<svg viewBox="0 0 20 22" fill="none">{shield}</svg>"""


def main() -> None:
    pages = [("botpic-avatar.png", _avatar(), 512, 512)]
    pages += [(f"botpic-{lang}.png", _start_page(t), 640, 360)
              for lang, t in TAGLINES.items()]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, html, w, h in pages:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.set_content(html, wait_until="load")
            page.screenshot(path=OUT / name)
            page.close()
            print(f"{name}  {w}x{h}")
        browser.close()


if __name__ == "__main__":
    main()
