import subprocess
import sys
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / "deploy" / "raspberry-pi" / "add-node-hash.py"


class DeploymentHelperTests(unittest.TestCase):
    def test_registration_rejects_unsafe_arguments_before_accessing_hub_config(self):
        for node_id, token_hash in (("INVALID NODE", "0" * 64), ("server01", "not-a-hash")):
            result = subprocess.run(
                [sys.executable, HELPER, node_id, token_hash], capture_output=True, text=True
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
