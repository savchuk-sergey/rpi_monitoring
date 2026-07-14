import argparse
import asyncio
import json
import logging
from pathlib import Path

import aiohttp
from PIL import ImageChops

from display.drivers.ili9341 import ILI9341
from display.drivers.xpt2046 import XPT2046
from display.categories import category, category_at, detail_view_at, metric_at
from display.gestures import GestureKind, GestureState, TouchRecognizer
from display.history import HistoryStore
from display.navigation import (
    DetailView,
    UiState,
    ViewMode,
    map_touch,
    move,
    selected_index,
    should_return_to_overview,
    touch_action,
)
from display.renderer import render


LOG = logging.getLogger("homelab-resource-monitor-display")


async def run(config: dict) -> None:
    calibration = json.loads(Path(config["calibration_file"]).read_text())
    lcd = ILI9341(int(config.get("lcd_speed_hz", 4_000_000)))
    touch = XPT2046(int(config.get("touch_speed_hz", 2_000_000)))
    recognizer = TouchRecognizer(
        long_press_seconds=float(config.get("long_press_seconds", 0.65)),
        movement_tolerance_pixels=int(config.get("movement_tolerance_pixels", 16)),
        release_debounce_seconds=float(config.get("release_debounce_seconds", 0.15)),
        minimum_short_press_seconds=float(config.get("minimum_short_press_seconds", 0.05)),
    )
    history = HistoryStore(
        int(config.get("history_window_seconds", 300)),
        int(config.get("history_max_samples", 180)),
    )
    state = UiState()
    index = 0
    nodes: list[dict] = []
    hub_online = True
    pressed_action: str | None = None
    touch_started: float | None = None
    feedback_pending = False
    auto_rotate = max(0.0, float(config.get("auto_rotate_seconds", 0)))
    pause_after_touch = max(0.0, float(config.get("pause_after_touch_seconds", 30)))
    detail_timeout = max(0.0, float(config.get("detail_timeout_seconds", 45)))
    menu_timeout = max(0.0, float(config.get("menu_timeout_seconds", 15)))
    pause_until = 0.0
    signature = ""
    lcd.initialize()
    last_frame = render(None)
    lcd.show(last_frame)
    timeout = aiohttp.ClientTimeout(total=2)
    loop = asyncio.get_running_loop()
    next_refresh = 0.0
    last_rotation = loop.time()
    state.last_interaction_at = last_rotation
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                now = loop.time()
                changed = False
                full_refresh = False
                completed_action: str | None = None
                if now >= next_refresh:
                    try:
                        async with session.get(config["state_url"]) as response:
                            response.raise_for_status()
                            nodes = (await response.json())["nodes"]
                            hub_online = True
                            for value in nodes:
                                history.add(value)
                    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError):
                        hub_online = False
                    index = selected_index(nodes, state.selected_node_id, index)
                    state.selected_node_id = nodes[index]["node_id"] if nodes else None
                    if nodes and state.mode == ViewMode.DETAIL:
                        selected = state.selected_category_id
                        if selected and (
                            category(selected).id != selected
                            or not category(selected).available(nodes[index])
                        ):
                            state.mode = ViewMode.OVERVIEW
                            full_refresh = True
                    next_refresh = now + 0.5

                gesture = None
                if touch.pressed:
                    raw = touch.read(3)
                    x, y = map_touch(*raw, calibration)
                    was_idle = recognizer.state == GestureState.IDLE
                    gesture = recognizer.update(True, x, y, now)
                    if was_idle and recognizer.state == GestureState.PRESSED:
                        touch_started = now
                        pressed_action = touch_action(x, y)
                        feedback_pending = pressed_action is not None
                        changed = feedback_pending
                    elif recognizer.state == GestureState.WAIT_RELEASE and pressed_action:
                        pressed_action = None
                        feedback_pending = False
                        changed = True
                else:
                    gesture = recognizer.update(False, now=now)
                    if pressed_action:
                        pressed_action = None
                        changed = True

                if gesture:
                    state.last_interaction_at = now
                    pause_until = now + pause_after_touch
                    footer_action = touch_action(gesture.x, gesture.y)
                    if gesture.kind == GestureKind.LONG:
                        if state.mode != ViewMode.MENU and footer_action == "center":
                            state.mode = ViewMode.MENU
                            completed_action = "long_menu"
                            full_refresh = True
                    elif footer_action in ("previous", "next") and len(nodes) > 1:
                        index = move(index, len(nodes), -1 if footer_action == "previous" else 1)
                        state.selected_node_id = nodes[index]["node_id"]
                        state.selected_gpu_index = 0
                        last_rotation = now
                        completed_action = footer_action
                        full_refresh = True
                    elif footer_action == "center":
                        if state.mode == ViewMode.OVERVIEW and nodes:
                            state.category_id(nodes[index])
                            state.metric_id(nodes[index])
                            state.detail_view = DetailView.VALUES
                            state.mode = ViewMode.DETAIL
                            completed_action = "short_center"
                            full_refresh = True
                        elif state.mode == ViewMode.DETAIL:
                            state.mode = ViewMode.OVERVIEW
                            completed_action = "short_center"
                            full_refresh = True
                    elif state.mode == ViewMode.MENU and nodes:
                        selected_category = category_at(gesture.x, gesture.y)
                        if selected_category and selected_category.available(nodes[index]):
                            state.select_category(nodes[index], selected_category.id)
                            state.detail_view = DetailView.VALUES
                            state.mode = ViewMode.DETAIL
                            completed_action = f"category_{selected_category.id}"
                            full_refresh = True
                    elif state.mode == ViewMode.DETAIL and nodes:
                        selected_view = detail_view_at(gesture.x, gesture.y)
                        if selected_view:
                            state.detail_view = DetailView(selected_view)
                            completed_action = f"view_{selected_view}"
                            full_refresh = True
                        else:
                            selected_metric = metric_at(
                                state.category_id(nodes[index]),
                                gesture.x,
                                gesture.y,
                            )
                            if selected_metric:
                                state.metric_by_category[state.category_id(nodes[index])] = selected_metric.id
                                completed_action = f"metric_{selected_metric.id}"
                    changed = changed or completed_action is not None

                if should_return_to_overview(
                    state,
                    now,
                    detail_timeout,
                    menu_timeout,
                    touch.pressed,
                ):
                    state.mode = ViewMode.OVERVIEW
                    completed_action = "timeout_overview"
                    changed = True
                    full_refresh = True

                if gesture and completed_action is None:
                    touch_started = None

                if (
                    auto_rotate
                    and len(nodes) > 1
                    and now >= pause_until
                    and now - last_rotation >= auto_rotate
                    and recognizer.state == GestureState.IDLE
                ):
                    index = move(index, len(nodes), 1)
                    state.selected_node_id = nodes[index]["node_id"]
                    state.selected_gpu_index = 0
                    last_rotation = now
                    changed = True
                    full_refresh = True

                state_signature = json.dumps(
                    (
                        hub_online,
                        nodes,
                        state.mode.value,
                        state.selected_node_id,
                        state.selected_category_id,
                        state.metric_by_category,
                        state.detail_view.value,
                        state.selected_gpu_index,
                        pressed_action,
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
                        state,
                        history,
                        pressed_action,
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
                    if feedback_pending and pressed_action and touch_started is not None:
                        conversion_ms, spi_ms = lcd.last_timing_ms
                        LOG.info(
                            "touch_feedback action=%s total_ms=%.1f render_ms=%.1f rgb565_ms=%.1f spi_ms=%.1f region=%s",
                            pressed_action,
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
                            "gesture action=%s total_ms=%.1f render_ms=%.1f rgb565_ms=%.1f spi_ms=%.1f region=%s",
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
