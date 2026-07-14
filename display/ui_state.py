from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from display.categories import category, category_at, default_category, detail_view_at, metric_at
from display.navigation import move, selected_index, touch_action


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
        if selected in {metric.id for metric in selected_category.metrics}:
            return selected
        return selected_category.metrics[0].id if selected_category.metrics else ""


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


def _select_node(
    state: UiState,
    nodes: tuple[dict[str, Any], ...],
    index: int,
    now: float,
) -> UiState:
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
    return next_state


def reduce_ui(
    state: UiState,
    event: UiEvent,
    context: UiContext,
) -> UiTransition:
    next_state = replace(state, metric_by_category=dict(state.metric_by_category))

    if isinstance(event, DataRefreshed):
        index = selected_index(event.nodes, state.selected_node_id, state.node_index_hint)
        if event.nodes:
            next_state.node_index_hint = index
            next_state.selected_node_id = event.nodes[index].get("node_id")
        else:
            next_state.node_index_hint = 0
            next_state.selected_node_id = None

        if event.nodes and state.screen in {Screen.VALUES, Screen.GRAPH}:
            selected = category(state.selected_category_id)
            if selected.id != state.selected_category_id or not selected.available(event.nodes[index]):
                next_state.screen = Screen.OVERVIEW
                return UiTransition(next_state, changed=True, full_refresh=True)
        return UiTransition(next_state)

    if isinstance(event, (ShortPress, LongPress)):
        next_state.last_interaction_at = event.now
        next_state.pause_until = event.now + context.pause_after_touch_seconds
        action = touch_action(event.x, event.y)

        if isinstance(event, LongPress):
            if action == "center" and state.screen in {
                Screen.OVERVIEW,
                Screen.VALUES,
                Screen.GRAPH,
            }:
                next_state.screen = Screen.MAIN_MENU
                return UiTransition(
                    next_state,
                    changed=True,
                    full_refresh=True,
                    completed_action="long_menu",
                )
            return UiTransition(next_state)

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

        if state.screen == Screen.MAIN_MENU and context.nodes:
            index = selected_index(
                context.nodes,
                state.selected_node_id,
                state.node_index_hint,
            )
            node = context.nodes[index]
            selected_category = category_at(event.x, event.y)
            if selected_category and selected_category.available(node):
                next_state.selected_category_id = selected_category.id
                metric_id = next_state.metric_id(node)
                if metric_id:
                    next_state.metric_by_category[selected_category.id] = metric_id
                next_state.screen = Screen.VALUES
                return UiTransition(
                    next_state,
                    changed=True,
                    full_refresh=True,
                    completed_action=f"category_{selected_category.id}",
                )
            return UiTransition(next_state)

        if state.screen in {Screen.VALUES, Screen.GRAPH} and context.nodes:
            selected_view = detail_view_at(event.x, event.y)
            if selected_view:
                next_state.screen = Screen(selected_view)
                return UiTransition(
                    next_state,
                    changed=True,
                    full_refresh=True,
                    completed_action=f"view_{selected_view}",
                )
            index = selected_index(
                context.nodes,
                state.selected_node_id,
                state.node_index_hint,
            )
            node = context.nodes[index]
            category_id = next_state.category_id(node)
            selected_metric = metric_at(category_id, event.x, event.y)
            if selected_metric:
                next_state.metric_by_category[category_id] = selected_metric.id
                return UiTransition(
                    next_state,
                    changed=True,
                    completed_action=f"metric_{selected_metric.id}",
                )
        return UiTransition(next_state)

    if isinstance(event, InactivityTick):
        if event.touch_pressed:
            return UiTransition(next_state)
        if state.screen == Screen.MAIN_MENU:
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
