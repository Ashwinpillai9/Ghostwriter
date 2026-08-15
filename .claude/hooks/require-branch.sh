#!/usr/bin/env bash
# PreToolUse guard: refuse to edit files while the repo is on a protected branch.
#
# Reads the tool-call JSON on stdin, works out which repo the target file lives in, and denies
# the edit if that repo is sitting on main/master. Files outside a git repo are always allowed,
# so scratchpad and config edits are unaffected.
#
# There is no jq on this machine, hence the sed extraction.

set -u

PROTECTED="main master"

payload=$(cat)
file=$(printf '%s' "$payload" |
  sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' |
  head -1)

[ -z "$file" ] && exit 0

# JSON escapes Windows separators as \\; turn them into / so dirname works.
file=$(printf '%s' "$file" | sed 's|\\\\|/|g; s|\\|/|g')
dir=$(dirname "$file")

branch=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
[ -z "$branch" ] && exit 0

for protected in $PROTECTED; do
  if [ "$branch" = "$protected" ]; then
    reason="Edits to $branch are blocked. Start the work on its own branch first:\n"
    reason="$reason  git checkout -b <type>/<short-description>   (feat/, fix/ or chore/)\n"
    reason="$reason Then re-apply this edit. The branch is pushed automatically on commit, and "
    reason="$reason lands on $branch through a PR once approved."
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$reason"
    exit 0
  fi
done

exit 0
