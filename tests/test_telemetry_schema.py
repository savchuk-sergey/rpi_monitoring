import copy
import json
import math
import unittest
from pathlib import Path

from protocol import load_sample, validate_sample


EXAMPLES = Path(__file__).parents[1] / "protocol" / "examples"


class TelemetrySchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = json.loads((EXAMPLES / "windows.json").read_text())

    def test_examples_are_valid(self) -> None:
        for path in EXAMPLES.glob("*.json"):
            with self.subTest(path=path.name):
                validate_sample(json.loads(path.read_text()))

    def test_optional_metrics_may_be_null_and_gpu_empty(self) -> None:
        validate_sample(json.loads((EXAMPLES / "linux.json").read_text()))

    def test_unsupported_schema_version_is_rejected(self) -> None:
        self.sample["schema_version"] = 2
        self.assert_invalid(self.sample)

    def test_non_finite_numbers_are_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                sample = copy.deepcopy(self.sample)
                sample["cpu"]["usage_percent"] = value
                self.assert_invalid(sample)
        with self.assertRaises(ValueError):
            load_sample('{"cpu": {"usage_percent": NaN}}')

    def test_usage_outside_zero_to_one_hundred_is_rejected(self) -> None:
        for value in (-0.1, 100.1):
            with self.subTest(value=value):
                self.sample["memory"]["usage_percent"] = value
                self.assert_invalid(self.sample)

    def test_missing_node_id_is_rejected(self) -> None:
        del self.sample["node_id"]
        self.assert_invalid(self.sample)

    def test_timestamp_requires_parseable_utc_z_value(self) -> None:
        for value in (
            "not-a-date",
            "2026-13-99T25:61:61Z",
            "2026-07-12T03:00:00+04:00",
        ):
            with self.subTest(value=value):
                self.sample["timestamp_utc"] = value
                self.assert_invalid(self.sample)

    def assert_invalid(self, sample: object) -> None:
        with self.assertRaises(ValueError):
            validate_sample(sample)


if __name__ == "__main__":
    unittest.main()
