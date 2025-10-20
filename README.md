# Requirements

1. [Nvidia Jetson Dev Kit](https://a.co/d/3CmGCRs)
2. [Anker PowerConf S330 Speakerphone](https://a.co/d/9CJIGMm)

## Jetson setup

- Running Jetpack 6.2
- Anker plugged into front USB port

# Getting started on a Nvidia Jetson Dev Kit
1. Clone this repo `git clone https://github.com/juno-ai-labs/juno-runtime.git`
2. `cd juno-runtime`
3. _(only needed once)_ `./setup-jetson.py` to apply some required settings to the Jetson **(may require a reboot)**.
4. `./run.sh`

# Organization

This will download the following services and run them in the foreground
- `stt`: Automatic Speech Recognition for english
- `llm`: LLM assistant
- `tts`: Text to Speech

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
