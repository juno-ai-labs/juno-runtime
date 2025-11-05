# Requirements

1. [Nvidia Jetson Dev Kit](https://a.co/d/3CmGCRs)

If you want to use it as a smart speaker you'll need a USB mic/speaker
- [Anker PowerConf S330 Speakerphone](https://a.co/d/9CJIGMm)
- [Seeed reSpeaker](https://www.seeedstudio.com/ReSpeaker-XVF3800-USB-Mic-Array-p-6488.html)
  - Requires a seperate 3.5mm powered speaker but has an LED ring

## Jetson setup

- Running Jetpack 6.2
- Speaker plugged into front USB port

# Getting started on a Nvidia Jetson Dev Kit
1. Clone this repo `git clone https://github.com/juno-ai-labs/juno-runtime.git`
2. `cd juno-runtime`
3. _(only needed once)_ `./setup-jetson.py` to apply some required settings to the Jetson **(may require a reboot)**.

### Running as a smart speaker (requires a USB mic/speaker)
4. `./run.sh`
5. Say _"What time is it Juno"_ or _"Hey Juno, what's the weather in San Francisco?"_


### Running audio through a browser
4. `curl -fsSL https://tailscale.com/install.sh | sh` to install tailscale (requires setting up a tailnet)
5. `sudo tailscale up`
6. [Authorize Tailscale funnel for all nodes](https://tailscale.com/kb/1223/funnel#funnel-node-attribute)
   - [Check other requirements for TS Funnel](https://tailscale.com/kb/1223/funnel#requirements-and-limitations)
8. `sudo tailscale funnel --bg localhost:8080` to set up HTTPs reverse proxy (browsers requires TLS for mic access)
9. `./run.sh --web-server`
10. Navigate to the address shown when setting up the funnel, enable mic access, and say _"What time is it Juno"_ or _"Hey Juno, what's the weather in San Francisco?"_

_The funnel will operate even after reboots due to the [`--bg`](https://tailscale.com/kb/1311/tailscale-funnel#effects-of-rebooting-and-restarting) flag, `sudo tailscale funnel --bg localhost:8080 off` will turn it off_ 

_Execute `./run.sh --help` to see all the options for customizing Juno_

# Repo organization

## Files
- `setup-echo.sh`: Sets up echo cancellation between the microphone and speaker
- `setup-jetson.py`: Idempotent Jetson configuration script for docker group membership, power mode, and clocks.
- `run.sh`: Shell launcher that calls `setup-jetson.py` before preparing the runtime Compose configuration and starting the foreground services.
- `cleanup-run.sh`: Cleanup script that removes all Juno Docker resources (containers, images, volumes, networks).
- `docker-compose.yml` + `docker-compose.runtime.yml`: Composed Docker Compose files

### Generated Files
- `.setup_complete.toml` configuration file for `setup-jetson.py` with last applied version metadata (ex: `2025.10.12`) and the applied settings.

## Auto-merged files

The following files are automatically synced from the upstream development repository, so local changes to them may be overwritten during the synchronization process:

- `run.sh`
- `cleanup-run.sh`
- `docker-compose.runtime.yml`
- `docker-compose.yml`
- `setup-echo.sh`

A GitHub Action in this repo enforces that `run.sh` calls `setup-jetson.py` immediately after configuring the cleanup trap so the Jetson provisioning script runs. Any incoming changes to `run.sh` will be amended to include a call to `setup-jetson.py`.
