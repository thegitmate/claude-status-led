#!/usr/bin/env bash
# Flash the firmware to the Arduino. Finds the port, and falls back to the
# old-bootloader board type that most clone Nanos need.
set -euo pipefail

SKETCH="$(cd "$(dirname "$0")" && pwd)/firmware/StatusLed"
FQBN_NEW="arduino:avr:nano"
FQBN_OLD="arduino:avr:nano:cpu=atmega328old"

if ! command -v arduino-cli >/dev/null 2>&1; then
  echo "arduino-cli not found. Install it with:  brew install arduino-cli" >&2
  exit 1
fi

PORT="${1:-}"
if [ -z "$PORT" ]; then
  PORT="$(ls /dev/cu.usbserial* /dev/cu.wchusbserial* /dev/cu.usbmodem* 2>/dev/null | head -1 || true)"
fi
if [ -z "$PORT" ]; then
  echo "No Arduino found. Check the USB cable is a DATA cable, not charge-only:" >&2
  echo "a charge-only cable still lights the board's power LED while staying invisible." >&2
  exit 1
fi
echo "Using port: $PORT"

echo "Compiling..."
arduino-cli compile --fqbn "$FQBN_NEW" "$SKETCH"

echo "Uploading (new bootloader)..."
if arduino-cli upload -p "$PORT" --fqbn "$FQBN_NEW" "$SKETCH" 2>/dev/null; then
  echo "Done."
else
  echo "That failed, which is normal for a clone board. Retrying with the old bootloader..."
  arduino-cli compile --fqbn "$FQBN_OLD" "$SKETCH"
  arduino-cli upload -p "$PORT" --fqbn "$FQBN_OLD" "$SKETCH"
  echo "Done (old bootloader)."
fi
