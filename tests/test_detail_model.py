import unittest

from display.categories import (
    CATEGORIES,
    DYNAMIC_SCALE,
    PERCENT_THRESHOLDS,
    TEMPERATURE_THRESHOLDS,
    Category,
    category,
)
from display.detail_model import (
    ChartMetric,
    ScaleDefinition,
    ScaleMode,
    Threshold,
    ThresholdTone,
    ValueRow,
    ValuesLayout,
    ValueTone,
)
from display.formatting import boolean, bytes_pair, clock, number, percent, power, rate, temperature, uptime
from display.renderer import (
    _format_bool,
    _format_bytes_pair,
    _format_clock,
    _format_percent,
    _format_power,
    _format_rate,
    _format_temperature,
    _format_uptime,
    _number,
)


def complete_node(**changes) -> dict:
    value = {
        "node_id": "desktop",
        "display_name": "Desktop",
        "timestamp_utc": "2026-07-12T03:00:00Z",
        "received_at_utc": "2026-07-12T03:00:01Z",
        "online": True,
        "cpu": {"usage_percent": 47, "temperature_c": 63, "power_w": 55, "clock_mhz": 4725},
        "memory": {
            "usage_percent": 63,
            "used_bytes": 24 * 1024**3,
            "total_bytes": 32 * 1024**3,
            "swap_used_bytes": 2 * 1024**3,
            "swap_total_bytes": 8 * 1024**3,
            "swap_usage_percent": 25,
            "pressure_some_percent": 1.25,
        },
        "gpu": [{
            "id": "0",
            "name": "RTX",
            "usage_percent": 81,
            "temperature_c": 69,
            "power_w": 117,
            "memory_used_bytes": 6 * 1024**3,
            "memory_total_bytes": 12 * 1024**3,
            "memory_usage_percent": 50,
            "fan_percent": 74,
            "clock_mhz": 2625,
        }],
        "storage": {
            "name": "/",
            "usage_percent": 60,
            "used_bytes": 60 * 1024**3,
            "total_bytes": 100 * 1024**3,
            "read_bytes_per_second": 1250000,
            "write_bytes_per_second": 640000,
            "temperature_c": 42,
        },
        "network": {
            "interface": "eth0",
            "link_up": True,
            "down_bytes_per_second": 12500000,
            "up_bytes_per_second": 2500000,
        },
        "health": {"uptime_seconds": 90000, "undervoltage": False, "throttled": False},
        "device": {"power_w": 6.2},
        "collector": {"version": "0.3.0", "errors": []},
    }
    value.update(changes)
    return value


class DetailModelTests(unittest.TestCase):
    def test_enum_values_are_exact(self) -> None:
        self.assertEqual(
            {"FIXED": "fixed", "DYNAMIC_ZERO_BASED": "dynamic_zero_based", "DYNAMIC_RANGE": "dynamic_range"},
            {item.name: item.value for item in ScaleMode},
        )
        self.assertEqual(
            {"WARNING": "warning", "CRITICAL": "critical"},
            {item.name: item.value for item in ThresholdTone},
        )
        self.assertEqual(
            {"NORMAL": "normal", "WARNING": "warning", "CRITICAL": "critical"},
            {item.name: item.value for item in ValueTone},
        )

    def test_scale_definition_validation(self) -> None:
        fixed = ScaleDefinition(ScaleMode.FIXED, 0.0, 100.0)
        self.assertEqual((0.0, 100.0), (fixed.minimum, fixed.maximum))
        for maximum in (None, 0.0, -1.0):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                ScaleDefinition(ScaleMode.FIXED, 0.0, maximum)

        dynamic = ScaleDefinition(ScaleMode.DYNAMIC_ZERO_BASED, 0.0, None, 5.0)
        self.assertEqual(5.0, dynamic.step)
        for minimum, maximum, step in ((1.0, None, 10.0), (0.0, 10.0, 10.0), (0.0, None, 0.0), (0.0, None, -1.0)):
            with self.subTest(minimum=minimum, maximum=maximum, step=step), self.assertRaises(ValueError):
                ScaleDefinition(ScaleMode.DYNAMIC_ZERO_BASED, minimum, maximum, step)
        for step in (0.0, -1.0):
            with self.subTest(dynamic_range_step=step), self.assertRaises(ValueError):
                ScaleDefinition(ScaleMode.DYNAMIC_RANGE, 0.0, None, step)

    def test_values_layout_validation(self) -> None:
        self.assertEqual((10,), ValuesLayout((10,)).row_y_positions)
        titled = ValuesLayout((20,), title="TITLE", title_y=5)
        self.assertEqual(("TITLE", 5), (titled.title, titled.title_y))
        for args in (
            {"row_y_positions": (), "title": None, "title_y": None},
            {"row_y_positions": (10,), "title": "TITLE", "title_y": None},
            {"row_y_positions": (10,), "title": None, "title_y": 5},
            {"row_y_positions": (-1,), "title": None, "title_y": None},
            {"row_y_positions": (240,), "title": None, "title_y": None},
            {"row_y_positions": (10,), "title": "TITLE", "title_y": 240},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ValuesLayout(**args)

    def test_value_row_validation(self) -> None:
        text = lambda node, index, age: age
        self.assertEqual("age", ValueRow("id", "TITLE", text).text({}, 0, "age"))
        for row_id, title, fit_width in (("", "TITLE", None), ("id", "", None), ("id", "TITLE", 0), ("id", "TITLE", -1)):
            with self.subTest(row_id=row_id, title=title, fit_width=fit_width), self.assertRaises(ValueError):
                ValueRow(row_id, title, text, fit_width=fit_width)

    def test_chart_metric_validation_and_key(self) -> None:
        getter = lambda node, index: 1
        metric = ChartMetric("load", "LOAD", "%", getter, DYNAMIC_SCALE)
        self.assertEqual("load", metric.key)
        for metric_id, title in (("", "LOAD"), ("load", "")):
            with self.subTest(metric_id=metric_id, title=title), self.assertRaises(ValueError):
                ChartMetric(metric_id, title, "%", getter, DYNAMIC_SCALE)
        with self.assertRaises(ValueError):
            ChartMetric(
                "load",
                "LOAD",
                "%",
                getter,
                DYNAMIC_SCALE,
                (Threshold(95, ThresholdTone.CRITICAL), Threshold(80, ThresholdTone.WARNING)),
            )
        with self.assertRaises(ValueError):
            ChartMetric(
                "range",
                "RANGE",
                "",
                getter,
                ScaleDefinition(ScaleMode.DYNAMIC_RANGE, 0.0, None),
            )

    def test_category_registry_shape_is_exact(self) -> None:
        expected_rows = {
            "cpu": ("load", "temperature", "power", "clock"),
            "memory": ("ram_load", "used", "swap", "psi"),
            "gpu": ("gpu_name", "load", "temperature_power", "vram", "fan_clock"),
            "storage": ("volume", "used", "capacity", "read_write", "temperature"),
            "network": ("interface", "link", "down", "up"),
            "health": ("collector", "undervoltage", "throttling", "data_age", "uptime"),
        }
        expected_metrics = {
            "cpu": ("load", "temperature", "clock", "power"),
            "memory": ("ram", "swap", "psi"),
            "gpu": ("load", "temperature", "vram", "power"),
            "storage": ("used", "read", "write", "temperature"),
            "network": ("down", "up"),
            "health": ("temperature", "power", "errors"),
        }
        self.assertEqual(tuple(expected_rows), tuple(item.id for item in CATEGORIES))
        for item in CATEGORIES:
            with self.subTest(category=item.id):
                self.assertTrue(item.value_rows)
                self.assertTrue(item.chart_metrics)
                self.assertFalse(hasattr(item, "metrics"))
                self.assertEqual(expected_rows[item.id], tuple(row.id for row in item.value_rows))
                self.assertEqual(expected_metrics[item.id], tuple(metric.id for metric in item.chart_metrics))
                self.assertEqual(len(item.value_rows), len({row.id for row in item.value_rows}))
                self.assertEqual(len(item.chart_metrics), len({metric.id for metric in item.chart_metrics}))
                self.assertLessEqual(len(item.value_rows), len(item.values_layout.row_y_positions))
        self.assertEqual(205, category("gpu").value_rows[0].fit_width)

    def test_chart_scales_and_thresholds_are_exact(self) -> None:
        expected_modes = {
            "cpu": (ScaleMode.FIXED, ScaleMode.FIXED, ScaleMode.DYNAMIC_ZERO_BASED, ScaleMode.DYNAMIC_ZERO_BASED),
            "memory": (ScaleMode.FIXED,) * 3,
            "gpu": (ScaleMode.FIXED, ScaleMode.FIXED, ScaleMode.FIXED, ScaleMode.DYNAMIC_ZERO_BASED),
            "storage": (ScaleMode.FIXED, ScaleMode.DYNAMIC_ZERO_BASED, ScaleMode.DYNAMIC_ZERO_BASED, ScaleMode.FIXED),
            "network": (ScaleMode.DYNAMIC_ZERO_BASED,) * 2,
            "health": (ScaleMode.FIXED, ScaleMode.DYNAMIC_ZERO_BASED, ScaleMode.DYNAMIC_ZERO_BASED),
        }
        for item in CATEGORIES:
            self.assertEqual(expected_modes[item.id], tuple(metric.scale.mode for metric in item.chart_metrics))
            for metric in item.chart_metrics:
                if metric.unit == "%":
                    self.assertEqual(PERCENT_THRESHOLDS, metric.thresholds)
                elif metric.unit == "C":
                    self.assertEqual(TEMPERATURE_THRESHOLDS, metric.thresholds)
                else:
                    self.assertEqual((), metric.thresholds)

    def test_declared_value_rows_match_existing_strings(self) -> None:
        value = complete_node()
        expected = {
            "cpu": (("LOAD", "47%"), ("TEMP", "63°C"), ("POWER", "55W"), ("CLOCK", "4.72G")),
            "memory": (("RAM LOAD", "63%"), ("USED", "24.0/32.0GiB"), ("SWAP", "2.0/8.0GiB"), ("PSI", "1%")),
            "gpu": (("GPU NAME", "RTX"), ("LOAD", "81%"), ("TEMP / PWR", "69°C / 117W"), ("VRAM", "6.0/12.0GiB"), ("FAN / CLK", "74% / 2.62G")),
            "storage": (("VOLUME", "/"), ("USED", "60%"), ("CAPACITY", "60.0/100.0GiB"), ("READ / WRITE", "1.2M/s / 625.0K/s"), ("TEMP", "42°C")),
            "network": (("INTERFACE", "eth0"), ("LINK", "YES"), ("DOWN", "11.9M/s"), ("UP", "2.4M/s")),
            "health": (("COLLECTOR", "OK"), ("UNDERVOLTAGE", "NO"), ("THROTTLING", "NO"), ("DATA AGE", "2s"), ("UPTIME", "1d01h")),
        }
        for category_id, rows in expected.items():
            declared = category(category_id).value_rows
            self.assertEqual(rows, tuple((row.title, row.text(value, 0, "2s")) for row in declared))

    def test_health_value_tones_are_declarative(self) -> None:
        rows = {row.id: row for row in category("health").value_rows}
        normal = complete_node()
        self.assertTrue(all(row.tone(normal, 0, "2s") is ValueTone.NORMAL for row in rows.values()))
        errors = complete_node(collector={"version": "0.3.0", "errors": ["a"]})
        self.assertIs(ValueTone.WARNING, rows["collector"].tone(errors, 0, "2s"))
        critical = complete_node(health={"uptime_seconds": 1, "undervoltage": True, "throttled": True})
        self.assertIs(ValueTone.CRITICAL, rows["undervoltage"].tone(critical, 0, "2s"))
        self.assertIs(ValueTone.CRITICAL, rows["throttling"].tone(critical, 0, "2s"))
        missing = complete_node(health={})
        self.assertIs(ValueTone.NORMAL, rows["undervoltage"].tone(missing, 0, "2s"))
        self.assertIs(ValueTone.NORMAL, rows["throttling"].tone(missing, 0, "2s"))
        self.assertEqual("2s", rows["data_age"].text(normal, 0, "2s"))

    def test_formatting_functions_and_renderer_aliases(self) -> None:
        self.assertEqual(("0.7", "5"), (number(0.7), number(5)))
        self.assertEqual(("—", "63%"), (percent(None), percent(63)))
        self.assertEqual(("—", "N/A", "63°C", "63.5°C"), (temperature(None), temperature(None, True), temperature(63), temperature(63.5)))
        self.assertEqual(("—", "N/A", "6.2W", "117W"), (power(None), power(None, True), power(6.2), power(117)))
        self.assertEqual(("N/A", "4.72G"), (clock(None), clock(4725)))
        self.assertEqual("N/A", bytes_pair(None, 1))
        self.assertEqual("N/A", bytes_pair(1, None))
        self.assertEqual("24.0/32.0GiB", bytes_pair(24 * 1024**3, 32 * 1024**3))
        self.assertEqual("OFF", bytes_pair(0, 0, True))
        self.assertEqual(("N/A", "YES", "NO"), (boolean(None), boolean(True), boolean(False)))
        self.assertEqual(("N/A", "1d01h"), (uptime(None), uptime(90000)))
        self.assertEqual(("N/A", "125B/s", "2.0K/s", "11.9M/s"), (rate(None), rate(125), rate(2048), rate(12500000)))
        self.assertEqual(
            (number, percent, temperature, power, clock, bytes_pair, boolean, uptime, rate),
            (_number, _format_percent, _format_temperature, _format_power, _format_clock, _format_bytes_pair, _format_bool, _format_uptime, _format_rate),
        )

    def test_category_validation_rejects_invalid_registries(self) -> None:
        icon = lambda draw, box, fill: None
        available = lambda node: True
        row = ValueRow("row", "ROW", lambda node, index, age: "value")
        metric = ChartMetric("metric", "METRIC", "", lambda node, index: 1, DYNAMIC_SCALE)
        layout = ValuesLayout((10,))
        for args in (
            ("", "TITLE", (row,), layout, (metric,)),
            ("id", "", (row,), layout, (metric,)),
            ("id", "TITLE", (), layout, (metric,)),
            ("id", "TITLE", (row, row), ValuesLayout((10, 20)), (metric,)),
            ("id", "TITLE", (row,), layout, (metric, metric)),
            ("id", "TITLE", (row, row), layout, (metric,)),
        ):
            with self.subTest(args=args[:2]), self.assertRaises(ValueError):
                Category(args[0], args[1], icon, available, args[2], args[3], args[4])


if __name__ == "__main__":
    unittest.main()
