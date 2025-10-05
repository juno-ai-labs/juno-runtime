#!/usr/bin/env bash
set -euo pipefail

# Device masters (adjust if your IDs change)
SRC="alsa_input.usb-ANKER_Anker_PowerConf_S330_ACCUDP1F11602750-00.analog-stereo"
SNK="alsa_output.usb-ANKER_Anker_PowerConf_S330_ACCUDP1F11602750-00.analog-stereo"

log(){ echo "[setup-echo] $*"; }

# Unload any existing instance
pactl unload-module module-echo-cancel 2>/dev/null || true

# Verify we can talk to the Pulse server
if ! pactl info >/dev/null 2>&1; then
  log "ERROR: cannot connect to PulseAudio. Is it running for this user/session?"
  log "Hint: systemctl --user status pulseaudio; echo \$PULSE_SERVER"
  exit 1
fi

# Try WebRTC first (if PA was built with it). Start simple to avoid arg-related failures.
if MODIDX=$(pactl load-module module-echo-cancel \
    aec_method=webrtc \
    source_name=echocancel.mic sink_name=echocancel.spk \
    source_master="$SRC" sink_master="$SNK" 2>/dev/null); then
  log "Loaded echo cancel with WebRTC (module index $MODIDX)."
else
  log "WebRTC AEC failed (likely not built in). Falling back to Speex..."
  # Ensure WebRTC attempt is not lingering partially
  pactl unload-module module-echo-cancel 2>/dev/null || true
  # Speex fallback
  if MODIDX=$(pactl load-module module-echo-cancel \
      aec_method=speex \
      aec_args="usec_tail=200000" \
      source_name=echocancel.mic sink_name=echocancel.spk \
      source_master="$SRC" sink_master="$SNK" 2>/dev/null); then
    log "Loaded echo cancel with Speex (module index $MODIDX)."
  else
    log "ERROR: Speex AEC also failed to load. Printing recent PulseAudio logs:" 
    journalctl --user -u pulseaudio -n 100 --no-pager || true
    exit 1
  fi
fi

# Optionally set defaults so new clients pick them up automatically
pactl set-default-source echocancel.mic 2>/dev/null || true
pactl set-default-sink   echocancel.spk 2>/dev/null || true

# Show results
log "Sources:"; pactl list short sources | sed 's/^/[src] /'
log "Sinks:";   pactl list short sinks   | sed 's/^/[snk] /'

