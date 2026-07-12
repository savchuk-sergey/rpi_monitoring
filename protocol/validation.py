import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


SCHEMAS = {
    version: json.loads(Path(__file__).with_name(f"telemetry-v{version}.schema.json").read_text())
    for version in (1, 2)
}
for schema in SCHEMAS.values():
    Draft202012Validator.check_schema(schema)
VALIDATORS = {version: Draft202012Validator(schema) for version, schema in SCHEMAS.items()}


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

    version = sample.get("schema_version")
    validator = VALIDATORS.get(version) if isinstance(version, int) and not isinstance(version, bool) else None
    if validator is None:
        raise ValueError("schema_version: unsupported telemetry schema")
    error = next(validator.iter_errors(sample), None)
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
