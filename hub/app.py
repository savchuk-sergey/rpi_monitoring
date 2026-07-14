import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import signal
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from protocol import load_sample


LOG = logging.getLogger("homelab-resource-monitor-hub")
MAX_SAMPLE_AGE = timedelta(minutes=5)
MAX_FUTURE_SKEW = timedelta(seconds=30)


class HubState:
    def __init__(
        self,
        token_hashes: dict[str, str],
        offline_seconds: int = 10,
        *,
        config_path: Path | None = None,
        database_path: Path | None = None,
        state_retention_seconds: int = 86400,
        state_persist_seconds: int = 30,
    ):
        self.token_hashes = token_hashes
        self.offline_seconds = offline_seconds
        self.config_path = config_path
        self.database_path = database_path
        self.state_retention_seconds = state_retention_seconds
        self.state_persist_seconds = state_persist_seconds
        self.samples: dict[str, dict[str, Any]] = {}
        self._last_persisted: dict[str, datetime] = {}
        self._config_mtime_ns = config_path.stat().st_mtime_ns if config_path else None
        if database_path:
            self._restore()

    def authenticate(self, node_id: str, token: str) -> bool:
        self._reload_config()
        expected = self.token_hashes.get(node_id, "0" * 64)
        actual = hashlib.sha256(token.encode()).hexdigest()
        return len(token) >= 32 and hmac.compare_digest(actual, expected)

    def accept(self, sample: dict[str, Any]) -> bool:
        now = datetime.now(timezone.utc)
        timestamp = _timestamp(sample)
        if now - timestamp > MAX_SAMPLE_AGE or timestamp - now > MAX_FUTURE_SKEW:
            raise ValueError("timestamp_utc is outside the accepted time window")

        current = self.samples.get(sample["node_id"])
        if current and timestamp <= _timestamp(current["sample"]):
            return False
        self.samples[sample["node_id"]] = {"sample": sample, "received_at": now}
        self._persist(sample, now)
        return True

    def current(self) -> dict[str, Any]:
        self._reload_config()
        now = datetime.now(timezone.utc)
        nodes = []
        for node_id in sorted(self.token_hashes):
            record = self.samples.get(node_id)
            if record is None:
                nodes.append(
                    {
                        "node_id": node_id,
                        "display_name": node_id,
                        "cpu": {
                            "usage_percent": None,
                            "temperature_c": None,
                            "power_w": None,
                        },
                        "memory": {"usage_percent": None},
                        "gpu": [],
                        "collector": {"version": None, "errors": []},
                        "online": False,
                        "waiting": True,
                    }
                )
                continue
            nodes.append(
                {
                    **record["sample"],
                    "received_at_utc": record["received_at"].isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "online": (now - record["received_at"]).total_seconds()
                    <= self.offline_seconds,
                }
            )
        return {
            "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
            "nodes": nodes,
        }

    def _reload_config(self) -> None:
        if self.config_path is None:
            return
        try:
            mtime = self.config_path.stat().st_mtime_ns
        except OSError:
            return
        if mtime == self._config_mtime_ns:
            return
        self._config_mtime_ns = mtime
        try:
            config, hashes = _read_config(self.config_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            LOG.error("ignoring invalid hub config reload: %s", error)
            return
        removed = self.token_hashes.keys() - hashes.keys()
        self.token_hashes = hashes
        self.offline_seconds = int(config.get("offline_seconds", 10))
        self.state_retention_seconds = int(config.get("state_retention_seconds", 86400))
        self.state_persist_seconds = int(config.get("state_persist_seconds", 30))
        for node_id in removed:
            self.samples.pop(node_id, None)
        if removed and self.database_path:
            with closing(sqlite3.connect(self.database_path)) as database, database:
                database.executemany(
                    "DELETE FROM last_samples WHERE node_id = ?",
                    ((node_id,) for node_id in removed),
                )

    def _persist(self, sample: dict[str, Any], received_at: datetime) -> None:
        if self.database_path is None:
            return
        previous = self._last_persisted.get(sample["node_id"])
        if previous and (received_at - previous).total_seconds() < self.state_persist_seconds:
            return
        with closing(sqlite3.connect(self.database_path)) as database, database:
            database.execute(
                """
                INSERT INTO last_samples(node_id, sample_json, received_at_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    sample_json = excluded.sample_json,
                    received_at_utc = excluded.received_at_utc
                """,
                (
                    sample["node_id"],
                    json.dumps(sample, separators=(",", ":")),
                    received_at.isoformat().replace("+00:00", "Z"),
                ),
            )
        self._last_persisted[sample["node_id"]] = received_at

    def _restore(self) -> None:
        assert self.database_path is not None
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.state_retention_seconds)
        with closing(sqlite3.connect(self.database_path)) as database, database:
            database.execute(
                """
                CREATE TABLE IF NOT EXISTS last_samples(
                    node_id TEXT PRIMARY KEY,
                    sample_json TEXT NOT NULL,
                    received_at_utc TEXT NOT NULL
                )
                """
            )
            database.execute(
                "DELETE FROM last_samples WHERE received_at_utc < ?",
                (cutoff.isoformat().replace("+00:00", "Z"),),
            )
            for node_id, payload, received_at in database.execute(
                "SELECT node_id, sample_json, received_at_utc FROM last_samples"
            ):
                if node_id in self.token_hashes:
                    restored_at = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
                    self.samples[node_id] = {
                        "sample": json.loads(payload),
                        "received_at": restored_at,
                    }
                    self._last_persisted[node_id] = restored_at


STATE_KEY = web.AppKey("state", HubState)


def create_public_app(state: HubState) -> web.Application:
    app = web.Application(client_max_size=64 * 1024)
    app[STATE_KEY] = state
    app.add_routes(
        [web.get("/healthz", health), web.post("/api/v1/telemetry", telemetry)]
    )
    return app


def create_local_app(state: HubState) -> web.Application:
    app = web.Application()
    app[STATE_KEY] = state
    app.add_routes([web.get("/api/v1/state", current_state)])
    return app


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def telemetry(request: web.Request) -> web.Response:
    try:
        sample = load_sample(await request.read())
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        return web.json_response({"error": str(error)}, status=400)

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return web.json_response({"error": "missing bearer token"}, status=401)
    if not request.app[STATE_KEY].authenticate(sample["node_id"], header[7:]):
        return web.json_response({"error": "invalid credentials"}, status=403)

    try:
        accepted = request.app[STATE_KEY].accept(sample)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=422)
    return web.json_response(
        {"status": "accepted" if accepted else "ignored_older"},
        status=202 if not accepted else 200,
    )


async def current_state(request: web.Request) -> web.Response:
    return web.json_response(request.app[STATE_KEY].current())


def _read_config(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    config = json.loads(path.read_text())
    hashes = config.get("token_sha256", {})
    if not hashes or any(
        not isinstance(node, str)
        or not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
        for node, value in hashes.items()
    ):
        raise ValueError("config must contain token_sha256 node-to-hash mappings")
    return config, hashes


def load_config(path: Path) -> HubState:
    config, hashes = _read_config(path)
    return HubState(
        hashes,
        int(config.get("offline_seconds", 10)),
        config_path=path,
        database_path=Path(
            config.get(
                "state_database",
                "/var/lib/homelab-resource-monitor/last-state.sqlite3",
            )
        ),
        state_retention_seconds=int(config.get("state_retention_seconds", 86400)),
        state_persist_seconds=int(config.get("state_persist_seconds", 30)),
    )


async def serve(state: HubState, public_port: int, local_port: int) -> None:
    public_runner = web.AppRunner(create_public_app(state))
    local_runner = web.AppRunner(create_local_app(state))
    await public_runner.setup()
    await local_runner.setup()
    await web.TCPSite(public_runner, "0.0.0.0", public_port).start()
    await web.TCPSite(local_runner, "127.0.0.1", local_port).start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    LOG.info("hub listening on :%d; local state on 127.0.0.1:%d", public_port, local_port)
    try:
        await stop.wait()
    finally:
        await local_runner.cleanup()
        await public_runner.cleanup()


def _timestamp(sample: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(sample["timestamp_utc"].replace("Z", "+00:00"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--public-port", type=int, default=8765)
    parser.add_argument("--local-port", type=int, default=8766)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(load_config(args.config), args.public_port, args.local_port))


if __name__ == "__main__":
    main()
