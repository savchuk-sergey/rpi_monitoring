import argparse
import asyncio
import json
import logging
from pathlib import Path

from agents.linux.collector import LinuxCollector


LOG = logging.getLogger("homelab-resource-monitor-linux-agent")


async def run(config: dict) -> None:
    import aiohttp

    collector = LinuxCollector()
    headers = {"Authorization": f"Bearer {config['token']}"}
    timeout = aiohttp.ClientTimeout(total=5, connect=2)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        while True:
            sample = collector.collect(config["node_id"], config["display_name"])
            try:
                async with session.post(config["hub_url"], json=sample) as response:
                    if response.status >= 400:
                        LOG.warning("hub rejected telemetry with HTTP %d", response.status)
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                LOG.warning("hub unavailable: %s", type(error).__name__)
            await asyncio.sleep(float(config.get("interval_seconds", 2)))


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    required = ("hub_url", "node_id", "display_name", "token")
    if any(not isinstance(config.get(key), str) or not config[key] for key in required):
        raise ValueError(f"config requires: {', '.join(required)}")
    if len(config["token"]) < 32:
        raise ValueError("token must contain at least 32 characters")
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--capabilities", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.capabilities:
        print(json.dumps(LinuxCollector().capabilities(), indent=2))
        return
    asyncio.run(run(load_config(args.config)))


if __name__ == "__main__":
    main()
