#!/usr/bin/env python3
"""Prompt Recall — surfaces relevant episodic memory from past sessions.

UserPromptSubmit hook that detects temporal/recall signals in the prompt,
queries kcp-memory (http://localhost:7735) for relevant past sessions,
and injects a concise summary as context.

Requires: kcp-memory running as HTTP daemon (port 7735)
  https://github.com/Cantara/kcp-memory

Design: pure Python stdlib, no API calls, <200ms target. Silent fail on errors.

Usage (in ~/.claude/settings.json):
  {
    "hooks": {
      "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": "python3 ~/.kcp/hooks/prompt-recall.py"}]}
      ]
    }
  }
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

KCP_MEMORY_URL = "http://localhost:7735"
MAX_RESULTS = 3
MAX_SNIPPET_LEN = 200

# Temporal/recall signal patterns — trigger episodic memory lookup.
# A prompt matching ANY of these gets a memory query.
RECALL_PATTERNS = [
    # Explicit temporal references
    re.compile(r"\b(yesterday|last\s+week|last\s+time|previously|before|earlier|recently)\b", re.IGNORECASE),
    # "What did I / we / you do/say/decide..."
    re.compile(r"\bwhat\s+(did\s+)?(i|we|you)\s+(do|say|decide|build|write|fix|change|work)", re.IGNORECASE),
    # "When did I / we..."
    re.compile(r"\bwhen\s+did\s+(i|we)\b", re.IGNORECASE),
    # "How did I / we..."
    re.compile(r"\bhow\s+did\s+(i|we)\b", re.IGNORECASE),
    # "Do you remember..."
    re.compile(r"\bdo\s+you\s+remember\b", re.IGNORECASE),
    # "Same as before / last session"
    re.compile(r"\b(same\s+as\s+before|last\s+session|from\s+before|from\s+last)\b", re.IGNORECASE),
    # "Continue from where..."
    re.compile(r"\b(continue|pick\s+up)\s+(from|where)\b", re.IGNORECASE),
    # Ago references
    re.compile(r"\b\d+\s+(days?|weeks?|hours?)\s+ago\b", re.IGNORECASE),
]


def should_recall(prompt: str) -> bool:
    """Return True if the prompt contains temporal/recall signals."""
    for pattern in RECALL_PATTERNS:
        if pattern.search(prompt):
            return True
    return False


def extract_search_query(prompt: str) -> str:
    """Build a search query from the prompt — strip signal words, keep content words."""
    # Remove the trigger phrases to get the semantic core
    cleaned = prompt
    for pattern in RECALL_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    # Collapse whitespace, take first 120 chars as query
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:120] if cleaned else prompt[:120]


def query_kcp_memory(query: str) -> list[dict]:
    """Query kcp-memory /search endpoint. Returns list of hit dicts."""
    encoded = urllib.request.quote(query, safe="")
    url = f"{KCP_MEMORY_URL}/search?q={encoded}&limit={MAX_RESULTS}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
            # kcp-memory returns {"results": [...]} or a list directly
            if isinstance(data, list):
                return data
            return data.get("results", [])
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []


def format_hit(hit: dict) -> str:
    """Format a single search hit as a concise line."""
    # kcp-memory hit fields: first_message, project_dir, started_at, snippet
    project = Path(hit.get("project_dir", "")).name or "unknown"
    date = hit.get("started_at", "")[:10] if hit.get("started_at") else ""
    snippet = hit.get("first_message") or hit.get("snippet") or ""
    snippet = snippet[:MAX_SNIPPET_LEN].replace("\n", " ").strip()
    if len(snippet) == MAX_SNIPPET_LEN:
        snippet += "..."

    parts = []
    if date:
        parts.append(date)
    if project:
        parts.append(f"[{project}]")
    if snippet:
        parts.append(snippet)

    return "- " + " ".join(parts) if parts else ""


def main() -> None:
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt", "")
    except (json.JSONDecodeError, KeyError, ValueError):
        sys.exit(0)

    if not prompt or len(prompt) < 8:
        sys.exit(0)

    if not should_recall(prompt):
        sys.exit(0)

    query = extract_search_query(prompt)
    if not query.strip():
        sys.exit(0)

    hits = query_kcp_memory(query)
    hits = [h for h in hits if h]

    if not hits:
        sys.exit(0)

    lines = [f"## Episodic Memory — relevant past sessions (query: \"{query[:60]}\")"]
    for hit in hits[:MAX_RESULTS]:
        line = format_hit(hit)
        if line:
            lines.append(line)

    if len(lines) == 1:
        sys.exit(0)

    lines.append("")
    lines.append("_From kcp-memory. Run `kcp-memory search \"<query>\"` for more._")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
