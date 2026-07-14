from typing import Any


NAV_WIDTH = 64
FOOTER_TOP = 192
Rect = tuple[int, int, int, int]
PREVIOUS_HITBOX: Rect = (0, FOOTER_TOP, 61, 240)
MODE_HITBOX: Rect = (67, FOOTER_TOP, 253, 240)
NEXT_HITBOX: Rect = (259, FOOTER_TOP, 320, 240)
VALUES_GRAPH_HITBOX: Rect = (0, 140, 320, 192)
VALUES_GRAPH_BUTTON_RECT: Rect = (8, 142, 312, 190)
GRAPH_PREVIOUS_METRIC_HITBOX: Rect = (0, 192, 64, 240)
GRAPH_VALUES_HITBOX: Rect = (64, 192, 256, 240)
GRAPH_NEXT_METRIC_HITBOX: Rect = (256, 192, 320, 240)
MENU_PAGE_COUNT = 2
MENU_TILE_RECTS: tuple[Rect, ...] = (
    (0, 32, 160, 112),
    (160, 32, 320, 112),
    (0, 112, 160, 192),
    (160, 112, 320, 192),
)
MENU_PAGES: tuple[tuple[str, ...], ...] = (
    (
        "cpu",
        "memory",
        "gpu",
        "nodes",
    ),
    (
        "storage",
        "network",
        "health",
        "system",
    ),
)
MENU_PREVIOUS_PAGE_HITBOX: Rect = (
    0,
    192,
    64,
    240,
)
MENU_BACK_HITBOX: Rect = (
    64,
    192,
    256,
    240,
)
MENU_NEXT_PAGE_HITBOX: Rect = (
    256,
    192,
    320,
    240,
)
NODES_PAGE_SIZE = 3
NODES_ROW_RECTS: tuple[Rect, ...] = (
    (0, 32, 320, 85),
    (0, 85, 320, 138),
    (0, 138, 320, 192),
)
NODES_PREVIOUS_PAGE_HITBOX: Rect = (
    0,
    192,
    64,
    240,
)
NODES_BACK_HITBOX: Rect = (
    64,
    192,
    256,
    240,
)
NODES_NEXT_PAGE_HITBOX: Rect = (
    256,
    192,
    320,
    240,
)
SYSTEM_RESTART_AREA: Rect = (
    0,
    32,
    320,
    104,
)
SYSTEM_SHUTDOWN_AREA: Rect = (
    0,
    112,
    320,
    184,
)
SYSTEM_BACK_HITBOX: Rect = (
    64,
    192,
    256,
    240,
)
SYSTEM_RESTART_CARD_RECT: Rect = (
    8,
    36,
    312,
    100,
)
SYSTEM_SHUTDOWN_CARD_RECT: Rect = (
    8,
    116,
    312,
    180,
)
POWER_CANCEL_HITBOX: Rect = (
    0,
    192,
    112,
    240,
)
POWER_HOLD_HITBOX: Rect = (
    112,
    192,
    320,
    240,
)
POWER_ERROR_BACK_HITBOX: Rect = (
    64,
    192,
    256,
    240,
)
POWER_CANCEL_CARD_RECT: Rect = (
    0,
    192,
    111,
    239,
)
POWER_HOLD_CARD_RECT: Rect = (
    112,
    192,
    319,
    239,
)
POWER_HOLD_PROGRESS_RECT: Rect = (
    124,
    228,
    308,
    236,
)


def move(index: int, count: int, delta: int) -> int:
    return (index + delta) % count if count else 0

def selected_index(
    nodes: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    node_id: str | None,
    fallback: int = 0,
) -> int:
    if node_id is not None:
        for index, node in enumerate(nodes):
            if node.get("node_id") == node_id:
                return index
    return min(max(0, fallback), max(0, len(nodes) - 1))

def touch_action(x: int, y: int) -> str | None:
    for action, (left, top, right, bottom) in (
        ("previous", PREVIOUS_HITBOX),
        ("center", MODE_HITBOX),
        ("next", NEXT_HITBOX),
    ):
        if left <= x < right and top <= y < bottom:
            return action
    return None


def values_action_at(x: int, y: int) -> str | None:
    left, top, right, bottom = VALUES_GRAPH_HITBOX
    return "open_graph" if left <= x < right and top <= y < bottom else None


def graph_action_at(x: int, y: int) -> str | None:
    for action, (left, top, right, bottom) in (
        ("graph_previous_metric", GRAPH_PREVIOUS_METRIC_HITBOX),
        ("graph_values", GRAPH_VALUES_HITBOX),
        ("graph_next_metric", GRAPH_NEXT_METRIC_HITBOX),
    ):
        if left <= x < right and top <= y < bottom:
            return action
    return None


def normalize_menu_page(page: int) -> int:
    if page < 0:
        return 0
    if page >= MENU_PAGE_COUNT:
        return MENU_PAGE_COUNT - 1
    return page


def menu_page_for_category(category_id: str) -> int:
    return next(
        (page for page, category_ids in enumerate(MENU_PAGES) if category_id in category_ids),
        0,
    )


def menu_tile_id_at(page: int, x: int, y: int) -> str | None:
    category_ids = MENU_PAGES[normalize_menu_page(page)]
    for category_id, (left, top, right, bottom) in zip(category_ids, MENU_TILE_RECTS):
        if left <= x < right and top <= y < bottom:
            return category_id
    return None


def menu_action_at(page: int, x: int, y: int) -> str | None:
    for action, (left, top, right, bottom) in (
        ("menu_previous_page", MENU_PREVIOUS_PAGE_HITBOX),
        ("menu_back", MENU_BACK_HITBOX),
        ("menu_next_page", MENU_NEXT_PAGE_HITBOX),
    ):
        if left <= x < right and top <= y < bottom:
            return action
    category_id = menu_tile_id_at(page, x, y)
    return f"menu_tile_{category_id}" if category_id is not None else None


def ordered_nodes(
    nodes: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(sorted(nodes, key=lambda node: str(node.get("node_id") or "")))


def nodes_page_count(node_count: int) -> int:
    return max(
        1,
        (max(0, node_count) + NODES_PAGE_SIZE - 1)
        // NODES_PAGE_SIZE,
    )


def normalize_nodes_page(page: int, node_count: int) -> int:
    if page < 0:
        return 0
    page_count = nodes_page_count(node_count)
    if page >= page_count:
        return page_count - 1
    return page


def nodes_page_items(
    nodes: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    page: int,
) -> tuple[dict[str, Any], ...]:
    ordered = ordered_nodes(nodes)
    normalized_page = normalize_nodes_page(page, len(ordered))
    start = normalized_page * NODES_PAGE_SIZE
    return ordered[start:start + NODES_PAGE_SIZE]


def nodes_action_at(
    page: int,
    node_count: int,
    x: int,
    y: int,
) -> str | None:
    page_count = nodes_page_count(node_count)
    for action, hitbox in (
        ("nodes_previous_page", NODES_PREVIOUS_PAGE_HITBOX),
        ("nodes_back", NODES_BACK_HITBOX),
        ("nodes_next_page", NODES_NEXT_PAGE_HITBOX),
    ):
        left, top, right, bottom = hitbox
        if left <= x < right and top <= y < bottom:
            if action == "nodes_back" or page_count > 1:
                return action
            return None

    normalized_page = normalize_nodes_page(page, node_count)
    visible_count = min(
        NODES_PAGE_SIZE,
        max(0, node_count - normalized_page * NODES_PAGE_SIZE),
    )
    for index, (left, top, right, bottom) in enumerate(NODES_ROW_RECTS):
        if left <= x < right and top <= y < bottom:
            return f"nodes_select_{index}" if index < visible_count else None
    return None


def system_action_at(x: int, y: int) -> str | None:
    for action, (left, top, right, bottom) in (
        ("system_restart", SYSTEM_RESTART_AREA),
        ("system_shutdown", SYSTEM_SHUTDOWN_AREA),
        ("system_back", SYSTEM_BACK_HITBOX),
    ):
        if left <= x < right and top <= y < bottom:
            return action
    return None


def power_confirm_action_at(x: int, y: int) -> str | None:
    for action, (left, top, right, bottom) in (
        ("power_cancel", POWER_CANCEL_HITBOX),
        ("power_hold", POWER_HOLD_HITBOX),
    ):
        if left <= x < right and top <= y < bottom:
            return action
    return None


def power_error_action_at(x: int, y: int) -> str | None:
    left, top, right, bottom = POWER_ERROR_BACK_HITBOX
    return "power_error_back" if left <= x < right and top <= y < bottom else None


def map_touch(raw_x: int, raw_y: int, calibration: dict[str, Any]) -> tuple[int, int]:
    if calibration.get("swap_xy"):
        raw_x, raw_y = raw_y, raw_x
    x = _scale(raw_x, calibration["raw_x_min"], calibration["raw_x_max"], 319)
    y = _scale(raw_y, calibration["raw_y_min"], calibration["raw_y_max"], 239)
    if calibration.get("invert_x"):
        x = 319 - x
    if calibration.get("invert_y"):
        y = 239 - y
    return x, y





def _scale(value: int, low: int, high: int, output_max: int) -> int:
    if high <= low:
        raise ValueError("invalid calibration range")
    return max(0, min(output_max, round((value - low) * output_max / (high - low))))
