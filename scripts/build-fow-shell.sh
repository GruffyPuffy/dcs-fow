#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
container=dcs-fow-server
build_root=/tmp/fow-shell-build
container_venv=/tmp/dcs-fow-pydcs-venv
container_output=/tmp/fow-shell-built.miz
scenario="$repo_dir/fow/scenarios/caucasus_pve.json"
output="$repo_dir/fow/missions/fow-shell.miz"

if [[ "$#" -ne 0 ]]; then
  echo "Usage: ./scripts/build-fow-shell.sh" >&2
  exit 2
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

docker exec "$container" /bin/bash -lc \
  'if [[ ! -x /tmp/dcs-fow-pydcs-venv/bin/python ]]; then
     python3 -m venv /tmp/dcs-fow-pydcs-venv
     /tmp/dcs-fow-pydcs-venv/bin/pip install --disable-pip-version-check pydcs==0.15.0
   fi'
docker exec "$container" rm -rf "$build_root"
docker exec "$container" mkdir -p \
  "$build_root/fow/dcs" "$build_root/fow/scenarios" "$build_root/missions"
docker cp "$repo_dir/fow/dcs/build_shell_mission.py" \
  "$container:$build_root/fow/dcs/build_shell_mission.py"
docker cp "$repo_dir/fow/dcs/slot_guard.lua" \
  "$container:$build_root/fow/dcs/slot_guard.lua"
docker cp "$scenario" "$container:$build_root/fow/scenarios/caucasus_pve.json"
docker cp "$repo_dir/missions/fow_bridge_generic.lua" \
  "$container:$build_root/missions/fow_bridge_generic.lua"
docker exec -w "$build_root" "$container" "$container_venv/bin/python" \
  fow/dcs/build_shell_mission.py --output "$container_output" 2>&1 | tail -n 5

mkdir -p "$(dirname "$output")"
temporary="$(mktemp "$(dirname "$output")/.fow-shell.XXXXXX.miz")"
trap 'rm -f "$temporary"' EXIT
docker cp "$container:$container_output" "$temporary"
python3 - "$temporary" "$scenario" <<'PY'
import json
import sys
import zipfile

with open(sys.argv[2]) as stream:
    scenario = json.load(stream)
with zipfile.ZipFile(sys.argv[1]) as archive:
    mission = archive.read("mission").decode("utf-8")
slots = scenario["mission"]["client_slots"]
if mission.count('["skill"]="Client"') != len(slots):
    raise SystemExit("Mission validation failed: unexpected Client slot count")
for marker in ["FOW_BRIDGE_READY", "set_slot_access", *[slot["name"] for slot in slots]]:
    if marker not in mission:
        raise SystemExit(f"Mission validation failed: missing {marker}")
if "BattleCommander" in mission:
    raise SystemExit("Mission validation failed: Foothold campaign runtime present")
PY

chmod 644 "$temporary"
mv -f "$temporary" "$output"
trap - EXIT
echo "Built and validated: $output"
echo "To deploy it, run: ./scripts/dcs.sh shell-mission"