import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.linux.collector import LinuxCollector


class LinuxCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, path: str, value: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def test_proc_cpu_and_memory_fixtures(self) -> None:
        self.write("proc/stat", "cpu  100 0 100 800 0 0 0 0\n")
        self.write(
            "proc/meminfo",
            "MemTotal: 1000 kB\nMemAvailable: 250 kB\nSwapTotal: 500 kB\nSwapFree: 400 kB\n",
        )
        collector = LinuxCollector(self.root)
        self.assertIsNone(collector.cpu_usage())
        self.write("proc/stat", "cpu  200 0 200 900 0 0 0 0\n")
        self.assertEqual(66.7, collector.cpu_usage())
        self.assertEqual(75.0, collector.memory_usage())
        self.assertEqual(20.0, collector.memory_metrics()["swap_usage_percent"])

    def test_v2_clock_pressure_uptime_and_pi_health_fixtures(self) -> None:
        self.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "1800000\n")
        self.write("sys/devices/system/cpu/cpu1/cpufreq/scaling_cur_freq", "2200000\n")
        self.write("proc/pressure/memory", "some avg10=1.25 avg60=0.50 avg300=0.10 total=42\n")
        self.write("proc/uptime", "86400.75 10.0\n")
        collector = LinuxCollector(self.root)
        self.assertEqual(2000.0, collector.cpu_clock())
        self.assertEqual(1.25, collector.memory_pressure())
        self.assertEqual(86400, collector.uptime())

        runner = lambda *_: subprocess.CompletedProcess([], 0, "throttled=0x5\n", "")
        self.assertEqual(
            {"undervoltage": True, "throttled": True},
            LinuxCollector(self.root, runner=runner).raspberry_pi_health(),
        )

    def test_storage_and_network_rate_fixtures(self) -> None:
        self.write("proc/self/mountinfo", "36 25 8:1 / / rw - ext4 /dev/sda1 rw\n")
        self.write("proc/diskstats", "8 1 sda1 0 0 100 0 0 0 200 0 0 0 0 0 0 0 0\n")
        storage = LinuxCollector(self.root, clock=iter((1.0, 3.0)).__next__)
        with patch("agents.linux.collector.shutil.disk_usage", return_value=(4096000, 3072000, 1024000)):
            self.assertIsNone(storage.storage_metrics()["read_bytes_per_second"])
            self.write("proc/diskstats", "8 1 sda1 0 0 140 0 0 0 260 0 0 0 0 0 0 0 0\n")
            rates = storage.storage_metrics()
        self.assertEqual((10240.0, 15360.0), (
            rates["read_bytes_per_second"], rates["write_bytes_per_second"]
        ))

        self.write("sys/class/net/eth0/operstate", "up\n")
        self.write("proc/net/dev", "eth0: 100 0 0 0 0 0 0 0 50 0 0 0 0 0 0 0\n")
        network = LinuxCollector(self.root, clock=iter((1.0, 3.0)).__next__)
        self.assertIsNone(network.network_metrics()["down_bytes_per_second"])
        self.write("proc/net/dev", "eth0: 300 0 0 0 0 0 0 0 150 0 0 0 0 0 0 0\n")
        rates = network.network_metrics()
        self.assertEqual((100.0, 50.0, True), (
            rates["down_bytes_per_second"], rates["up_bytes_per_second"], rates["link_up"]
        ))

    def test_thermal_fixture(self) -> None:
        self.write("sys/class/thermal/thermal_zone0/type", "cpu-thermal\n")
        self.write("sys/class/thermal/thermal_zone0/temp", "46200\n")
        self.assertEqual(46.2, LinuxCollector(self.root).cpu_temperature())

    def test_k10temp_hwmon_fixture(self) -> None:
        self.write("sys/class/hwmon/hwmon1/name", "k10temp\n")
        self.write("sys/class/hwmon/hwmon1/temp1_label", "Tctl\n")
        self.write("sys/class/hwmon/hwmon1/temp1_input", "50000\n")
        self.assertEqual(50.0, LinuxCollector(self.root).cpu_temperature())

    def test_ina2xx_device_power_fixture(self) -> None:
        self.write("sys/class/hwmon/hwmon0/name", "ina226\n")
        self.write("sys/class/hwmon/hwmon0/power1_input", "6234000\n")
        self.assertEqual(6.234, LinuxCollector(self.root).device_power())

    def test_device_field_is_raspberry_pi_only(self) -> None:
        self.write("sys/class/hwmon/hwmon0/name", "ina226\n")
        self.write("sys/class/hwmon/hwmon0/power1_input", "6234000\n")
        generic = LinuxCollector(self.root).collect("linux", "Linux")
        self.assertNotIn("device", generic)
        self.write("sys/firmware/devicetree/base/model", "Raspberry Pi 3 Model B\x00")
        raspberry_pi = LinuxCollector(self.root).collect("pi", "Pi")
        self.assertEqual(6.234, raspberry_pi["device"]["power_w"])

    def test_rapl_delta_and_rollover(self) -> None:
        energy = "sys/class/powercap/intel-rapl-0/energy_uj"
        self.write(energy, "900000\n")
        self.write("sys/class/powercap/intel-rapl-0/max_energy_range_uj", "1000000\n")
        times = iter((1.0, 2.0, 3.0))
        collector = LinuxCollector(self.root, clock=lambda: next(times))
        self.assertIsNone(collector.cpu_power())
        self.write(energy, "950000\n")
        self.assertEqual(0.05, collector.cpu_power())
        self.write(energy, "50000\n")
        self.assertEqual(0.1, collector.cpu_power())

    def test_rapl_uses_package_domain_only(self) -> None:
        self.write("sys/class/powercap/intel-rapl-0/name", "package-0\n")
        self.write("sys/class/powercap/intel-rapl-0/energy_uj", "1000000\n")
        self.write("sys/class/powercap/intel-rapl-0/max_energy_range_uj", "10000000\n")
        self.write("sys/class/powercap/intel-rapl-0-0/name", "core\n")
        self.write("sys/class/powercap/intel-rapl-0-0/energy_uj", "9000000\n")
        self.write("sys/class/powercap/intel-rapl-0-0/max_energy_range_uj", "10000000\n")
        times = iter((1.0, 2.0))
        collector = LinuxCollector(self.root, clock=lambda: next(times))
        self.assertIsNone(collector.cpu_power())
        self.write("sys/class/powercap/intel-rapl-0/energy_uj", "2000000\n")
        self.write("sys/class/powercap/intel-rapl-0-0/energy_uj", "10000000\n")
        self.assertEqual(1.0, collector.cpu_power())

    def test_nvidia_smi_fixture_and_malformed_output(self) -> None:
        good = lambda *_: subprocess.CompletedProcess(
            [], 0, "0, RTX, 81, 69, 117, 6144, 12288, 74, 2625\n", ""
        )
        gpu = LinuxCollector(self.root, runner=good).gpus()[0]
        self.assertEqual(
            (81.0, 117.0, 50.0, 74.0, 2625.0),
            (
                gpu["usage_percent"],
                gpu["power_w"],
                gpu["memory_usage_percent"],
                gpu["fan_percent"],
                gpu["clock_mhz"],
            ),
        )
        bad = lambda *_: subprocess.CompletedProcess([], 0, "broken\n", "")
        with self.assertRaises(ValueError):
            LinuxCollector(self.root, runner=bad).gpus()

    def test_nvidia_smi_timeout_and_missing_binary(self) -> None:
        def timeout(*_):
            raise subprocess.TimeoutExpired("nvidia-smi", 2)

        with self.assertRaises(subprocess.TimeoutExpired):
            LinuxCollector(self.root, runner=timeout).gpus()
        with patch("agents.linux.collector.shutil.which", return_value=None):
            self.assertEqual([], LinuxCollector(self.root).gpus())

    def test_partial_failures_do_not_break_sample(self) -> None:
        with patch("agents.linux.collector.shutil.which", return_value=None):
            sample = LinuxCollector(self.root).collect("node", "Node")
        self.assertEqual("node", sample["node_id"])
        self.assertEqual(2, sample["schema_version"])
        self.assertEqual("0.3.0", sample["collector"]["version"])
        self.assertGreater(len(sample["collector"]["errors"]), 0)
        self.assertEqual([], sample["gpu"])
        self.assertTrue(sample["capabilities"]["storage.usage_percent"]["supported"])
        self.assertEqual(
            "sensor_not_found",
            sample["capabilities"]["gpu.usage_percent"]["reason"],
        )


if __name__ == "__main__":
    unittest.main()
