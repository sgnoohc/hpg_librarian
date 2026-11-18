#!/bin/env python3

import csv
import time
import sys
import os
import re
import json
import subprocess
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import datetime
import math
import pytz

qos = "avery"

if len(sys.argv) > 1:
    arg = sys.argv[1]
    # Backward compatible: bare "2" still selects the avery burst QoS.
    qos = "avery-b" if arg == "2" else arg

#----------------------------------------
# Configuration
time_res = 3600 # 1 hour
time_window = 3600 * 24 * 30 # 30 days
#----------------------------------------

# Current time
eastern_timezone = pytz.timezone('US/Eastern')
current_time = datetime.datetime.now(eastern_timezone)
nearest_10_minutes = math.ceil(current_time.minute / 10) * 10 # Calculate the nearest 10 minutes
if nearest_10_minutes == 60:
    nearest_10_minutes = 59
rounded_time = current_time.replace(minute=nearest_10_minutes, second=0, microsecond=0) # Round the time to the nearest 10 minutes
current_time = int(rounded_time.timestamp()) # Convert the rounded time to Unix timestamp

# Compute time bin boundaries
to_time = current_time
from_time = current_time - time_window
from_date = datetime.datetime.fromtimestamp(from_time).strftime('%Y-%m-%d')
nbins = int(time_window / time_res)

# Goal is to create histograms of n bins where each bin contains number of CPUs / memory per user
time_idxs = [ from_time + time_res * x for x in range(nbins) ]
d = {}
observables = [
        "NCPUS",
        "NGPUS",
        "ReqMem",
        "NNodes",
        ]
# Per-QoS resource limits (threshold lines drawn on the plots).
# ReqMem is in GB to match the computed ReqMem column below.
qos_thresholds = {
        "avery"     : {"NCPUS": 430,  "NGPUS": 34, "ReqMem": 3359,  "NNodes": 0},
        "avery-b"   : {"NCPUS": 3870, "NGPUS": 0,  "ReqMem": 30234, "NNodes": 0},
        "p.chang"   : {"NCPUS": 16,   "NGPUS": 9,  "ReqMem": 125,   "NNodes": 0},
        "p.chang-b" : {"NCPUS": 144,  "NGPUS": 0,  "ReqMem": 1125,  "NNodes": 0},
        }
# Unknown QoS: no threshold lines (all zeros).
thresholds = qos_thresholds.get(qos, {"NCPUS": 0, "NGPUS": 0, "ReqMem": 0, "NNodes": 0})
nicenames = {
        "NCPUS" : "# of CPUs",
        "NGPUS" : "# of GPUs",
        "ReqMem" : "Memory (GB)",
        "NNodes": "# of Jobs",
        }
shortnames = {
        "NCPUS" : "NCPUS",
        "NGPUS" : "NGPUS",
        "ReqMem" : "MEMORY",
        "NNodes": "NJOBS",
        }


# Following are the data to obtain
column_headers = [
        "User",
        "Submit",
        "NNodes",
        "NCPUS",
        "ReqMem",
        "ReqTRES",
        "State",
        "Priority",
        "Start",
        "ElapsedRaw",
        "JobID",
        "JobIDRaw",
        "NodeList",
        "Reason",
        "Eligible",
        "End",
        "ReqCPUS",
        "AllocTRES",
        "Partition",
        ]

# Creating some colunm name to integer matching
cols = {}
for i, c in enumerate(column_headers):
    cols[c] = i

# Process the Slurm command and obtain the data
columns = ",".join(column_headers)
os.system(f"/opt/slurm/bin/sacct -a -S {from_date} -q {qos} --format=\"{columns}\" -P --noconvert > {qos}.txt")

df = pd.read_csv(f"{qos}.txt", sep="|")
df = df[~df.User.isna()] # Get rid of rows with user name NaN

#pd.set_option('display.max_rows', None)     # Show all rows

#print(df["Start"])

to_ts = lambda x : int(time.mktime(time.strptime(x, "%Y-%m-%dT%H:%M:%S"))) if x != "Unknown" and x != "None" else 0
df["Start"] = df["Start"].apply(to_ts)
df["Submit"] = df["Submit"].apply(to_ts)
df["Eligible"] = df["Eligible"].apply(to_ts)
df["EndRaw"] = df["End"].apply(to_ts)  # sacct End; df["End"] is recomputed below
df["ElapsedRaw"] = df["ElapsedRaw"].apply(lambda x : int(x))
df["End"] = df["Start"] + df["ElapsedRaw"]
df['NGPUS'] = df["ReqTRES"].apply(lambda x : int(x.split("gpu=")[1].split(",")[0]) if "gpu" in x else 0)
df['ReqMem'] = df["ReqMem"].apply(lambda x : int(x.replace("M", "")) / 1024)

#----------------------------------------
# GPU type split (L4 / B200 / Other)
#----------------------------------------
# Type = allocated type, else requested type, else the partition's GPU type.
# Jobs that ask for "any GPU" only get a type once allocated, so pending jobs
# rely on the partition (each GPU partition has a single GPU model).
GPU_TYPE_BUCKETS = {"l4": "L4", "b200": "B200"}
gpu_type_observables = {"L4": "NGPUS_L4", "B200": "NGPUS_B200", "Other": "NGPUS_OTHER"}

def partition_gpu_types():
    out = subprocess.run(["/opt/slurm/bin/sinfo", "-h", "-o", "%P %G"],
                         capture_output=True, text=True).stdout
    types = {}
    for line in out.splitlines():
        part, _, gres = line.partition(" ")
        for m in re.finditer(r"gpu:([^:(,]+):", gres):
            types.setdefault(part.rstrip("*"), set()).add(m.group(1))
    return {p: t.pop() for p, t in types.items() if len(t) == 1}

partition_gpu = partition_gpu_types()

def gpu_type(*tres, partition=""):
    for s in tres:
        m = re.search(r"gres/gpu:([^=,]+)=", str(s))
        if m:
            return GPU_TYPE_BUCKETS.get(m.group(1), "Other")
    types = {partition_gpu.get(p) for p in str(partition).split(",")}
    return GPU_TYPE_BUCKETS.get(types.pop(), "Other") if len(types) == 1 else "Other"

has_gpu = df["NGPUS"] > 0
df["GPUTYPE"] = ""
df.loc[has_gpu, "GPUTYPE"] = [gpu_type(a, r, partition=p) for a, r, p in
                              zip(df.loc[has_gpu, "AllocTRES"], df.loc[has_gpu, "ReqTRES"], df.loc[has_gpu, "Partition"])]
for bucket, col in gpu_type_observables.items():
    df[col] = df["NGPUS"].where(df["GPUTYPE"] == bucket, 0)
all_observables = observables + list(gpu_type_observables.values())

def mystate(x):
    if "PENDING" in x: return 0
    if "RUNNING" in x: return 1
    if "COMPLETED" in x: return 2
    if "TIMEOUT" in x: return 3
    if "CANCELLED" in x: return 4
    if "FAILED" in x: return 5
is_pending = df['State'].str.startswith("PENDING")
df['State'] = df['State'].apply(mystate)

#----------------------------------------
# Pending (queued) jobs
#----------------------------------------
# A job's queue wait runs from Eligible (so --begin and dependency waits don't
# count) until Start. Jobs still pending wait until now; jobs cancelled while
# pending wait until their End. A never-started array record "123_[0-99%5]"
# stands for every task of it still pending, so it is weighted by task count.
# Pending jobs have NCPUS=0 in sacct, so requested CPUs (ReqCPUS) are used.
def array_tasks(jobid):
    m = re.search(r"_\[([^\]]*)\]$", str(jobid))
    if not m:
        return 1
    n = 0
    for part in m.group(1).split("%")[0].split(","):
        rng, _, step = part.partition(":")
        lo, _, hi = rng.partition("-")
        try:
            n += len(range(int(lo), int(hi or lo) + 1, int(step or 1)))
        except ValueError:
            n += 1
    return max(n, 1)

now_ts = int(time.time())
never_started = (df["Start"] == 0).to_numpy()
pend_stop = np.where(~never_started, df["Start"], np.where(is_pending, now_ts, df["EndRaw"]))
pmask = ((df["Eligible"] > 0) & (pend_stop > df["Eligible"]) & (pend_stop > from_time)).to_numpy()
gpu_cols = ["NGPUS"] + list(gpu_type_observables.values())
pdf = df.loc[pmask, ["User", "JobID", "ReqCPUS", "ReqMem"] + gpu_cols].copy()
pdf["a"] = df.loc[pmask, "Eligible"]
pdf["b"] = pend_stop[pmask]
mult = np.where(never_started[pmask], pdf["JobID"].apply(array_tasks), 1)
pdf["NCPUS"] = pdf["ReqCPUS"] * mult
for col in gpu_cols:
    pdf[col] = pdf[col] * mult
pdf["ReqMem"] = pdf["ReqMem"] * mult
pdf["NNodes"] = mult  # "# of Jobs"

def _cum_at(x, w, t, ramp):
    # Sum over i with x_i <= t of w_i (ramp=False) or w_i * (t - x_i) (ramp=True).
    order = np.argsort(x)
    xs, ws = x[order], w[order]
    cw = np.concatenate([[0.0], np.cumsum(ws)])
    k = np.searchsorted(xs, t, side="right")
    if not ramp:
        return cw[k]
    cwx = np.concatenate([[0.0], np.cumsum(ws * xs)])
    return t * cw[k] - cwx[k]

def interval_series(a, b, w, t, averaged):
    # Sum of weights w_i over intervals [a_i, b_i): the value at each time t
    # (averaged=False), or its average over each bin [t_k, t_k+1) (averaged=True).
    # Times are shifted to from_time to keep the float arithmetic exact.
    a = (np.asarray(a) - from_time).astype(float)
    b = (np.asarray(b) - from_time).astype(float)
    w = np.asarray(w).astype(float)
    t = (np.asarray(t) - from_time).astype(float)
    if not averaged:
        return _cum_at(a, w, t, False) - _cum_at(b, w, t, False)
    # difference of the running integral at the bin edges
    g = _cum_at(a, w, t, True) - _cum_at(b, w, t, True)
    return np.diff(g) / time_res

def per_user_series(frame, a_col, b_col, user_list, t, averaged):
    out = {}
    for user in user_list:
        sub = frame[frame["User"] == user]
        out[user] = {o: interval_series(sub[a_col], sub[b_col], sub[o], t, averaged) for o in all_observables}
    return out

pending_users = pdf["User"].value_counts().index.tolist()
bin_edges = [from_time + time_res * k for k in range(nbins + 1)]
pend_snapshot_res = 300  # 5 min samples for the pending snapshot view
pend_snapshot_from = (to_time - 3600 * 24 * 3) // pend_snapshot_res * pend_snapshot_res
pend_snapshot_times = list(range(pend_snapshot_from, now_ts + 1, pend_snapshot_res))
d_pending = per_user_series(pdf, "a", "b", pending_users, bin_edges, True)
d_pending_snapshot = per_user_series(pdf, "a", "b", pending_users, pend_snapshot_times, False)

# Live view of the queue right now, with Slurm's pending reasons.
def mem_gb(s):
    m = re.match(r"([\d.]+)([KMGT]?)", s)
    if not m:
        return 0.0
    return float(m.group(1)) * {"K": 1 / 1024**2, "M": 1 / 1024, "G": 1, "T": 1024, "": 1 / 1024}[m.group(2)]

pending_now = {}
sq = subprocess.run(["/opt/slurm/bin/squeue", "-r", "-t", "PD", "-q", qos, "-h",
                     "-O", "UserName:64,tres-alloc:400,Partition:400,Reason:64"],
                    capture_output=True, text=True).stdout
for line in sq.splitlines():
    parts = line.split()
    if len(parts) < 4:
        continue
    user, tres, partition, reason = parts[:4]
    t = dict(kv.split("=", 1) for kv in tres.split(",") if "=" in kv)
    gpus = int(t.get("gres/gpu") or sum(int(v) for k, v in t.items() if k.startswith("gres/gpu:")))
    u = pending_now.setdefault(user, {"jobs": 0, "NCPUS": 0, "NGPUS": 0, "MEMORY": 0.0, "reasons": {},
                                      "gpu_types": {}})
    u["jobs"] += 1
    u["NCPUS"] += int(t.get("cpu", 0))
    u["NGPUS"] += gpus
    if gpus:
        gt = gpu_type(tres, partition=partition)
        u["gpu_types"][gt] = u["gpu_types"].get(gt, 0) + gpus
    u["MEMORY"] += mem_gb(t.get("mem", "0"))
    u["reasons"][reason] = u["reasons"].get(reason, 0) + 1
for u in pending_now.values():
    u["MEMORY"] = round(u["MEMORY"], 1)

# Following are the data to obtain
selected_columns = [
        "User",
        "Submit",
        "NCPUS",
        "NGPUS",
        "NNodes",
        "ReqMem",
        "State",
        "Priority",
        "Start",
        "End",
        "JobIDRaw",
        "NodeList",
        "Reason",
        ] + list(gpu_type_observables.values())

# Subselect the columns
df = df[selected_columns]

# Get all users within this time period
users = df["User"].value_counts().index.tolist()

# Running usage per user, averaged over each time bin: each job counts for the
# part of [Start, End) that overlaps the bin.
d = per_user_series(df, "Start", "End", users, bin_edges, True)

# ---- Event-driven snapshot computation ----
# Collect all unique event timestamps (job starts + ends) within the time window
events = set()
events.update(df["Start"].tolist())
events.update(df["End"].tolist())
snapshot_from_time = to_time - 3600 * 24 * 3  # last 3 days only
snapshot_time_idxs = sorted([t for t in events if snapshot_from_time <= t <= to_time])

# At each event timestamp, what's running per user (Start <= t < End)
d_snapshot = per_user_series(df, "Start", "End", users, snapshot_time_idxs, False)

dfs = []
for observable in observables:
    data = {}
    for user in users:
        data[user] = d[user][observable]

    df = pd.DataFrame(data, index = time_idxs)
    df.index = pd.to_datetime(df.index, unit='s')
    df['Total'] = df[users].sum(axis=1)
    max_value = df[['Total'] + users].max().max() if len(users) > 0 else 0
    threshold_value = thresholds[observable]

    # Create the stacked area plot
    plt.figure(figsize=(10, 6))
    if len(users) > 0:
        stack_data = [df[col] for col in users]
        plt.stackplot(df.index, stack_data, labels=users)
    # plt.plot(df.index, df['Total'], color='black', linewidth=2, label='Total')
    if threshold_value != 0:
        plt.title(f'{nicenames[observable]} Usage Over Time (MAX: {threshold_value})')
    else:
        plt.title(f'{nicenames[observable]} Usage Over Time')
    plt.xlabel('Time')
    plt.ylabel(f'{nicenames[observable]} Usage')
    plt.grid(True)
    plt.legend(loc='upper left')

    # Rotate x-axis labels for readability (optional)
    plt.xticks(rotation=45)

    # Add a threshold line of maximum usage
    if threshold_value != 0:
        plt.axhline(y=threshold_value, color='red', linestyle='--', label=f'Threshold ({threshold_value})')

    plt.tight_layout()

    # Set the max value
    plt.ylim(0, 1.7 * max_value)

    # Show or save the plot
    plt.yscale('linear')
    plt.savefig(f"{shortnames[observable]}_{qos}.png")
    plt.savefig(f"{shortnames[observable]}_{qos}.pdf")

# Export JSON data for interactive dashboard
json_time_idxs = [
    datetime.datetime.fromtimestamp(t, tz=eastern_timezone).strftime('%Y-%m-%dT%H:%M:%S%z')
    for t in time_idxs
]

def compact(values):
    # 2 decimals; whole numbers as ints ("3" not "3.0") to keep the JSON small
    out = []
    for v in values:
        v = round(float(v), 2)
        out.append(int(v) if v.is_integer() else v)
    return out

def json_series(series, user_list):
    # The four main observables list every user (as before); the per-GPU-type
    # series only list users with nonzero values (the dashboard treats a
    # missing user as all zeros).
    out = {}
    for o in all_observables:
        key = shortnames.get(o, o)
        out[key] = {}
        for user in user_list:
            vals = series[user][o]
            if o in observables or np.any(vals):
                out[key][user] = compact(vals)
    return out

#----------------------------------------
# Stable per-user colors
#----------------------------------------
# The dashboard has 8 categorical color slots. The most significant users get
# one and keep it across runs (user_colors.json); everyone else is drawn as
# "Other". Significance = a user's largest share of any 30-day running or
# pending total, or of all-time monthly GPU-hours, so a heavy GPU user with
# few CPUs still gets a color. Slots only change hands when a newcomer enters
# the top 8 and none is free: the weakest holder gives theirs up.
# (Delete user_colors.json to reassign everything from scratch.)
N_COLOR_SLOTS = 8

def usage_shares(series):
    out = {}
    for o in observables:
        tot = {u: float(np.sum(series[u][o])) for u in series}
        s = sum(tot.values())
        for u, v in tot.items():
            if s > 0:
                out[u] = max(out.get(u, 0.0), v / s)
    return out

score = {}
gpu_hours_alltime = {}
if os.path.exists("gpu_usage/gpu_monthly_by_user.csv"):
    with open("gpu_usage/gpu_monthly_by_user.csv") as f:
        for r in csv.DictReader(f):
            if r["qos"] == qos:
                gpu_hours_alltime[r["user"]] = gpu_hours_alltime.get(r["user"], 0.0) + float(r["gpu_hours"] or 0)
gh_total = sum(gpu_hours_alltime.values())
monthly_share = {u: v / gh_total for u, v in gpu_hours_alltime.items()} if gh_total > 0 else {}
for part in (usage_shares(d), usage_shares(d_pending), monthly_share):
    for u, v in part.items():
        score[u] = max(score.get(u, 0.0), v)

try:
    with open("user_colors.json") as f:
        all_colors = json.load(f)
except (OSError, ValueError):
    all_colors = {}
user_colors = {u: s for u, s in all_colors.get(qos, {}).items()
               if score.get(u, 0) > 0 and isinstance(s, int) and 0 <= s < N_COLOR_SLOTS}
ranked = sorted((u for u in score if score[u] > 0), key=lambda u: (-score[u], u))
newcomers = [u for u in ranked[:N_COLOR_SLOTS] if u not in user_colors]
free_slots = lambda: sorted(set(range(N_COLOR_SLOTS)) - set(user_colors.values()))
# Pass 1: a newcomer whose slot in another QoS tab is free here takes it, so
# the same person tends to keep one color across tabs too.
for u in newcomers:
    pref = [m[u] for q, m in sorted(all_colors.items()) if q != qos and m.get(u) in free_slots()]
    if pref:
        user_colors[u] = pref[0]
# Pass 2: the rest take the lowest free slot, or the weakest holder's.
for u in newcomers:
    if u in user_colors:
        continue
    free = free_slots()
    if free:
        user_colors[u] = free[0]
    else:
        weakest = min(user_colors, key=lambda x: (score.get(x, 0), x))
        user_colors[u] = user_colors.pop(weakest)
all_colors[qos] = user_colors
with open("user_colors.json", "w") as f:
    json.dump(all_colors, f, indent=1, sort_keys=True)

fmt_ts = lambda t: datetime.datetime.fromtimestamp(t, tz=eastern_timezone).strftime('%Y-%m-%dT%H:%M:%S%z')
json_observables = json_series(d, users)
json_snapshot_time_idxs = [fmt_ts(t) for t in snapshot_time_idxs]
json_observables_snapshot = json_series(d_snapshot, users)
json_observables_pending = json_series(d_pending, pending_users)
json_observables_snapshot_pending = json_series(d_pending_snapshot, pending_users)

json_data = {
    "metadata": {
        "qos": qos,
        "last_updated": datetime.datetime.now(eastern_timezone).strftime('%Y-%m-%dT%H:%M:%S%z'),
        "time_resolution_seconds": time_res,
        "pending_snapshot_resolution_seconds": pend_snapshot_res,
    },
    "observables_pending": json_observables_pending,
    "time_idxs_snapshot_pending": [fmt_ts(t) for t in pend_snapshot_times],
    "observables_snapshot_pending": json_observables_snapshot_pending,
    "pending_now": pending_now,
    "time_idxs": json_time_idxs,
    "time_idxs_snapshot": json_snapshot_time_idxs,
    "users": users,
    "observables": json_observables,
    "observables_snapshot": json_observables_snapshot,
    "thresholds": {shortnames[k]: v for k, v in thresholds.items()},
    "nice_names": {shortnames[k]: v for k, v in nicenames.items()},
    "gpu_types": gpu_type_observables,
    "user_colors": user_colors,
}

with open(f"data_{qos}.json", "w") as f:
    json.dump(json_data, f, separators=(",", ":"))
