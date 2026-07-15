from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from math import ceil

from PIL import Image, ImageDraw, ImageFont

from display.categories import can_open_graph, category
from display.detail_model import ChartMetric, ScaleMode, ThresholdTone, ValueTone
from display.formatting import (
    boolean as _format_bool,
    bytes_pair as _format_bytes_pair,
    clock as _format_clock,
    number as _number,
    percent as _format_percent,
    power as _format_power,
    rate as _format_rate,
    temperature as _format_temperature,
    uptime as _format_uptime,
)
from display.history import HistoryStore, Sample
from display.navigation import (
    GRAPH_NEXT_METRIC_HITBOX,
    GRAPH_PREVIOUS_METRIC_HITBOX,
    GRAPH_VALUES_HITBOX,
    MENU_BACK_HITBOX,
    MENU_NEXT_PAGE_HITBOX,
    MENU_PAGES,
    MENU_PREVIOUS_PAGE_HITBOX,
    MENU_TILE_RECTS,
    NODES_BACK_HITBOX,
    NODES_NEXT_PAGE_HITBOX,
    NODES_PREVIOUS_PAGE_HITBOX,
    NODES_ROW_RECTS,
    POWER_CANCEL_CARD_RECT,
    POWER_HOLD_CARD_RECT,
    POWER_HOLD_PROGRESS_RECT,
    POWER_ERROR_BACK_HITBOX,
    SYSTEM_BACK_HITBOX,
    SYSTEM_RESTART_CARD_RECT,
    SYSTEM_SHUTDOWN_CARD_RECT,
    VALUES_GRAPH_BUTTON_RECT,
    normalize_menu_page,
    normalize_nodes_page,
    nodes_page_count,
    nodes_page_items,
)
from display.ui_state import (
    PowerAction,
    PowerRequestError,
    PowerRequestStatus,
    Screen,
    UiState,
    power_hold_progress,
)


SIZE = (320, 240)
BACKGROUND = "#000400"
GREEN = "#43ff6b"
BRIGHT = "#c4ffcf"
MUTED = "#438d50"
RED = "#ff5c5c"
AMBER = "#ffb84d"
FONT_PATH = Path(__file__).with_name("assets") / "ShareTechMono-Regular.ttf"
HEADER_BOTTOM = 40
FOOTER_TOP = 192
GRAPH_HEADER_BOTTOM = 28
GRAPH_PLOT_RECT = (20, 28, 312, 184)
GRAPH_GRID_RECT = (42, 32, 312, 162)
GRAPH_SUMMARY_Y = 178
GRAPH_STATUS_DOT = (6, 10, 12, 16)
GRAPH_IDENTITY_POSITION = (16, 14)
GRAPH_IDENTITY_WIDTH = 112
GRAPH_TITLE_POSITION = (186, 14)
GRAPH_TITLE_WIDTH = 118
GRAPH_META_POSITION = (310, 14)


def render(
    node: dict[str, Any] | None,
    position: tuple[int, int] = (0, 0),
    hub_online: bool = True,
    ui_state: UiState | None = None,
    history: HistoryStore | None = None,
    pressed_action: str | None = None,
    now: datetime | None = None,
    nodes: tuple[dict[str, Any], ...] | None = None,
    local_target_name: str = "LOCAL DISPLAY",
    interaction_now: float | None = None,
    power_confirm_hold_seconds: float = 1.5,
    power_actions_enabled: bool = True,
) -> Image.Image:
    state = ui_state or UiState()
    target_name = str(
        local_target_name
        or "LOCAL DISPLAY"
    ).strip() or "LOCAL DISPLAY"
    snapshot = (
        tuple(nodes)
        if nodes is not None
        else ((node,) if node is not None else ())
    )
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    fonts = {
        "tiny": _font(11),
        "small": _font(13),
        "detail": _font(15),
        "label": _font(18),
        "title": _font(22),
        "value": _font(38),
    }
    if state.screen == Screen.SYSTEM:
        _system(
            draw,
            fonts,
            target_name,
            pressed_action,
            power_actions_enabled,
        )
        _system_footer(draw, fonts, pressed_action)
        return image
    if state.screen == Screen.POWER_CONFIRM:
        _power_confirmation(
            draw,
            fonts,
            state,
            target_name,
            pressed_action,
            (
                interaction_now
                if interaction_now is not None
                else state.confirmation_started_at or 0.0
            ),
            power_confirm_hold_seconds,
        )
        return image
    if state.screen == Screen.POWER_PENDING:
        _power_pending(draw, fonts, state, target_name)
        return image
    if state.screen == Screen.POWER_ERROR:
        _power_error(draw, fonts, state, target_name, pressed_action)
        return image
    if state.screen == Screen.NODES:
        if snapshot:
            _nodes(
                draw,
                fonts,
                snapshot,
                state,
                hub_online,
                pressed_action,
                now,
            )
            _nodes_footer(
                draw,
                fonts,
                state.nodes_page,
                len(snapshot),
                pressed_action,
            )
        else:
            _empty_state(draw, fonts, hub_online)
            _footer(draw, fonts, Screen.OVERVIEW, pressed_action)
        return image
    if node is None:
        _empty_state(draw, fonts, hub_online)
        _footer(draw, fonts, Screen.OVERVIEW, pressed_action)
        return image

    status, status_color = _status(node, hub_online)
    age = _age(node.get("received_at_utc") or node.get("timestamp_utc"), now)
    if state.screen == Screen.MAIN_MENU:
        _menu(draw, fonts, node, snapshot, state, pressed_action)
        _menu_footer(draw, fonts, state.menu_page, pressed_action)
        return image
    elif state.screen == Screen.VALUES:
        _detail_header(draw, fonts, node, position, state, status_color, age)
        _details(draw, fonts, node, state, age, pressed_action)
    elif state.screen == Screen.GRAPH:
        category_id = state.category_id(node)
        if not can_open_graph(category_id):
            _detail_header(draw, fonts, node, position, state, status_color, age)
            _values_detail(draw, fonts, node, state, age)
            _footer(draw, fonts, Screen.VALUES, pressed_action)
            return image
        selected_category = category(category_id)
        metrics = selected_category.chart_metrics
        selected_metric_id = state.metric_id(node)
        selected_metric = next(
            (metric for metric in metrics if metric.id == selected_metric_id),
            metrics[0],
        )
        _graph_header(
            draw,
            fonts,
            node,
            position,
            selected_category.title,
            selected_metric.title,
            status,
            status_color,
            age,
        )
        samples = (
            history.series(node["node_id"], category_id, selected_metric.id)
            if history
            else ()
        )
        _chart(
            draw,
            fonts,
            samples,
            selected_metric,
            selected_metric.value(node, state.selected_gpu_index),
            now,
            history.window_seconds if history else 300,
        )
        _graph_footer(draw, fonts, metrics, selected_metric.id, pressed_action)
        return image
    elif state.screen == Screen.OVERVIEW:
        _header(draw, fonts, node, position, status, status_color, age)
        cpu = node.get("cpu", {})
        gpu = node.get("gpu") or []
        power = node.get("device", {}).get("power_w")
        if power is None:
            power = cpu.get("power_w")
        if gpu:
            third = ("GPU", gpu[0].get("usage_percent"), "%", 0.0, 100.0)
        elif cpu.get("temperature_c") is not None:
            third = ("TEMP", cpu.get("temperature_c"), "C", 20.0, 100.0)
        elif node.get("storage", {}).get("usage_percent") is not None:
            third = ("DISK", node["storage"]["usage_percent"], "%", 0.0, 100.0)
        elif power is not None:
            third = ("PWR", power, "W", 0.0, 100.0)
        else:
            third = ("GPU", None, "%", 0.0, 100.0)
        metrics = (
            ("CPU", cpu.get("usage_percent"), "%", 0.0, 100.0),
            ("RAM", node.get("memory", {}).get("usage_percent"), "%", 0.0, 100.0),
            third,
        )
        for top, (label, value, unit, minimum, maximum) in zip((40, 91, 142), metrics):
            _metric_row(draw, fonts, top, label, value, unit, minimum, maximum)
    else:
        raise ValueError(f"unsupported screen: {state.screen.value}")

    _footer(draw, fonts, state.screen, pressed_action)
    return image


def _header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    position: tuple[int, int],
    status: str,
    status_color: str,
    age: str,
) -> None:
    draw.ellipse((10, 8, 18, 16), fill=status_color)
    draw.text((24, 12), status, font=fonts["small"], fill=status_color, anchor="lm")
    draw.text(
        (310, 12),
        f"{position[0]}/{position[1]}",
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )
    name = _fit(
        draw,
        str(node.get("display_name", node["node_id"])).upper(),
        fonts["title"],
        250,
    )
    draw.text((10, 31), name, font=fonts["title"], fill=GREEN, anchor="lm")
    draw.text((310, 31), age, font=fonts["small"], fill=MUTED, anchor="rm")


def _details(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    state: UiState,
    age: str,
    pressed_action: str | None,
) -> None:
    category_id = state.category_id(node)
    _values_detail(draw, fonts, node, state, age)
    if can_open_graph(category_id):
        _open_graph_action(draw, fonts, pressed_action == "open_graph")


def _open_graph_action(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    pressed: bool,
) -> None:
    draw.rectangle(
        VALUES_GRAPH_BUTTON_RECT,
        fill=MUTED if pressed else None,
        outline=None if pressed else GREEN,
        width=1,
    )
    draw.text(
        (160, 166),
        "OPEN GRAPH",
        font=fonts["detail"],
        fill=BACKGROUND if pressed else GREEN,
        anchor="mm",
    )

def _values_detail(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    state: UiState,
    age: str,
) -> None:
    selected = category(state.category_id(node))
    layout = selected.values_layout
    if layout.title is not None:
        draw.text((10, layout.title_y), layout.title, font=fonts["detail"], fill=GREEN, anchor="lm")
    colors = {
        ValueTone.NORMAL: BRIGHT,
        ValueTone.WARNING: AMBER,
        ValueTone.CRITICAL: RED,
    }
    for y, row in zip(layout.row_y_positions, selected.value_rows):
        value = row.text(node, state.selected_gpu_index, age)
        if row.fit_width is not None:
            value = _fit(draw, value, fonts["detail"], row.fit_width)
        draw.text((10, y), row.title, font=fonts["detail"], fill=MUTED, anchor="lm")
        draw.text(
            (310, y),
            value,
            font=fonts["detail"],
            fill=colors[row.tone(node, state.selected_gpu_index, age)],
            anchor="rm",
        )

def _detail_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    position: tuple[int, int],
    state: UiState,
    status_color: str,
    age: str,
) -> None:
    selected = category(state.category_id(node))
    name = _fit(
        draw,
        str(node.get("display_name", node["node_id"])).upper(),
        fonts["detail"],
        135,
    )
    draw.ellipse((8, 11, 16, 19), fill=status_color)
    draw.text((22, 15), name, font=fonts["detail"], fill=GREEN, anchor="lm")
    draw.text(
        (205, 15),
        f"/ {selected.title}",
        font=fonts["detail"],
        fill=GREEN,
        anchor="mm",
    )
    draw.text(
        (310, 15),
        f"{position[0]}/{position[1]}  {age}",
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )


def _graph_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    position: tuple[int, int],
    category_title: str,
    metric_title: str,
    status: str,
    status_color: str,
    age: str,
) -> None:
    draw.rectangle(GRAPH_STATUS_DOT, fill=status_color)
    display_name = str(node.get("display_name", node["node_id"]))
    identity = _fit(
        draw,
        f"{status} {display_name.upper()}",
        fonts["small"],
        GRAPH_IDENTITY_WIDTH,
    )
    draw.text(
        GRAPH_IDENTITY_POSITION,
        identity,
        font=fonts["small"],
        fill=status_color,
        anchor="lm",
    )
    title = _fit(
        draw,
        f"{category_title} / {metric_title}",
        fonts["detail"],
        GRAPH_TITLE_WIDTH,
    )
    draw.text(
        GRAPH_TITLE_POSITION,
        title,
        font=fonts["detail"],
        fill=BRIGHT,
        anchor="mm",
    )
    draw.text(
        GRAPH_META_POSITION,
        f"{position[0]}/{position[1]} {age}",
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )


def _menu(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    node: dict[str, Any],
    nodes: tuple[dict[str, Any], ...],
    state: UiState,
    pressed_action: str | None,
) -> None:
    draw.text((10, 16), "MENU", font=fonts["detail"], fill=GREEN, anchor="lm")
    name = _fit(
        draw,
        str(node.get("display_name", node["node_id"])).upper(),
        fonts["small"],
        180,
    )
    draw.text((310, 16), name, font=fonts["small"], fill=MUTED, anchor="rm")
    selected_id = state.category_id(node)
    errors = node.get("collector", {}).get("errors") or []
    page = normalize_menu_page(state.menu_page)
    for category_id, (left, top, right, bottom) in zip(MENU_PAGES[page], MENU_TILE_RECTS):
        center_x = (left + right) // 2
        icon_box = (center_x - 20, top + 5, center_x + 20, top + 45)
        if category_id == "nodes":
            title = "NODES"
            available = bool(nodes)
            color = GREEN if available else MUTED
            icon = _draw_nodes_menu_icon
        elif category_id == "system":
            title = "SYSTEM"
            color = GREEN
            available = True
            icon = _draw_system_menu_icon
        else:
            item = category(category_id)
            title = item.title
            available = item.available(node)
            selected = available and category_id == selected_id
            color = (
                BRIGHT
                if selected
                else AMBER if category_id == "health" and errors else GREEN if available else MUTED
            )
            icon = item.icon
        pressed = available and pressed_action == f"menu_tile_{category_id}"
        hinted = not available and pressed_action == f"menu_hint_{category_id}"
        visual_rect = (left + 3, top + 3, right - 4, bottom - 4)
        if pressed:
            draw.rectangle(visual_rect, fill=MUTED)
        elif category_id == selected_id and available:
            draw.rectangle(visual_rect, outline=MUTED, width=1)
        icon(draw, icon_box, BACKGROUND if pressed else color)
        draw.text(
            (center_x, top + 59),
            title,
            font=fonts["tiny"],
            fill=BACKGROUND if pressed else MUTED,
            anchor="mm",
        )
        if hinted:
            draw.text(
                (center_x, top + 72),
                "NO NODES" if category_id == "nodes" else "NO DATA",
                font=fonts["tiny"],
                fill=MUTED,
                anchor="mm",
            )


def _nodes(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    nodes: tuple[dict[str, Any], ...],
    state: UiState,
    hub_online: bool,
    pressed_action: str | None,
    now: datetime | None,
) -> None:
    draw.text((10, 16), "NODES", font=fonts["detail"], fill=GREEN, anchor="lm")
    count_text = "1 NODE" if len(nodes) == 1 else f"{len(nodes)} NODES"
    draw.text(
        (310, 16),
        count_text,
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )
    for index, (node, (left, top, right, bottom)) in enumerate(
        zip(nodes_page_items(nodes, state.nodes_page), NODES_ROW_RECTS)
    ):
        action = f"nodes_select_{index}"
        pressed = pressed_action == action
        selected = node.get("node_id") == state.selected_node_id
        visual_rect = (left + 3, top + 3, right - 4, bottom - 4)
        if pressed:
            draw.rectangle(visual_rect, fill=MUTED)
        elif selected:
            draw.rectangle(visual_rect, outline=MUTED, width=1)

        status, status_color = _status(node, hub_online)
        status = _fit(draw, status, fonts["small"], 76)
        name = _fit(
            draw,
            str(node.get("display_name", node["node_id"])).upper(),
            fonts["detail"],
            142,
        )
        age = _age(
            node.get("received_at_utc")
            or node.get("timestamp_utc"),
            now,
        )
        cpu_text = f"CPU {_format_percent(node.get('cpu', {}).get('usage_percent'))}"
        ram_text = f"RAM {_format_percent(node.get('memory', {}).get('usage_percent'))}"
        temperature = node.get("cpu", {}).get("temperature_c")
        gpus = node.get("gpu") or []
        gpu_usage = gpus[0].get("usage_percent") if gpus else None
        storage_usage = node.get("storage", {}).get("usage_percent")
        if temperature is not None:
            third_text = f"TEMP {_format_temperature(temperature)}"
        elif gpu_usage is not None:
            third_text = f"GPU {_format_percent(gpu_usage)}"
        elif storage_usage is not None:
            third_text = f"DISK {_format_percent(storage_usage)}"
        else:
            third_text = "N/A"

        status_foreground = BACKGROUND if pressed else status_color
        name_foreground = BACKGROUND if pressed else BRIGHT if selected else GREEN
        summary_foreground = BACKGROUND if pressed else BRIGHT
        draw.ellipse(
            (8, top + 9, 16, top + 17),
            fill=status_foreground,
        )
        draw.text(
            (22, top + 13),
            status,
            font=fonts["small"],
            fill=status_foreground,
            anchor="lm",
        )
        draw.text(
            (104, top + 13),
            name,
            font=fonts["detail"],
            fill=name_foreground,
            anchor="lm",
        )
        draw.text(
            (310, top + 13),
            age,
            font=fonts["small"],
            fill=BACKGROUND if pressed else MUTED,
            anchor="rm",
        )
        for x, text in (
            (10, cpu_text),
            (112, ram_text),
            (220, third_text),
        ):
            draw.text(
                (x, top + 38),
                text,
                font=fonts["small"],
                fill=summary_foreground,
                anchor="lm",
            )

    for y in (85, 138, 192):
        draw.line((0, y, 319, y), fill=MUTED)


def _nodes_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    page: int,
    node_count: int,
    pressed_action: str | None,
) -> None:
    page_count = nodes_page_count(node_count)
    page = normalize_nodes_page(page, node_count)
    buttons = (
        ("nodes_previous_page", NODES_PREVIOUS_PAGE_HITBOX, "<"),
        ("nodes_back", NODES_BACK_HITBOX, f"BACK {page + 1}/{page_count}"),
        ("nodes_next_page", NODES_NEXT_PAGE_HITBOX, ">"),
    )
    draw.line((0, 192, 319, 192), fill=MUTED)
    for action, hitbox, label in buttons:
        box = (hitbox[0], hitbox[1], hitbox[2] - 1, hitbox[3] - 1)
        actionable = action == "nodes_back" or page_count > 1
        pressed = actionable and action == pressed_action
        if pressed:
            draw.rectangle(box, fill=MUTED)
        draw.text(
            ((box[0] + box[2]) // 2, 216),
            label,
            font=fonts["small"] if action == "nodes_back" else fonts["label"],
            fill=(
                BACKGROUND
                if pressed
                else GREEN if actionable
                else MUTED
            ),
            anchor="mm",
        )


def _draw_nodes_menu_icon(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
) -> None:
    left, top, right, bottom = box
    center_x = (left + right) // 2
    for rectangle in (
        (center_x - 3, top + 2, center_x + 3, top + 8),
        (left + 2, bottom - 9, left + 8, bottom - 3),
        (right - 8, bottom - 9, right - 2, bottom - 3),
    ):
        draw.rectangle(rectangle, outline=fill, width=2)
    for line in (
        (center_x, top + 8, center_x, top + 14),
        (left + 5, top + 14, right - 5, top + 14),
        (left + 5, top + 14, left + 5, bottom - 9),
        (right - 5, top + 14, right - 5, bottom - 9),
    ):
        draw.line(line, fill=fill, width=2)


def _draw_system_menu_icon(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
) -> None:
    left, top, right, bottom = box
    draw.rectangle(
        (left + 2, top + 4, right - 2, bottom - 4),
        outline=fill,
        width=2,
    )
    draw.line(
        (
            (left + 7, top + 11),
            (left + 12, top + 16),
            (left + 7, top + 21),
        ),
        fill=fill,
        width=2,
    )
    draw.line((left + 16, top + 22, right - 7, top + 22), fill=fill, width=2)


def _system(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    local_target_name: str,
    pressed_action: str | None,
    power_actions_enabled: bool,
) -> None:
    draw.text((10, 16), "SYSTEM", font=fonts["detail"], fill=GREEN, anchor="lm")
    draw.text(
        (310, 16),
        _fit(draw, local_target_name.upper(), fonts["small"], 190),
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )
    restart_pressed = power_actions_enabled and pressed_action == "system_restart"
    restart_color = (
        BACKGROUND if restart_pressed else AMBER if power_actions_enabled else MUTED
    )
    draw.rectangle(
        SYSTEM_RESTART_CARD_RECT,
        fill=MUTED if restart_pressed else BACKGROUND,
        outline=AMBER if power_actions_enabled else MUTED,
        width=2,
    )
    _draw_restart_icon(draw, (20, 48, 48, 76), restart_color)
    draw.text((58, 56), "RESTART", font=fonts["label"], fill=restart_color, anchor="lm")
    draw.text(
        (58, 82),
        "TAP TO CONFIRM" if power_actions_enabled else "DISABLED BY CONFIG",
        font=fonts["small"],
        fill=restart_color,
        anchor="lm",
    )
    shutdown_pressed = power_actions_enabled and pressed_action == "system_shutdown"
    shutdown_color = (
        BACKGROUND if shutdown_pressed else RED if power_actions_enabled else MUTED
    )
    draw.rectangle(
        SYSTEM_SHUTDOWN_CARD_RECT,
        fill=MUTED if shutdown_pressed else BACKGROUND,
        outline=RED if power_actions_enabled else MUTED,
        width=2,
    )
    _draw_shutdown_icon(draw, (20, 128, 48, 156), shutdown_color)
    draw.text((58, 136), "SHUTDOWN", font=fonts["label"], fill=shutdown_color, anchor="lm")
    draw.text(
        (58, 162),
        "TAP TO CONFIRM" if power_actions_enabled else "DISABLED BY CONFIG",
        font=fonts["small"],
        fill=shutdown_color,
        anchor="lm",
    )


def _power_confirmation(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    state: UiState,
    local_target_name: str,
    pressed_action: str | None,
    interaction_now: float,
    hold_seconds: float,
) -> None:
    action = state.pending_power_action
    if action == PowerAction.REBOOT:
        title, consequence, color = (
            "CONFIRM RESTART",
            "LOCAL DISPLAY WILL RESTART",
            AMBER,
        )
    elif action == PowerAction.POWEROFF:
        title, consequence, color = (
            "CONFIRM SHUTDOWN",
            "LOCAL DISPLAY WILL SHUT DOWN",
            RED,
        )
    else:
        title, consequence, color = "CONFIRM ACTION", "NO ACTION SELECTED", MUTED
    draw.text((10, 16), title, font=fonts["detail"], fill=color, anchor="lm")
    draw.text(
        (310, 16),
        _fit(draw, local_target_name.upper(), fonts["small"], 150),
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )
    draw.text((160, 64), consequence, font=fonts["label"], fill=color, anchor="mm")
    draw.text(
        (160, 94),
        "REMOTE NODES ARE NOT AFFECTED",
        font=fonts["small"],
        fill=GREEN,
        anchor="mm",
    )
    draw.text(
        (160, 132),
        "HOLD THE RIGHT BUTTON TO CONFIRM",
        font=fonts["small"],
        fill=BRIGHT,
        anchor="mm",
    )
    draw.text(
        (160, 158),
        "RELEASE OR MOVE AWAY TO CANCEL",
        font=fonts["small"],
        fill=MUTED,
        anchor="mm",
    )
    draw.line((0, 192, 319, 192), fill=MUTED)
    cancel_pressed = pressed_action == "power_cancel"
    if cancel_pressed:
        draw.rectangle(POWER_CANCEL_CARD_RECT, fill=MUTED)
    draw.text(
        (55, 216),
        "CANCEL",
        font=fonts["label"],
        fill=BACKGROUND if cancel_pressed else GREEN,
        anchor="mm",
    )
    hold_enabled = action is not None
    hold_pressed = hold_enabled and pressed_action == "power_hold"
    draw.rectangle(
        POWER_HOLD_CARD_RECT,
        fill=MUTED if hold_pressed else BACKGROUND,
        outline=color if hold_enabled else MUTED,
        width=1,
    )
    draw.text(
        (216, 207),
        "HOLD TO CONFIRM",
        font=fonts["small"],
        fill=BACKGROUND if hold_pressed else color,
        anchor="mm",
    )
    draw.rectangle(POWER_HOLD_PROGRESS_RECT, outline=MUTED, width=1)
    progress = power_hold_progress(state, interaction_now, hold_seconds)
    if progress > 0:
        left = POWER_HOLD_PROGRESS_RECT[0] + 1
        inner_width = POWER_HOLD_PROGRESS_RECT[2] - POWER_HOLD_PROGRESS_RECT[0] - 2
        draw.rectangle(
            (
                left,
                POWER_HOLD_PROGRESS_RECT[1] + 1,
                left + round(inner_width * progress),
                POWER_HOLD_PROGRESS_RECT[3] - 1,
            ),
            fill=color,
        )


def _power_pending(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    state: UiState,
    local_target_name: str,
) -> None:
    action = state.pending_power_action
    if action == PowerAction.REBOOT:
        action_title, color = "RESTART REQUEST", AMBER
    elif action == PowerAction.POWEROFF:
        action_title, color = "SHUTDOWN REQUEST", RED
    else:
        action_title, color = "POWER REQUEST", MUTED
    draw.text((10, 16), "POWER REQUEST", font=fonts["detail"], fill=GREEN, anchor="lm")
    draw.text(
        (310, 16),
        _fit(draw, local_target_name.upper(), fonts["small"], 150),
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )
    draw.text((160, 72), action_title, font=fonts["label"], fill=color, anchor="mm")
    if state.power_request_status == PowerRequestStatus.SENDING:
        lines = (
            ("SENDING REQUEST", fonts["detail"], BRIGHT),
            ("WAITING FOR LOCAL HELPER", fonts["small"], GREEN),
            ("PENDING FRAME DISPLAYED FIRST", fonts["tiny"], MUTED),
        )
    elif state.power_request_status == PowerRequestStatus.ACCEPTED:
        lines = (
            ("REQUEST ACCEPTED", fonts["detail"], BRIGHT),
            ("WAITING FOR LOCAL SYSTEM", fonts["small"], GREEN),
            ("LOCAL HELPER CONFIRMED REQUEST", fonts["tiny"], MUTED),
        )
    else:
        lines = (("REQUEST STATE UNKNOWN", fonts["detail"], MUTED),)
    for y, (text, font, fill) in zip((112, 142, 170), lines):
        draw.text((160, y), text, font=font, fill=fill, anchor="mm")


def _power_error(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    state: UiState,
    local_target_name: str,
    pressed_action: str | None,
) -> None:
    if state.pending_power_action == PowerAction.REBOOT:
        action_title, color = "RESTART REQUEST FAILED", AMBER
    elif state.pending_power_action == PowerAction.POWEROFF:
        action_title, color = "SHUTDOWN REQUEST FAILED", RED
    else:
        action_title, color = "POWER REQUEST FAILED", MUTED
    error_labels = {
        PowerRequestError.HELPER_UNAVAILABLE: "HELPER UNAVAILABLE",
        PowerRequestError.PERMISSION_DENIED: "PERMISSION DENIED",
        PowerRequestError.TIMEOUT: "REQUEST TIMED OUT",
        PowerRequestError.PROTOCOL_ERROR: "INVALID HELPER RESPONSE",
        PowerRequestError.IO_ERROR: "LOCAL I/O ERROR",
    }
    error_label = (
        error_labels[state.power_request_error]
        if state.power_request_error is not None
        else "UNKNOWN LOCAL ERROR"
    )

    draw.text((10, 16), "POWER ERROR", font=fonts["detail"], fill=RED, anchor="lm")
    draw.text(
        (310, 16),
        _fit(draw, local_target_name.upper(), fonts["small"], 150),
        font=fonts["small"],
        fill=MUTED,
        anchor="rm",
    )
    draw.text((160, 62), action_title, font=fonts["label"], fill=color, anchor="mm")
    draw.text((160, 98), error_label, font=fonts["detail"], fill=RED, anchor="mm")
    draw.text(
        (160, 132),
        "NO ACCEPTANCE RECEIVED",
        font=fonts["small"],
        fill=BRIGHT,
        anchor="mm",
    )
    draw.text(
        (160, 162),
        "CHECK LOCAL POWER HELPER",
        font=fonts["small"],
        fill=MUTED,
        anchor="mm",
    )
    draw.line((0, 192, 319, 192), fill=MUTED)
    pressed = pressed_action == "power_error_back"
    if pressed:
        draw.rectangle(
            (
                POWER_ERROR_BACK_HITBOX[0],
                POWER_ERROR_BACK_HITBOX[1],
                POWER_ERROR_BACK_HITBOX[2] - 1,
                POWER_ERROR_BACK_HITBOX[3] - 1,
            ),
            fill=MUTED,
        )
    draw.text(
        (159, 216),
        "BACK",
        font=fonts["small"],
        fill=BACKGROUND if pressed else GREEN,
        anchor="mm",
    )


def _draw_restart_icon(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
) -> None:
    left, top, right, bottom = box
    draw.arc((left + 2, top + 2, right - 2, bottom - 2), 35, 330, fill=fill, width=2)
    draw.polygon(((right - 7, top + 1), (right, top + 2), (right - 3, top + 9)), fill=fill)


def _draw_shutdown_icon(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
) -> None:
    left, top, right, bottom = box
    draw.ellipse((left + 2, top + 2, right - 2, bottom - 2), outline=fill, width=2)
    center_x = (left + right) // 2
    draw.line((center_x, top - 1, center_x, top + 13), fill=fill, width=3)


def _system_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    pressed_action: str | None,
) -> None:
    draw.line((0, 192, 319, 192), fill=MUTED)
    box = (
        SYSTEM_BACK_HITBOX[0],
        SYSTEM_BACK_HITBOX[1],
        SYSTEM_BACK_HITBOX[2] - 1,
        SYSTEM_BACK_HITBOX[3] - 1,
    )
    pressed = pressed_action == "system_back"
    if pressed:
        draw.rectangle(box, fill=MUTED)
    draw.text(
        (159, 216),
        "BACK",
        font=fonts["small"],
        fill=BACKGROUND if pressed else GREEN,
        anchor="mm",
    )


def _chart(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    samples: tuple[Sample, ...],
    metric: ChartMetric,
    current: Any,
    now: datetime | None,
    window_seconds: int,
) -> None:
    left, top, right, bottom = GRAPH_GRID_RECT
    values = [sample.value for sample in samples if sample.value is not None]
    if metric.scale.mode is ScaleMode.FIXED:
        minimum = metric.scale.minimum
        maximum = metric.scale.maximum
        assert maximum is not None
    elif metric.scale.mode is ScaleMode.DYNAMIC_ZERO_BASED:
        minimum = 0.0
        observed = max(values + ([float(current)] if current is not None else []) + [1.0])
        maximum = max(
            1.0,
            ceil(observed / metric.scale.step) * metric.scale.step,
        )
    else:
        raise ValueError("dynamic range scale is not implemented")
    for y in (top, (top + bottom) // 2, bottom):
        draw.line((left, y, right, y), fill=MUTED)
    threshold_colors = {
        ThresholdTone.WARNING: AMBER,
        ThresholdTone.CRITICAL: RED,
    }
    for threshold in metric.thresholds:
        y = round(bottom - (threshold.value - minimum) / (maximum - minimum) * (bottom - top))
        draw.line((right - 18, y, right, y), fill=threshold_colors[threshold.tone])
    draw.text((38, top), _number(maximum), font=fonts["tiny"], fill=MUTED, anchor="rm")
    draw.text((38, bottom), _number(minimum), font=fonts["tiny"], fill=MUTED, anchor="rm")

    end = (
        (now or datetime.now(timezone.utc)).timestamp()
        if not samples
        else max(samples[-1].timestamp, (now or datetime.now(timezone.utc)).timestamp())
    )
    start = end - window_seconds
    segment: list[tuple[int, int]] = []
    last_point = None
    for sample in samples:
        if sample.value is None or sample.timestamp < start:
            if len(segment) > 1:
                draw.line(segment, fill=GREEN, width=2)
            segment = []
            continue
        x = round(left + (sample.timestamp - start) / window_seconds * (right - left))
        ratio = (float(sample.value) - minimum) / (maximum - minimum)
        y = round(bottom - min(1.0, max(0.0, ratio)) * (bottom - top))
        segment.append((x, y))
        last_point = (x, y)
    if len(segment) > 1:
        draw.line(segment, fill=GREEN, width=2)
    elif len(segment) == 1:
        draw.point(segment[0], fill=GREEN)
    if last_point:
        x, y = last_point
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=BRIGHT)
    elif not values:
        draw.text((177, 97), "COLLECTING HISTORY", font=fonts["small"], fill=MUTED, anchor="mm")

    valid = [value for value in values]
    now_value = _format_metric(current, metric.unit)
    minimum_value = _format_metric(min(valid), metric.unit) if valid else "—"
    maximum_value = _format_metric(max(valid), metric.unit) if valid else "—"
    draw.text((10, GRAPH_SUMMARY_Y), f"NOW {now_value}", font=fonts["small"], fill=BRIGHT, anchor="lm")
    draw.text((160, GRAPH_SUMMARY_Y), f"MIN {minimum_value}", font=fonts["small"], fill=MUTED, anchor="mm")
    draw.text((310, GRAPH_SUMMARY_Y), f"MAX {maximum_value}", font=fonts["small"], fill=MUTED, anchor="rm")


def _format_metric(value: Any, unit: str) -> str:
    if unit == "%":
        return _format_percent(value)
    if unit == "C":
        return _format_temperature(value)
    if unit == "W":
        return _format_power(value)
    if unit == "MHz":
        return _format_clock(value)
    if unit == "B/s":
        return _format_rate(value)
    return "—" if value is None else _number(value)


def _empty_state(
    draw: ImageDraw.ImageDraw, fonts: dict[str, Any], hub_online: bool
) -> None:
    color = GREEN if hub_online else AMBER
    title = "WAITING FOR SIGNAL" if hub_online else "LINK LOST"
    detail = "HUB ONLINE" if hub_online else "RETRYING"
    draw.text((160, 101), title, font=fonts["title"], fill=color, anchor="mm")
    draw.text((160, 130), detail, font=fonts["small"], fill=MUTED, anchor="mm")


def _value(value: Any, unit: str) -> str:
    if value is None:
        return "—"
    suffix = "°" if unit == "C" else unit
    return f"{float(value):.0f}{suffix}"


def _status(node: dict[str, Any], hub_online: bool) -> tuple[str, str]:
    if not hub_online:
        return "LINK LOST", AMBER
    if node.get("waiting"):
        return "WAITING", AMBER
    if not node.get("online"):
        return "OFFLINE", RED
    errors = node.get("collector", {}).get("errors") or []
    if errors:
        return f"DEGRADED ERR {len(errors)}", AMBER
    return "ONLINE", GREEN


def _age(timestamp: Any, now: datetime | None = None) -> str:
    if not timestamp:
        return "—"
    try:
        then = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "—"
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _metric_row(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    top: int,
    label: str,
    value: Any,
    unit: str,
    minimum: float,
    maximum: float,
) -> None:
    draw.text((12, top + 22), label, font=fonts["label"], fill=MUTED, anchor="lm")
    draw.text(
        (308, top + 22),
        _value(value, unit),
        font=fonts["value"],
        fill=BRIGHT if value is not None else MUTED,
        anchor="rm",
    )
    active_segments = 0
    if value is not None:
        ratio = min(1.0, max(0.0, (float(value) - minimum) / (maximum - minimum)))
        if ratio > 0:
            active_segments = ceil(ratio * 12)
    for index in range(12):
        left = 64 + index * 13
        box = (left, top + 16, left + 10, top + 27)
        if index < active_segments:
            draw.rectangle(box, fill=GREEN)
        else:
            draw.rectangle(box, fill=BACKGROUND, outline=MUTED)


def _graph_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    metrics: tuple[ChartMetric, ...],
    selected_metric_id: str,
    pressed_action: str | None,
) -> None:
    selected_index = next(
        (index for index, metric in enumerate(metrics) if metric.id == selected_metric_id),
        0,
    )
    if len(metrics) >= 2:
        previous_label = _fit(
            draw,
            f"< {metrics[(selected_index - 1) % len(metrics)].title}",
            fonts["small"],
            56,
        )
        next_label = _fit(
            draw,
            f"{metrics[(selected_index + 1) % len(metrics)].title} >",
            fonts["small"],
            56,
        )
    else:
        previous_label, next_label = "<", ">"
    buttons = (
        ("graph_previous_metric", GRAPH_PREVIOUS_METRIC_HITBOX, previous_label),
        ("graph_values", GRAPH_VALUES_HITBOX, "VALUES"),
        ("graph_next_metric", GRAPH_NEXT_METRIC_HITBOX, next_label),
    )
    draw.line((0, 192, 319, 192), fill=MUTED)
    for action, hitbox, label in buttons:
        box = (hitbox[0], hitbox[1], hitbox[2] - 1, hitbox[3] - 1)
        pressed = action == pressed_action
        if pressed:
            draw.rectangle(box, fill=MUTED)
        draw.text(
            ((box[0] + box[2]) // 2, 216),
            label,
            font=fonts["small"],
            fill=BACKGROUND if pressed else GREEN,
            anchor="mm",
        )


def _menu_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    page: int,
    pressed_action: str | None,
) -> None:
    page = normalize_menu_page(page)
    buttons = (
        ("menu_previous_page", MENU_PREVIOUS_PAGE_HITBOX, "<"),
        ("menu_back", MENU_BACK_HITBOX, f"BACK {page + 1}/2"),
        ("menu_next_page", MENU_NEXT_PAGE_HITBOX, ">"),
    )
    draw.line((0, 192, 319, 192), fill=MUTED)
    for action, hitbox, label in buttons:
        box = (hitbox[0], hitbox[1], hitbox[2] - 1, hitbox[3] - 1)
        pressed = action == pressed_action
        if pressed:
            draw.rectangle(box, fill=MUTED)
        draw.text(
            ((box[0] + box[2]) // 2, 216),
            label,
            font=fonts["small"] if action == "menu_back" else fonts["label"],
            fill=BACKGROUND if pressed else GREEN,
            anchor="mm",
        )


def _footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, Any],
    screen: Screen,
    pressed_action: str | None,
) -> None:
    center_label = {
        Screen.OVERVIEW: "HOLD: MENU",
        Screen.VALUES: "TAP: OVERVIEW",
    }[screen]
    buttons = (
        ("previous", (0, FOOTER_TOP, 63, 239), "<"),
        ("center", (64, FOOTER_TOP, 255, 239), center_label),
        ("next", (256, FOOTER_TOP, 319, 239), ">"),
    )
    draw.line((0, FOOTER_TOP, 319, FOOTER_TOP), fill=MUTED)
    for action, box, label in buttons:
        pressed = action == pressed_action
        if pressed:
            draw.rectangle(box, fill=MUTED)
        draw.text(
            ((box[0] + box[2]) // 2, 216),
            label,
            font=fonts["label"] if action != "center" else fonts["small"],
            fill=BACKGROUND if pressed else GREEN,
            anchor="mm",
        )


def _font(size: int):
    for path in (
        FONT_PATH,
        "DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > width:
        text = text[:-1]
    return text + suffix if text else "?"
