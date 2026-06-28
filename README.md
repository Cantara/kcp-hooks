# kcp-hooks

<img src="https://totto.goatcounter.com/count?p=/kcp-hooks-readme" alt="" style="display:none">

**Three hooks that give Claude Code memory, routing, and hygiene — without changing how you work.**

Claude Code starts each session with an empty context window. You know your codebase, your conventions, your past decisions. Claude doesn't, until you explain them. Again. Every time.

kcp-hooks fixes three distinct parts of that problem:

| Hook | Fires when | What it does |
|------|-----------|-------------|
| `prompt-router.py` | Every prompt | Detects the topic and surfaces relevant skill files from `~/.claude/skills/` |
| `prompt-recall.py` | Temporal signals detected | Queries [kcp-memory](https://github.com/Cantara/kcp-memory) for relevant past sessions |
| `prompt-hygiene.py` | Every prompt | Detects influence tactics — emotional pressure, false urgency, authority overload |

All three are passive. You don't invoke them. They fire on every `UserPromptSubmit` event, complete in <200ms, and inject context before Claude sees your prompt.

Part of the [Knowledge Context Protocol](https://github.com/Cantara/knowledge-context-protocol) ecosystem.

---

## Why this works

### The session amnesia problem

Every Claude Code session starts from zero. You spend the first few prompts re-establishing context: *"this is a Node.js project, we use PostgreSQL, deployments go through GitHub Actions, don't touch the legacy auth module..."*

That's not a Claude problem — it's an architecture problem. The context window is the right unit of work, but it has no built-in way to accumulate knowledge across sessions.

kcp-hooks fills that gap at the prompt boundary, not by changing the model but by giving it better inputs.

### Why hooks, not CLAUDE.md?

`CLAUDE.md` is a static file. It's good for stable, always-relevant context (company conventions, architecture decisions). It's bad for dynamic context — which runbook applies to *this* prompt? What did you actually do last Tuesday?

Hooks are dynamic. `prompt-router.py` routes the *current* prompt to the *relevant* skill file. `prompt-recall.py` only fires when the prompt contains a temporal signal. Nothing gets injected that isn't relevant right now.

### Why zero API calls?

All three hooks are pure regex + file I/O (plus one HTTP call to the local kcp-memory daemon for recall). No external API calls. No latency. No cost. No failure mode that blocks your prompt.

---

## Install

```bash
git clone https://github.com/Cantara/kcp-hooks
cd kcp-hooks
bash install.sh
```

Restart Claude Code. Done.

The installer copies hooks to `~/.kcp/hooks/` and merges the hook config into `~/.claude/settings.json`. Existing settings are preserved — it only adds, never overwrites.

### Prerequisites

- Python 3.8+
- Claude Code with hooks support
- (Optional) [kcp-memory](https://github.com/Cantara/kcp-memory) running on port 7735 for `prompt-recall.py`

---

## Hook 1 — Prompt Router

Surfaces relevant skill files from `~/.claude/skills/` before every prompt reaches Claude.

**How it scores skills:**

```
Name match    ×3   (most specific — if "postgres" is in the skill name)
Tag match     ×2   (topic keywords you defined)
Trigger match ×2   (phrases you said would reliably indicate this skill)
Domain match  ×2   (domain affinity)
Description   ×1   (fallback)
```

Generic tokens (`fix`, `build`, `test`) are downweighted to 0.5× to avoid false positives.

**Session decay:** Skills shown earlier in the same session are scored progressively lower (×0.72 per prior showing). This surfaces variety rather than hammering the same skill on every prompt.

**Output example:**

```
## Prompt Router -- Relevant Context
- `my-deployment-runbook` (devops) -- Step-by-step deploy checklist: staging gate, DB migration order, rollback procedure
- `postgres-schema` (backend) -- Current schema, migration conventions, index strategy for the user_events table

_Read skill file: `cat ~/.claude/skills/<name>.yaml` — these are NOT Skill-tool invocable._
```

### Writing skills

Skills live in `~/.claude/skills/<name>.yaml`. The router auto-discovers all `*.yaml` files in that directory — no registration step.

A minimal skill:

```yaml
name: my-deploy-runbook
description: |
  Deploy checklist for the payments service. Staging gate required.
  Always run DB migrations before app deployment.
domain: devops
tags:
  - deploy
  - migrations
  - rollback
trigger_phrases:
  - "deploy to production"
  - "run migrations"
  - "rollback"
instructions: |
  # Payments Service — Deploy Runbook

  ## Pre-deploy
  1. Verify staging passes all smoke tests
  2. Run `make db-migrate` BEFORE deploying app

  ## Deploy
  ```bash
  make deploy ENV=production
  ```

  ## Rollback
  ```bash
  make rollback ENV=production VERSION=<previous>
  ```

  ## Gotchas
  - Never deploy on Fridays after 15:00
  - The payment_events table has a partial index — check explain plans after schema changes
```

See [`skills/_format.yaml`](skills/_format.yaml) for the complete format reference.

---

## Hook 2 — Prompt Recall

Detects temporal and recall signals in your prompt, then queries [kcp-memory](https://github.com/Cantara/kcp-memory) for relevant past sessions.

**Triggers on:**

```python
"yesterday", "last week", "last time", "previously", "recently"
"what did I / we do / build / fix / decide..."
"when did I / we..."
"do you remember..."
"same as before", "continue from where..."
"3 days ago", "2 weeks ago"
```

**What it queries:** `GET localhost:7735/search?q=<extracted_query>&limit=3`

kcp-memory indexes your Claude Code session transcripts (everything you've ever built, discussed, or fixed) into SQLite+FTS5. The recall hook is the retrieval interface.

**Output example:**

```
## Episodic Memory — relevant past sessions (query: "auth service token refresh")
- 2026-06-19 [payments-api] Implemented JWT refresh token rotation — added 7-day sliding window, fixed the race condition in concurrent refresh attempts
- 2026-06-12 [auth-service] Debugged token expiry issue — root cause was clock skew between auth and API nodes, fixed with NTP sync

_From kcp-memory. Run `kcp-memory search "<query>"` for more._
```

**Requires kcp-memory:**

```bash
# Install
# https://github.com/Cantara/kcp-memory

# Run as daemon
java -jar ~/.kcp/kcp-memory-daemon.jar daemon

# Verify
curl http://localhost:7735/health
```

If kcp-memory is not running, `prompt-recall.py` fails silently. Your prompts are unaffected.

---

## Hook 3 — Prompt Hygiene

Pure regex scan for influence tactics in prompts. Based on [Lucid/synaptiai](https://github.com/synaptiai/lucid) (MIT).

**Detects:**

| Category | Example |
|----------|---------|
| `emotional-triggers` | "I really need you to...", "I'm desperate" |
| `urgent-action-demands` | "right now", "ASAP", "before it's too late" |
| `emotional-repetition` | `!!!`, `???`, `PLEASE PLEASE PLEASE` |
| `false-dilemmas` | "either you do X or Y", "no other option" |
| `authority-overload` | "experts say", "the science shows", "we all know" |

**Silent on clean prompts.** Flags with a single line when tactics are detected:

```
[hygiene] Influence tactics detected: emotional-triggers, urgent-action-demands
```

`framing-techniques` is excluded — too noisy in technical prompts.

---

## The three-layer memory model

kcp-hooks occupies two of the three layers:

| Layer | What it holds | Provided by |
|-------|--------------|-------------|
| **Procedural** | How to do things — runbooks, conventions, patterns | kcp-hooks `prompt-router` + your skill files |
| **Episodic** | What happened — past sessions, decisions, bugs fixed | kcp-hooks `prompt-recall` + [kcp-memory](https://github.com/Cantara/kcp-memory) |
| **Semantic** | What the codebase means — structure, relationships, dependencies | [Synthesis](https://github.com/Cantara/synthesis) |

Working memory (the current context window) sits on top of all three.

---

## Customising prompt-router

### Domain signals

Add your project names and distinctive vocabulary to route prompts to the right domain:

```python
# In prompt-router.py, DOMAIN_SIGNALS dict:
DOMAIN_SIGNALS: dict[str, list[str]] = {
    "kcp": ["kcp", "kcp-commands", "kcp-memory", "manifest"],
    # Add yours:
    "payments": ["stripe", "webhook", "idempotency", "payment_intent"],
    "infra": ["terraform", "eks", "helm", "namespace"],
}
```

Skills with a `domain` matching a detected signal get a 1.2× score boost. Skills from unrelated specific domains get a 0.4× penalty.

### Score thresholds

```python
MIN_SCORE = 4     # Minimum score to surface a skill (raise to reduce noise)
MAX_RESULTS = 3   # Max skills injected per prompt (keep low — context is precious)
```

### Session decay rate

```python
SESSION_DECAY = 0.72  # Score multiplier per prior showing this session
                       # 0.72 → second showing at 72%, third at 52%
                       # Set to 1.0 to disable decay
```

---

## Repository layout

```
kcp-hooks/
├── hooks/
│   ├── prompt-router.py     # Skill routing
│   ├── prompt-hygiene.py    # Influence detection
│   └── prompt-recall.py     # Episodic recall via kcp-memory
├── skills/
│   ├── _format.yaml         # Complete skill file format spec
│   └── examples/
│       └── git-workflow.yaml
├── install.sh               # Wires hooks into ~/.claude/settings.json
└── README.md
```

After install:

```
~/.kcp/hooks/                ← Installed hook scripts
~/.claude/skills/            ← Your skill files live here
~/.claude/settings.json      ← Hook registration (auto-updated by install.sh)
```

---

## Sibling projects

| Project | Hook type | What it does |
|---------|-----------|-------------|
| [kcp-commands](https://github.com/Cantara/kcp-commands) | PreToolUse + PostToolUse | CLI guidance injection and output noise filtering — 291 command manifests |
| [kcp-memory](https://github.com/Cantara/kcp-memory) | HTTP daemon + MCP | Indexes session transcripts into SQLite+FTS5, exposes 9 MCP tools |
| [knowledge-context-protocol](https://github.com/Cantara/knowledge-context-protocol) | Spec | The YAML standard behind all of this |

Together they cover the full Claude Code lifecycle:

```
Before Bash runs:   kcp-commands injects CLI guidance
After Bash runs:    kcp-commands filters output noise + logs to events.jsonl
Before prompt sent: kcp-hooks injects skill context + episodic memory
Between sessions:   kcp-memory indexes everything that happened
```

---

## Contributing

Issues and PRs welcome. The most valuable contributions are skill files — if you write a useful skill for a common tool, stack, or workflow, it belongs in `skills/examples/`.

The hook scripts are intentionally kept simple: pure Python stdlib, no dependencies, no build step. A new hook is ~50 lines.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

`prompt-hygiene.py` pattern library based on [Lucid/synaptiai](https://github.com/synaptiai/lucid) (MIT).
