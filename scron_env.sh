#!/bin/bash
# scron_env.sh — run a scrontab command inside a normal login environment.
#
# Why: "#SCRON --export=NONE" makes Slurm build the user env on the compute
# node via an implicit --get-user-env (a timed "su - user" before the job
# starts). If that times out (slow NFS, busy node) the job goes to
# "user env retrieval failed requeued held", and scrontab jobs cannot be
# released or requeued — the whole cron series stops until cancelled and
# reinstalled.
#
# Instead, scrontab.txt uses "--export=NIL" (no env retrieval; the job starts
# with HOME/PATH/USER unset) and wraps each command with this script, which
# builds the same login environment inside the job. A slow login now just
# makes the job slower; a failure fails only that run and the next one still
# fires.
#
# Usage (in scrontab):  /home/p.chang/librarian/scron_env.sh '<command line>'

U="$(id -un)"
export USER="$U" LOGNAME="$U"
export HOME="$(getent passwd "$U" | cut -d: -f6)"
export SHELL=/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin
cd "$HOME" || exit 1

exec /bin/bash -l -c "$*"
