import json
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd

LOG_FILE = "data.txt"
OUTPUT_PNG = "plot.png"

# Load data
data = pd.read_csv(LOG_FILE, names=["Time", "Value"])
data["Time"] = pd.to_datetime(data["Time"])

print(data["Time"])
print(data["Value"])

# Plot
plt.figure(figsize=(10, 5))
plt.plot(data["Time"], data["Value"], marker="o", linestyle="-")
plt.xlabel("Time")
plt.ylabel("N CPUs")
plt.title("Number of CPUs to be drained")
plt.xticks(rotation=0)
plt.grid(True)

# Save graph
plt.savefig(OUTPUT_PNG)
plt.close()

# Export JSON for interactive dashboard
data_filled = data.fillna(0)
drain_json = {
    "metadata": {
        "last_updated": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
    },
    "timestamps": data_filled["Time"].dt.strftime('%Y-%m-%dT%H:%M:%S').tolist(),
    "values": data_filled["Value"].tolist(),
}
with open("drain_data.json", "w") as f:
    json.dump(drain_json, f)
