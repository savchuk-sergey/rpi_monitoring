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

    def collect(self, node_id: str, display_name: str) -> dict:
        errors: list[str] = []
        cpu_usage = self._safe("cpu usage", self.cpu_usage, errors)
        temperature = self._safe("cpu temperature", self.cpu_temperature, errors)
        power = self._safe("cpu power", self.cpu_power, errors)
        memory = self._safe("memory usage", self.memory_usage, errors)
        gpu = self._safe("gpu", self.gpus, errors) or []
        sample = {
            "schema_version": 1,
            "node_id": node_id,
            "display_name": display_name,
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "os": {"family": "linux", "version": platform.platform()},
            "cpu": {
                "usage_percent": cpu_usage,
                "temperature_c": temperature,
                "power_w": power,
            },
            "memory": {"usage_percent": memory},
            "gpu": gpu,
            "collector": {"version": "0.1.0", "errors": errors},
        }
        if self.is_raspberry_pi():
            sample["device"] = {
                "power_w": self._safe("device power", self.device_power, errors)
            }
        return sample

    def capabilities(self) -> dict:
        return {
            "cpu_usage": self._path("/proc/stat").is_file(),
            "memory_usage": self._path("/proc/meminfo").is_file(),
            "cpu_temperature": self.cpu_temperature() is not None,
            "cpu_power": bool(self._rapl_energy_paths()),
            "device_power": self.is_raspberry_pi() and self.device_power() is not None,
            "nvidia_gpu": shutil.which("nvidia-smi") is not None,
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
        values = {
            key.rstrip(":"): int(value)
            for key, value, *_ in (
                line.split() for line in self._path("/proc/meminfo").read_text().splitlines()
            )
        }
        return round(100 * (values["MemTotal"] - values["MemAvailable"]) / values["MemTotal"], 1)

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
                "--query-gpu=index,name,utilization.gpu,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            2,
        )
        if result.returncode:
            raise RuntimeError("nvidia-smi failed")
        gpus = []
        for line in result.stdout.splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) != 5:
                raise ValueError("malformed nvidia-smi output")
            index, name, usage, temperature, power = fields
            gpus.append(
                {
                    "id": index,
                    "name": name,
                    "usage_percent": _number(usage),
                    "temperature_c": _number(temperature),
                    "power_w": _number(power),
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
