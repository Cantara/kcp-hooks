#!/usr/bin/env python3
"""Prompt Router — auto-decorates prompts with relevant skill/context preambles.

UserPromptSubmit hook that reads the incoming prompt, extracts keywords,
scores them against your skill library, and outputs concise context preambles
for the top 2-3 matches.

Design: pure Python stdlib, no API calls, <100ms target. Silent fail on errors.

Usage (in ~/.claude/settings.json):
  {
    "hooks": {
      "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": "python3 ~/.kcp/hooks/prompt-router.py"}]}
      ]
    }
  }

Skills live in ~/.claude/skills/<name>.yaml — see ../skills/_format.yaml for spec.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# --- Configuration ---
SKILLS_DIR = Path.home() / ".claude" / "skills"
SESSION_FILE = Path("/tmp/prompt-router-session.json")
SESSION_MAX_AGE_HOURS = 4   # Session resets after 4 hours of inactivity
SESSION_DECAY = 0.72        # Score multiplier per prior showing this session
MAX_RESULTS = 3
MIN_SCORE = 4               # Minimum match score to surface a skill

# Generic tokens that appear in many skills — downweight to avoid false positives.
GENERIC_TOKENS = {
    "fix", "display", "progress", "create", "update", "add", "remove",
    "delete", "change", "move", "set", "run", "build", "test", "check",
    "show", "list", "view", "page", "component", "module", "service",
    "file", "data", "type", "model", "system", "status", "index",
    "code", "app", "api", "config", "error", "log", "report",
    "write", "read", "use", "start", "stop", "work", "help",
    "card", "table", "form", "button", "link", "text", "name",
    "score", "scoring", "changes", "commit", "template", "tool",
}

# Domain signal tokens — map domain names to their distinctive vocabulary.
# Edit this to match your projects. Prompts containing these tokens boost
# skills from the corresponding domain.
# Example:
#   "myproject": ["myproject", "widget", "sprocket", "api-key"],
DOMAIN_SIGNALS: dict[str, list[str]] = {
    "kcp": ["kcp", "kcp-commands", "kcp-memory", "kcp-hooks", "manifest"],
    # Add your own domains here:
    # "myproject": ["myproject", "specific-term", ...],
}


def split_camel_case(word: str) -> list[str]:
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", word)
    parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", parts)
    return [p.lower() for p in parts.split() if len(p) >= 2]


def tokenize(text: str) -> set[str]:
    """Extract lowercase tokens, handling camelCase, hyphenated, and underscored words."""
    stops = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "to", "of", "in",
        "for", "on", "with", "at", "by", "from", "as", "into", "through",
        "during", "before", "after", "above", "below", "between", "out",
        "off", "over", "under", "again", "further", "then", "once", "here",
        "there", "when", "where", "why", "how", "all", "each", "every",
        "both", "few", "more", "most", "other", "some", "such", "no", "nor",
        "not", "only", "own", "same", "so", "than", "too", "very", "just",
        "don", "now", "and", "but", "or", "if", "while", "that", "this",
        "these", "those", "it", "its", "i", "me", "my", "we", "our", "you",
        "your", "he", "she", "they", "them", "what", "which", "who", "whom",
        "up", "about", "get", "make", "like", "new", "also", "us", "let",
    }
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*[a-zA-Z0-9]|[a-zA-Z]", text)
    tokens: set[str] = set()
    for w in raw:
        low = w.lower()
        if low not in stops and len(low) >= 2:
            tokens.add(low)
        for part in split_camel_case(w):
            if part not in stops and len(part) >= 2:
                tokens.add(part)
        if "-" in low:
            for part in low.split("-"):
                if part not in stops and len(part) >= 2:
                    tokens.add(part)
        if "_" in low:
            for part in low.split("_"):
                if part not in stops and len(part) >= 2:
                    tokens.add(part)
    return tokens


def detect_domains(prompt_tokens: set[str]) -> set[str]:
    detected: set[str] = set()
    for domain, signals in DOMAIN_SIGNALS.items():
        if prompt_tokens & set(signals):
            detected.add(domain)
    return detected


def load_skills() -> list[dict]:
    """Auto-discover skills by globbing SKILLS_DIR for *.yaml files.

    Parses: name, description, domain, tags, trigger_phrases from YAML frontmatter.
    Uses simple line-by-line parsing — no yaml library required.
    """
    skills = []
    if not SKILLS_DIR.exists():
        return skills

    for path in sorted(SKILLS_DIR.glob("*.yaml")):
        skill = _parse_skill_file(path)
        if skill:
            skills.append(skill)
    return skills


def _parse_skill_file(path: Path) -> dict | None:
    """Parse a single skill YAML file. Returns None if unparseable."""
    skill: dict = {
        "name": path.stem,
        "description": "",
        "domain": "general",
        "tags": [],
        "trigger_phrases": [],
        "see_also": [],
    }
    try:
        in_tags = False
        in_triggers = False
        in_see_also = False
        with open(path, "r", errors="ignore") as f:
            for line in f:
                line_stripped = line.rstrip()

                # name:
                m = re.match(r"^name:\s*(.+)", line_stripped)
                if m:
                    skill["name"] = m.group(1).strip().strip("\"'")
                    in_tags = in_triggers = in_see_also = False
                    continue

                # description: single-line or block scalar start
                m = re.match(r'^description:\s*"(.+)"', line_stripped)
                if m:
                    skill["description"] = m.group(1)
                    in_tags = in_triggers = in_see_also = False
                    continue
                m = re.match(r"^description:\s*\|", line_stripped)
                if m:
                    in_tags = in_triggers = in_see_also = False
                    continue
                # First non-empty line of a block scalar description
                if (not in_tags and not in_triggers and not in_see_also
                        and not skill["description"]
                        and line_stripped.startswith("  ")):
                    candidate = line_stripped.strip()
                    if candidate and not candidate.startswith("-"):
                        skill["description"] = candidate

                # domain:
                m = re.match(r"^domain:\s*(.+)", line_stripped)
                if m:
                    skill["domain"] = m.group(1).strip().strip("\"'")
                    in_tags = in_triggers = in_see_also = False
                    continue

                # tags: [list] or block
                m = re.match(r"^tags:\s*\[(.+)\]", line_stripped)
                if m:
                    skill["tags"] = [t.strip().strip("\"'") for t in m.group(1).split(",")]
                    in_tags = False
                    continue
                if re.match(r"^tags:\s*$", line_stripped):
                    in_tags = True
                    in_triggers = in_see_also = False
                    continue
                if in_tags and re.match(r"^\s+-\s+(.+)", line_stripped):
                    tm = re.match(r"^\s+-\s+(.+)", line_stripped)
                    if tm:
                        skill["tags"].append(tm.group(1).strip().strip("\"'"))
                    continue
                if in_tags and not line_stripped.startswith(" "):
                    in_tags = False

                # trigger_phrases:
                if re.match(r"^trigger_phrases:\s*$", line_stripped):
                    in_triggers = True
                    in_tags = in_see_also = False
                    continue
                if in_triggers and re.match(r"^\s+-\s+(.+)", line_stripped):
                    tm = re.match(r'^\s+-\s+"?(.+?)"?\s*$', line_stripped)
                    if tm:
                        skill["trigger_phrases"].append(tm.group(1).strip())
                    continue
                if in_triggers and not line_stripped.startswith(" "):
                    in_triggers = False

                # see_also:
                m = re.match(r"^see_also:\s*\[(.+)\]", line_stripped)
                if m:
                    skill["see_also"] = [t.strip().strip("\"'") for t in m.group(1).split(",")]
                    continue

    except OSError:
        return None

    # Require at least a description to be useful
    if not skill["description"]:
        return None
    return skill


def load_session() -> dict:
    import time
    try:
        if not SESSION_FILE.exists():
            return {}
        data = json.loads(SESSION_FILE.read_text())
        last = data.get("_t", 0)
        if time.time() - last > SESSION_MAX_AGE_HOURS * 3600:
            return {}
        return {k: v for k, v in data.items() if k != "_t"}
    except (OSError, json.JSONDecodeError, KeyError):
        return {}


def save_session(shown_names: list[str], existing: dict) -> None:
    import time
    updated = dict(existing)
    for name in shown_names:
        updated[name] = updated.get(name, 0) + 1
    updated["_t"] = time.time()
    try:
        SESSION_FILE.write_text(json.dumps(updated))
    except OSError:
        pass


def apply_session_decay(score: float, skill_name: str, session: dict) -> float:
    count = session.get(skill_name, 0)
    if count == 0:
        return score
    return score * (SESSION_DECAY ** count)


def token_weight(token: str) -> float:
    return 0.5 if token in GENERIC_TOKENS else 1.0


def score_skill(skill: dict, prompt_tokens: set[str], detected_domains: set[str]) -> float:
    """Score a skill by weighted keyword matches across name, description, domain, tags."""
    score = 0.0

    name_tokens = tokenize(skill["name"])
    desc_tokens = tokenize(skill["description"])
    domain_tokens = tokenize(skill["domain"])
    tag_tokens: set[str] = set()
    for tag in skill["tags"]:
        tag_tokens |= tokenize(tag)
    trigger_tokens: set[str] = set()
    for phrase in skill.get("trigger_phrases", []):
        trigger_tokens |= tokenize(phrase)

    # Name: x3
    for t in prompt_tokens & name_tokens:
        score += 3.0 * token_weight(t)
    # Tags: x2
    for t in prompt_tokens & tag_tokens:
        score += 2.0 * token_weight(t)
    # Trigger phrases: x2
    for t in prompt_tokens & trigger_tokens:
        score += 2.0 * token_weight(t)
    # Domain: x2
    for t in prompt_tokens & domain_tokens:
        score += 2.0 * token_weight(t)
    # Description: x1
    for t in prompt_tokens & desc_tokens:
        score += 1.0 * token_weight(t)

    # Domain affinity boost/penalty
    if detected_domains and score > 0:
        skill_domain_root = skill["domain"].split("/")[0]
        in_detected = any(skill["domain"].startswith(d) for d in detected_domains)
        if in_detected:
            score *= 1.2
        elif skill_domain_root in detected_domains:
            pass  # neutral
        # No cross-domain penalty by default — add your own logic here if needed

    return score


def deduplicate(results: list[tuple]) -> list[tuple]:
    """Limit to 2 per domain for variety."""
    seen_domains: dict[str, int] = {}
    out = []
    for score, skill in results:
        d = skill["domain"]
        if seen_domains.get(d, 0) >= 2:
            continue
        seen_domains[d] = seen_domains.get(d, 0) + 1
        out.append((score, skill))
    return out


def main() -> None:
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt", "")
    except (json.JSONDecodeError, KeyError, ValueError):
        sys.exit(0)

    if not prompt or len(prompt) < 5:
        sys.exit(0)

    prompt_tokens = tokenize(prompt)
    if not prompt_tokens:
        sys.exit(0)

    detected_domains = detect_domains(prompt_tokens)
    session = load_session()
    skills = load_skills()

    scored = []
    for skill in skills:
        score = score_skill(skill, prompt_tokens, detected_domains)
        score = apply_session_decay(score, skill["name"], session)
        if score >= MIN_SCORE:
            scored.append((score, skill))

    scored.sort(key=lambda x: x[0], reverse=True)
    scored = deduplicate(scored)
    top = scored[:MAX_RESULTS]

    if not top:
        sys.exit(0)

    shown = [s["name"] for _, s in top]
    save_session(shown, session)

    lines = ["## Prompt Router -- Relevant Context"]
    for score, skill in top:
        desc = skill["description"]
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(f"- **`{skill['name']}`** ({skill['domain']}) -- {desc}")
    lines.append("")
    lines.append("_Read skill file: `cat ~/.claude/skills/<name>.yaml` — these are NOT Skill-tool invocable._")

    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
