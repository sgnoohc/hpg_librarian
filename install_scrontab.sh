#!/bin/bash
# install_scrontab.sh — restore the canonical scrontab.
#
# When you scancel a scrontab job, Slurm prepends "#DISABLED:" to that line
# instead of removing it, so killed jobs never come back on their own. Running
# this reinstalls scrontab.txt verbatim, re-enabling everything.
#
# Usage:
#   ./install_scrontab.sh          install canonical scrontab (backs up current)
#   ./install_scrontab.sh --diff   show what would change, install nothing
#   ./install_scrontab.sh --enable re-enable in-place (strip #DISABLED:), no overwrite

set -euo pipefail

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CANON="$DIR/scrontab.txt"
SCRONTAB=/opt/slurm/bin/scrontab
BACKUP_DIR="$HOME/scron/backups"

[ -f "$CANON" ] || { echo "error: missing $CANON" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"

case "${1:-}" in
  --diff)
    echo "# current scrontab vs canonical ($CANON):"
    diff <("$SCRONTAB" -l 2>/dev/null || true) "$CANON" && echo "# identical"
    exit 0
    ;;
  --enable)
    # Re-enable in place: strip the "#DISABLED: " prefix Slurm adds on scancel.
    current="$("$SCRONTAB" -l 2>/dev/null || true)"
    if ! grep -q '#DISABLED:' <<<"$current"; then
      echo "nothing disabled — scrontab unchanged"
      exit 0
    fi
    echo "$current" > "$BACKUP_DIR/scrontab.$(date +%Y%m%d-%H%M%S).bak"
    sed 's/^#DISABLED: //' <<<"$current" | "$SCRONTAB" -
    echo "re-enabled disabled entries. Current jobs:"
    "$SCRONTAB" -l | grep -vE '^\s*#' | grep -v '^\s*$' || true
    exit 0
    ;;
  "" )
    : # default: install canonical
    ;;
  *)
    echo "usage: $0 [--diff|--enable]" >&2
    exit 2
    ;;
esac

# Back up whatever is currently installed before overwriting.
"$SCRONTAB" -l 2>/dev/null > "$BACKUP_DIR/scrontab.$(date +%Y%m%d-%H%M%S).bak" || true

"$SCRONTAB" "$CANON"
echo "installed canonical scrontab. Active entries:"
"$SCRONTAB" -l | grep -vE '^\s*#' | grep -v '^\s*$' || true
