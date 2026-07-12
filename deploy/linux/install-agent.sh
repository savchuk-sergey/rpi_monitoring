#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ "$#" -ge 1 ] && [ "$#" -le 2 ] || { echo "usage: $0 RUNTIME_DIR [CONFIG_FILE]" >&2; exit 2; }
runtime=$1
[ -f "$runtime/agents/linux/agent.py" ] || { echo "runtime artifact is invalid" >&2; exit 2; }
config=/etc/homelab-resource-monitor/linux-agent.json
if [ "$#" -eq 2 ]; then
    [ -f "$2" ] || { echo "config file not found" >&2; exit 2; }
elif [ ! -f "$config" ]; then
    echo "CONFIG_FILE is required for the first installation" >&2
    exit 2
fi

id homelab-monitor-agent >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin homelab-monitor-agent
install -d -o root -g root -m 0755 /opt/homelab-resource-monitor
systemctl stop homelab-resource-monitor-linux-agent.service 2>/dev/null || true
rm -rf /opt/homelab-resource-monitor/app /opt/homelab-resource-monitor/.venv /opt/homelab-resource-monitor/agents /opt/homelab-resource-monitor/display /opt/homelab-resource-monitor/hub /opt/homelab-resource-monitor/protocol /opt/homelab-resource-monitor/pyproject.toml /opt/homelab-resource-monitor/homelab_resource_monitor.egg-info
install -d -o root -g root -m 0755 /opt/homelab-resource-monitor/app
cp -a "$runtime"/. /opt/homelab-resource-monitor/app/
chmod -R a+rX /opt/homelab-resource-monitor/app
install -d -o root -g homelab-monitor-agent -m 0750 /etc/homelab-resource-monitor
if [ "$#" -eq 2 ]; then
    install -o root -g homelab-monitor-agent -m 0640 "$2" "$config"
else
    chown root:homelab-monitor-agent "$config"
    chmod 0640 "$config"
fi
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
install -o root -g root -m 0644 "$repo/deploy/systemd/homelab-resource-monitor-linux-agent.service" /etc/systemd/system/
install -o root -g root -m 0644 "$repo/deploy/systemd/homelab-resource-monitor-rapl-permissions.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable homelab-resource-monitor-rapl-permissions.service
systemctl restart homelab-resource-monitor-rapl-permissions.service
systemctl enable homelab-resource-monitor-linux-agent.service
systemctl restart homelab-resource-monitor-linux-agent.service
