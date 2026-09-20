#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" != 1 || ! "$1" =~ ^(PING|BLUE_HOLD|RED_HOLD|BLUE_MOVE_TEST)$ ]]; then
  echo "Usage: ./scripts/fow-command.sh PING|BLUE_HOLD|RED_HOLD|BLUE_MOVE_TEST" >&2
  exit 2
fi

directory='/data/dcs-fow/config/.wine/drive_c/users/abc/Saved Games/DCS.dcs_serverrelease/FoW'
if [[ ! -d "$directory" || ! -w "$directory" ]]; then
  echo "Bridge directory is missing or not writable. Run ./scripts/dcs.sh bridge." >&2
  exit 1
fi
if [[ -e "$directory/command.txt" ]]; then
  echo "A command is already waiting for DCS; retry after it is acknowledged." >&2
  exit 1
fi
temporary="$(mktemp "$directory/.command.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
printf '%s\n' "$1" > "$temporary"
mv "$temporary" "$directory/command.txt"
trap - EXIT
echo "Queued $1. Check $directory/ack.txt and the DCS log."
