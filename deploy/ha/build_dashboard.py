"""Build the bird camera dashboard (Lovelace storage JSON) from:
  * deploy/ha/dashboard_sections.yaml (latest visitor, last bird, today)
  * the "Camera health" section of ha-vicohome-bridge's dashboard

Usage: UNSUB_PUBLIC_URL=http://your-server:8095 UNSUB_CAMERA=my_bird_cam python3 deploy/ha/build_dashboard.py \\
         <ha-vicohome-bridge>/dashboard/<your dashboard>.yaml out.json
"""

import json
import os
import sys
from pathlib import Path

import yaml

here = Path(__file__).parent
bridge = yaml.safe_load(open(sys.argv[1]))
url = (os.environ.get("UNSUB_PUBLIC_URL") or os.environ["WBS_PUBLIC_URL"]).rstrip("/")   # WBS_: the old name
text = (here / "dashboard_sections.yaml").read_text()
ours = yaml.safe_load(text.replace("__UNSUB_PUBLIC_URL__", url).replace("__CAMERA__", (os.environ.get("UNSUB_CAMERA") or os.environ["WBS_CAMERA"])))
view = bridge["views"][0]
health = [s for s in view["sections"] if s["cards"][0].get("heading") == "Camera health"]
assert health, "no Camera health section in the bridge dashboard"
view["sections"] = ours + health
view["max_columns"] = 4
out = {"version": 1, "minor_version": 1, "key": "lovelace.dashboard_vicohome", "data": {"config": bridge}}
Path(sys.argv[2]).write_text(json.dumps(out))
print("sections:", [s["cards"][0].get("heading") for s in view["sections"]])
