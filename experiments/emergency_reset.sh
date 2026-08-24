#!/usr/bin/env bash
# Reset only this project’s testbed processes and restart its three TE controllers.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./experiments/emergency_reset.sh" >&2
  exit 1
fi

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RESULTS_DIR="$PROJECT_ROOT/results/controllers"
RUN_USER=${SUDO_USER:-$USER}
RUN_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)
DEFAULT_RYU_MANAGER=${RUN_HOME:+$RUN_HOME/ryu311/bin/ryu-manager}
RYU_MANAGER=${RYU_MANAGER:-$DEFAULT_RYU_MANAGER}
TE_ENABLED=${TE_ENABLED:-1}

if [[ ! -x "$RYU_MANAGER" ]] && ! command -v "$RYU_MANAGER" >/dev/null 2>&1; then
  echo "ryu-manager not found. Set RYU_MANAGER to the venv executable." >&2
  exit 1
fi

echo "[1/4] Stopping only known project attack processes..."
pkill -f 'attacks/(packetin_flood|eastwest_flood|topology_poison)\.py' 2>/dev/null || true

echo "[2/4] Stopping this project’s EW controller processes..."
pkill -f 'ryu-manager.*controllers/ew_controller\.py' 2>/dev/null || true
sleep 1

echo "[3/4] Cleaning stale Mininet and Open vSwitch state..."
mn -c

echo "[4/4] Starting clean EW controllers with TE_ENABLED=$TE_ENABLED..."
mkdir -p "$RESULTS_DIR"
start_controller() {
  local domain=$1 dpids=$2 api_port=$3 of_port=$4
  nohup env DOMAIN_ID="$domain" DOMAIN_DPIDS="$dpids" EW_API_PORT="$api_port" \
    TE_ENABLED="$TE_ENABLED" "$RYU_MANAGER" "$PROJECT_ROOT/controllers/ew_controller.py" \
    --ofp-tcp-listen-port "$of_port" >"$RESULTS_DIR/controller_${domain}.log" 2>&1 &
}

start_controller A 1,2,3 8080 6633
start_controller B 4,5,6 8081 6634
start_controller C 7,8,9 8082 6653

echo "Reset complete. Controller logs: $RESULTS_DIR"
echo "Start a topology/test only after the controllers have finished starting."
