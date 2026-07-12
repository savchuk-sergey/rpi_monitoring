import subprocess
import sys
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / "deploy" / "raspberry-pi" / "add-node-hash.py"
PI_INSTALLER = Path(__file__).parents[1] / "deploy" / "raspberry-pi" / "install.sh"
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

    def test_registration_rejects_unsafe_arguments_before_accessing_hub_config(self):
        for node_id, token_hash in (("INVALID NODE", "0" * 64), ("server01", "not-a-hash")):
            result = subprocess.run(
                [sys.executable, HELPER, node_id, token_hash], capture_output=True, text=True
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
