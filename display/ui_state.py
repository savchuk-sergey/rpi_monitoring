from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from display.categories import can_open_graph, category, default_category
from display.navigation import (
    MENU_PAGE_COUNT,
    NODES_PAGE_SIZE,
    graph_action_at,
    menu_action_at,
    menu_page_for_category,
    move,
    nodes_action_at,
    nodes_page_count,
    nodes_page_items,
    normalize_menu_page,
    normalize_nodes_page,
    ordered_nodes,
    selected_index,
    touch_action,
    values_action_at,
)


class Screen(Enum):
    OVERVIEW = "overview"
    MAIN_MENU = "main_menu"
    VALUES = "values"
    GRAPH = "graph"
    NODES = "nodes"
    SYSTEM = "system"
    POWER_CONFIRM = "power_confirm"
    POWER_PENDING = "power_pending"
    POWER_ERROR = "power_error"


class PowerAction(Enum):
    REBOOT = "reboot"
    POWEROFF = "poweroff"


class UiEffect(Enum):
    NONE = "none"


@dataclass
class UiState:
    screen: Screen = Screen.OVERVIEW

    selected_node_id: str | None = None
    node_index_hint: int = 0

    selected_category_id: str = "cpu"
    metric_by_category: dict[str, str] = field(default_factory=dict)
    selected_gpu_index: int = 0

    menu_page: int = 0
    nodes_page: int = 0

    pending_power_action: PowerAction | None = None
    confirmation_started_at: float | None = None

    last_interaction_at: float = 0.0
    pause_until: float = 0.0
    last_rotation_at: float = 0.0

    def category_id(self, node: dict[str, Any]) -> str:
        selected = category(self.selected_category_id)
        if selected.id == self.selected_category_id and selected.available(node):
            return selected.id
        return default_category(node).id

    def metric_id(self, node: dict[str, Any]) -> str:
        selected_category = category(self.category_id(node))
        selected = self.metric_by_category.get(selected_category.id)
        if selected in {metric.id for metric in selected_category.chart_metrics}:
            return selected
        return selected_category.chart_metrics[0].id if selected_category.chart_metrics else ""


@dataclass(frozen=True)
class ShortPress:
    x: int
    y: int
    now: float


@dataclass(frozen=True)
class LongPress:
    x: int
    y: int
    now: float


@dataclass(frozen=True)
class DataRefreshed:
    nodes: tuple[dict[str, Any], ...]
    hub_online: bool
    now: float


@dataclass(frozen=True)
class InactivityTick:
    now: float
    touch_pressed: bool


@dataclass(frozen=True)
class AutoRotateTick:
    now: float
    interaction_idle: bool


UiEvent = ShortPress | LongPress | DataRefreshed | InactivityTick | AutoRotateTick


@dataclass(frozen=True)
class UiContext:
    nodes: tuple[dict[str, Any], ...]
    pause_after_touch_seconds: float
    detail_timeout_seconds: float
    menu_timeout_seconds: float
    auto_rotate_seconds: float


@dataclass(frozen=True)
class UiTransition:
    state: UiState
    changed: bool = False
    full_refresh: bool = False
    completed_action: str | None = None
    effect: UiEffect = UiEffect.NONE


_ACTIVE_SCREENS = {
    Screen.OVERVIEW,
    Screen.MAIN_MENU,
    Screen.VALUES,
    Screen.GRAPH,
}


def visible_action_at(
    state: UiState,
    node: dict[str, Any] | None,
    x: int,
    y: int,
    nodes: tuple[dict[str, Any], ...] | None = None,
) -> str | None:
    snapshot = (
        tuple(nodes)
        if nodes is not None
        else ((node,) if node is not None else ())
    )
    if (
        state.screen == Screen.GRAPH
        and node is not None
        and can_open_graph(state.category_id(node))
    ):
        return graph_action_at(x, y)
    if state.screen == Screen.MAIN_MENU and node is not None:
        action = menu_action_at(state.menu_page, x, y)
        if action in {"menu_previous_page", "menu_back", "menu_next_page"}:
            return action
        if action == "menu_tile_nodes":
            return action if snapshot else None
        if action is None or action == "menu_tile_system":
            return None
        category_id = action.removeprefix("menu_tile_")
        selected = category(category_id)
        return action if selected.id == category_id and selected.available(node) else None
    if state.screen == Screen.NODES and snapshot:
        return nodes_action_at(
            state.nodes_page,
            len(snapshot),
            x,
            y,
        )
    footer_action = touch_action(x, y)
    if footer_action is not None:
        return footer_action
    if state.screen != Screen.VALUES or node is None:
        return None
    category_id = state.category_id(node)
    if not can_open_graph(category_id):
        return None
    return values_action_at(x, y)


def _open_main_menu(state: UiState, node: dict[str, Any]) -> UiState:
    next_state = replace(state, metric_by_category=dict(state.metric_by_category))
    category_id = state.category_id(node)
    next_state.selected_category_id = category_id
    metric_id = next_state.metric_id(node)
    if metric_id:
        next_state.metric_by_category[category_id] = metric_id
    next_state.menu_page = menu_page_for_category(category_id)
    next_state.screen = Screen.MAIN_MENU
    return next_state


def _select_graph_metric(
    state: UiState,
    node: dict[str, Any],
    delta: int,
) -> UiState:
    next_state = replace(state, metric_by_category=dict(state.metric_by_category))
    category_id = state.category_id(node)
    selected_category = category(category_id)
    metrics = selected_category.chart_metrics
    if not can_open_graph(category_id) or len(metrics) < 2:
        return next_state
    current_metric_id = state.metric_id(node)
    index = next(
        (index for index, metric in enumerate(metrics) if metric.id == current_metric_id),
        0,
    )
    next_state.metric_by_category[category_id] = metrics[(index + delta) % len(metrics)].id
    return next_state


def _select_node(
    state: UiState,
    nodes: tuple[dict[str, Any], ...],
    index: int,
    now: float,
) -> UiState:
    previous_category_id = state.category_id(
        nodes[selected_index(nodes, state.selected_node_id, state.node_index_hint)]
    )
    next_state = replace(
        state,
        metric_by_category=dict(state.metric_by_category),
        selected_node_id=nodes[index].get("node_id"),
        node_index_hint=index,
        selected_gpu_index=0,
        last_rotation_at=now,
    )
    if state.screen in {Screen.MAIN_MENU, Screen.VALUES, Screen.GRAPH}:
        node = nodes[index]
        category_id = next_state.category_id(node)
        next_state.selected_category_id = category_id
        metric_id = next_state.metric_id(node)
        if metric_id:
            next_state.metric_by_category[category_id] = metric_id
        if next_state.screen == Screen.MAIN_MENU:
            next_state.menu_page = (
                menu_page_for_category(category_id)
                if category_id != previous_category_id
                else normalize_menu_page(state.menu_page)
            )
        if next_state.screen == Screen.GRAPH and not can_open_graph(category_id):
            next_state.screen = Screen.VALUES
    return next_state


def reduce_ui(
    state: UiState,
    event: UiEvent,
    context: UiContext,
) -> UiTransition:
    next_state = replace(state, metric_by_category=dict(state.metric_by_category))

    if isinstance(event, DataRefreshed):
        if state.screen == Screen.NODES:
            if not event.nodes:
                next_state.selected_node_id = None
                next_state.node_index_hint = 0
                next_state.nodes_page = 0
                next_state.screen = Screen.OVERVIEW
                return UiTransition(next_state, changed=True, full_refresh=True)

            ordered = ordered_nodes(event.nodes)
            ordered_index = next(
                (
                    index
                    for index, item in enumerate(ordered)
                    if item.get("node_id") == state.selected_node_id
                ),
                None,
            )
            if ordered_index is None:
                selected_node = ordered[0]
                nodes_page = 0
            else:
                selected_node = ordered[ordered_index]
                nodes_page = normalize_nodes_page(state.nodes_page, len(event.nodes))
            selected_node_id = selected_node.get("node_id")
            original_index = next(
                index
                for index, item in enumerate(event.nodes)
                if item.get("node_id") == selected_node_id
            )
            next_state.selected_node_id = selected_node_id
            next_state.node_index_hint = original_index
            next_state.nodes_page = nodes_page
            changed = (
                selected_node_id != state.selected_node_id
                or original_index != state.node_index_hint
                or nodes_page != state.nodes_page
            )
            return UiTransition(
                next_state,
                changed=changed,
                full_refresh=changed,
            )

        index = selected_index(event.nodes, state.selected_node_id, state.node_index_hint)
        if event.nodes:
            next_state.node_index_hint = index
            next_state.selected_node_id = event.nodes[index].get("node_id")
        else:
            next_state.node_index_hint = 0
            next_state.selected_node_id = None
            if state.screen in {Screen.MAIN_MENU, Screen.VALUES, Screen.GRAPH, Screen.NODES}:
                next_state.screen = Screen.OVERVIEW
                return UiTransition(next_state, changed=True, full_refresh=True)

        if event.nodes and state.screen == Screen.MAIN_MENU:
            normalized_page = normalize_menu_page(state.menu_page)
            next_state.menu_page = normalized_page
            node = event.nodes[index]
            selected = category(state.selected_category_id)
            if selected.id != state.selected_category_id or not selected.available(node):
                category_id = next_state.category_id(node)
                next_state.selected_category_id = category_id
                metric_id = next_state.metric_id(node)
                if metric_id:
                    next_state.metric_by_category[category_id] = metric_id
                next_state.menu_page = menu_page_for_category(category_id)
                return UiTransition(next_state, changed=True, full_refresh=True)
            if normalized_page != state.menu_page:
                return UiTransition(next_state, changed=True, full_refresh=True)

        if event.nodes and state.screen in {Screen.VALUES, Screen.GRAPH}:
            selected = category(state.selected_category_id)
            if selected.id != state.selected_category_id or not selected.available(event.nodes[index]):
                next_state.screen = Screen.OVERVIEW
                return UiTransition(next_state, changed=True, full_refresh=True)
            if state.screen == Screen.GRAPH and not can_open_graph(next_state.category_id(event.nodes[index])):
                next_state.screen = Screen.VALUES
                return UiTransition(next_state, changed=True, full_refresh=True)
        return UiTransition(next_state)

    if isinstance(event, (ShortPress, LongPress)):
        next_state.last_interaction_at = event.now
        next_state.pause_until = event.now + context.pause_after_touch_seconds
        node = None
        if context.nodes:
            index = selected_index(
                context.nodes,
                state.selected_node_id,
                state.node_index_hint,
            )
            node = context.nodes[index]
        action = visible_action_at(
            state,
            node,
            event.x,
            event.y,
            nodes=context.nodes,
        )

        if isinstance(event, LongPress):
            if (
                node is not None
                and action == "center"
                and state.screen in {Screen.OVERVIEW, Screen.VALUES, Screen.GRAPH}
            ) or (
                node is not None
                and action == "graph_values"
                and state.screen == Screen.GRAPH
            ):
                next_state = _open_main_menu(next_state, node)
                return UiTransition(
                    next_state,
                    changed=True,
                    full_refresh=True,
                    completed_action="long_menu",
                )
            return UiTransition(next_state)

        if state.screen == Screen.NODES and action in {
            "nodes_previous_page",
            "nodes_next_page",
        }:
            page_count = nodes_page_count(len(context.nodes))
            if page_count <= 1:
                return UiTransition(next_state)
            next_state.nodes_page = move(
                normalize_nodes_page(state.nodes_page, len(context.nodes)),
                page_count,
                -1 if action == "nodes_previous_page" else 1,
            )
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action=action,
            )

        if state.screen == Screen.NODES and action == "nodes_back":
            next_state.screen = Screen.MAIN_MENU
            next_state.menu_page = 0
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action=action,
            )

        if (
            state.screen == Screen.NODES
            and action in {"nodes_select_0", "nodes_select_1", "nodes_select_2"}
        ):
            row_index = int(action.rsplit("_", 1)[1])
            page_items = nodes_page_items(context.nodes, state.nodes_page)
            if row_index >= len(page_items):
                return UiTransition(next_state)
            selected_node_id = page_items[row_index].get("node_id")
            original_index = next(
                (
                    index
                    for index, item in enumerate(context.nodes)
                    if item.get("node_id") == selected_node_id
                ),
                None,
            )
            if original_index is None:
                return UiTransition(next_state)
            next_state = _select_node(
                next_state,
                context.nodes,
                original_index,
                event.now,
            )
            next_state.screen = Screen.OVERVIEW
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action="select_node",
            )

        if state.screen == Screen.MAIN_MENU and action in {
            "menu_previous_page",
            "menu_next_page",
        }:
            next_state.menu_page = move(
                normalize_menu_page(state.menu_page),
                MENU_PAGE_COUNT,
                -1 if action == "menu_previous_page" else 1,
            )
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action=action,
            )

        if state.screen == Screen.MAIN_MENU and action == "menu_back":
            next_state.screen = Screen.OVERVIEW
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action=action,
            )

        if state.screen == Screen.MAIN_MENU and action == "menu_tile_nodes":
            if not context.nodes:
                return UiTransition(next_state)
            ordered = ordered_nodes(context.nodes)
            ordered_index = next(
                (
                    index
                    for index, item in enumerate(ordered)
                    if item.get("node_id") == state.selected_node_id
                ),
                None,
            )
            if ordered_index is None:
                ordered_index = 0
            selected_node_id = ordered[ordered_index].get("node_id")
            original_index = next(
                index
                for index, item in enumerate(context.nodes)
                if item.get("node_id") == selected_node_id
            )
            next_state.screen = Screen.NODES
            next_state.selected_node_id = selected_node_id
            next_state.node_index_hint = original_index
            next_state.nodes_page = ordered_index // NODES_PAGE_SIZE
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action="open_nodes",
            )

        if state.screen == Screen.MAIN_MENU and action == "menu_tile_system":
            return UiTransition(next_state)

        if state.screen == Screen.MAIN_MENU and action is not None and action.startswith("menu_tile_"):
            if node is None:
                return UiTransition(next_state)
            category_id = action.removeprefix("menu_tile_")
            selected_category = category(category_id)
            if selected_category.id != category_id or not selected_category.available(node):
                return UiTransition(next_state)
            next_state.selected_category_id = category_id
            metric_id = next_state.metric_id(node)
            if metric_id:
                next_state.metric_by_category[category_id] = metric_id
            next_state.screen = Screen.VALUES
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action=f"category_{category_id}",
            )

        if state.screen in _ACTIVE_SCREENS and action in {"previous", "next"}:
            if len(context.nodes) > 1:
                index = selected_index(
                    context.nodes,
                    state.selected_node_id,
                    state.node_index_hint,
                )
                index = move(index, len(context.nodes), -1 if action == "previous" else 1)
                next_state = _select_node(next_state, context.nodes, index, event.now)
                return UiTransition(
                    next_state,
                    changed=True,
                    full_refresh=True,
                    completed_action=action,
                )
            return UiTransition(next_state)

        if state.screen == Screen.GRAPH and action in {
            "graph_previous_metric",
            "graph_next_metric",
        }:
            if node is None:
                return UiTransition(next_state)
            selected_state = _select_graph_metric(
                next_state,
                node,
                -1 if action == "graph_previous_metric" else 1,
            )
            if selected_state.metric_by_category == next_state.metric_by_category:
                return UiTransition(next_state)
            return UiTransition(
                selected_state,
                changed=True,
                full_refresh=True,
                completed_action=(
                    "previous_metric"
                    if action == "graph_previous_metric"
                    else "next_metric"
                ),
            )

        if state.screen == Screen.GRAPH and action == "graph_values":
            next_state.screen = Screen.VALUES
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action="graph_values",
            )

        if action == "open_graph":
            next_state.screen = Screen.GRAPH
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action="open_graph",
            )

        if action == "center":
            if state.screen == Screen.OVERVIEW and context.nodes:
                index = selected_index(
                    context.nodes,
                    state.selected_node_id,
                    state.node_index_hint,
                )
                node = context.nodes[index]
                next_state.selected_node_id = node.get("node_id")
                next_state.node_index_hint = index
                category_id = next_state.category_id(node)
                next_state.selected_category_id = category_id
                metric_id = next_state.metric_id(node)
                if metric_id:
                    next_state.metric_by_category[category_id] = metric_id
                next_state.screen = Screen.VALUES
                return UiTransition(
                    next_state,
                    changed=True,
                    full_refresh=True,
                    completed_action="short_center",
                )
            if state.screen in {Screen.VALUES, Screen.GRAPH}:
                next_state.screen = Screen.OVERVIEW
                return UiTransition(
                    next_state,
                    changed=True,
                    full_refresh=True,
                    completed_action="short_center",
                )
            return UiTransition(next_state)

        if state.screen == Screen.VALUES:
            return UiTransition(next_state)

        return UiTransition(next_state)

    if isinstance(event, InactivityTick):
        if event.touch_pressed:
            return UiTransition(next_state)
        if state.screen in {Screen.MAIN_MENU, Screen.NODES}:
            timeout = context.menu_timeout_seconds
        elif state.screen in {Screen.VALUES, Screen.GRAPH}:
            timeout = context.detail_timeout_seconds
        else:
            return UiTransition(next_state)
        if timeout > 0 and event.now - state.last_interaction_at >= timeout:
            next_state.screen = Screen.OVERVIEW
            return UiTransition(
                next_state,
                changed=True,
                full_refresh=True,
                completed_action="timeout_overview",
            )
        return UiTransition(next_state)

    if (
        context.auto_rotate_seconds > 0
        and len(context.nodes) > 1
        and event.now >= state.pause_until
        and event.now - state.last_rotation_at >= context.auto_rotate_seconds
        and event.interaction_idle
        and state.screen in _ACTIVE_SCREENS
    ):
        index = selected_index(
            context.nodes,
            state.selected_node_id,
            state.node_index_hint,
        )
        index = move(index, len(context.nodes), 1)
        next_state = _select_node(next_state, context.nodes, index, event.now)
        return UiTransition(next_state, changed=True, full_refresh=True)
    return UiTransition(next_state)
