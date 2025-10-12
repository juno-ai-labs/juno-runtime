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
- `run_juno.py`: Python wrapper that prepares the runtime Compose configuration and launches the foreground services.
- `run.sh`: Thin wrapper that delegates to `run_juno.py`.
- `docker-compose.yml` + `docker-compose.runtime.yml`: Composed Docker Compose files
