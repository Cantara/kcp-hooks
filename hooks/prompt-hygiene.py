#!/usr/bin/env python3
"""Prompt hygiene check — detects influence tactics in user prompts.

Runs as a UserPromptSubmit hook. Outputs a hygiene flag on suspicious prompts,
silent on clean ones. Zero API cost — pure regex.

Based on Module F heuristics from Lucid/synaptiai (MIT license):
https://github.com/synaptiai/lucid

Categories detected:
  - emotional-triggers     : "I really need you to", "I'm desperate"
  - urgent-action-demands  : "right now", "ASAP", "before it's too late"
  - emotional-repetition   : "!!!", "please please please"
  - false-dilemmas         : "either X or Y", "no other option"
  - authority-overload     : "experts say", "the science shows"

Note: framing-techniques excluded (too noisy in technical prompts).

Usage (in ~/.claude/settings.json):
  {
    "hooks": {
      "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": "python3 ~/.kcp/hooks/prompt-hygiene.py"}]}
      ]
    }
  }
"""
from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping

_PATTERNS: Mapping[str, tuple] = {
    "emotional-triggers": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\bi\s*(really\s+)?need\s+you\s+to\b",
            r"\bi\s*(really\s+)?want\s+you\s+to\b",
            r"\b(please|plz)\s+(please|plz)\b",
            r"\bi\s*('m|\s+am)\s+(desperate|begging|pleading)\b",
            r"\bso\s+(important|critical)\s+(that|to)\b",
            r"\bi\s*('ll|\s+will)\s+(lose|die|fail|suffer)\b",
            r"\bi\s+feel\s+(so|really)\s+(hopeless|scared|lost|trapped)\b",
        )
    ),
    "urgent-action-demands": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\bright\s+now\b",
            r"\bimmediately\b",
            r"\bASAP\b",
            r"\bthere('s|\s+is)\s+no\s+time\b",
            r"\bwe\s+(must|have\s+to)\s+act\b",
            r"\bdeadline\s+(is|in)\s+(hours|today|tomorrow)\b",
            r"\bbefore\s+it('s|\s+is)\s+too\s+late\b",
            r"\burgent(ly)?\b",
        )
    ),
    "emotional-repetition": tuple(
        re.compile(p)
        for p in (
            r"!{3,}",
            r"\?{3,}",
            r"[A-Z]{6,}\s+[A-Z]{3,}",
            r"(please)\s+\1\s+\1",
            r"(never|always)\s+\1",
        )
    ),
    "false-dilemmas": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\beither\s+[\w\s']+\s+or\s+[\w\s']+(\.|$)",
            r"\bonly\s+two\s+(options|choices|ways)\b",
            r"\bno\s+other\s+(way|option|choice)\b",
            r"\byou\s+(either|must)\s+\w+\s+or\b",
            r"\bit('s|\s+is)\s+(this|that)\s+or\s+\w+\b",
        )
    ),
    "authority-overload": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(experts|scientists|doctors|researchers|everyone)\s+(say|agree|know)\b",
            r"\baccording\s+to\s+(a\s+)?(professor|doctor|expert|authority)\b",
            r"\bper\s+(the|a)\s+(study|paper|research|expert)\b",
            r"\bthe\s+(data|science|research)\s+(shows|proves|confirms)\b",
            r"\bwe\s+(all|already)\s+know\b",
        )
    ),
}


def check(prompt: str) -> list[str]:
    matched = []
    for category, patterns in _PATTERNS.items():
        for pat in patterns:
            if pat.search(prompt):
                matched.append(category)
                break
    return matched


def main() -> None:
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt", "")
    except (json.JSONDecodeError, KeyError, ValueError):
        sys.exit(0)

    tactics = check(prompt)
    if tactics:
        # Output a warning — Claude Code will show this to the user
        print(f"[hygiene] Influence tactics detected: {', '.join(tactics)}", flush=True)
    # Silent if clean


if __name__ == "__main__":
    main()
