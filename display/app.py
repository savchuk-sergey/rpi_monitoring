import argparse
import asyncio
import json
import logging
from pathlib import Path

import aiohttp

from display.drivers.ili9341 import ILI9341
from display.drivers.xpt2046 import XPT2046
from display.navigation import TouchDebouncer, map_touch, move, touch_action
from display.renderer import render


LOG = logging.getLogger("homelab-resource-monitor-display")


async def run(config: dict) -> None:
    calibration = json.loads(Path(config["calibration_file"]).read_text())
    lcd = ILI9341(int(config.get("lcd_speed_hz", 4_000_000)))
    touch = XPT2046(int(config.get("touch_speed_hz", 2_000_000)))
    debounce = TouchDebouncer()
    index = 0
    nodes: list[dict] = []
    hub_online = True
    signature = ""
    lcd.initialize()
    lcd.show(render(None))
    timeout = aiohttp.ClientTimeout(total=2)
    loop = asyncio.get_running_loop()
    next_refresh = 0.0
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                if loop.time() >= next_refresh:
                    try:
                        async with session.get(config["state_url"]) as response:
                            response.raise_for_status()
                            nodes = (await response.json())["nodes"]
                            hub_online = True
                    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError):
                        hub_online = False
                    next_refresh = loop.time() + 0.5

                changed = False
                if touch.pressed:
                    raw = touch.read(3)
                    if debounce.update(True):
                        x, _ = map_touch(*raw, calibration)
                        delta = touch_action(x)
                        if delta and len(nodes) > 1:
                            index = move(index, len(nodes), delta)
                            changed = True
                else:
                    debounce.update(False)

                index = min(index, max(0, len(nodes) - 1))
                state_signature = json.dumps(
                    (hub_online, nodes), sort_keys=True, separators=(",", ":")
                )
                if changed or state_signature != signature:
                    lcd.show(
                        render(
                            nodes[index] if nodes else None,
                            (index + 1, len(nodes)),
                            hub_online,
                        )
                    )
                    signature = state_signature
                await asyncio.sleep(0.02)
    finally:
        touch.close()
        lcd.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(json.loads(args.config.read_text())))


if __name__ == "__main__":
    main()
