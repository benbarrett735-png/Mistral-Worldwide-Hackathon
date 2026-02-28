#!/bin/bash
# Louise — ArduPilot SITL Setup for macOS
# Run: bash autopilot_adapter/sitl_setup.sh
#
# This installs ArduPilot SITL and its dependencies so you can
# simulate drone flights in Paris without hardware.

set -e

echo "=== Louise — ArduPilot SITL Setup ==="
echo ""

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "Python 3 required"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "Git required"; exit 1; }

# Install pymavlink + MAVProxy
echo "[1/3] Installing MAVLink tools..."
pip3 install pymavlink MAVProxy --break-system-packages 2>/dev/null || \
pip3 install pymavlink MAVProxy

# Clone ArduPilot (if not already present)
ARDUPILOT_DIR="${HOME}/ardupilot"
if [ ! -d "$ARDUPILOT_DIR" ]; then
    echo "[2/3] Cloning ArduPilot..."
    git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git "$ARDUPILOT_DIR"
    cd "$ARDUPILOT_DIR"
    Tools/environment_install/install-prereqs-mac.sh -y
else
    echo "[2/3] ArduPilot already at $ARDUPILOT_DIR"
fi

echo "[3/3] Setup complete!"
echo ""
echo "=== How to run SITL ==="
echo ""
echo "  # Terminal 1: Start SITL (copter mode, Paris location)"
echo "  cd $ARDUPILOT_DIR"
echo "  Tools/autotest/sim_vehicle.py -v ArduCopter -L Paris --map --console"
echo ""
echo "  # Terminal 2: Load Louise mission into SITL"
echo "  cd $(pwd)"
echo "  python3 autopilot_adapter/mavlink_connector.py"
echo ""
echo "  The connector will:"
echo "    1. Connect to SITL on localhost:14550"
echo "    2. Upload the waypoints from mission.waypoints"
echo "    3. Arm the copter and start the mission"
echo "    4. Stream telemetry back to the Louise server"
echo ""
