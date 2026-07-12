#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ "$#" -eq 2 ] || { echo "usage: $0 SOURCE_DIR CALIBRATION_FILE" >&2; exit 2; }
source_dir=$1
calibration=$2
[ -f "$source_dir/pyproject.toml" ] && [ -f "$calibration" ] || { echo "source or calibration missing" >&2; exit 3; }

for user in homelab-monitor homelab-monitor-display homelab-monitor-agent; do
    id "$user" >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin "$user"
done
usermod -a -G gpio,spi homelab-monitor-display

install -d -o root -g root -m 0755 /opt/homelab-resource-monitor
cp -a "$source_dir/agents" "$source_dir/display" "$source_dir/hub" "$source_dir/protocol" "$source_dir/pyproject.toml" /opt/homelab-resource-monitor/
chmod -R a+rX /opt/homelab-resource-monitor/agents /opt/homelab-resource-monitor/display /opt/homelab-resource-monitor/hub /opt/homelab-resource-monitor/protocol
python3 -m venv --system-site-packages /opt/homelab-resource-monitor/.venv
/opt/homelab-resource-monitor/.venv/bin/pip install --disable-pip-version-check /opt/homelab-resource-monitor

install -d -o root -g root -m 0755 /etc/homelab-resource-monitor
if [ ! -f /etc/homelab-resource-monitor/hub.json ] || [ ! -f /etc/homelab-resource-monitor/linux-agent.json ]; then
    umask 077
    python3 - /tmp/hub.json /tmp/linux-agent.json <<'PY'
import hashlib, json, secrets, sys
token = secrets.token_urlsafe(32)
with open(sys.argv[1], "w") as file:
    json.dump({"offline_seconds": 10, "token_sha256": {"display-rpi": hashlib.sha256(token.encode()).hexdigest()}}, file)
with open(sys.argv[2], "w") as file:
    json.dump({"hub_url": "http://127.0.0.1:8765/api/v1/telemetry", "node_id": "display-rpi", "display_name": "Raspberry Pi", "token": token, "interval_seconds": 2}, file)
PY
    install -o homelab-monitor -g homelab-monitor -m 0600 /tmp/hub.json /etc/homelab-resource-monitor/hub.json
    install -o homelab-monitor-agent -g homelab-monitor-agent -m 0600 /tmp/linux-agent.json /etc/homelab-resource-monitor/linux-agent.json
    rm -f /tmp/hub.json /tmp/linux-agent.json
fi
install -o homelab-monitor-display -g homelab-monitor-display -m 0600 "$calibration" /etc/homelab-resource-monitor/touch-calibration.json
printf '%s\n' '{"state_url":"http://127.0.0.1:8766/api/v1/state","calibration_file":"/etc/homelab-resource-monitor/touch-calibration.json","lcd_speed_hz":16000000,"touch_speed_hz":2000000}' >/tmp/display.json
install -o homelab-monitor-display -g homelab-monitor-display -m 0600 /tmp/display.json /etc/homelab-resource-monitor/display.json
rm -f /tmp/display.json

for unit in hub display linux-agent; do
    install -o root -g root -m 0644 "$source_dir/deploy/systemd/homelab-resource-monitor-$unit.service" /etc/systemd/system/
done
systemctl daemon-reload
systemctl enable homelab-resource-monitor-hub.service homelab-resource-monitor-display.service homelab-resource-monitor-linux-agent.service
systemctl restart homelab-resource-monitor-hub.service
systemctl restart homelab-resource-monitor-display.service
systemctl restart homelab-resource-monitor-linux-agent.service
sleep 3
curl --fail --silent http://127.0.0.1:8765/healthz >/dev/null
systemctl --quiet is-active homelab-resource-monitor-hub.service homelab-resource-monitor-display.service homelab-resource-monitor-linux-agent.service
