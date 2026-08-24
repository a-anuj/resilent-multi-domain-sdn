#!/usr/bin/env bash
# Reset only this project's testbed processes. Controllers are deliberately not
# restarted: launch them visibly in separate terminals after this command.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./experiments/emergency_reset.sh" >&2
  exit 1
fi

echo "[1/3] Stopping only known project attack processes..."
pkill -f 'attacks/(packetin_flood|eastwest_flood|topology_poison)\.py' 2>/dev/null || true

echo "[2/3] Stopping this project’s EW controller processes..."
pkill -f 'ryu-manager.*controllers/ew_controller\.py' 2>/dev/null || true
sleep 1

echo "[3/3] Cleaning stale Mininet and Open vSwitch state..."
mn -c

echo "Reset complete. No controllers were started."
echo "Start controllers manually in separate visible terminals, then start a topology/test."
