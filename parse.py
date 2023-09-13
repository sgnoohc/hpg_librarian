#!/bin/env python3

import csv
import time
import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
import datetime
import math
import pytz

qos = "avery"

if len(sys.argv) > 1:
    qos = "avery-b"

#----------------------------------------
# Configuration
time_res = 600 # 10 minutes
time_window = 3600 * 24 * 5 # 5 days
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
thresholds = {
        "NCPUS" : 430 if qos == "avery" else 3870,
        "NGPUS" : 14 if qos == "avery" else 0,
        "ReqMem" : 3359 if qos == "avery" else 30234,
        "NNodes": 0,
        }
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
        ]

# Creating some colunm name to integer matching
cols = {}
for i, c in enumerate(column_headers):
    cols[c] = i

# Process the Slurm command and obtain the data
columns = ",".join(column_headers)
os.system(f"/opt/slurm/bin/sacct -a -S {from_date} -q {qos} --format=\"{columns}\" -P --noconvert > data.txt")

df = pd.read_csv("data.txt", sep="|")
df = df[~df.User.isna()] # Get rid of rows with user name NaN

df["Start"] = df["Start"].apply(lambda x : int(time.mktime(time.strptime(x, "%Y-%m-%dT%H:%M:%S"))) if x != "Unknown" else 0)
df["Submit"] = df["Submit"].apply(lambda x : int(time.mktime(time.strptime(x, "%Y-%m-%dT%H:%M:%S"))) if x != "Unknown" else 0)
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
df['State'] = df['State'].apply(mystate)

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

dfs = []
for observable in observables:
    data = {}
    for user in users:
        data[user] = d[user][observable]

    df = pd.DataFrame(data, index = time_idxs)
    df.index = pd.to_datetime(df.index, unit='s')
    df['Total'] = df[users].sum(axis=1)
    max_value = df[['Total'] + users].max().max()
    threshold_value = thresholds[observable]

    # Create the stacked area plot
    plt.figure(figsize=(10, 6))
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
