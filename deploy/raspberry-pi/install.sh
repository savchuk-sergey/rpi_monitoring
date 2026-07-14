#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ "$#" -eq 3 ] || { echo "usage: $0 SOURCE_DIR CALIBRATION_FILE POWER_ACTIONS_ENABLED" >&2; exit 2; }
source_dir=$1
calibration=$2
power_actions_enabled=$3
case "$power_actions_enabled" in
    true|false) ;;
    *) echo "POWER_ACTIONS_ENABLED must be true or false" >&2; exit 2 ;;
esac
[ -f "$source_dir/pyproject.toml" ] && [ -f "$calibration" ] || { echo "source or calibration missing" >&2; exit 3; }

for user in homelab-monitor homelab-monitor-display homelab-monitor-agent; do
    id "$user" >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin "$user"
done
usermod -a -G gpio,spi homelab-monitor-display
usermod -a -G video homelab-monitor-agent

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
printf '%s\n' "{\"state_url\":\"http://127.0.0.1:8766/api/v1/state\",\"calibration_file\":\"/etc/homelab-resource-monitor/touch-calibration.json\",\"local_node_id\":\"display-rpi\",\"power_actions_enabled\":$power_actions_enabled,\"power_socket\":\"/run/homelab-resource-monitor/power.sock\",\"power_confirm_hold_seconds\":1.5,\"lcd_speed_hz\":16000000,\"touch_speed_hz\":2000000,\"auto_rotate_seconds\":0,\"pause_after_touch_seconds\":30,\"long_press_seconds\":0.65,\"movement_tolerance_pixels\":16,\"release_debounce_seconds\":0.15,\"minimum_short_press_seconds\":0.05,\"detail_timeout_seconds\":45,\"menu_timeout_seconds\":15,\"history_window_seconds\":300,\"history_max_samples\":180}" >/tmp/display.json
install -o homelab-monitor-display -g homelab-monitor-display -m 0600 /tmp/display.json /etc/homelab-resource-monitor/display.json
rm -f /tmp/display.json

for unit in hub display linux-agent; do
    install -o root -g root -m 0644 "$source_dir/deploy/systemd/homelab-resource-monitor-$unit.service" /etc/systemd/system/
done
for unit in homelab-resource-monitor-power.socket homelab-resource-monitor-power@.service; do
    install -o root -g root -m 0644 "$source_dir/deploy/systemd/$unit" /etc/systemd/system/
done
install -d -o root -g root -m 0755 /etc/systemd/system/homelab-resource-monitor-linux-agent.service.d
printf '%s\n' '[Service]' 'Environment=PYTHONPATH=/opt/homelab-resource-monitor' 'ExecStart=' 'ExecStart=/opt/homelab-resource-monitor/.venv/bin/python -m agents.linux.agent --config /etc/homelab-resource-monitor/linux-agent.json' 'WorkingDirectory=/opt/homelab-resource-monitor' >/tmp/linux-agent-override.conf
install -o root -g root -m 0644 /tmp/linux-agent-override.conf /etc/systemd/system/homelab-resource-monitor-linux-agent.service.d/override.conf
rm -f /tmp/linux-agent-override.conf
systemd-analyze verify /etc/systemd/system/homelab-resource-monitor-power.socket /etc/systemd/system/homelab-resource-monitor-power@.service
systemctl daemon-reload
systemctl enable homelab-resource-monitor-hub.service homelab-resource-monitor-display.service homelab-resource-monitor-linux-agent.service
systemctl enable --now homelab-resource-monitor-power.socket
systemctl restart homelab-resource-monitor-hub.service
systemctl restart homelab-resource-monitor-display.service
systemctl restart homelab-resource-monitor-linux-agent.service
sleep 3
curl --fail --silent http://127.0.0.1:8765/healthz >/dev/null
systemctl --quiet is-active homelab-resource-monitor-power.socket
power_socket_dir=/run/homelab-resource-monitor
power_socket=/run/homelab-resource-monitor/power.sock
[ "$(stat -c %U "$power_socket_dir")" = root ]
[ "$(stat -c %G "$power_socket_dir")" = homelab-monitor-display ]
[ "$(stat -c %a "$power_socket_dir")" = 750 ]
[ -S "$power_socket" ]
[ "$(stat -c %U "$power_socket")" = root ]
[ "$(stat -c %G "$power_socket")" = homelab-monitor-display ]
[ "$(stat -c %a "$power_socket")" = 660 ]
runuser -u homelab-monitor-display -- /opt/homelab-resource-monitor/.venv/bin/python - <<'PY'
import socket

client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.settimeout(2)
client.connect("/run/homelab-resource-monitor/power.sock")
client.sendall(b"invalid\n")
client.shutdown(socket.SHUT_WR)
response = bytearray()
while True:
    chunk = client.recv(32)
    if not chunk:
        break
    response.extend(chunk)
client.close()
if bytes(response) != b"rejected\n":
    raise SystemExit("invalid power probe was not rejected")
PY
if runuser -u homelab-monitor -- /opt/homelab-resource-monitor/.venv/bin/python - <<'PY'
import socket

client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.connect("/run/homelab-resource-monitor/power.sock")
client.close()
PY
then
    echo "unauthorized power socket connection succeeded" >&2
    exit 1
fi
systemctl --quiet is-active homelab-resource-monitor-hub.service homelab-resource-monitor-display.service homelab-resource-monitor-linux-agent.service homelab-resource-monitor-power.socket
