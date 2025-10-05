# Requirements

1. [Nvidia Jetson Dev Kit](https://a.co/d/3CmGCRs)
2. [Anker PowerConf S330 Speakerphone](https://a.co/d/9CJIGMm)

## Jetson setup

- Running Jetpack 6.2
- Anker plugged into front USB port

# Getting started on a Nvidia Jetson Dev Kit
1. Clone this repo `git clone https://github.com/juno-ai-labs/juno-runtime.git)
2. `cd juno-runtime`
3. `./run.sh`

# Organization

This will download the following services and run them in the foreground
- `stt`: Automatic Speech Recognition for english
- `llm`: LLM assistant
- `tts`: Text to Speech

## Files
- `setup-echo.sh`: Sets up echo cancellation between the microphone and speaker
- `run.sh`: Runs the commnds start the Juno services
- `docker-compose.yml` + `docker-compose.runtime.yml`: Composed Docker Compose files
