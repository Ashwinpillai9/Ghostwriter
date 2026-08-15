#!/usr/bin/env bash
# PostToolUse: push the current feature branch whenever it has commits the remote lacks.
#
# Deliberately checks the repo state rather than parsing the command that just ran: commits
# arrive as `git commit`, `git add -A && git commit`, `git commit --amend` and so on, and a
# pattern match would miss half of them. Protected branches are never pushed from here.

set -u

PROTECTED="main master"

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
[ -z "$branch" ] || [ "$branch" = "HEAD" ] && exit 0

for protected in $PROTECTED; do
  [ "$branch" = "$protected" ] && exit 0
done

if git rev-parse --abbrev-ref "@{u}" >/dev/null 2>&1; then
  # An amend or rebase leaves the branch behind as well as ahead, so compare both ways.
  counts=$(git rev-list --left-right --count "@{u}...HEAD" 2>/dev/null) || exit 0
  behind=$(printf '%s' "$counts" | cut -f1)
  ahead=$(printf '%s' "$counts" | cut -f2)
  [ "${ahead:-0}" = "0" ] && exit 0
  if [ "${behind:-0}" != "0" ]; then
    # Diverged: force-pushing here could discard someone else's work silently.
    printf '{"systemMessage":"%s has diverged from its remote; push skipped."}\n' "$branch"
    exit 0
  fi
  output=$(git push 2>&1)
else
  output=$(git push -u origin HEAD 2>&1)
fi

if [ $? -eq 0 ]; then
  printf '{"systemMessage":"Pushed %s","suppressOutput":true}\n' "$branch"
else
  escaped=$(printf '%s' "$output" | tr '\n' ' ' | sed 's/"/\\"/g' | cut -c1-300)
  printf '{"systemMessage":"Auto-push of %s failed: %s"}\n' "$branch" "$escaped"
fi

exit 0
