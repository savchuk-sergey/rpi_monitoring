import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


SCHEMA = json.loads(Path(__file__).with_name("telemetry-v1.schema.json").read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


def load_sample(raw: str | bytes) -> dict[str, Any]:
    sample = json.loads(
        raw,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite number: {value}")
        ),
    )
    validate_sample(sample)
    return sample


def validate_sample(sample: Any) -> None:
    if not isinstance(sample, dict):
        raise ValueError("telemetry sample must be an object")
    if not _finite(sample):
        raise ValueError("telemetry sample contains a non-finite number")

    error = next(VALIDATOR.iter_errors(sample), None)
    if error:
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise ValueError(f"{path}: {error.message}")

    timestamp = datetime.fromisoformat(sample["timestamp_utc"].replace("Z", "+00:00"))
    if timestamp.tzinfo != timezone.utc:
        raise ValueError("timestamp_utc must use UTC Z suffix")


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    return True
