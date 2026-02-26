#!/bin/bash
# watchdog.sh - Self-healing watchdog for scrontab jobs
# Detects stuck Slurm jobs and attempts recovery.
# Intended to run every 5 minutes via scrontab.

LOGFILE="$HOME/scron/logs/watchdog.log"
mkdir -p "$(dirname "$LOGFILE")"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOGFILE"
}

# Find our stuck jobs: held, requeued, or with known failure reasons
STUCK_JOBS=$(/opt/slurm/bin/squeue --me --noheader --states=PD \
    --format="%i %T %r" 2>/dev/null | \
    grep -iE "held|requeue|user env|launch failed" || true)

if [ -z "$STUCK_JOBS" ]; then
    exit 0
fi

log "Found stuck jobs:"
echo "$STUCK_JOBS" | while read -r line; do
    log "  $line"
done

echo "$STUCK_JOBS" | while read -r JOBID STATE REASON; do
    # Try release first (non-destructive)
    log "Attempting scontrol release on job $JOBID (state=$STATE reason=$REASON)"
    /opt/slurm/bin/scontrol release "$JOBID" 2>>"$LOGFILE"

    sleep 5

    # Check if still stuck
    STILL_STUCK=$(/opt/slurm/bin/squeue --me --noheader --job="$JOBID" \
        --format="%T %r" 2>/dev/null | \
        grep -iE "held|requeue|user env|launch failed" || true)

    if [ -n "$STILL_STUCK" ]; then
        log "Job $JOBID still stuck after release, cancelling"
        /opt/slurm/bin/scancel "$JOBID" 2>>"$LOGFILE"
        log "Cancelled job $JOBID - scrontab will reschedule"
    else
        log "Job $JOBID released successfully"
    fi
done

log "Watchdog check complete"
