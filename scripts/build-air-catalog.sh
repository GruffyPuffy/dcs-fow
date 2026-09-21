#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
container=dcs-fow-server
# Uses the same pinned pydcs environment as build-mission.sh, without a mission reload.
docker cp "$repo_dir/missions/air_catalog.py" "$container:/tmp/fow-air-catalog.py"
docker cp "$repo_dir/missions/air_trial.json" "$container:/tmp/fow-air-trial.json"
docker exec "$container" /tmp/dcs-fow-pydcs-venv/bin/python /tmp/fow-air-catalog.py /tmp/fow-air-trial.json /tmp/fow-air-templates.json
docker cp "$container:/tmp/fow-air-templates.json" "$repo_dir/missions/air_templates.json"
echo 'Updated server aircraft templates. No mission rebuild is needed.'
