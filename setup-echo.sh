#!/usr/bin/env bash
set -euo pipefail

log(){ echo "[setup-echo] $*"; }

# Find audio devices dynamically instead of hardcoding serial numbers
# Search patterns for common speakerphone devices
SEARCH_PATTERNS=("ANKER" "PowerConf" "S330")

# Test beep duration in seconds
BEEP_DURATION=0.25

# Verify we can talk to the Pulse server first
if ! pactl info >/dev/null 2>&1; then
  log "ERROR: cannot connect to PulseAudio. Is it running for this user/session?"
  log "Hint: systemctl --user status pulseaudio; echo \$PULSE_SERVER"
  exit 1
fi

find_device() {
  local device_type="$1"  # "sources" or "sinks"
  local search_patterns=("${@:2}")

  # Get list of devices
  local devices
  devices=$(pactl list short "$device_type" 2>/dev/null) || {
    log "ERROR: Failed to list $device_type"
    return 1
  }

  # For sources, exclude monitor devices (they're output loopbacks, not real inputs)
  if [[ "$device_type" == "sources" ]]; then
    devices=$(grep -v '.monitor' <<< "$devices")
  fi

  # Try each search pattern
  for pattern in "${search_patterns[@]}"; do
    local match

    # Use word boundaries to avoid matching substrings like "BANKER" when looking for "ANKER"
    # First try: match with analog-stereo filter
    local filtered
    filtered=$(grep -iE "(^|[^a-zA-Z])$pattern([^a-zA-Z]|$)" <<< "$devices") || filtered=""
    local analog
    analog=$(grep -i "analog-stereo" <<< "$filtered") || analog=""
    local first_line
    first_line=$(head -n1 <<< "$analog") || first_line=""
    match=$(awk '{print $2}' <<< "$first_line") || match=""

    # Second try: match without analog-stereo filter if first attempt failed
    if [[ -z "$match" ]]; then
      filtered=$(grep -iE "(^|[^a-zA-Z])$pattern([^a-zA-Z]|$)" <<< "$devices") || filtered=""
      first_line=$(head -n1 <<< "$filtered") || first_line=""
      match=$(awk '{print $2}' <<< "$first_line") || match=""
    fi

    if [[ -n "$match" ]]; then
      echo "$match"
      return 0
    fi
  done

  return 1
}

get_device_rate() {
  local device_name="$1"
  local device_type="$2"  # "sources" or "sinks"

  # Get the sample rate from the device specification
  local rate
  rate=$(pactl list "$device_type" | grep -A 30 "Name: $device_name" | grep "Sample Specification:" | head -n1 | grep -oE '[0-9]+Hz' | grep -oE '[0-9]+')

  if [[ -n "$rate" ]]; then
    echo "$rate"
    return 0
  fi

  log "WARNING: Could not detect sample rate for $device_name, defaulting to 48000Hz"
  echo "48000"
  return 0
}

# Find source (microphone input)
log "Searching for audio input device..."
SRC=$(find_device "sources" "${SEARCH_PATTERNS[@]}") || {
  log "ERROR: No matching audio input device found!"
  log "Available sources (excluding monitors):"
  pactl list short sources | grep -v '.monitor' | sed 's/^/  /'
  exit 1
}
log "Found input device: $SRC"

# Find sink (speaker output)
log "Searching for audio output device..."
SNK=$(find_device "sinks" "${SEARCH_PATTERNS[@]}") || {
  log "ERROR: No matching audio output device found!"
  log "Available sinks:"
  pactl list short sinks | sed 's/^/  /'
  exit 1
}
log "Found output device: $SNK"

# Detect native sample rate from the source device
log "Detecting native sample rate..."
RATE=$(get_device_rate "$SRC" "sources")
log "Using sample rate: ${RATE}Hz"

# Validate source and sink are different devices
if [[ "$SRC" == "$SNK" ]]; then
  log "ERROR: Source and sink cannot be the same device!"
  log "Source: $SRC"
  log "Sink: $SNK"
  exit 1
fi

log ""

# Unload any existing echo-cancel module by specific device names
# This prevents accidentally removing user-created modules
for module_id in $(pactl list short modules | grep module-echo-cancel | grep "echocancel.mic" | awk '{print $1}'); do
  log "Unloading existing echo-cancel module (ID: $module_id)..."
  pactl unload-module "$module_id" 2>/dev/null || true
done

# Try WebRTC first (if PA was built with it).
# Request mono since WebRTC AEC typically doesn't support stereo.
LOAD_OUTPUT=""
if LOAD_OUTPUT=$(pactl load-module module-echo-cancel \
    aec_method=webrtc \
    rate="$RATE" \
    channels=1 \
    source_name=echocancel.mic sink_name=echocancel.spk \
    source_master="$SRC" sink_master="$SNK" 2>&1); then
  log "Loaded echo cancel with WebRTC (module index $LOAD_OUTPUT)."
  MODIDX="$LOAD_OUTPUT"
  AEC_METHOD="WebRTC"
else
  log "WebRTC AEC failed: $LOAD_OUTPUT"
  log "Falling back to Speex..."
  # Ensure WebRTC attempt is not lingering partially
  for module_id in $(pactl list short modules | grep module-echo-cancel | grep "echocancel.mic" | awk '{print $1}'); do
    pactl unload-module "$module_id" 2>/dev/null || true
  done
  # Speex fallback
  if LOAD_OUTPUT=$(pactl load-module module-echo-cancel \
      aec_method=speex \
      aec_args="usec_tail=200000" \
      rate="$RATE" \
      channels=1 \
      source_name=echocancel.mic sink_name=echocancel.spk \
      source_master="$SRC" sink_master="$SNK" 2>&1); then
    log "Loaded echo cancel with Speex (module index $LOAD_OUTPUT)."
    MODIDX="$LOAD_OUTPUT"
    AEC_METHOD="Speex"
  else
    log "ERROR: Speex AEC also failed to load: $LOAD_OUTPUT"
    exit 1
  fi
fi

# Validate the loaded module configuration
log "Validating module configuration..."
SINK_INFO=$(pactl list sinks | grep -A 20 "Name: echocancel.spk" || true)
ACTUAL_CHANNELS=$(echo "$SINK_INFO" | grep -i "Channel Map:" | head -n1 | awk '{print $3}' || echo "")
ACTUAL_RATE=$(echo "$SINK_INFO" | grep -i "Sample Specification:" | awk '{print $3}' || echo "")

if [[ -n "$ACTUAL_CHANNELS" && -n "$ACTUAL_RATE" ]]; then
  log "Actual configuration: $ACTUAL_CHANNELS @ $ACTUAL_RATE"
else
  log "WARNING: Could not validate module configuration"
fi

# Set defaults - warn if this fails
if ! pactl set-default-source echocancel.mic 2>/dev/null; then
  log "WARNING: Failed to set echocancel.mic as default source"
fi

if ! pactl set-default-sink echocancel.spk 2>/dev/null; then
  log "WARNING: Failed to set echocancel.spk as default sink"
fi

# Show results
log "Echo cancellation setup complete!"
log "  Method: $AEC_METHOD"
log "  Module: $MODIDX"
log "  Input: $SRC -> echocancel.mic"
log "  Output: $SNK -> echocancel.spk"
log ""
log "Sources:"; pactl list short sources | sed 's/^/[src] /'
log "Sinks:";   pactl list short sinks   | sed 's/^/[snk] /'
log ""
log "Playing test beeps through echocancel.spk..."
# Generate a 1000Hz sine wave and play it through default (which should be echocancel.spk)
play -n -c 1 -r "$RATE" synth "$BEEP_DURATION" sine 1000 2>/dev/null || log "WARNING: Could not play test beep (sox not available)"
sleep 0.2
# Play a second tone at 1500Hz explicitly through echocancel.spk
PULSE_SINK=echocancel.spk play -n -c 1 -r "$RATE" synth "$BEEP_DURATION" sine 1500 2>/dev/null || true
log "Setup complete!"

