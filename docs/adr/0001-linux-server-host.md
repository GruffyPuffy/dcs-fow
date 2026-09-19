# ADR 0001: Host the simulation on Ubuntu

Date: 2026-09-19  
Status: Proposed

## Context

The desired end state places DCS dedicated server, orchestrator and local model on one Ubuntu 24.04 machine. [Eagle Dynamics distributes a dedicated server installer](https://www.digitalcombatsimulator.com/en/downloads/world/server/). Community projects demonstrate [containerized Wine](https://github.com/Aterfax/DCS-World-Dedicated-Server-Docker) and [direct Wine](https://github.com/ActiumDev/dcs-server-wine) deployments. Their existence establishes plausible paths, not compatibility with this host or current DCS build.

## Proposed decision

Target Ubuntu 24.04. Keep the DCS server installation, Wine prefix, terrain data and server state under `/data/dcs-fow/` on the mounted ext4 data disk. Evaluate a maintained Wine container first for repeatability, then direct Wine if the container obstructs DCS updates, scripting or networking. Keep the orchestrator and model as separate host services during the first trial. Do not select Proton by default without a demonstrated server benefit.

## Alternatives

- Direct Wine may be simpler to debug and integrate with server files, but host dependencies can be harder to reproduce.
- A Windows DCS host with Ubuntu orchestration is the fallback if Linux server operation proves unreliable.

## Consequences and acceptance

The project depends on community compatibility and DCS updates may break it. Accept only after an Ubuntu 24.04 trial can install, launch, host a basic mission, accept a client connection, restart, and expose usable logs. Record version and resource measurements. No installation is authorized by this ADR alone.
