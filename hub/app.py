import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from protocol import load_sample


LOG = logging.getLogger("homelab-resource-monitor-hub")
MAX_SAMPLE_AGE = timedelta(minutes=5)
MAX_FUTURE_SKEW = timedelta(seconds=30)


class HubState:
    def __init__(self, token_hashes: dict[str, str], offline_seconds: int = 10):
        self.token_hashes = token_hashes
        self.offline_seconds = offline_seconds
        self.samples: dict[str, dict[str, Any]] = {}

    def authenticate(self, node_id: str, token: str) -> bool:
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
        return True

    def current(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        nodes = []
        for node_id in sorted(self.samples):
            record = self.samples[node_id]
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


def load_config(path: Path) -> HubState:
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
    return HubState(hashes, int(config.get("offline_seconds", 10)))


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
