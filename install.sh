#!/usr/bin/env bash
# kcp-hooks installer
# Copies hooks to ~/.kcp/hooks/ and wires them into ~/.claude/settings.json
set -euo pipefail

HOOKS_DIR="${HOME}/.kcp/hooks"
SETTINGS="${HOME}/.claude/settings.json"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "kcp-hooks installer"
echo "==================="
echo "Hooks dir : ${HOOKS_DIR}"
echo "Settings  : ${SETTINGS}"
echo ""

# 1. Copy hooks
mkdir -p "${HOOKS_DIR}"
cp "${REPO_DIR}/hooks/prompt-router.py"  "${HOOKS_DIR}/"
cp "${REPO_DIR}/hooks/prompt-hygiene.py" "${HOOKS_DIR}/"
cp "${REPO_DIR}/hooks/prompt-recall.py"  "${HOOKS_DIR}/"
chmod +x "${HOOKS_DIR}/"*.py
echo "✓ Hooks copied to ${HOOKS_DIR}"

# 2. Create skills directory if missing
SKILLS_DIR="${HOME}/.claude/skills"
mkdir -p "${SKILLS_DIR}"
echo "✓ Skills directory: ${SKILLS_DIR}"

# 3. Wire hooks into ~/.claude/settings.json
if [ ! -f "${SETTINGS}" ]; then
    echo '{}' > "${SETTINGS}"
fi

# Use Python to safely merge hook config into existing settings.json
python3 - "${SETTINGS}" "${HOOKS_DIR}" <<'PYEOF'
import json, sys, os

settings_path = sys.argv[1]
hooks_dir = sys.argv[2]

with open(settings_path, "r") as f:
    settings = json.load(f)

# Build hook entries
hook_commands = [
    f"python3 {hooks_dir}/prompt-hygiene.py",
    f"python3 {hooks_dir}/prompt-router.py",
    f"python3 {hooks_dir}/prompt-recall.py",
]

new_hooks = [{"type": "command", "command": cmd} for cmd in hook_commands]

# Merge: add our hooks if not already present (by command string)
existing_hooks = settings.get("hooks", {})
existing_ups = existing_hooks.get("UserPromptSubmit", [])

# Flatten existing hook commands for dedup check
existing_cmds = set()
for entry in existing_ups:
    for h in entry.get("hooks", []):
        existing_cmds.add(h.get("command", ""))

to_add = [h for h in new_hooks if h["command"] not in existing_cmds]

if to_add:
    existing_ups.append({"hooks": to_add})
    existing_hooks["UserPromptSubmit"] = existing_ups
    settings["hooks"] = existing_hooks
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"✓ Wired {len(to_add)} hook(s) into {settings_path}")
else:
    print("✓ Hooks already present in settings.json — no changes needed")
PYEOF

echo ""
echo "Installation complete."
echo ""
echo "Next steps:"
echo "  1. Add your skill files to ${SKILLS_DIR}/<name>.yaml"
echo "     See skills/_format.yaml for the format spec."
echo "  2. (Optional) Start kcp-memory for episodic recall:"
echo "     https://github.com/Cantara/kcp-memory"
echo "  3. Restart Claude Code — hooks fire on next session start."
echo ""
echo "Hooks installed:"
echo "  - prompt-hygiene.py  : detects influence tactics (always active)"
echo "  - prompt-router.py   : surfaces relevant skills from ~/.claude/skills/"
echo "  - prompt-recall.py   : queries kcp-memory for past sessions (requires daemon)"
