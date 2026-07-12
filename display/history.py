from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from display.categories import CATEGORIES


@dataclass(frozen=True)
class Sample:
    timestamp: float
    value: float | None


class HistoryStore:
    def __init__(self, window_seconds: int = 300, max_samples: int = 180) -> None:
        self.window_seconds = window_seconds
        self.max_samples = max_samples
        self._last_timestamp: dict[str, str] = {}
        self._samples: dict[str, dict[str, deque[Sample]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=max_samples))
        )

    def add(self, node: dict[str, Any], hub_online: bool = True) -> bool:
        if not hub_online:
            return False
        node_id = str(node.get("node_id", ""))
        timestamp_text = str(node.get("timestamp_utc", ""))
        if not node_id or not timestamp_text or self._last_timestamp.get(node_id) == timestamp_text:
            return False
        try:
            timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return False

        online = bool(node.get("online"))
        for category in CATEGORIES:
            for metric in category.metrics:
                value = metric.value(node, 0) if online else None
                number = float(value) if value is not None else None
                samples = self._samples[node_id][f"{category.id}.{metric.id}"]
                samples.append(Sample(timestamp, number))
                cutoff = timestamp - self.window_seconds
                while samples and samples[0].timestamp < cutoff:
                    samples.popleft()
        self._last_timestamp[node_id] = timestamp_text
        return True

    def series(self, node_id: str, category_id: str, metric_id: str) -> tuple[Sample, ...]:
        return tuple(self._samples[node_id][f"{category_id}.{metric_id}"])
