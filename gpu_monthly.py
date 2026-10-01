#!/bin/env python3
"""Permanent monthly GPU usage log for a QoS.

The dashboard only covers a rolling 30 days, and Slurm purges job records
after ~6 months, so this script aggregates each month into CSVs that are kept
forever (and shipped to gh-pages by deploy_pages.sh).

Outputs (in gpu_usage/):
  gpu_monthly.csv          one row per (month, qos): totals, peak, saturation
  gpu_monthly_by_user.csv  one row per (month, qos, user, gpu_type)

Rows for the months being recomputed are replaced; all other rows are kept
untouched, so months that Slurm has already purged are never lost.

Usage:
  ./gpu_monthly.py                       recompute current + previous month
  ./gpu_monthly.py 2026-04 2026-05 ...   recompute specific months (backfill)
  ./gpu_monthly.py --qos avery,p.chang   choose QoS (default: avery)
"""

import csv
import datetime
import os
import subprocess
import sys
import time

SACCT = "/opt/slurm/bin/sacct"
SACCTMGR = "/opt/slurm/bin/sacctmgr"
DIR = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(DIR, "gpu_usage")
SUMMARY_CSV = os.path.join(OUTDIR, "gpu_monthly.csv")
BY_USER_CSV = os.path.join(OUTDIR, "gpu_monthly_by_user.csv")

SUMMARY_FIELDS = [
    "month", "qos", "gpu_limit", "hours_covered", "complete",
    "gpu_hours", "avg_gpus_in_use", "avg_frac_of_limit", "peak_gpus_in_use",
    "hours_at_limit", "frac_hours_at_limit", "gpu_hours_queued",
    "n_gpu_jobs", "n_gpu_users", "data_start", "last_updated",
]
BY_USER_FIELDS = [
    "month", "qos", "user", "gpu_type", "gpu_hours", "gpu_hours_queued", "n_gpu_jobs",
]


def parse_time(s):
    if s in ("Unknown", "None", "", None):
        return None
    return int(time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S")))


def parse_gpus(tres):
    """Return (n_gpus, gpu_type) from a TRES string like
    'cpu=4,gres/gpu:l4=1,gres/gpu=1,mem=24G'."""
    n, gtype = 0, "unspecified"
    for item in tres.split(","):
        key, _, val = item.partition("=")
        if key == "gres/gpu":
            n = int(val)
        elif key.startswith("gres/gpu:"):
            gtype = key.split(":", 1)[1]
    return n, gtype


def month_bounds(month):
    y, m = map(int, month.split("-"))
    start = datetime.datetime(y, m, 1)
    end = datetime.datetime(y + (m == 12), m % 12 + 1, 1)
    return int(time.mktime(start.timetuple())), int(time.mktime(end.timetuple()))


def gpu_limit(qos):
    out = subprocess.run([SACCTMGR, "-nP", "show", "qos", qos, "format=grptres"],
                         capture_output=True, text=True).stdout
    for item in out.strip().split(","):
        if item.startswith("gres/gpu="):
            return int(item.split("=")[1])
    return 0


def query_jobs(qos, t0, t1):
    fmt = "User,Start,ElapsedRaw,Eligible,AllocTRES,ReqTRES"
    s = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0))
    e = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t1))
    out = subprocess.run([SACCT, "-a", "-X", "-n", "-P", "-q", qos, "-S", s, "-E", e,
                          f"--format={fmt}"], capture_output=True, text=True, check=True).stdout
    jobs = []
    first_end = None  # earliest end of ANY job: tells us where Slurm's purge cut off
    for line in out.splitlines():
        user, start, elapsed, eligible, alloc, req = line.split("|")
        start = parse_time(start)
        if not user or not start:
            continue  # never started: no GPU use and no satisfied demand to count
        end = start + int(elapsed or 0)
        if first_end is None or end < first_end:
            first_end = end
        ngpus, gtype = parse_gpus(alloc)
        if ngpus == 0:
            continue
        jobs.append(dict(user=user, start=start, end=end, eligible=parse_time(eligible),
                         ngpus=ngpus, gtype=gtype))
    return jobs, first_end


def summarize(qos, month, now):
    m0, m1 = month_bounds(month)
    t1 = min(m1, now)
    jobs, first_end = query_jobs(qos, m0, t1)
    limit = gpu_limit(qos)

    # Jobs end every few minutes, so a first end hours past the month start means
    # Slurm has already purged the beginning of this month.
    data_start = first_end if first_end and first_end - m0 > 6 * 3600 else m0
    by_user = {}
    events = []
    gpu_sec = queued_sec = 0
    for j in jobs:
        key = (j["user"], j["gtype"])
        u = by_user.setdefault(key, dict(gpu_sec=0, queued_sec=0, n=0))
        u["n"] += 1
        a, b = max(j["start"], m0), min(j["end"], t1)
        if b > a:
            u["gpu_sec"] += j["ngpus"] * (b - a)
            gpu_sec += j["ngpus"] * (b - a)
            events += [(a, j["ngpus"]), (b, -j["ngpus"])]
        # GPU-time spent waiting in queue after becoming eligible = delayed demand.
        if j["eligible"]:
            a, b = max(j["eligible"], m0), min(j["start"], t1)
            if b > a:
                u["queued_sec"] += j["ngpus"] * (b - a)
                queued_sec += j["ngpus"] * (b - a)

    # Sweep job start/end events for peak concurrency and time spent at the limit.
    events.sort()
    cur = peak = 0
    at_limit_sec = 0
    prev_t = None
    for t, delta in events:
        if prev_t is not None and limit and cur >= limit:
            at_limit_sec += t - prev_t
        cur += delta
        peak = max(peak, cur)
        prev_t = t

    hours = (t1 - data_start) / 3600
    gpu_hours = gpu_sec / 3600
    avg = gpu_hours / hours if hours else 0
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    summary = {
        "month": month, "qos": qos, "gpu_limit": limit,
        "hours_covered": round(hours, 1),
        "complete": int(t1 == m1 and data_start == m0),
        "gpu_hours": round(gpu_hours, 1),
        "avg_gpus_in_use": round(avg, 2),
        "avg_frac_of_limit": round(avg / limit, 3) if limit else "",
        "peak_gpus_in_use": peak,
        "hours_at_limit": round(at_limit_sec / 3600, 1),
        "frac_hours_at_limit": round(at_limit_sec / 3600 / hours, 3) if hours else 0,
        "gpu_hours_queued": round(queued_sec / 3600, 1),
        "n_gpu_jobs": len(jobs),
        "n_gpu_users": len({j["user"] for j in jobs}),
        "data_start": time.strftime("%Y-%m-%d", time.localtime(data_start)),
        "last_updated": stamp,
    }
    rows = [{"month": month, "qos": qos, "user": user, "gpu_type": gtype,
             "gpu_hours": round(u["gpu_sec"] / 3600, 1),
             "gpu_hours_queued": round(u["queued_sec"] / 3600, 1),
             "n_gpu_jobs": u["n"]}
            for (user, gtype), u in by_user.items()]
    rows.sort(key=lambda r: -r["gpu_hours"])
    return summary, rows


def merge(path, fields, new_rows, replaced):
    """Rewrite path keeping every existing row whose (month, qos) wasn't recomputed."""
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            rows = [r for r in csv.DictReader(f) if (r["month"], r["qos"]) not in replaced]
    rows += new_rows
    rows.sort(key=lambda r: (r["month"], r["qos"], -float(r.get("gpu_hours") or 0)))
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def main():
    args = sys.argv[1:]
    qos_list = ["avery"]
    if "--qos" in args:
        i = args.index("--qos")
        qos_list = args[i + 1].split(",")
        del args[i:i + 2]

    now = int(time.time())
    today = datetime.date.today()
    if args:
        months = args
    else:
        prev = (today.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
        months = [prev, today.strftime("%Y-%m")]

    os.makedirs(OUTDIR, exist_ok=True)
    complete = set()
    if os.path.exists(SUMMARY_CSV):
        with open(SUMMARY_CSV) as f:
            complete = {(r["month"], r["qos"]) for r in csv.DictReader(f) if r["complete"] == "1"}

    summaries, user_rows, replaced = [], [], set()
    for qos in qos_list:
        for month in months:
            s, rows = summarize(qos, month, now)
            # Never let a purge-truncated recompute clobber a month logged in full.
            if (month, qos) in complete and not s["complete"]:
                print(f"{month} {qos}: keeping existing complete row (Slurm data now partial)")
                continue
            summaries.append(s)
            user_rows += rows
            replaced.add((month, qos))
            print(f"{month} {qos}: {s['gpu_hours']} GPU-h, avg {s['avg_gpus_in_use']}/"
                  f"{s['gpu_limit']}, peak {s['peak_gpus_in_use']}, "
                  f"{s['hours_at_limit']} h at limit, {s['n_gpu_users']} users")

    merge(SUMMARY_CSV, SUMMARY_FIELDS, summaries, replaced)
    merge(BY_USER_CSV, BY_USER_FIELDS, user_rows, replaced)


if __name__ == "__main__":
    main()
