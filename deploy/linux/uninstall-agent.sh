#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
systemctl disable --now homelab-resource-monitor-linux-agent.service 2>/dev/null || true
rm -f /etc/systemd/system/homelab-resource-monitor-linux-agent.service
rm -f /etc/homelab-resource-monitor/linux-agent.json
systemctl daemon-reload
echo "Application files and service account were retained because hub/display may share them."
