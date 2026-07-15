import subprocess
import sys
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / "deploy" / "raspberry-pi" / "add-node-hash.py"
PI_INSTALLER = Path(__file__).parents[1] / "deploy" / "raspberry-pi" / "install.sh"
WINDOWS_INSTALLER = Path(__file__).parents[1] / "deploy" / "windows" / "install.ps1"
DEPLOY_SCRIPTS = [
    Path(__file__).parents[1] / "scripts" / name
    for name in ("deploy-windows-node.ps1", "deploy-linux-node.ps1")
]
PI_DEPLOY = Path(__file__).parents[1] / "scripts" / "deploy-pi.ps1"
HUB_UNIT = Path(__file__).parents[1] / "deploy" / "systemd" / "homelab-resource-monitor-hub.service"
LINUX_UNIT = (
    Path(__file__).parents[1]
    / "deploy"
    / "systemd"
    / "homelab-resource-monitor-linux-agent.service"
)
RAPL_PERMISSIONS_UNIT = (
    Path(__file__).parents[1]
    / "deploy"
    / "systemd"
    / "homelab-resource-monitor-rapl-permissions.service"
)


class DeploymentHelperTests(unittest.TestCase):
    def test_pi_linux_agent_override_uses_the_installed_venv(self):
        unit = LINUX_UNIT.read_text()
        installer = PI_INSTALLER.read_text()
        self.assertIn("WorkingDirectory=/opt/homelab-resource-monitor/app\n", unit)
        self.assertIn("ExecStart=/opt/homelab-resource-monitor/.venv/bin/python", installer)
        self.assertIn("WorkingDirectory=/opt/homelab-resource-monitor'", installer)
        self.assertIn("usermod -a -G video homelab-monitor-agent", installer)
        self.assertIn("StateDirectory=homelab-resource-monitor", HUB_UNIT.read_text())

    def test_registration_rejects_unsafe_arguments_before_accessing_hub_config(self):
        for node_id, token_hash in (("INVALID NODE", "0" * 64), ("server01", "not-a-hash")):
            result = subprocess.run(
                [sys.executable, HELPER, node_id, token_hash], capture_output=True, text=True
            )
            self.assertNotEqual(result.returncode, 0)

    def test_windows_installer_waits_for_service_process_before_copy(self):
        installer = WINDOWS_INSTALLER.read_text()
        self.assertIn("Where-Object ProcessId -gt 0", installer)
        self.assertLess(installer.index("WaitForExit"), installer.index("Copy-Item -Path"))
        self.assertIn("WaitForStatus('Running'", installer)

    def test_node_deploy_verification_avoids_nested_shell_quoting(self):
        for path in DEPLOY_SCRIPTS:
            script = path.read_text()
            self.assertNotIn("systemctl restart homelab-resource-monitor-hub.service", script)
            self.assertIn("ConvertFrom-Json", script)
            self.assertNotIn("json.load(sys.stdin)", script)

    def test_pi_deploy_normalizes_windows_line_endings(self):
        script = PI_DEPLOY.read_text()
        self.assertIn("sed -i 's/\\r`$//'", script)

    def test_rapl_permissions_wait_for_late_driver(self):
        unit = RAPL_PERMISSIONS_UNIT.read_text()
        self.assertIn("for attempt in 1 2 3 4 5", unit)
        self.assertIn("sleep 1", unit)
        self.assertIn('chgrp homelab-monitor-agent "$file" || exit 1', unit)


if __name__ == "__main__":
    unittest.main()
