# kcp-hooks

Three `UserPromptSubmit` hooks that give Claude Code proactive memory, skill routing, and prompt hygiene — without touching your code or requiring any cloud service.

Part of the [Knowledge Context Protocol](https://github.com/Cantara/knowledge-context-protocol) ecosystem.

## What's included

| Hook | What it does |
|------|-------------|
| `prompt-router.py` | Detects the topic of your prompt and surfaces relevant skill files from `~/.claude/skills/` before Claude responds |
| `prompt-hygiene.py` | Detects influence tactics in prompts (emotional pressure, false urgency, authority overload) — flags them silently |
| `prompt-recall.py` | Detects temporal/recall signals ("last time", "yesterday", "what did I...") and queries [kcp-memory](https://github.com/Cantara/kcp-memory) for relevant past sessions |

## How it works

Claude Code supports `UserPromptSubmit` hooks — scripts that run before every prompt is sent to the model. kcp-hooks uses this to inject context automatically, without you having to think about it.

```
You type a prompt
       ↓
UserPromptSubmit fires (parallel)
  ├── prompt-hygiene.py  → flags manipulation attempts
  ├── prompt-router.py   → injects relevant skill context
  └── prompt-recall.py   → injects relevant past session summaries
       ↓
Claude sees: [your prompt] + [injected context]
```

No API calls. No cloud. Everything runs locally in <200ms.

## Install

```bash
git clone https://github.com/Cantara/kcp-hooks
cd kcp-hooks
bash install.sh
```

The installer:
1. Copies hooks to `~/.kcp/hooks/`
2. Wires them into `~/.claude/settings.json`
3. Creates `~/.claude/skills/` if it doesn't exist

Restart Claude Code to activate.

## Skills

Skills are YAML files that teach Claude Code about your projects, patterns, and context.

```
~/.claude/skills/
  my-project.yaml
  deployment-runbook.yaml
  database-schema.yaml
  ...
```

`prompt-router.py` auto-discovers all `*.yaml` files in that directory and scores them against each incoming prompt. Top 3 matches are injected as context.

See [`skills/_format.yaml`](skills/_format.yaml) for the full format spec.

A minimal skill:

```yaml
name: my-project
description: |
  Our internal API service. Node.js + PostgreSQL + Redis.
  Deployed on AWS ECS via GitHub Actions.
domain: my-project
tags:
  - nodejs
  - postgres
  - aws
trigger_phrases:
  - "deploy the API"
  - "database migration"
instructions: |
  # My Project

  ## Key facts
  - API runs on port 3000
  - DB: postgres://prod-db:5432/myapp
  - Deploy: push to main → GitHub Actions → ECS

  ## Common gotchas
  - Always run migrations before deploying
  - Redis TTL is 1 hour — don't cache auth tokens longer
```

## Episodic recall (optional)

`prompt-recall.py` requires [kcp-memory](https://github.com/Cantara/kcp-memory) running as an HTTP daemon on port 7735.

```bash
# Install kcp-memory
# https://github.com/Cantara/kcp-memory

# Start daemon
java -jar ~/.kcp/kcp-memory-daemon.jar daemon

# Verify
curl http://localhost:7735/health
```

Once running, prompts like "what did I do last week with the auth service?" automatically pull relevant session history into context.

## Architecture

```
~/.claude/settings.json          ← Hook registration
~/.kcp/hooks/
  prompt-router.py               ← Skill routing
  prompt-hygiene.py              ← Influence detection
  prompt-recall.py               ← Episodic memory (calls kcp-memory)
~/.claude/skills/
  *.yaml                         ← Your skill files
```

The three-layer memory model this fits into:

| Layer | What it holds | Provided by |
|-------|--------------|-------------|
| Procedural | How to do things (skills) | **kcp-hooks** prompt-router |
| Episodic | What happened in past sessions | **kcp-hooks** prompt-recall + kcp-memory |
| Semantic | What the codebase means | [Synthesis](https://github.com/Cantara/synthesis) |

## Siblings

| Project | What it does |
|---------|-------------|
| [kcp-commands](https://github.com/Cantara/kcp-commands) | PreToolUse/PostToolUse hooks — CLI guidance + output filtering |
| [kcp-memory](https://github.com/Cantara/kcp-memory) | Episodic memory daemon — indexes session transcripts |
| [knowledge-context-protocol](https://github.com/Cantara/knowledge-context-protocol) | The KCP spec |

## License

Apache 2.0 — see LICENSE.

`prompt-hygiene.py` pattern library based on [Lucid/synaptiai](https://github.com/synaptiai/lucid) (MIT).
