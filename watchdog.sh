#!/bin/bash
# watchdog.sh - Self-healing watchdog for scrontab jobs.
# Intended to run every 5 minutes via scrontab.
#
# A scrontab job whose launch fails (e.g. "user env retrieval failed requeued
# held") stays held forever: Slurm rejects scontrol release/requeue for cron
# jobs. The only recovery is to scancel it (Slurm then comments its line out
# as "#DISABLED:") and re-enable the scrontab, which creates a fresh job.
#
# Only cron jobs (CronJob=Yes) are touched; regular batch jobs are never
# cancelled.

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOGFILE="$HOME/scron/logs/watchdog.log"
mkdir -p "$(dirname "$LOGFILE")"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOGFILE"
}

HELD=()
while read -r JOBID REASON; do
    [ -n "$JOBID" ] || continue
    /opt/slurm/bin/scontrol show job "$JOBID" 2>/dev/null | grep -q 'CronJob=Yes' || continue
    log "held cron job $JOBID: $REASON"
    HELD+=("$JOBID")
done < <(/opt/slurm/bin/squeue --me --noheader --states=PD --format="%i %r" 2>/dev/null | \
         grep -iE "held|requeue|user env|launch failed")

[ ${#HELD[@]} -eq 0 ] && exit 0

log "cancelling ${HELD[*]} and re-enabling scrontab"
/opt/slurm/bin/scancel "${HELD[@]}" >>"$LOGFILE" 2>&1
sleep 5
"$DIR/install_scrontab.sh" --enable >>"$LOGFILE" 2>&1 || log "install_scrontab.sh --enable failed"

log "now queued: $(/opt/slurm/bin/squeue --me --noheader --format='%i:%r' 2>/dev/null | tr '\n' ' ')"
