# ADR 0001: Host the simulation on Ubuntu

Date: 2026-09-19  
Status: Accepted for the current server baseline

## Context

The project needs a DCS dedicated server on Ubuntu 24.04 with its large files on the `/data` disk. The [Aterfax Docker/Wine container](https://github.com/Aterfax/DCS-World-Dedicated-Server-Docker) was installed on this host. A Windows client joined and spawned in a repo-owned mission.

## Decision

Use the Aterfax Docker/Wine container. Keep the DCS installation, Wine prefix, terrain data and saved state under `/data/dcs-fow/config/` on the mounted ext4 disk. Keep project source in this repository. The external orchestrator and model deployment are separate future decisions.

## Alternatives

- Direct Wine may be simpler to debug and integrate with server files, but host dependencies can be harder to reproduce.
- A Windows DCS host with Ubuntu orchestration is the fallback if Linux server operation proves unreliable.

## Consequences and acceptance

The setup installed, launched, hosted `fow.miz`, accepted a Windows client, spawned aircraft and exposed logs. Auto start after a container restart also worked. A host reboot, update behavior and resource measurements remain operational follow-up. The project depends on community compatibility; DCS updates may break the setup.
