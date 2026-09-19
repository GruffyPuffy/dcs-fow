#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_dir="$repo_dir/deploy/dcs"
env_file="$compose_dir/.env"
data_root=/data/dcs-fow
mission_source="$repo_dir/missions"
mission_target="$data_root/config/.wine/drive_c/users/abc/Saved Games/DCS.dcs_serverrelease/Missions"
expected_uuid=d15d08d9-8da9-4f2a-8c6d-530907121096

usage() {
  cat <<'EOF'
Usage: ./scripts/dcs.sh <command>

  install   Prepare configuration and start the container (first installation)
  start     Start the container and apply Compose changes
  stop      Stop the container without deleting its data
  status    Show container status
  logs      Follow recent container logs (Ctrl+C to exit)
  missions  Copy the repo FoW mission into DCS Saved Games
  config    Prepare configuration and validate Compose without starting
  help      Show this help
EOF
}

compose() {
  docker compose --project-directory "$compose_dir" -f "$compose_dir/docker-compose.yml" "$@"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "Docker Engine and the Compose plugin are required. See deploy/dcs/README.md." >&2
    exit 1
  fi
}

require_data_disk() {
  if [[ "$(findmnt -n -o UUID --target /data 2>/dev/null || true)" != "$expected_uuid" ]]; then
    echo "/data must be the expected data-disk mount before continuing." >&2
    exit 1
  fi
  if [[ ! -w /data ]]; then
    echo "/data is not writable by $(id -un). Check its ownership on the host." >&2
    exit 1
  fi
}

prepare_env() {
  python3 - "$env_file" "$(id -u)" "$(id -g)" <<'PY'
import os
import secrets
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
uid, gid = sys.argv[2:]
old = path.read_text() if path.exists() else ""
lines = old.splitlines()
values = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines if "=" in line}
password = values.get("WEBTOP_PASSWORD", "")
generated = not password or password == "REPLACE_WITH_A_LONG_UNIQUE_PASSWORD"
if generated:
    password = secrets.token_urlsafe(24)

replacements = {"PUID": uid, "PGID": gid, "WEBTOP_PASSWORD": password}
seen = set()
updated = []
for line in lines:
    key = line.split("=", 1)[0]
    if key in replacements:
        if key not in seen:
            updated.append(f"{key}={replacements[key]}")
            seen.add(key)
    else:
        updated.append(line)
for key, value in replacements.items():
    if key not in seen:
        updated.append(f"{key}={value}")
new = "\n".join(updated) + "\n"
if new != old:
    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(new)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
else:
    path.chmod(0o600)
if generated:
    print(f"Generated a Webtop password in {path}; keep this file private.")
PY
}

prepare() {
  require_data_disk
  require_docker
  prepare_env
  mkdir -p "$data_root/config"
  if [[ ! -w "$data_root/config" ]]; then
    echo "$data_root/config is not writable by $(id -un)." >&2
    exit 1
  fi
  compose config --quiet
}

deploy_missions() {
  require_data_disk
  mkdir -p "$mission_target"
  if [[ ! -w "$mission_target" ]]; then
    echo "$mission_target is not writable by $(id -un)." >&2
    exit 1
  fi
  local source="$mission_source/fow.miz"
  local destination="$mission_target/fow.miz"
  local temporary
  if [[ ! -f "$source" ]]; then
    echo "Missing repo mission: $source" >&2
    exit 1
  fi
  if [[ -f "$destination" ]] && cmp -s "$source" "$destination"; then
    echo "Already current: fow.miz"
    return
  fi
  temporary="$(mktemp "$mission_target/.fow-mission.XXXXXX")"
  install -m 644 "$source" "$temporary"
  mv -f "$temporary" "$destination"
  echo "Deployed: $destination"
}

command="${1:-help}"
if [[ "$#" -gt 1 ]]; then
  usage >&2
  exit 2
fi

case "$command" in
  help|-h|--help)
    usage
    ;;
  config)
    prepare
    echo "Configuration valid. Persistent DCS data: $data_root/config"
    ;;
  install|start)
    prepare
    deploy_missions
    compose up -d
    echo "Container running. Follow progress with: ./scripts/dcs.sh logs"
    ;;
  missions)
    deploy_missions
    ;;
  stop)
    require_docker
    compose stop
    ;;
  status)
    require_docker
    compose ps
    ;;
  logs)
    require_docker
    compose logs -f --tail=100
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
