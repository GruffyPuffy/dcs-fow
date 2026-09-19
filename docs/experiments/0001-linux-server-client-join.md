# Experiment 0001: Join a minimal Linux-hosted DCS mission

Status: Air-start client join passed; ground starts need diagnosis.  
Date prepared: 2026-09-19.

## Question

Can this Ubuntu 24.04 machine host a DCS dedicated server under Wine, run a minimal Caucasus mission, and let the user's Windows DCS client occupy one F/A-18C slot over the LAN?

## Fixed scope

- Caucasus, one airfield, daylight and clear weather.
- One Caucasus mission with three blue F/A-18C **Client** slots: air start, runway start, and cold ramp start. No scripts, mods, AI commander or LLM.
- Direct LAN connection to the DCS game port. Keep the server unlisted for this test.
- The repo contains `missions/fow.miz` generated with pydcs. The Windows client owns the F/A-18C module.

## Host baseline

Observed in this workspace: Ubuntu 24.04.5 LTS; Intel i9-10900K (10 cores/20 threads); 31 GiB RAM. `/data` is the ext4 filesystem with UUID `d15d08d9-8da9-4f2a-8c6d-530907121096`, about 179 GiB available at the time of inspection; `/data2` is a separate, larger disk. `docker` and `wine` are not installed. No GPU inference is needed for this experiment. The current tool session cannot use sudo or write to `/data`, so package installation and LAN details remain pending.

Keep the DCS server installation, Wine prefix, downloaded terrain content, saved games and test logs under a dedicated tree on `/data` (suggested root: `/data/dcs-fow/`). Keep project source and documentation in this workspace. Any installer or third-party deployment tool must be checked for paths that would otherwise place large DCS content in a home directory or on `/`. Confirm the actual `/data` mount and write access in the host shell before installation; this tool session sees the mount as read-only.

## Trial sequence

1. Verify the repo's `missions/fow.miz` has three F/A-18C `Client` slots. Note the Windows DCS client version.
2. Select a Linux deployment path. The [ActiumDev Wine setup](https://github.com/ActiumDev/dcs-server-wine) already includes a minimal Caucasus mission and describes an unlisted server on port 10308, but its instructions target Debian 13 and use Git commands; adapt them explicitly for Ubuntu and keep Git operations with the user. The [Aterfax container](https://github.com/Aterfax/DCS-World-Dedicated-Server-Docker) is another candidate but would first require Docker. Record the exact chosen revision and installation steps before running them.
3. Install the [official DCS dedicated server](https://www.digitalcombatsimulator.com/en/downloads/world/server/) through the chosen Wine setup with Caucasus only. Place its Wine prefix and persistent DCS data under `/data/dcs-fow/`, using a separate service user or suitable ownership as needed. Enter DCS credentials interactively when required; do not put them in repository files or logs.
4. Run `./scripts/dcs.sh missions`, select `fow.miz` in the DCS WebGUI, and start it. Confirm the server process, mission load and log output.
5. From Windows DCS, use direct IP connection to the Ubuntu LAN address and configured port. Join each Blue slot in turn, record whether it spawns, and disconnect. Restart the DCS server and repeat a successful join once.
6. Record versions, the chosen Wine/container revision, installation footprint, startup duration, approximate idle and connected RAM use, server logs, join result and any client error. Keep account details and private network identifiers out of shared logs.

## Pass criteria

The `.miz` loads; the Windows client connects and sees the F/A-18C client slot; the player can occupy it and control the aircraft; a server restart permits a second successful join. This establishes hosting and compatibility only. It does not prove the Lua bridge, dynamic AI tasking, campaign persistence or LLM performance.

## Likely failure checks

If the client cannot connect, check DCS client/server build compatibility, server process and mission state, LAN address, firewall and both TCP and UDP game port configuration. If the slot is missing, check `Client` skill and coalition selection. If mission loading fails, check Caucasus installation and the server log before changing the Wine stack.

## Outcome

On 2026-09-19, the container image pulled and `dcs-fow-server` started. Logs later reported `Install complete.` The Windows client connected to the initial Batumi ramp mission, selected Blue and saw a slot, but did not enter the aircraft. A second air-start mission spawned successfully, proving the basic Linux server and Windows client connection. The initial ramp used stand `01`, which pydcs describes as 26×24 m. A larger-stand (`10`) ramp mission was subsequently loaded and the client again could not spawn; the exact ground-start cause remains unknown. The server's mission selection still pointed at that large-stand mission after auto start. The three smoke missions were replaced in the repo with one `fow.miz` holding air, runway, and ramp slots. This combined mission awaits a Windows-client test.

The [DCS user manual](https://www.digitalcombatsimulator.com/upload/iblock/ed6/87v22jwd1xh51i3rgki944xsf503istq/DCS_User_Manual_EN_2020.pdf) describes runway, cold ramp and hot parking as distinct takeoff types at waypoint 1. The [pydcs mission API](https://github.com/pydcs/dcs/blob/master/dcs/mission.py) likewise exposes runway and cold ramp starts. Testing those slots in the same mission will distinguish a general ground-spawn problem from a parking-specific one. If the ramp slot still fails, open `fow.miz` in the Windows DCS Mission Editor and inspect its first waypoint, parking assignment and slot placement against the current Caucasus terrain; pydcs's airport data may not match the installed map.

The first `fow.miz` trial confirmed the air slot assigns the player's callsign and spawns, while neither ground slot assigns the callsign. Inspection of the generated `warehouses` file revealed Batumi (airport ID 22) was `NEUTRAL` despite the Hornets being Blue. pydcs initializes airfields as neutral and provides `set_blue()` for this setting. The generator and deployed mission now mark Batumi `BLUE`; the Windows client must retry after restarting the mission. Do not treat this as confirmed root cause until that retry succeeds.
