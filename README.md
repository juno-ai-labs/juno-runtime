# Requirements

1. [Nvidia Jetson Dev Kit](https://a.co/d/3CmGCRs)
2. [Anker PowerConf S330 Speakerphone](https://a.co/d/9CJIGMm)

## Jetson setup

- Running Jetpack 6.2
- Anker plugged into front USB port
- Run `./setup-jetson.py` to configure Docker, power mode, and Jetson clocks. The script records its completion in `.setup_complete.toml` with version `2025.10.12` so subsequent runs can detect when reconfiguration is required.

# Getting started on a Nvidia Jetson Dev Kit
1. Clone this repo `git clone https://github.com/juno-ai-labs/juno-runtime.git`
2. `cd juno-runtime`
3. `./run.sh`

# Organization

This will download the following services and run them in the foreground
- `stt`: Automatic Speech Recognition for english
- `llm`: LLM assistant
- `tts`: Text to Speech

## Files
- `setup-echo.sh`: Sets up echo cancellation between the microphone and speaker
- `setup-jetson.py`: Idempotent Jetson configuration script for Docker, power mode, and clocks. Maintains a `.setup_complete.toml` marker with version metadata (`2025.10.12`).
- `run.sh`: Shell launcher that calls `setup-jetson.py` before preparing the runtime Compose configuration and starting the foreground services.
- `docker-compose.yml` + `docker-compose.runtime.yml`: Composed Docker Compose files

## Auto-merged files

The following files are automatically synced from the upstream development repository, so local changes to them may be
overwritten during the synchronization process:

- `run.sh`
- `docker-compose.runtime.yml`
- `docker-compose.yml`
- `setup-echo.sh`

A GitHub Action enforces that `run.sh` calls `setup-jetson.py` immediately after configuring the cleanup trap so the
Jetson provisioning script runs even if the upstream sync omits that step.
