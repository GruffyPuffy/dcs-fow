# First DCS container trial

The [upstream Aterfax image](https://github.com/Aterfax/DCS-World-Dedicated-Server-Docker) automates Wine and the dedicated server installation. This project supplies a small Compose wrapper for our `/data` layout. The container has been installed on this host and a Windows client has joined and flown an air-start slot.

## Why this layout

Upstream's [Compose example](https://raw.githubusercontent.com/Aterfax/DCS-World-Dedicated-Server-Docker/main/docker-compose/Dedicated-Server/docker-compose.yml) mounts one persistent host directory at `/config/`. Its [documented DCS saved games path](https://github.com/Aterfax/DCS-World-Dedicated-Server-Docker#common-post-installation-configuration-actions) is `/config/.wine/drive_c/users/abc/Saved Games/DCS.server/`. The Wine prefix and DCS installation also live under `/config`. Therefore `/data/dcs-fow/config` holds all substantial persistent content. Do not use the pasted `/app/dcs_server` and `/root/Saved Games` binds without first confirming their behavior in the image.

The Compose file publishes TCP and UDP 10308 for DCS clients and Webtop HTTPS port 3001 on the Ubuntu network interfaces. From Windows on the same trusted LAN, browse `https://<ubuntu-lan-ip>:3001`; accept the image's self-signed certificate warning. The Webtop login name is `stefan`, with the password stored in the local `.env`. The Eagle Dynamics web control port 8088 is not published for this trial. Do not forward port 3001 from the internet router: [Webtop's own security guidance](https://docs.linuxserver.io/images/docker-webtop/#security) recommends stronger access controls for internet exposure. A private VPN or authenticated reverse proxy can be added later if remote access is needed.

Docker's image and writable container layers are separate from the `/config` bind mount. On a fresh Docker Engine installation they use host system storage by default: usually `/var/lib/docker`, or `/var/lib/containerd` for image contents with Docker Engine 29's containerd image store. The [Docker Hub listing](https://hub.docker.com/r/aterfax/dcs-world-dedicated-server) currently reports roughly 1.8 GB for the image; extracted layers, updates and logs need more. The container's [installer script](https://raw.githubusercontent.com/Aterfax/DCS-World-Dedicated-Server-Docker/main/docker/src/wine-dedicated-dcs-automated-installer/dcs-dedicated-server-automatic-installer.sh) explicitly downloads the DCS updater in `/config` and installs DCS in its `/config`-backed Wine tree, so the large DCS installation and maps land on `/data`. Check `docker info --format '{{.DockerRootDir}}'`, `docker system df`, `df -h / /data` and `du -sh /data/dcs-fow/config` after installation. There is no need to relocate Docker's global storage for this first trial.

## Prepare

1. Confirm `/data` is mounted from the expected ext4 disk and is writable by `stefan`.
2. Install Docker Engine and Compose on Ubuntu 24.04. The included `scripts/install-docker-ubuntu.sh` follows [Docker's official apt repository instructions](https://docs.docker.com/engine/install/ubuntu/). Review it, then run `sudo ./scripts/install-docker-ubuntu.sh` from the project root. It installs system packages and needs internet access.
3. Run `./scripts/dcs.sh config`. It creates or updates the Git-ignored `deploy/dcs/.env`, fills in the current user's UID/GID, generates a Webtop password if needed, creates `/data/dcs-fow/config`, and validates Compose. To view the generated password locally, run `sed -n 's/^WEBTOP_PASSWORD=//p' deploy/dcs/.env`; do not paste it into logs or chat.
4. Run `./scripts/dcs.sh install` to download the image and start the container. Watch `./scripts/dcs.sh logs` and use Webtop for the first DCS login. Auto installation and DCS server auto start are on. The DCS launcher must have saved login and auto login enabled for server auto start to work.

The manager is safe to rerun after Compose changes. `config`, `install` and `start` refresh UID/GID and preserve any existing non-placeholder Webtop password and `/data/dcs-fow/config` contents. `start` and `install` use `docker compose up -d`, which applies configuration changes without deleting the persistent bind mount; they do not intentionally force a DCS reinstall (`FORCEREINSTALL=0`). Avoid applying Compose changes in the middle of a DCS updater run because Docker may recreate the container.

## Management commands

Run these from the project root:

| Command | Action |
| --- | --- |
| `./scripts/dcs.sh config` | Prepare and validate configuration without starting |
| `./scripts/dcs.sh install` | First container start; image pulls if missing |
| `./scripts/dcs.sh start` | Start or apply Compose changes |
| `./scripts/dcs.sh stop` | Stop without deleting persistent data |
| `./scripts/dcs.sh status` | Show container status |
| `./scripts/dcs.sh logs` | Follow recent logs; Ctrl+C exits the log view |
| `./scripts/dcs.sh missions` | Copy `missions/fow.miz` to DCS Saved Games |


The setup script expects the current user to have Docker access. If `docker compose` reports a daemon permission error, the documented [Docker post-install options](https://docs.docker.com/engine/install/linux-postinstall/) include running Docker commands with sudo or adding the user to the `docker` group. Membership in that group grants root-level control over the host, so choose it deliberately.

## Mission and test

The repo owns one [`fow.miz`](../../missions/fow.miz), generated with [`build_mission.py`](../../missions/build_mission.py) and pydcs 0.15.0. It contains three Caucasus F/A-18C **Client** slots: air start (known to work in the earlier smoke mission), Batumi runway start, and Batumi cold ramp start at stand `10`. The two ground slots are diagnostic and have not been validated in this combined mission. Run `./scripts/dcs.sh missions` to copy `fow.miz` to `/data/dcs-fow/config/.wine/drive_c/users/abc/Saved Games/DCS.dcs_serverrelease/Missions/`. `install` and `start` also do this. The copy is repeatable and leaves an identical server copy alone. In DCS WebGUI, add `fow.miz`, select it as the startup mission, and remove the old smoke entries from the mission list. After that, the old smoke files can be deleted from Saved Games. See [Experiment 0001](../../docs/experiments/0001-linux-server-client-join.md).

The first combined mission showed the air slot working but neither ground slot accepting a player name. Its generated `warehouses` file marked Batumi **NEUTRAL**; the generator now calls `batumi.set_blue()` so the airfield belongs to the same coalition as the Hornets. This is the current hypothesis for the ground-slot failure. Restart the mission in DCS WebGUI after deployment so DCS loads the corrected archive, then retry the runway and ramp slots.

To change slots later, edit `missions/build_mission.py` and regenerate the same `fow.miz` using Python with `pydcs==0.15.0` (`python build_mission.py fow.miz` from `missions/`). Review the mission in the DCS Mission Editor before relying on new ground placements. Keep the generated `.miz` in the repo so deployment does not require pydcs.

To change the **Webtop** login password, edit only `WEBTOP_PASSWORD` in `deploy/dcs/.env`, then run `./scripts/dcs.sh start`. Compose will recreate the container to apply the environment change, interrupting any running mission. With `AUTOSTART=1`, the image starts DCS again if the DCS launcher has saved login and auto login enabled. The DCS multiplayer **server password** is a separate setting in the DCS WebGUI.

For unattended startup, Docker is enabled at Ubuntu boot and Compose uses `restart: unless-stopped`. The image's [auto-start script](https://raw.githubusercontent.com/Aterfax/DCS-World-Dedicated-Server-Docker/main/docker/src/s6-services/s6-init-dcs-server-autostart-longrun/run) checks for DCS's saved-login `network.vault`, starts `DCS_server.exe`, and restarts that process if it exits. A saved-login file was present in this host's DCS profile when auto start was enabled. If you explicitly use `./scripts/dcs.sh stop`, the container stays stopped until you run `./scripts/dcs.sh start` again. Check the DCS WebGUI after a reboot to confirm the selected mission loaded; `./scripts/dcs.sh status` confirms only the container.

### Using the browser desktop

Open `https://localhost:3001` on Ubuntu or `https://<ubuntu-lan-ip>:3001` from a trusted LAN client. Accept the self-signed certificate warning and sign in with Webtop username `stefan` and the password in `deploy/dcs/.env`. This is a remote **desktop inside the container**, distinct from the DCS game server and from DCS's own WebGUI.

The current install has desktop shortcuts named `Run DCS Server`, `Open DCS Server WebGUI`, `DCS Saved Games Dir`, `DCS Install Dir`, `Run DCS Updater`, and `Run DCS Module Installer`. For the first test:

1. On the first setup, complete the Eagle Dynamics login and enable the launcher's saved password and auto login. With `AUTOSTART=1`, the container launches DCS on later starts. **Run DCS Server** remains available for manual recovery if auto start has failed; do not launch a second copy while one is already running.
2. Double-click **Open DCS Server WebGUI** in the same browser desktop. Use it to configure the server and select/start the mission. Its shortcut opens the DCS WebGUI from the installed DCS files; port 8088 is not exposed directly to the LAN.
3. Run `./scripts/dcs.sh missions`, then add/select `fow.miz` in the DCS WebGUI. The mission has three **Client** aircraft slots.
4. Join from the Windows DCS client by direct IP using the Ubuntu LAN address and game port 10308. Confirm the F/A-18C slot appears and the aircraft can be controlled.

Use `./scripts/dcs.sh status` to check the **container** and `./scripts/dcs.sh logs` for container logs. The DCS WebGUI and DCS log report whether the **game server and mission** are running. Stopping the browser desktop view does not stop the container. For a full stop use `./scripts/dcs.sh stop`.

## Corrections to the pasted recipe

- The published container uses `/config` for persistent data. The three bind mounts in the pasted Compose file do not match its documented filesystem layout.
- Use `CAUCASUS_terrain` for `DCSMODULES`, as the modular installer names it; `CAUCASUS` may not be accepted.
- Set `AUTOSTART=0` for the first run. Upstream says automatic start needs a saved DCS login.
- A DCS client slot must use skill **Client** for multiplayer. Avoid assuming a `Player` slot is interchangeable.
- The `15–30 minute` installation time and `~120 GB` binary size in the suggestion are estimates, not measured facts for this host. Check actual logs and disk use.
