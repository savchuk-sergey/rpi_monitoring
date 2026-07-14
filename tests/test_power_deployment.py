import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PowerDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.socket_unit = (ROOT / "deploy/systemd/homelab-resource-monitor-power.socket").read_text()
        cls.service_unit = (ROOT / "deploy/systemd/homelab-resource-monitor-power@.service").read_text()
        cls.installer = (ROOT / "deploy/raspberry-pi/install.sh").read_text()
        cls.deploy_script = (ROOT / "scripts/deploy-pi.ps1").read_text()

    def test_socket_unit_is_exact_local_boundary(self) -> None:
        self.assertEqual(
            1,
            self.socket_unit.count(
                "ListenStream=/run/homelab-resource-monitor/power.sock"
            ),
        )
        for directive in (
            "SocketUser=root",
            "SocketGroup=homelab-monitor-display",
            "SocketMode=0660",
            "DirectoryMode=0750",
            "RemoveOnStop=yes",
            "Accept=yes",
            "MaxConnections=4",
            "WantedBy=sockets.target",
        ):
            self.assertIn(directive, self.socket_unit)
        self.assertNotRegex(self.socket_unit, r"ListenStream=.*:")
        self.assertNotIn("ListenDatagram", self.socket_unit)

    def test_service_template_is_socket_only_root_and_hardened(self) -> None:
        for directive in (
            "Type=exec",
            "User=root",
            "Group=root",
            "ExecStart=/opt/homelab-resource-monitor/.venv/bin/python -m display.power_helper",
            "WorkingDirectory=/opt/homelab-resource-monitor",
            "StandardInput=socket",
            "StandardOutput=socket",
            "StandardError=journal",
            "TimeoutStartSec=5s",
            "UMask=0077",
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "PrivateDevices=yes",
            "ProtectHome=yes",
            "ProtectSystem=strict",
            "ProtectKernelTunables=yes",
            "ProtectKernelModules=yes",
            "ProtectControlGroups=yes",
            "RestrictSUIDSGID=yes",
            "RestrictAddressFamilies=AF_UNIX",
            "LockPersonality=yes",
        ):
            self.assertIn(directive, self.service_unit)
        for forbidden in ("Restart=", "[Install]", "WantedBy=", "sudo", "/bin/sh"):
            self.assertNotIn(forbidden, self.service_unit)

    def test_installer_validates_three_arguments_and_boolean_before_changes(self) -> None:
        self.assertIn('[ "$#" -eq 3 ]', self.installer)
        self.assertIn("true|false)", self.installer)
        self.assertLess(
            self.installer.index('case "$power_actions_enabled"'),
            self.installer.index("for user in"),
        )

    def test_installer_config_preserves_existing_and_adds_power_keys(self) -> None:
        keys = (
            "state_url",
            "calibration_file",
            "local_node_id",
            "power_actions_enabled",
            "power_socket",
            "power_confirm_hold_seconds",
            "lcd_speed_hz",
            "touch_speed_hz",
            "auto_rotate_seconds",
            "pause_after_touch_seconds",
            "long_press_seconds",
            "movement_tolerance_pixels",
            "release_debounce_seconds",
            "minimum_short_press_seconds",
            "detail_timeout_seconds",
            "menu_timeout_seconds",
            "history_window_seconds",
            "history_max_samples",
        )
        for key in keys:
            self.assertIn(f'\\"{key}\\"', self.installer)
        self.assertIn("/run/homelab-resource-monitor/power.sock", self.installer)

    def test_installer_verifies_units_and_starts_socket_before_display(self) -> None:
        verify = self.installer.index("systemd-analyze verify")
        reload = self.installer.index("systemctl daemon-reload")
        socket_start = self.installer.index(
            "systemctl enable --now homelab-resource-monitor-power.socket"
        )
        display_restart = self.installer.index(
            "systemctl restart homelab-resource-monitor-display.service"
        )
        self.assertLess(verify, reload)
        self.assertLess(reload, socket_start)
        self.assertLess(socket_start, display_restart)
        self.assertNotIn(
            "enable --now homelab-resource-monitor-power@.service",
            self.installer,
        )

    def test_installer_uses_only_safe_socket_probes(self) -> None:
        for required in (
            "systemctl --quiet is-active homelab-resource-monitor-power.socket",
            '[ -S "$power_socket" ]',
            'stat -c %U "$power_socket"',
            'stat -c %G "$power_socket"',
            'stat -c %a "$power_socket"',
            "runuser -u homelab-monitor-display",
            'client.sendall(b"invalid\\n")',
            "client.shutdown(socket.SHUT_WR)",
            'b"rejected\\n"',
            "runuser -u homelab-monitor --",
        ):
            self.assertIn(required, self.installer)
        self.assertNotRegex(self.installer, r'(?:reboot|poweroff)\\\\n')

    def test_deploy_script_has_explicit_disabled_default_and_safe_dry_run(self) -> None:
        self.assertIn("[switch] $EnablePowerActions", self.deploy_script)
        self.assertIn("if ($EnablePowerActions) { 'true' } else { 'false' }", self.deploy_script)
        self.assertIn("power actions $powerActionsLabel", self.deploy_script)
        dry_run = self.deploy_script.index("if ($DryRun)")
        first_copy = self.deploy_script.index("& scp")
        self.assertLess(dry_run, first_copy)
        self.assertIn("BatchMode=yes", self.deploy_script)
        self.assertIn("StrictHostKeyChecking=yes", self.deploy_script)
        self.assertIn("/usr/sbin", self.deploy_script)
        for command in ("python3", "systemctl", "systemd-analyze", "runuser", "curl", "sed"):
            self.assertIn(f"command -v {command}", self.deploy_script)
        self.assertIn("/dev/spidev0.0", self.deploy_script)
        self.assertIn("/dev/spidev0.1", self.deploy_script)
        self.assertIn("$powerActionsEnabled", self.deploy_script)
        self.assertNotRegex(self.deploy_script, r"(?i)(?:reboot|poweroff)\\s")

    def test_deploy_diagnostics_include_socket_without_config_dump(self) -> None:
        self.assertIn("homelab-resource-monitor-power.socket", self.deploy_script)
        self.assertIn("homelab-resource-monitor-power@*.service", self.deploy_script)
        self.assertIn("homelab-resource-monitor-display.service", self.deploy_script)
        for forbidden in ("Get-Content", "display.json", "hub.json", "linux-agent.json"):
            self.assertNotIn(forbidden, self.deploy_script)

    def test_existing_display_and_hub_services_remain_unprivileged(self) -> None:
        for unit in (
            "deploy/systemd/homelab-resource-monitor-display.service",
            "deploy/systemd/homelab-resource-monitor-hub.service",
        ):
            source = (ROOT / unit).read_text()
            user = re.search(r"^User=(.+)$", source, re.MULTILINE)
            self.assertIsNotNone(user)
            assert user is not None
            self.assertNotEqual("root", user.group(1))


if __name__ == "__main__":
    unittest.main()
