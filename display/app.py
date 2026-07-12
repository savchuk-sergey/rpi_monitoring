import argparse
import asyncio
import json
import logging
from pathlib import Path

import aiohttp
from PIL import ImageChops

from display.drivers.ili9341 import ILI9341
from display.drivers.xpt2046 import XPT2046
from display.navigation import (
    TouchDebouncer,
    map_touch,
    move,
    selected_index,
    touch_action,
)
from display.renderer import render


LOG = logging.getLogger("homelab-resource-monitor-display")


async def run(config: dict) -> None:
    calibration = json.loads(Path(config["calibration_file"]).read_text())
    lcd = ILI9341(int(config.get("lcd_speed_hz", 4_000_000)))
    touch = XPT2046(int(config.get("touch_speed_hz", 2_000_000)))
    debounce = TouchDebouncer()
    index = 0
    selected_id: str | None = None
    nodes: list[dict] = []
    hub_online = True
    mode = "overview"
    gpu_index = 0
    active_action: str | None = None
    pending_action: str | None = None
    touch_started: float | None = None
    feedback_pending = False
    action_at = 0.0
    auto_rotate = max(0.0, float(config.get("auto_rotate_seconds", 0)))
    pause_after_touch = max(0.0, float(config.get("pause_after_touch_seconds", 30)))
    pause_until = 0.0
    signature = ""
    lcd.initialize()
    last_frame = render(None)
    lcd.show(last_frame)
    timeout = aiohttp.ClientTimeout(total=2)
    loop = asyncio.get_running_loop()
    next_refresh = 0.0
    last_rotation = loop.time()
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                now = loop.time()
                if now >= next_refresh:
                    try:
                        async with session.get(config["state_url"]) as response:
                            response.raise_for_status()
                            nodes = (await response.json())["nodes"]
                            hub_online = True
                    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError):
                        hub_online = False
                    index = selected_index(nodes, selected_id, index)
                    selected_id = nodes[index]["node_id"] if nodes else None
                    next_refresh = now + 0.5

                changed = False
                full_refresh = False
                completed_action: str | None = None
                if touch.pressed:
                    raw = touch.read(3)
                    if debounce.update(True):
                        x, y = map_touch(*raw, calibration)
                        active_action = touch_action(x, y, mode == "details")
                        if active_action:
                            touch_started = now
                            feedback_pending = True
                            changed = True
                else:
                    debounce.update(False)
                    if active_action and pending_action is None:
                        pending_action = active_action
                        action_at = max(now, action_at + 0.1)

                if active_action and not action_at:
                    action_at = now

                if pending_action and now >= action_at:
                    action = pending_action
                    completed_action = action
                    pending_action = None
                    active_action = None
                    action_at = 0.0
                    pause_until = now + pause_after_touch
                    if action in ("previous", "next") and len(nodes) > 1:
                        index = move(index, len(nodes), -1 if action == "previous" else 1)
                        selected_id = nodes[index]["node_id"]
                        gpu_index = 0
                        last_rotation = now
                        full_refresh = True
                    elif action == "mode":
                        mode = "details" if mode == "overview" else "overview"
                        full_refresh = True
                    elif action == "gpu" and nodes:
                        gpu_count = len(nodes[index].get("gpu") or [])
                        if gpu_count > 1:
                            gpu_index = (gpu_index + 1) % gpu_count
                            full_refresh = True
                    changed = True

                if (
                    auto_rotate
                    and len(nodes) > 1
                    and now >= pause_until
                    and now - last_rotation >= auto_rotate
                    and not active_action
                ):
                    index = move(index, len(nodes), 1)
                    selected_id = nodes[index]["node_id"]
                    gpu_index = 0
                    last_rotation = now
                    changed = True
                    full_refresh = True

                state_signature = json.dumps(
                    (
                        hub_online,
                        nodes,
                        selected_id,
                        mode,
                        gpu_index,
                        active_action,
                        int(now),
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if changed or state_signature != signature:
                    render_started = loop.time()
                    frame = render(
                        nodes[index] if nodes else None,
                        (index + 1, len(nodes)),
                        hub_online,
                        mode,
                        gpu_index,
                        active_action,
                    )
                    render_ms = (loop.time() - render_started) * 1000
                    box = ImageChops.difference(last_frame, frame).getbbox()
                    if box:
                        if full_refresh:
                            lcd.show(frame)
                            box = (0, 0, 320, 240)
                        else:
                            lcd.show_region(frame, box)
                        last_frame = frame
                    if feedback_pending and active_action and touch_started is not None:
                        conversion_ms, spi_ms = lcd.last_timing_ms
                        LOG.info(
                            "touch_feedback action=%s total_ms=%.1f render_ms=%.1f rgb565_ms=%.1f spi_ms=%.1f region=%s",
                            active_action,
                            (loop.time() - touch_started) * 1000,
                            render_ms,
                            conversion_ms,
                            spi_ms,
                            box,
                        )
                        feedback_pending = False
                    if completed_action and touch_started is not None:
                        conversion_ms, spi_ms = lcd.last_timing_ms
                        LOG.info(
                            "touch_complete action=%s total_ms=%.1f render_ms=%.1f rgb565_ms=%.1f spi_ms=%.1f region=%s",
                            completed_action,
                            (loop.time() - touch_started) * 1000,
                            render_ms,
                            conversion_ms,
                            spi_ms,
                            box,
                        )
                        touch_started = None
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
