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
