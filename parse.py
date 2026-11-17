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
pdf = df.loc[pmask, ["User", "JobID", "ReqCPUS", "NGPUS", "ReqMem"]].copy()
pdf["a"] = df.loc[pmask, "Eligible"]
pdf["b"] = pend_stop[pmask]
mult = np.where(never_started[pmask], pdf["JobID"].apply(array_tasks), 1)
pdf["NCPUS"] = pdf["ReqCPUS"] * mult
pdf["NGPUS"] = pdf["NGPUS"] * mult
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

def pending_series(sub, observable, t, averaged):
    # Times are shifted to from_time to keep the float arithmetic exact.
    a = (sub["a"].to_numpy() - from_time).astype(float)
    b = (sub["b"].to_numpy() - from_time).astype(float)
    w = sub[observable].to_numpy().astype(float)
    t = (np.asarray(t) - from_time).astype(float)
    if not averaged:  # instantaneous value at each t
        return _cum_at(a, w, t, False) - _cum_at(b, w, t, False)
    # average over [t_k, t_k+1): difference of the running integral at the edges
    g = _cum_at(a, w, t, True) - _cum_at(b, w, t, True)
    return np.diff(g) / time_res

pending_users = pdf["User"].value_counts().index.tolist()
bin_edges = [from_time + time_res * k for k in range(nbins + 1)]
pend_snapshot_res = 300  # 5 min samples for the pending snapshot view
pend_snapshot_from = (to_time - 3600 * 24 * 3) // pend_snapshot_res * pend_snapshot_res
pend_snapshot_times = list(range(pend_snapshot_from, now_ts + 1, pend_snapshot_res))
d_pending, d_pending_snapshot = {}, {}
for user in pending_users:
    sub = pdf[pdf["User"] == user]
    d_pending[user] = {o: pending_series(sub, o, bin_edges, True) for o in observables}
    d_pending_snapshot[user] = {o: pending_series(sub, o, pend_snapshot_times, False) for o in observables}

# Live view of the queue right now, with Slurm's pending reasons.
def mem_gb(s):
    m = re.match(r"([\d.]+)([KMGT]?)", s)
    if not m:
        return 0.0
    return float(m.group(1)) * {"K": 1 / 1024**2, "M": 1 / 1024, "G": 1, "T": 1024, "": 1 / 1024}[m.group(2)]

pending_now = {}
sq = subprocess.run(["/opt/slurm/bin/squeue", "-r", "-t", "PD", "-q", qos, "-h",
                     "-O", "UserName:64,tres-alloc:400,Reason:64"],
                    capture_output=True, text=True).stdout
for line in sq.splitlines():
    parts = line.split()
    if len(parts) < 3:
        continue
    user, tres, reason = parts[0], parts[1], parts[2]
    t = dict(kv.split("=", 1) for kv in tres.split(",") if "=" in kv)
    gpus = t.get("gres/gpu") or sum(int(v) for k, v in t.items() if k.startswith("gres/gpu:"))
    u = pending_now.setdefault(user, {"jobs": 0, "NCPUS": 0, "NGPUS": 0, "MEMORY": 0.0, "reasons": {}})
    u["jobs"] += 1
    u["NCPUS"] += int(t.get("cpu", 0))
    u["NGPUS"] += int(gpus)
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
        ]

# Subselect the columns
df = df[selected_columns]

# Get all users within this time period
users = df["User"].value_counts().index.tolist()

# Loop over time bin boundaries
for i in range(nbins):

    # If first bin create list
    if i == 0:
        for user in users:
            d[user] = {}
            for observable in observables:
                d[user][observable] = [0] * nbins

    # Obtain time bin boundary
    bt = from_time + time_res * (i)
    et = from_time + time_res * (i + 1)

    # Subselect data within time bin boundary
    df_timebin = df.loc[(df.Start < et) & (df.End > bt)]

    # Compute each length of job in the given time bin (some jobs may have started in this bin, some may have ended in this bin)
    df_timebin["WithinTimeBinEnd"] = df_timebin["End"].apply(lambda x : x if x < et else et)
    df_timebin["WithinTimeBinStart"] = df_timebin["Start"].apply(lambda x : x if x > bt else bt)
    df_timebin["WithinTimeBinElapsed"] = df_timebin["WithinTimeBinEnd"] - df_timebin["WithinTimeBinStart"]

    # Obtain active users with jobs within time bin boundary
    active_users = df_timebin["User"].value_counts().index.tolist()

    # Get usages for each user
    for active_user in active_users:
        df_timebin_user = df_timebin[df_timebin["User"] == active_user]
        for observable in observables:
            res = df_timebin_user[observable] * df_timebin_user["WithinTimeBinElapsed"] / time_res
            user_sum = res.sum()
            d[active_user][observable][i] = user_sum

# ---- Event-driven snapshot computation ----
# Collect all unique event timestamps (job starts + ends) within the time window
events = set()
events.update(df["Start"].tolist())
events.update(df["End"].tolist())
snapshot_from_time = to_time - 3600 * 24 * 3  # last 3 days only
snapshot_time_idxs = sorted([t for t in events if snapshot_from_time <= t <= to_time])

# Initialize snapshot data structure
d_snapshot = {}
for user in users:
    d_snapshot[user] = {}
    for observable in observables:
        d_snapshot[user][observable] = [0] * len(snapshot_time_idxs)

# At each event timestamp, snapshot what's running per user
for i, t in enumerate(snapshot_time_idxs):
    df_snapshot = df.loc[(df.Start <= t) & (df.End > t)]
    active_users = df_snapshot["User"].unique()
    for active_user in active_users:
        if active_user not in d_snapshot:
            continue
        df_user = df_snapshot[df_snapshot["User"] == active_user]
        for observable in observables:
            d_snapshot[active_user][observable][i] = df_user[observable].sum()

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

json_observables = {}
for observable in observables:
    json_observables[shortnames[observable]] = {}
    for user in users:
        json_observables[shortnames[observable]][user] = [round(v, 2) for v in d[user][observable]]

# Build snapshot JSON arrays
json_snapshot_time_idxs = [
    datetime.datetime.fromtimestamp(t, tz=eastern_timezone).strftime('%Y-%m-%dT%H:%M:%S%z')
    for t in snapshot_time_idxs
]

json_observables_snapshot = {}
for observable in observables:
    json_observables_snapshot[shortnames[observable]] = {}
    for user in users:
        json_observables_snapshot[shortnames[observable]][user] = [round(float(v), 2) for v in d_snapshot[user][observable]]

fmt_ts = lambda t: datetime.datetime.fromtimestamp(t, tz=eastern_timezone).strftime('%Y-%m-%dT%H:%M:%S%z')
json_observables_pending = {shortnames[o]: {} for o in observables}
json_observables_snapshot_pending = {shortnames[o]: {} for o in observables}
for user in pending_users:
    for o in observables:
        json_observables_pending[shortnames[o]][user] = [round(float(v), 2) for v in d_pending[user][o]]
        json_observables_snapshot_pending[shortnames[o]][user] = [round(float(v), 2) for v in d_pending_snapshot[user][o]]

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
}

with open(f"data_{qos}.json", "w") as f:
    json.dump(json_data, f)
