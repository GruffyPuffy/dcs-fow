#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
container=dcs-fow-server
generator="$repo_dir/missions/build_mission.py"
mission_lua="$repo_dir/missions/fow_bridge_generic.lua"
catalog="$repo_dir/missions/spawn_catalog.json"
unit_catalog="$repo_dir/missions/unit_catalog.json"
air_catalog="$repo_dir/missions/air_trial.json"
scenario="${1:-$repo_dir/missions/scenarios/caucasus_default.json}"
output="$repo_dir/missions/fow.miz"
container_venv=/tmp/dcs-fow-pydcs-venv
container_generator=/tmp/dcs-fow-build-mission.py
container_lua=/tmp/fow_bridge_generic.lua
container_catalog=/tmp/spawn_catalog.json
container_unit_catalog=/tmp/unit_catalog.json
container_air_catalog=/tmp/air_trial.json
container_scenario=/tmp/fow_scenario.json
container_air_templates=/tmp/air_templates.json
container_airbase_catalog=/tmp/airbase_catalog.json
container_scenario_manifest=/tmp/scenario_manifest.json
container_output=/tmp/dcs-fow-built.miz

if [[ "$#" -gt 1 ]]; then
  echo "Usage: ./scripts/build-mission.sh [SCENARIO.json]" >&2
  exit 2
fi
if [[ "$scenario" != /* ]]; then
  scenario="$repo_dir/$scenario"
fi

if [[ ! -f "$generator" ]]; then
  echo "Missing mission generator: $generator" >&2
  exit 1
fi
if [[ ! -f "$mission_lua" ]]; then
  echo "Missing mission Lua: $mission_lua" >&2
  exit 1
fi
if [[ ! -f "$catalog" ]]; then
  echo "Missing spawn catalog: $catalog" >&2
  exit 1
fi
if [[ ! -f "$unit_catalog" ]]; then
  echo "Missing DCS unit catalog. Run: ./scripts/refresh-unit-catalog.py" >&2
  exit 1
fi
if [[ ! -f "$air_catalog" ]]; then
  echo "Missing air trial catalog: $air_catalog" >&2
  exit 1
fi
if [[ ! -f "$scenario" ]]; then
  echo "Missing scenario: $scenario" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Start the DCS container first: ./scripts/dcs.sh start" >&2
  exit 1
fi
if ! container_state="$(docker inspect -f '{{.State.Running}}' "$container" 2>&1)"; then
  echo "Cannot inspect $container: $container_state" >&2
  exit 1
fi
if [[ "$container_state" != true ]]; then
  echo "$container is not running. Start it with: ./scripts/dcs.sh start" >&2
  exit 1
fi

# The venv lives in the container's temporary filesystem. Recreate it after a
# container replacement; never install Python packages into the DCS Wine tree.
docker exec "$container" /bin/bash -lc \
  'if [[ ! -x /tmp/dcs-fow-pydcs-venv/bin/python ]]; then
     python3 -m venv /tmp/dcs-fow-pydcs-venv
     /tmp/dcs-fow-pydcs-venv/bin/pip install --disable-pip-version-check pydcs==0.15.0
   fi'

docker cp "$repo_dir/missions/air_catalog.py" "$container:/tmp/air_catalog.py"
docker cp "$generator" "$container:$container_generator"
docker cp "$mission_lua" "$container:$container_lua"
docker cp "$catalog" "$container:$container_catalog"
docker cp "$unit_catalog" "$container:$container_unit_catalog"
docker cp "$air_catalog" "$container:$container_air_catalog"
docker cp "$scenario" "$container:$container_scenario"
docker exec "$container" "$container_venv/bin/python" "$container_generator" "$container_scenario" "$container_output" 2>&1 | tail -n 5

temporary="$(mktemp "$repo_dir/missions/.fow-build.XXXXXX.miz")"
trap 'rm -f "$temporary"' EXIT
docker cp "$container:$container_output" "$temporary"
docker cp "$container:$container_air_templates" "$repo_dir/missions/air_templates.json"
docker cp "$container:$container_airbase_catalog" "$repo_dir/missions/airbase_catalog.json"
docker cp "$container:$container_scenario_manifest" "$repo_dir/missions/scenario_manifest.json"

python3 - "$temporary" "$scenario" <<'PY'
import json
import sys
import zipfile

with open(sys.argv[2]) as stream:
    scenario = json.load(stream)
with zipfile.ZipFile(sys.argv[1]) as archive:
    mission = archive.read("mission").decode("utf-8")
    if mission.count('["skill"]="Client"') != len(scenario["client_slots"]):
        raise SystemExit("Mission validation failed: unexpected Client slot count")
    markers = ["FOW_BRIDGE_READY", "FoWSpawnCatalog", "FoWAirCatalog"]
    markers += [slot["name"] for slot in scenario["client_slots"]]
    markers += [group["name"] for group in scenario["initial_groups"]]
    markers += [flight["name"] for flight in scenario.get("initial_flights", [])]
    markers += [flight["name"] for flight in scenario.get("alert_flights", [])]
    for marker in markers:
        if marker not in mission:
            raise SystemExit(f"Mission validation failed: missing {marker}")
PY

chmod 644 "$temporary"
mv -f "$temporary" "$output"
trap - EXIT
echo "Built and validated: $output"
echo "To deploy it, run: ./scripts/dcs.sh missions"
