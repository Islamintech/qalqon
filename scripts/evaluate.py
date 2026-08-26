"""Measure the moderation pipeline against the real-community corpus.

    python scripts/evaluate.py

Runs the ACTUAL detectors (keyword + link + the LIVE Groq model) and the ACTUAL
policy, so the number at the end is what the group would experience — not what
the prompt looks like it should do.

A script rather than a unit test on purpose: it costs API calls and the model
is not perfectly deterministic, so it does not belong in a suite that runs on
every change. The deterministic half — that no legitimate message trips a
keyword — IS a test, in tests/test_corpus.py.

Run it after any change to SYSTEM_PROMPT or SCAM_PATTERNS, and whenever real
messages are added to tests/corpus.py. A prompt edit that reads like an
improvement can easily cost three false positives.
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"), override=True)

from corpus import LEGITIMATE, SCAMS  # noqa: E402
from models import (  # noqa: E402
    Action, KeywordFilter, LinkAnalyzer, LLMClient, Policy, Risk, Verdict,
)

PROFILE_NEWCOMER = Verdict(Risk.FIFTY_FIFTY, "no profile photo", "photo")
PROFILE_REGULAR = Verdict(Risk.CLEAN, "profile looks normal", "profile")


async def judge(llm, keywords, links, text, profile):
    kw = keywords.check(text) or Verdict(Risk.CLEAN, "no pattern matched", "keyword")
    link = links.analyze(text)
    verdict = await llm.analyze(text)
    content = Verdict.worst(verdict, kw, link)
    decision = Policy().decide(content, profile, strikes=0, trusted=False)
    return content, decision, kw, link, verdict


async def main():
    llm = LLMClient(os.getenv("GROQ_API_KEY"), os.getenv("GROQ_MODEL"), cache_ttl=0)
    keywords, links = KeywordFilter(), LinkAnalyzer()

    print("=" * 78)
    print("LEGITIMATE MESSAGES  (a newcomer posting — the harshest case)")
    print("=" * 78)
    false_positives = 0
    for text in LEGITIMATE:
        content, decision, kw, link, verdict = await judge(
            llm, keywords, links, text, PROFILE_NEWCOMER
        )
        bad = decision.action is not Action.NONE
        false_positives += bad
        mark = "FLAGGED" if bad else "  ok   "
        print(f"{mark} {decision.action.value:7} | {text[:62]}")
        if bad:
            print(f"          llm={verdict.risk.value}({verdict.reason[:46]})")
            if not kw.clean:
                print(f"          keyword={kw.reason[:60]}")
            if not link.clean:
                print(f"          link={link.reason[:60]}")

    print()
    print("=" * 78)
    print("SCAMS  (same newcomer profile)")
    print("=" * 78)
    misses = 0
    for text in SCAMS:
        content, decision, kw, link, verdict = await judge(
            llm, keywords, links, text, PROFILE_NEWCOMER
        )
        caught = decision.action is not Action.NONE
        misses += not caught
        mark = "  ok   " if caught else " MISSED"
        print(f"{mark} {decision.action.value:7} | {text[:62]}")
        if not caught:
            print(f"          llm={verdict.risk.value}({verdict.reason[:46]})")

    print()
    print("=" * 78)
    print(f"  false positives : {false_positives}/{len(LEGITIMATE)}"
          "   <- every one is an innocent member flagged")
    print(f"  missed scams    : {misses}/{len(SCAMS)}")
    print("=" * 78)


asyncio.run(main())
