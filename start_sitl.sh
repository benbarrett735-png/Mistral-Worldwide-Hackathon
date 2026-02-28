#!/bin/bash
# Louise — Start ArduPilot SITL.
#
# MAVProxy connects to TCP 5760 to initialize SITL and keep EKF warm.
# When a mission starts, the server kills MAVProxy and the connector
# takes over TCP 5760 directly.

set -e

export PATH="$HOME/.pyenv/bin:$HOME/.pyenv/shims:$HOME/Library/Python/3.13/bin:$PATH"
eval "$(pyenv init -)" 2>/dev/null || true

ARDUPILOT_DIR="$HOME/ardupilot"
ARDUCOPTER="$ARDUPILOT_DIR/build/sitl/bin/arducopter"

if [ ! -f "$ARDUCOPTER" ]; then
    echo "ERROR: ArduCopter not built at $ARDUCOPTER"
    exit 1
fi

echo "Cleaning up..."
pkill -f "arducopter.*--model" 2>/dev/null || true
pkill -f mavproxy 2>/dev/null || true
sleep 2

rm -f "$ARDUPILOT_DIR/eeprom.bin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOME_FILE="$SCRIPT_DIR/autopilot_adapter/output/sitl_home.txt"
if [ -f "$HOME_FILE" ]; then
  SITL_HOME="$(cat "$HOME_FILE")"
  echo "Home: $SITL_HOME"
else
  SITL_HOME="48.8606,2.3376,35.0,0.0"
  echo "Home (Louvre): $SITL_HOME"
fi

echo "=== Louise SITL ==="
cd "$ARDUPILOT_DIR"

"$ARDUCOPTER" \
    --model + \
    --speedup 1 \
    --defaults Tools/autotest/default_params/copter.parm \
    --sim-address=127.0.0.1 \
    -I0 \
    --home "$SITL_HOME" &
COPTER_PID=$!

echo "ArduCopter PID: $COPTER_PID"

cleanup() {
    echo "Shutting down..."
    kill $COPTER_PID $MAVPROXY_PID 2>/dev/null
    wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# Wait for TCP port to be ready
for i in $(seq 1 10); do
    sleep 1
    if lsof -i :5760 -sTCP:LISTEN >/dev/null 2>&1; then
        echo "TCP 5760 ready"
        break
    fi
done

# MAVProxy initializes SITL (EKF, GPS convergence)
# Output goes to stdout so server can parse the log for EKF readiness
mavproxy.py \
    --master tcp:127.0.0.1:5760 \
    --daemon 2>&1 &
MAVPROXY_PID=$!

echo "MAVProxy PID: $MAVPROXY_PID (EKF warmup)"
echo "SITL ready. Connector takes TCP 5760 when mission starts."

wait $COPTER_PID
