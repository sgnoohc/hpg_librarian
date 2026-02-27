# HiPerGator Librarian

Automated Slurm resource monitoring for HiPerGator QoS groups.
Generates interactive dashboards showing CPU, GPU, memory, and job usage per user over time.

**Live dashboard:** [https://sgnoohc.github.io/hpg_librarian/](https://sgnoohc.github.io/hpg_librarian/)

## What It Does

- Queries `sacct` every 10 minutes for resource usage across all users in a QoS
- Bins usage into 1-hour intervals over a 30-day rolling window
- Generates static PNG/PDF plots and JSON data files
- Deploys an interactive Plotly.js dashboard to GitHub Pages and/or a web server
- Includes a watchdog that auto-recovers stuck scrontab jobs

## Dashboard Features

- Stacked area charts: NCPUS, NGPUS, Memory, Jobs in a 2x2 grid
- Hover for per-user values at any timestamp
- Click legend entries to toggle users on/off
- Zoom/pan with built-in Plotly toolbar
- Tabs to switch between QoS groups (e.g. avery, avery-b)
- Time range presets (6h, 12h, 24h, 3d, 7d, 14d, 30d) and custom date picker
- Current usage table (last time bin) and total usage table (CPU-hours, GPU-hours, etc.)
- Dark mode (persisted in browser)
- Auto-refreshes data every 5 minutes

## Prerequisites

- HiPerGator account with access to `sacct` and `scrontab`
- `module load python3` (provides Python 3.10 with pandas, matplotlib, pytz)
- `module load git` (for GitHub Pages deployment)
- SSH key configured for your web server (if using SCP deployment)

No `pip install` required. All Python dependencies are included in the `python3` module.

## Setup Guide

### 1. Clone the repo

```bash
cd ~
git clone git@github.com:YOUR_USERNAME/hpg_librarian.git librarian
cd librarian
```

### 2. Configure your QoS

Edit `parse.py` and update the following to match your group's QoS:

```python
qos = "avery"  # line 14: default QoS name

if len(sys.argv) > 1:
    qos = "avery-b"  # line 17: secondary QoS name (burst)
```

Update the thresholds to match your group's allocation limits:

```python
thresholds = {
    "NCPUS" : 430 if qos == "avery" else 3870,
    "NGPUS" : 39 if qos == "avery" else 0,
    "ReqMem" : 3359 if qos == "avery" else 30234,
    "NNodes": 0,
}
```

### 3. Configure deployment targets

Edit `run.sh` and update the SCP destinations to your web server:

```bash
scp *_avery.{pdf,png} YOUR_SERVER:~/public_html/hpg/usage/
scp *_avery-b.{pdf,png} YOUR_SERVER:~/public_html/hpg/usage_burst/
scp data_avery.json data_avery-b.json YOUR_SERVER:~/public_html/hpg/usage/
scp dashboard/index.html YOUR_SERVER:~/public_html/hpg/usage/
```

If you only want GitHub Pages (no SCP), you can remove/comment out the SCP lines.

### 4. Configure GitHub Pages

Edit `dashboard/index.html` and update the `DATA_FILES` object if you changed the QoS names:

```javascript
const DATA_FILES = {
    'your-qos': 'data_your-qos.json',
    'your-qos-burst': 'data_your-qos-burst.json',
};
```

Also update the tab buttons in the HTML to match:

```html
<button class="tab active" data-tab="your-qos">your-qos</button>
<button class="tab" data-tab="your-qos-burst">your-qos-burst</button>
```

### 5. Set up the gh-pages branch

```bash
# Create orphan gh-pages branch
cd /tmp
mkdir gh-pages-init && cd gh-pages-init
git init
git checkout --orphan gh-pages
echo "init" > .gitkeep
git add . && git commit -m "Initialize gh-pages"
git remote add origin git@github.com:YOUR_USERNAME/hpg_librarian.git
git push origin gh-pages
cd ~ && rm -rf /tmp/gh-pages-init
```

Then go to your GitHub repo **Settings > Pages** and set:
- Source: **Deploy from a branch**
- Branch: **gh-pages** / **(root)**

Your dashboard will be available at `https://YOUR_USERNAME.github.io/hpg_librarian/`

### 6. Test manually

```bash
cd ~/librarian
source /etc/profile.d/modules.sh
module load python3

# Generate data for both QoS
./parse.py
./parse.py 2

# Verify JSON output
python3 -c "import json; json.load(open('data_avery.json')); print('avery OK')"
python3 -c "import json; json.load(open('data_avery-b.json')); print('avery-b OK')"

# Deploy to GitHub Pages
module load git
./deploy_pages.sh

# Deploy to web server (if configured)
bash run.sh
```

### 7. Set up scrontab

```bash
scrontab -e
```

Add the following:

```
#SCRON --export=NONE
*/5 * * * * ~/librarian/watchdog.sh
#SCRON --export=NONE
*/10 * * * * ~/librarian/run.sh
```

This runs:
- **watchdog.sh** every 5 minutes: detects and recovers stuck scrontab jobs
- **run.sh** every 10 minutes: regenerates data and deploys

### 8. Verify scrontab is running

```bash
# Check jobs are queued
squeue --me

# Check logs after a cycle completes
tail ~/scron/logs/testlogs.txt
tail ~/scron/logs/watchdog.log
```

## Files

| File | Purpose |
|------|---------|
| `parse.py` | Queries sacct, bins resource usage, generates plots + JSON |
| `run.sh` | Main pipeline: runs parse, SCPs files, deploys to GitHub Pages |
| `deploy_pages.sh` | Pushes dashboard + JSON to gh-pages branch |
| `watchdog.sh` | Monitors and recovers stuck scrontab jobs |
| `dashboard/index.html` | Self-contained interactive Plotly.js dashboard |

## Tuning

| Parameter | Location | Default | Description |
|-----------|----------|---------|-------------|
| `time_res` | `parse.py:21` | `3600` (1 hour) | Bin size in seconds |
| `time_window` | `parse.py:22` | `3600 * 24 * 30` (30 days) | Rolling window |
| `REFRESH_MS` | `dashboard/index.html` | `5 * 60 * 1000` (5 min) | Dashboard auto-refresh interval |

Smaller `time_res` = more detail but spikier charts and larger JSON.
Larger `time_window` = more history but slower `sacct` queries.

## Troubleshooting

**Jobs stuck with "user env retrieval failed requeued held":**
This is a transient Slurm issue where compute nodes fail to source your shell environment (usually NFS hiccups). The watchdog handles this automatically by cancelling stuck jobs so scrontab can reschedule them.

**scrontab jobs not appearing in `squeue --me`:**
Check `scrontab -l` to verify your entries. Jobs only appear when their cron schedule triggers.

**Empty charts for a QoS:**
Normal if no jobs have run on that QoS in the past 30 days.

**`sacct` returns no data:**
Ensure you have the correct QoS name. Check with: `sacctmgr show qos format=name`
