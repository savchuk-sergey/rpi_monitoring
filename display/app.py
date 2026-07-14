import argparse
import asyncio
import json
import logging
from pathlib import Path

import aiohttp
from PIL import ImageChops

from display.drivers.ili9341 import ILI9341
from display.drivers.xpt2046 import XPT2046
from display.gestures import GestureKind, GestureState, TouchRecognizer
from display.history import HistoryStore
from display.navigation import map_touch, power_confirm_action_at, selected_index
from display.ui_state import (
    AutoRotateTick,
    DataRefreshed,
    InactivityTick,
    LongPress,
    PowerHoldCancelled,
    PowerHoldReleased,
    PowerHoldStarted,
    PowerHoldTick,
    Screen,
    ShortPress,
    UiContext,
    UiEffect,
    UiState,
    power_hold_progress,
    reduce_ui,
    visible_action_at,
)
from display.renderer import render


LOG = logging.getLogger("homelab-resource-monitor-display")


async def run(config: dict) -> None:
    local_target_name = str(
        config.get("local_node_id")
        or "LOCAL DISPLAY"
    ).strip() or "LOCAL DISPLAY"
    power_confirm_hold_seconds = float(
        config.get(
            "power_confirm_hold_seconds",
            1.5,
        )
    )
    if power_confirm_hold_seconds <= 0:
        raise ValueError(
            "power_confirm_hold_seconds must be positive"
        )
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
    loop = asyncio.get_running_loop()
    initial_now = loop.time()
    state = UiState(
        last_interaction_at=initial_now,
        last_rotation_at=initial_now,
    )
    nodes: list[dict] = []
    hub_online = True
    pressed_action: str | None = None
    touch_started: float | None = None
    feedback_pending = False
    auto_rotate = max(0.0, float(config.get("auto_rotate_seconds", 0)))
    pause_after_touch = max(0.0, float(config.get("pause_after_touch_seconds", 30)))
    detail_timeout = max(0.0, float(config.get("detail_timeout_seconds", 45)))
    menu_timeout = max(0.0, float(config.get("menu_timeout_seconds", 15)))
    signature = ""
    lcd.initialize()
    last_frame = render(None)
    lcd.show(last_frame)
    timeout = aiohttp.ClientTimeout(total=2)
    next_refresh = 0.0
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
                    context = UiContext(
                        tuple(nodes),
                        pause_after_touch,
                        detail_timeout,
                        menu_timeout,
                        auto_rotate,
                        power_confirm_hold_seconds,
                    )
                    transition = reduce_ui(
                        state,
                        DataRefreshed(tuple(nodes), hub_online, now),
                        context,
                    )
                    state = transition.state
                    changed |= transition.changed
                    full_refresh |= transition.full_refresh
                    if transition.completed_action is not None:
                        completed_action = transition.completed_action
                    assert transition.effect is UiEffect.NONE
                    next_refresh = now + 0.5

                context = UiContext(
                    tuple(nodes),
                    pause_after_touch,
                    detail_timeout,
                    menu_timeout,
                    auto_rotate,
                    power_confirm_hold_seconds,
                )
                gesture = None
                if touch.pressed:
                    raw = touch.read(3)
                    x, y = map_touch(*raw, calibration)
                    was_idle = recognizer.state == GestureState.IDLE
                    gesture = recognizer.update(True, x, y, now)
                    if was_idle and recognizer.state == GestureState.PRESSED:
                        touch_started = now
                        index = selected_index(
                            nodes,
                            state.selected_node_id,
                            state.node_index_hint,
                        )
                        node = nodes[index] if nodes else None
                        pressed_action = visible_action_at(
                            state,
                            node,
                            x,
                            y,
                            tuple(nodes),
                        )
                        feedback_pending = pressed_action is not None
                        changed |= feedback_pending
                        if (
                            pressed_action == "power_hold"
                            and state.screen == Screen.POWER_CONFIRM
                        ):
                            transition = reduce_ui(
                                state,
                                PowerHoldStarted(now),
                                context,
                            )
                            state = transition.state
                            changed |= transition.changed
                            full_refresh |= transition.full_refresh
                            if transition.completed_action is not None:
                                completed_action = transition.completed_action
                            assert transition.effect is UiEffect.NONE
                    if (
                        pressed_action == "power_hold"
                        and state.screen == Screen.POWER_CONFIRM
                    ):
                        if (
                            recognizer.state != GestureState.WAIT_RELEASE
                            and power_confirm_action_at(x, y) == "power_hold"
                        ):
                            transition = reduce_ui(
                                state,
                                PowerHoldTick(now),
                                context,
                            )
                            state = transition.state
                            changed |= transition.changed
                            full_refresh |= transition.full_refresh
                            if transition.completed_action is not None:
                                completed_action = transition.completed_action
                            assert transition.effect is UiEffect.NONE
                            if state.screen == Screen.POWER_PENDING:
                                recognizer.consume_current_press()
                                gesture = None
                                pressed_action = None
                                feedback_pending = False
                        else:
                            transition = reduce_ui(
                                state,
                                PowerHoldCancelled(now),
                                context,
                            )
                            state = transition.state
                            changed |= transition.changed
                            full_refresh |= transition.full_refresh
                            if transition.completed_action is not None:
                                completed_action = transition.completed_action
                            assert transition.effect is UiEffect.NONE
                            pressed_action = None
                            feedback_pending = False
                    elif recognizer.state == GestureState.WAIT_RELEASE and pressed_action:
                        pressed_action = None
                        feedback_pending = False
                        changed = True
                else:
                    gesture = recognizer.update(False, now=now)
                    released_action = pressed_action
                    if (
                        released_action == "power_hold"
                        and state.screen == Screen.POWER_CONFIRM
                    ):
                        transition = reduce_ui(
                            state,
                            PowerHoldReleased(now),
                            context,
                        )
                        state = transition.state
                        changed |= transition.changed
                        full_refresh |= transition.full_refresh
                        if transition.completed_action is not None:
                            completed_action = transition.completed_action
                        assert transition.effect is UiEffect.NONE
                    if pressed_action:
                        pressed_action = None
                        changed = True

                if gesture:
                    event = (
                        LongPress(gesture.x, gesture.y, now)
                        if gesture.kind == GestureKind.LONG
                        else ShortPress(gesture.x, gesture.y, now)
                    )
                    transition = reduce_ui(state, event, context)
                    state = transition.state
                    changed |= transition.changed
                    full_refresh |= transition.full_refresh
                    if transition.completed_action is not None:
                        completed_action = transition.completed_action
                    assert transition.effect is UiEffect.NONE

                transition = reduce_ui(
                    state,
                    InactivityTick(now, touch.pressed),
                    context,
                )
                state = transition.state
                changed |= transition.changed
                full_refresh |= transition.full_refresh
                if transition.completed_action is not None:
                    completed_action = transition.completed_action
                assert transition.effect is UiEffect.NONE

                if gesture and completed_action is None:
                    touch_started = None

                transition = reduce_ui(
                    state,
                    AutoRotateTick(
                        now,
                        recognizer.state == GestureState.IDLE,
                    ),
                    context,
                )
                state = transition.state
                changed |= transition.changed
                full_refresh |= transition.full_refresh
                if transition.completed_action is not None:
                    completed_action = transition.completed_action
                assert transition.effect is UiEffect.NONE

                state_signature = json.dumps(
                    (
                        hub_online,
                        nodes,
                        state.screen.value,
                        state.selected_node_id,
                        state.selected_category_id,
                        state.metric_by_category,
                        state.selected_gpu_index,
                        state.menu_page,
                        state.nodes_page,
                        local_target_name,
                        state.pending_power_action.value if state.pending_power_action else None,
                        state.confirmation_started_at,
                        power_confirm_hold_seconds,
                        round(
                            power_hold_progress(
                                state,
                                now,
                                power_confirm_hold_seconds,
                            )
                            * 20
                        ),
                        pressed_action,
                        int(now),
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if changed or state_signature != signature:
                    index = selected_index(
                        nodes,
                        state.selected_node_id,
                        state.node_index_hint,
                    )
                    render_started = loop.time()
                    frame = render(
                        nodes[index] if nodes else None,
                        (index + 1, len(nodes)),
                        hub_online,
                        state,
                        history,
                        pressed_action,
                        nodes=tuple(nodes),
                        local_target_name=local_target_name,
                        interaction_now=now,
                        power_confirm_hold_seconds=power_confirm_hold_seconds,
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
