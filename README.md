# Homelab Resource Monitor

Standalone, read-only resource monitoring for a Raspberry Pi 3B with a
320x240 SPI display. Linux and Windows agents push telemetry over the local
network; the Pi stores only current state and renders one selected node.

This project is not part of Homelab Control Plane and contains no remote
command or management API.

## Architecture

```text
Linux agent ---\
                +-- HTTP telemetry --> Pi hub --> localhost state --> display
Windows agent --/                                      |              + touch
```

MVP deliberately has no time-series database, browser UI, container runtime,
inbound agent ports, or remote actions.

## Hardware baseline

- Raspberry Pi 3 Model B Rev 1.2
- Debian 13 (trixie), arm64
- display: 2.8 TFT SPI 240x320 V1.2, landscape 320x240
- LCD controller: ILI9341 hypothesis, not confirmed until a visible test image
- touch controller: XPT2046
- `/dev/spidev0.0`: LCD CE0
- `/dev/spidev0.1`: touch CE1

Wiring uses SPI0: GPIO8 LCD CS, GPIO7 touch CS, GPIO10 MOSI, GPIO9 MISO,
GPIO11 SCLK, GPIO24 RESET, GPIO25 DC, and GPIO17 touch IRQ. LCD SDO is not
connected. LCD and touch chip-select lines must remain separate.

## Telemetry contract

`protocol/telemetry-v1.schema.json` and `protocol/telemetry-v2.schema.json` are
the backward-compatible Draft 2020-12 authorities. Optional measurements are
JSON `null`; a missing GPU is `[]`. Percentages are 0..100.
`NaN` and infinities are rejected before schema validation. Timestamps must be
parseable UTC values ending in `Z`.

Telemetry v2 may include a `capabilities` map keyed by metric path. Each entry
states whether the metric is supported, its source, or an explicit unavailable
reason. The display uses it to hide unsupported categories while retaining the
value-based fallback for older samples.

The hub treats `token_sha256` as the node registry, reloads it after atomic
config updates, and keeps one last-known sample per node in SQLite. Registered
nodes without a sample are exposed as `WAITING`. Persistence is limited to one
write per node every 30 seconds and one day of last-known state by default.

Run the current unit tests:

```shell
python -m unittest discover -s tests -v
```

## Deployment

Deployment is intentionally based on the OpenSSH client included with current
Windows versions. Run commands from a local checkout; no files are downloaded
from GitHub on a monitored node.

### Prerequisites

Add every SSH target to the operator's `known_hosts` and configure key-based
authentication before running a deployment. Scripts use `BatchMode=yes` and
`StrictHostKeyChecking=yes`: they do not accept passwords or unknown host keys.

Linux agent targets need Python 3.11 or newer, `systemd`, `curl`, and outbound
HTTP access to the hub on port 8765; only the Raspberry Pi service installation
also needs the Python `venv` module. The SSH deployment
account must be able to run the installer commands through non-interactive
`sudo`. Because the installer executes a staged root shell script, this account
is effectively trusted as a root deployment account even if sudoers rules are
narrowed.

The Windows node needs an elevated PowerShell, the .NET 8 SDK, OpenSSH client,
and the signed PawnIO driver used by the hardware collector. Keep generated
`deploy/windows/windows-agent.json` out of Git; it contains a bearer token and
is already covered by `.gitignore`.

### Raspberry Pi service

The Pi command installs or updates the hub, display, and its local Linux agent:

```powershell
.\scripts\deploy-pi.ps1 `
  -HostName 192.168.31.94 `
  -UserName deploy `
  -CalibrationFile .\touch-calibration.json
```

Use `-DryRun` to perform only SSH, hardware, dependency, and sudo preflight.
The real deployment checks all three systemd services plus both hub endpoints
and removes its remote staging directory even when installation fails.

To inspect the Pi:

```powershell
ssh deploy@192.168.31.94 "sudo systemctl status homelab-resource-monitor-hub.service homelab-resource-monitor-display.service homelab-resource-monitor-linux-agent.service"
ssh deploy@192.168.31.94 "sudo journalctl -n 100 -u homelab-resource-monitor-hub.service -u homelab-resource-monitor-display.service -u homelab-resource-monitor-linux-agent.service"
ssh deploy@192.168.31.94 "curl -fsS http://127.0.0.1:8765/healthz; curl -fsS http://127.0.0.1:8766/api/v1/state"
```

Full removal is deliberately explicit because it deletes calibration and hub
tokens:

```powershell
ssh deploy@192.168.31.94 "sudo systemctl disable --now homelab-resource-monitor-hub.service homelab-resource-monitor-display.service homelab-resource-monitor-linux-agent.service; sudo rm -f /etc/systemd/system/homelab-resource-monitor-hub.service /etc/systemd/system/homelab-resource-monitor-display.service /etc/systemd/system/homelab-resource-monitor-linux-agent.service; sudo systemctl daemon-reload; sudo rm -rf /opt/homelab-resource-monitor /etc/homelab-resource-monitor /var/lib/homelab-resource-monitor"
```

### Linux agent over SSH

Install a new node or update an existing one with the same command:

```powershell
.\scripts\deploy-linux-node.ps1 `
  -AgentHost server01.example.lan `
  -AgentUser deploy `
  -HubHost 192.168.31.94 `
  -HubUser deploy `
  -NodeId server01 `
  -DisplayName 'Storage server'
```

On first installation the script generates a random token, stores only its
SHA-256 hash in the hub, and installs the token as
`root:homelab-monitor-agent` with mode `0640` on the agent.
Updates preserve the installed config and token. A different requested
`NodeId` is rejected instead of silently replacing the node identity. Use
`-DryRun` for a read-only preflight.

Before copying files, Windows builds a platform-specific ready runtime under
`artifacts/linux-agent`. The target only copies that directory into `/opt`;
it does not need `venv` or `pip`, access PyPI, compile code, or resolve packages.
Windows may download a missing compatible wheel while preparing this local,
ignored artifact. The target still needs a matching system Python interpreter.

Inspect or remove the Linux agent:

```powershell
ssh deploy@server01.example.lan "sudo systemctl status homelab-resource-monitor-linux-agent.service"
ssh deploy@server01.example.lan "sudo journalctl -n 100 -u homelab-resource-monitor-linux-agent.service"
scp .\deploy\linux\uninstall-agent.sh deploy@server01.example.lan:/tmp/
ssh deploy@server01.example.lan "sudo sh /tmp/uninstall-agent.sh; rm -f /tmp/uninstall-agent.sh"
```

The uninstaller retains `/opt/homelab-resource-monitor` and the service account
because those paths may be shared with another component. Remove them manually
only after confirming nothing else uses them. Removing a node's old hash from
`/etc/homelab-resource-monitor/hub.json` is also an explicit operator action.

### Windows agent

Run this command as Administrator on the Windows node being monitored:

```powershell
.\scripts\deploy-windows-node.ps1 `
  -HubHost 192.168.31.94 `
  -HubUser deploy `
  -NodeId desktop `
  -DisplayName 'Desktop'
```

The command publishes a self-contained `win-x64` artifact, registers a token
for a new node, installs the Windows Service, and verifies that the node appears
in hub state. Re-running it preserves the installed config and token.

Inspect or remove the Windows agent from an elevated PowerShell:

```powershell
Get-Service HomelabResourceMonitorWindowsAgent
Get-WinEvent -LogName Application -MaxEvents 100 | Where-Object ProviderName -Like '*Homelab*'
.\deploy\windows\uninstall.ps1
```

### Installed paths and troubleshooting

- Linux application: `/opt/homelab-resource-monitor`
- Linux configuration: `/etc/homelab-resource-monitor`
- Linux units: `/etc/systemd/system/homelab-resource-monitor-*.service`
- Windows application: `%ProgramFiles%\HomelabResourceMonitor\WindowsAgent`
- Windows configuration: `%ProgramData%\HomelabResourceMonitor\windows-agent.json`

Diagnose failures in this order: SSH and host key, non-interactive sudo,
service status, journal or Windows Event Log, hub `/healthz`, then hub state.
Do not work around SSH errors by disabling host-key checking.

## Current gate

Stage 0 service restart, reboot recovery, network return, SSH host-key
continuity, SPI, `throttled=0x0`, and live Linux/Windows agent gates passed on
2026-07-12. Visible LCD/touch confirmation and the 24-72 hour soak remain NOT
RUN.
