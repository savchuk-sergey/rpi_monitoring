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
from display.power_client import (
    DEFAULT_POWER_SOCKET,
    request_power_action,
    validate_power_socket_path,
)
from display.ui_state import (
    AutoRotateTick,
    DataRefreshed,
    InactivityTick,
    LongPress,
    PowerAction,
    PowerHoldCancelled,
    PowerHoldReleased,
    PowerHoldStarted,
    PowerHoldTick,
    PowerRequestAccepted,
    PowerRequestFailed,
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
    configured_power_enabled = config.get(
        "power_actions_enabled",
        False,
    )
    if not isinstance(configured_power_enabled, bool):
        raise ValueError("power_actions_enabled must be a boolean")
    power_actions_enabled = configured_power_enabled
    power_socket = validate_power_socket_path(
        config.get(
            "power_socket",
            DEFAULT_POWER_SOCKET,
        )
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
    queued_power_effect: tuple[UiEffect, PowerAction] | None = None
    force_full_refresh_next_iteration = False
    lcd.initialize()
    last_frame = render(
        None,
        power_actions_enabled=power_actions_enabled,
    )
    lcd.show(last_frame)
    timeout = aiohttp.ClientTimeout(total=2)
    next_refresh = 0.0
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                now = loop.time()
                changed = force_full_refresh_next_iteration
                full_refresh = force_full_refresh_next_iteration
                force_full_refresh_next_iteration = False
                completed_action: str | None = None
                power_frame_presented = False

                def apply_transition(transition) -> None:
                    nonlocal state
                    nonlocal changed
                    nonlocal full_refresh
                    nonlocal completed_action
                    nonlocal queued_power_effect

                    state = transition.state
                    changed |= transition.changed
                    full_refresh |= transition.full_refresh
                    if transition.completed_action is not None:
                        completed_action = transition.completed_action
                    if transition.effect is UiEffect.NONE:
                        return
                    if transition.effect is not UiEffect.REQUEST_POWER:
                        raise AssertionError(
                            f"unknown UI effect: {transition.effect!r}"
                        )
                    if state.pending_power_action is None:
                        raise AssertionError(
                            "power request effect requires an action"
                        )
                    if queued_power_effect is not None:
                        raise AssertionError("multiple UI effects queued")
                    queued_power_effect = (
                        transition.effect,
                        state.pending_power_action,
                    )
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
                        power_actions_enabled=power_actions_enabled,
                    )
                    transition = reduce_ui(
                        state,
                        DataRefreshed(tuple(nodes), hub_online, now),
                        context,
                    )
                    apply_transition(transition)
                    next_refresh = now + 0.5

                context = UiContext(
                    tuple(nodes),
                    pause_after_touch,
                    detail_timeout,
                    menu_timeout,
                    auto_rotate,
                    power_confirm_hold_seconds,
                    power_actions_enabled=power_actions_enabled,
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
                            power_actions_enabled=power_actions_enabled,
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
                            apply_transition(transition)
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
                            apply_transition(transition)
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
                            apply_transition(transition)
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
                        apply_transition(transition)
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
                    apply_transition(transition)

                transition = reduce_ui(
                    state,
                    InactivityTick(now, touch.pressed),
                    context,
                )
                apply_transition(transition)

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
                apply_transition(transition)

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
                        (
                            state.power_request_status.value
                            if state.power_request_status
                            else None
                        ),
                        (
                            state.power_request_error.value
                            if state.power_request_error
                            else None
                        ),
                        power_actions_enabled,
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
                        power_actions_enabled=power_actions_enabled,
                    )
                    render_ms = (loop.time() - render_started) * 1000
                    box = ImageChops.difference(last_frame, frame).getbbox()
                    if box:
                        if full_refresh:
                            lcd.show(frame)
                            if queued_power_effect is not None:
                                power_frame_presented = True
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
                if queued_power_effect is not None:
                    effect, captured_action = queued_power_effect
                    if effect is not UiEffect.REQUEST_POWER:
                        raise AssertionError(f"unknown queued effect: {effect!r}")
                    if not power_frame_presented:
                        raise RuntimeError(
                            "power pending frame was not presented"
                        )
                    try:
                        result = await request_power_action(
                            power_socket,
                            captured_action,
                        )
                        LOG.info(
                            "power_request action=%s result=%s",
                            captured_action.value,
                            (
                                "accepted"
                                if result.accepted
                                else result.error.value
                            ),
                        )
                        result_now = loop.time()
                        if result.accepted:
                            result_event = PowerRequestAccepted(result_now)
                        else:
                            assert result.error is not None
                            result_event = PowerRequestFailed(
                                result.error,
                                result_now,
                            )
                        result_transition = reduce_ui(
                            state,
                            result_event,
                            context,
                        )
                        apply_transition(result_transition)
                        force_full_refresh_next_iteration |= (
                            result_transition.full_refresh
                        )
                    finally:
                        queued_power_effect = None
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
