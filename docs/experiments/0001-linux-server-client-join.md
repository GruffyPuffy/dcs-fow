# Experiment 0001: Linux DCS server and Windows client join

Status: Passed for a basic mission, 2026-09-19.

## Goal

Host a Caucasus mission on Ubuntu 24.04 in the Aterfax Docker/Wine container and join it from a Windows DCS client over the LAN.

## Setup

- Host: Ubuntu 24.04.5, Intel i9-10900K, 31 GiB RAM.
- Persistent DCS files: `/data/dcs-fow/config/` on the ext4 data disk.
- Server: Aterfax container, game port TCP/UDP 10308, Webtop HTTPS 3001, saved DCS login and auto start.
- Mission: repo-owned `missions/fow.miz`, built with pydcs 0.15.0. One Blue F/A-18C Client slot each for air, Batumi runway and Batumi cold ramp starts.

## Result

The container installed and launched DCS. The Windows client connected, joined Blue and spawned in the air slot. Ground slots initially appeared but did not accept the player's callsign. The generated mission marked Batumi as `NEUTRAL` while the Hornets were Blue. After the generator set Batumi to `BLUE` and the mission was reloaded, the user confirmed ground spawning worked. The container also relaunched DCS automatically after a Compose restart.

This proves a basic server, mission deployment and multiplayer client path. It does not test the Lua bridge, AI orders, fog of war, LLMs, persistence across mission reloads or DCS update compatibility.

## Follow-up

- Record exact DCS and image versions, disk/RAM/CPU use, and startup time when operational measurements become relevant.
- Confirm unattended host reboot and mission auto start separately from the already tested container restart.
- Preserve the Blue airfield assignment in future pydcs changes. The [pydcs airport API](https://github.com/pydcs/dcs/blob/master/dcs/terrain/terrain.py) provides `set_blue()`; the [DCS mission editor manual](https://www.digitalcombatsimulator.com/upload/iblock/ed6/87v22jwd1xh51i3rgki944xsf503istq/DCS_User_Manual_EN_2020.pdf) distinguishes air, runway and ramp starts.
