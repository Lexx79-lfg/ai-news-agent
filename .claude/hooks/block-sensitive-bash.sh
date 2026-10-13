#!/bin/bash
# PreToolUse hook: blocks any Bash command containing ".env", or "git" followed later by "push".
# Exit code 2 tells Claude Code to block the tool call; stderr is shown to Claude.

input=$(cat)

if ! command -v jq >/dev/null 2>&1; then
  echo "Blocked: jq not found, so the command could not be checked." >&2
  exit 2
fi

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

if [[ "$cmd" == *".env"* ]]; then
  echo "Blocked: the command mentions .env, and access to .env files is not allowed." >&2
  exit 2
fi

if [[ "$cmd" =~ git.*push ]]; then
  echo "Blocked: git push is not allowed. The user pushes manually." >&2
  exit 2
fi

exit 0
