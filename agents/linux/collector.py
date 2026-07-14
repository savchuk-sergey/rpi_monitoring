import json
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def run_command(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


class LinuxCollector:
    def __init__(
        self,
        root: Path = Path("/"),
        runner: Runner = run_command,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.root = root
        self.runner = runner
        self.clock = clock
        self.previous_cpu: tuple[int, int] | None = None
        self.previous_rapl: tuple[int, float] | None = None
        self.previous_storage: tuple[str, int, int, float] | None = None
        self.previous_network: tuple[str, int, int, float] | None = None

    def collect(self, node_id: str, display_name: str) -> dict:
        errors: list[str] = []
        cpu_usage = self._safe("cpu usage", self.cpu_usage, errors)
        temperature = self._safe("cpu temperature", self.cpu_temperature, errors)
        power = self._safe("cpu power", self.cpu_power, errors)
        clock = self._safe("cpu clock", self.cpu_clock, errors)
        memory = self._safe("memory", self.memory_metrics, errors) or {
            "usage_percent": None,
            "used_bytes": None,
            "total_bytes": None,
            "swap_used_bytes": None,
            "swap_total_bytes": None,
            "swap_usage_percent": None,
        }
        memory["pressure_some_percent"] = self._safe(
            "memory pressure", self.memory_pressure, errors
        )
        gpu = self._safe("gpu", self.gpus, errors) or []
        storage = self._safe("storage", self.storage_metrics, errors) or {
            "name": None, "usage_percent": None, "used_bytes": None, "total_bytes": None,
            "read_bytes_per_second": None, "write_bytes_per_second": None, "temperature_c": None,
        }
        network = self._safe("network", self.network_metrics, errors) or {
            "interface": None, "link_up": None,
            "down_bytes_per_second": None, "up_bytes_per_second": None,
        }
        health = {
            "uptime_seconds": self._safe("uptime", self.uptime, errors),
            "undervoltage": None,
            "throttled": None,
        }
        if self.is_raspberry_pi():
            pi_health = self._safe("raspberry pi health", self.raspberry_pi_health, errors)
            if pi_health:
                health.update(pi_health)
        sample = {
            "schema_version": 2,
            "node_id": node_id,
            "display_name": display_name,
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "os": {"family": "linux", "version": platform.platform()},
            "cpu": {
                "usage_percent": cpu_usage,
                "temperature_c": temperature,
                "power_w": power,
                "clock_mhz": clock,
            },
            "memory": memory,
            "gpu": gpu,
            "storage": storage,
            "network": network,
            "health": health,
            "collector": {"version": "0.3.0", "errors": errors},
        }
        if self.is_raspberry_pi():
            sample["device"] = {
                "power_w": self._safe("device power", self.device_power, errors)
            }
        sample["capabilities"] = self.capabilities(sample)
        return sample

    def capabilities(self, sample: dict) -> dict:
        def item(supported: bool, source: str, reason: str = "sensor_not_found") -> dict:
            return {
                "supported": supported,
                "source": source if supported else None,
                "reason": None if supported else reason,
            }

        cpu = sample["cpu"]
        memory = sample["memory"]
        gpu_supported = bool(sample["gpu"]) or shutil.which("nvidia-smi") is not None
        storage = sample["storage"]
        network_supported = self._path("/proc/net/dev").is_file()
        pi_health = self.is_raspberry_pi() and (
            shutil.which("vcgencmd") is not None or self.runner is not run_command
        )
        device_power = sample.get("device", {}).get("power_w") is not None
        disk_rates = self._root_disk_counters() is not None

        return {
            "cpu.usage_percent": item(self._path("/proc/stat").is_file(), "procfs"),
            "cpu.temperature_c": item(cpu["temperature_c"] is not None, "hwmon"),
            "cpu.power_w": item(bool(self._rapl_energy_paths()), "rapl"),
            "cpu.clock_mhz": item(
                cpu["clock_mhz"] is not None, "cpufreq", "metric_unavailable"
            ),
            "memory.usage_percent": item(
                self._path("/proc/meminfo").is_file(), "procfs"
            ),
            "memory.swap_usage_percent": item(
                self._path("/proc/meminfo").is_file(), "procfs"
            ),
            "memory.pressure_some_percent": item(
                self._path("/proc/pressure/memory").is_file(),
                "psi",
                "unsupported_kernel",
            ),
            "gpu.usage_percent": item(gpu_supported, "nvidia-smi"),
            "gpu.temperature_c": item(gpu_supported, "nvidia-smi"),
            "gpu.memory_usage_percent": item(gpu_supported, "nvidia-smi"),
            "gpu.power_w": item(gpu_supported, "nvidia-smi"),
            "storage.usage_percent": item(True, "statvfs"),
            "storage.read_bytes_per_second": item(
                disk_rates, "procfs", "device_not_resolved"
            ),
            "storage.write_bytes_per_second": item(
                disk_rates, "procfs", "device_not_resolved"
            ),
            "storage.temperature_c": item(False, "hwmon"),
            "network.down_bytes_per_second": item(
                network_supported, "procfs", "interface_not_found"
            ),
            "network.up_bytes_per_second": item(
                network_supported, "procfs", "interface_not_found"
            ),
            "health.uptime_seconds": item(
                self._path("/proc/uptime").is_file(), "procfs"
            ),
            "health.undervoltage": item(
                pi_health, "vcgencmd", "unsupported_platform"
            ),
            "health.throttled": item(
                pi_health, "vcgencmd", "unsupported_platform"
            ),
            "device.power_w": item(device_power, "ina2xx"),
        }

    def cpu_usage(self) -> float | None:
        fields = [int(value) for value in self._path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields)
        current = (idle, total)
        previous, self.previous_cpu = self.previous_cpu, current
        if previous is None or total <= previous[1]:
            return None
        return round(100 * (1 - (idle - previous[0]) / (total - previous[1])), 1)

    def memory_usage(self) -> float:
        return self.memory_metrics()["usage_percent"]

    def memory_metrics(self) -> dict:
        values = {
            key.rstrip(":"): int(value)
            for key, value, *_ in (
                line.split() for line in self._path("/proc/meminfo").read_text().splitlines()
            )
        }
        total = values["MemTotal"] * 1024
        used = (values["MemTotal"] - values["MemAvailable"]) * 1024
        swap_total = values.get("SwapTotal", 0) * 1024
        swap_used = (values.get("SwapTotal", 0) - values.get("SwapFree", 0)) * 1024
        return {
            "usage_percent": round(100 * used / total, 1),
            "used_bytes": used,
            "total_bytes": total,
            "swap_used_bytes": swap_used,
            "swap_total_bytes": swap_total,
            "swap_usage_percent": round(100 * swap_used / swap_total, 1) if swap_total else None,
        }

    def memory_pressure(self) -> float | None:
        path = self._path("/proc/pressure/memory")
        if not path.is_file():
            return None
        line = next((line for line in path.read_text().splitlines() if line.startswith("some ")), "")
        value = next((item.split("=", 1)[1] for item in line.split() if item.startswith("avg10=")), None)
        return round(float(value), 2) if value is not None else None

    def cpu_clock(self) -> float | None:
        paths = self._path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq")
        values = [float(path.read_text()) / 1000 for path in paths]
        if not values:
            path = self._path("/proc/cpuinfo")
            if path.is_file():
                values = [
                    float(line.split(":", 1)[1])
                    for line in path.read_text().splitlines()
                    if line.lower().startswith("cpu mhz")
                ]
        return round(sum(values) / len(values), 1) if values else None

    def uptime(self) -> int | None:
        path = self._path("/proc/uptime")
        return int(float(path.read_text().split()[0])) if path.is_file() else None

    def raspberry_pi_health(self) -> dict | None:
        if shutil.which("vcgencmd") is None and self.runner is run_command:
            return None
        result = self.runner(["vcgencmd", "get_throttled"], 2)
        if result.returncode:
            raise RuntimeError("vcgencmd get_throttled failed")
        mask = int(result.stdout.strip().split("=", 1)[1], 16)
        return {"undervoltage": bool(mask & 0x1), "throttled": bool(mask & 0x4)}

    def storage_metrics(self) -> dict:
        total, used, _ = shutil.disk_usage(self._path("/"))
        read_rate = write_rate = None
        counters = self._root_disk_counters()
        if counters:
            device, read_bytes, write_bytes = counters
            now = self.clock()
            previous = self.previous_storage
            self.previous_storage = (device, read_bytes, write_bytes, now)
            if previous and previous[0] == device and now > previous[3]:
                elapsed = now - previous[3]
                read_rate = max(0.0, (read_bytes - previous[1]) / elapsed)
                write_rate = max(0.0, (write_bytes - previous[2]) / elapsed)
        return {
            "name": "/",
            "usage_percent": round(100 * used / total, 1) if total else None,
            "used_bytes": used,
            "total_bytes": total,
            "read_bytes_per_second": round(read_rate, 1) if read_rate is not None else None,
            "write_bytes_per_second": round(write_rate, 1) if write_rate is not None else None,
            "temperature_c": None,
        }

    def _root_disk_counters(self) -> tuple[str, int, int] | None:
        mountinfo = self._path("/proc/self/mountinfo")
        diskstats = self._path("/proc/diskstats")
        if not mountinfo.is_file() or not diskstats.is_file():
            return None
        device = next(
            (fields[2] for line in mountinfo.read_text().splitlines()
             if len(fields := line.split()) > 4 and fields[4] == "/"),
            None,
        )
        for line in diskstats.read_text().splitlines():
            fields = line.split()
            if device and len(fields) > 9 and f"{fields[0]}:{fields[1]}" == device:
                return fields[2], int(fields[5]) * 512, int(fields[9]) * 512
        return None

    def network_metrics(self) -> dict:
        path = self._path("/proc/net/dev")
        interfaces = []
        if path.is_file():
            for line in path.read_text().splitlines():
                if ":" not in line:
                    continue
                name, raw = line.split(":", 1)
                fields = raw.split()
                if name.strip() != "lo" and len(fields) >= 9:
                    interfaces.append((name.strip(), int(fields[0]), int(fields[8])))
        if not interfaces:
            return {"interface": None, "link_up": None, "down_bytes_per_second": None, "up_bytes_per_second": None}
        name, received, sent = max(interfaces, key=lambda item: item[1] + item[2])
        now = self.clock()
        previous = self.previous_network
        self.previous_network = (name, received, sent, now)
        down = up = None
        if previous and previous[0] == name and now > previous[3]:
            elapsed = now - previous[3]
            down = max(0.0, (received - previous[1]) / elapsed)
            up = max(0.0, (sent - previous[2]) / elapsed)
        operstate = self._path(f"/sys/class/net/{name}/operstate")
        return {
            "interface": name,
            "link_up": operstate.read_text().strip() == "up" if operstate.is_file() else None,
            "down_bytes_per_second": round(down, 1) if down is not None else None,
            "up_bytes_per_second": round(up, 1) if up is not None else None,
        }

    def cpu_temperature(self) -> float | None:
        zones = self._path("/sys/class/thermal")
        for temp_path in zones.glob("thermal_zone*/temp"):
            type_path = temp_path.with_name("type")
            kind = type_path.read_text().strip().lower() if type_path.exists() else ""
            if "cpu" in kind or "x86_pkg" in kind or "soc" in kind:
                return round(float(temp_path.read_text()) / 1000, 1)
        preferred_labels = ("tdie", "tctl", "package id 0", "package")
        for directory in self._path("/sys/class/hwmon").glob("hwmon*"):
            name_path = directory / "name"
            if not name_path.exists() or name_path.read_text().strip().lower() not in {
                "k10temp",
                "coretemp",
                "zenpower",
            }:
                continue
            temperatures: list[tuple[int, float]] = []
            for input_path in directory.glob("temp*_input"):
                label_path = input_path.with_name(input_path.name.replace("_input", "_label"))
                label = label_path.read_text().strip().lower() if label_path.exists() else ""
                priority = next(
                    (index for index, preferred in enumerate(preferred_labels) if preferred in label),
                    len(preferred_labels),
                )
                temperatures.append((priority, float(input_path.read_text()) / 1000))
            if temperatures:
                return round(min(temperatures)[1], 1)
        return None

    def cpu_power(self) -> float | None:
        paths = self._rapl_energy_paths()
        if not paths:
            return None
        energy = sum(int(path.read_text()) for path in paths)
        now = self.clock()
        previous, self.previous_rapl = self.previous_rapl, (energy, now)
        if previous is None or now <= previous[1]:
            return None
        delta = energy - previous[0]
        if delta < 0:
            ranges = [int(path.with_name("max_energy_range_uj").read_text()) for path in paths]
            delta += sum(ranges)
        return round(delta / 1_000_000 / (now - previous[1]), 2)

    def _rapl_energy_paths(self) -> list[Path]:
        directories = [
            path.parent
            for path in self._path("/sys/class/powercap").glob("intel-rapl*/energy_uj")
        ]
        packages = []
        for directory in directories:
            name_path = directory / "name"
            if name_path.exists() and name_path.read_text().strip().lower().startswith("package-"):
                packages.append(directory / "energy_uj")
        if packages:
            return sorted(packages)
        return sorted(
            directory / "energy_uj"
            for directory in directories
            if directory.name.count(":") <= 1
        )

    def is_raspberry_pi(self) -> bool:
        model = self._path("/sys/firmware/devicetree/base/model")
        return model.exists() and "raspberry pi" in model.read_text().lower()

    def device_power(self) -> float | None:
        for directory in self._path("/sys/class/hwmon").glob("hwmon*"):
            name = directory.joinpath("name")
            power = directory.joinpath("power1_input")
            if name.exists() and power.exists() and name.read_text().strip().startswith("ina2"):
                return round(float(power.read_text()) / 1_000_000, 3)
        return None

    def gpus(self) -> list[dict]:
        if shutil.which("nvidia-smi") is None and self.runner is run_command:
            return []
        result = self.runner(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total,fan.speed,clocks.gr",
                "--format=csv,noheader,nounits",
            ],
            2,
        )
        if result.returncode:
            raise RuntimeError("nvidia-smi failed")
        gpus = []
        for line in result.stdout.splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) != 9:
                raise ValueError("malformed nvidia-smi output")
            index, name, usage, temperature, power, memory_used, memory_total, fan, clock = fields
            used_mib, total_mib = _number(memory_used), _number(memory_total)
            gpus.append(
                {
                    "id": index,
                    "name": name,
                    "usage_percent": _number(usage),
                    "temperature_c": _number(temperature),
                    "power_w": _number(power),
                    "memory_used_bytes": round(used_mib * 1024 * 1024) if used_mib is not None else None,
                    "memory_total_bytes": round(total_mib * 1024 * 1024) if total_mib is not None else None,
                    "memory_usage_percent": round(100 * used_mib / total_mib, 1)
                    if used_mib is not None and total_mib
                    else None,
                    "fan_percent": _number(fan),
                    "clock_mhz": _number(clock),
                }
            )
        return gpus

    def _path(self, absolute: str) -> Path:
        return self.root / absolute.lstrip("/")

    @staticmethod
    def _safe(name: str, function: Callable, errors: list[str]):
        try:
            return function()
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
            errors.append(f"{name}: {type(error).__name__}")
            return None


def _number(value: str) -> float | None:
    return None if value in ("N/A", "[Not Supported]", "") else float(value)
