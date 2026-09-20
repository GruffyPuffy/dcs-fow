#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
container=dcs-fow-server
generator="$repo_dir/missions/build_mission.py"
mission_lua="$repo_dir/missions/fow_bridge_generic.lua"
catalog="$repo_dir/missions/spawn_catalog.json"
unit_catalog="$repo_dir/missions/unit_catalog.json"
air_catalog="$repo_dir/missions/air_trial.json"
output="$repo_dir/missions/fow.miz"
container_venv=/tmp/dcs-fow-pydcs-venv
container_generator=/tmp/dcs-fow-build-mission.py
container_lua=/tmp/fow_bridge_generic.lua
container_catalog=/tmp/spawn_catalog.json
container_unit_catalog=/tmp/unit_catalog.json
container_air_catalog=/tmp/air_trial.json
container_air_templates=/tmp/air_templates.json
container_output=/tmp/dcs-fow-built.miz

if [[ "$#" -ne 0 ]]; then
  echo "Usage: ./scripts/build-mission.sh" >&2
  exit 2
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

docker cp "$generator" "$container:$container_generator"
docker cp "$mission_lua" "$container:$container_lua"
docker cp "$catalog" "$container:$container_catalog"
docker cp "$unit_catalog" "$container:$container_unit_catalog"
docker cp "$air_catalog" "$container:$container_air_catalog"
docker exec "$container" "$container_venv/bin/python" "$container_generator" "$container_output" 2>&1 | tail -n 5

temporary="$(mktemp "$repo_dir/missions/.fow-build.XXXXXX.miz")"
trap 'rm -f "$temporary"' EXIT
docker cp "$container:$container_output" "$temporary"
docker cp "$container:$container_air_templates" "$repo_dir/missions/air_templates.json"

python3 - "$temporary" <<'PY'
import re
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    mission = archive.read("mission").decode("utf-8")
    warehouses = archive.read("warehouses").decode("utf-8")
    batumi = re.search(r'\[22\]=\s*\{.{0,400}?\["coalition"\]="([A-Z]+)"', warehouses, re.S)
    if mission.count('["skill"]="Client"') != 3 or not batumi or batumi.group(1) != "BLUE":
        raise SystemExit("Mission validation failed: expected three Client slots and Blue Batumi")
    for marker in ('FoW Blue Ground', 'FoW Red Ground', 'FOW_BRIDGE_READY', 'FoWSpawnCatalog', 'FoWAirCatalog'):
        if marker not in mission:
            raise SystemExit(f"Mission validation failed: missing {marker}")
PY

chmod 644 "$temporary"
mv -f "$temporary" "$output"
trap - EXIT
echo "Built and validated: $output"
echo "To deploy it, run: ./scripts/dcs.sh missions"
