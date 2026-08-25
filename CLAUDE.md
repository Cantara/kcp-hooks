# kcp-hooks

Three passive Claude Code `UserPromptSubmit` hooks — `prompt-router` (surfaces relevant
skill files from `~/.claude/skills/`), `prompt-recall` (queries kcp-memory for relevant
past sessions), `prompt-hygiene` (flags influence tactics in prompts). Pure stdlib
Python, no external API calls, <200ms per hook. Part of the Knowledge Context Protocol
ecosystem.

## Start here

Read `knowledge.yaml` first — the canonical agent-navigable index (currently a single
`overview` unit pointing at README.md). Query it the standard KCP way:
`npx kcp-agent plan '<intent>' --manifest .`

For the shared conventions on how a governed skill unit should be authored
(`action_scope` as a firewall rule, `PROFILE.md`), see
[kcp-skill](https://github.com/Cantara/kcp-skill) — this repo does not vendor
kcp-skill's own skill library, only its authoring conventions.

## `skills/` is product, not local skills

`skills/_format.yaml` + `skills/examples/` define the skill-file format `prompt-router.py`
reads from end users' `~/.claude/skills/` — it ships with the product, it isn't this
repo's own operational knowledge. This repo's own dev procedures live in
**`.claude/skills/`**: `add-a-hook` — wiring a new `UserPromptSubmit` hook into
`install.sh` and the README.

## Gotchas

- `install.sh` wires each hook in **two separate places** (the `cp` list and the
  `hook_commands` Python list) — add a hook script without touching both and it's
  either copied but never fires, or wired but never installed.
- No CI, no test suite, no release tags yet (4 commits, no `v*` tags). Verifying a
  hook change is manual: pipe JSON on stdin and read stdout.
- `knowledge.yaml` has exactly one unit (`overview` → README.md) — it does not
  enumerate the three hooks individually or reference `.claude/skills/`.
