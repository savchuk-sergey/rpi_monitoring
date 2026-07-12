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
LINUX_UNIT = (
    Path(__file__).parents[1]
    / "deploy"
    / "systemd"
    / "homelab-resource-monitor-linux-agent.service"
)


class DeploymentHelperTests(unittest.TestCase):
    def test_pi_linux_agent_override_uses_the_installed_venv(self):
        unit = LINUX_UNIT.read_text()
        installer = PI_INSTALLER.read_text()
        self.assertIn("WorkingDirectory=/opt/homelab-resource-monitor/app\n", unit)
        self.assertIn("ExecStart=/opt/homelab-resource-monitor/.venv/bin/python", installer)
        self.assertIn("WorkingDirectory=/opt/homelab-resource-monitor'", installer)
        self.assertIn("usermod -a -G video homelab-monitor-agent", installer)

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
            self.assertIn("ConvertFrom-Json", script)
            self.assertNotIn("json.load(sys.stdin)", script)


if __name__ == "__main__":
    unittest.main()
