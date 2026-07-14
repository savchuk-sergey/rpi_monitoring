import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from display.categories import CATEGORIES, category
from display.renderer import _status
from display.ui_state import (
    AutoRotateTick,
    DataRefreshed,
    InactivityTick,
    LongPress,
    PowerAction,
    Screen,
    ShortPress,
    UiContext,
    UiEffect,
    UiState,
    _select_graph_metric,
    reduce_ui,
    visible_action_at,
)


def node(node_id: str = "desktop", **changes) -> dict:
    value = {
        "node_id": node_id,
        "display_name": node_id,
        "timestamp_utc": "2026-07-12T03:00:00Z",
        "received_at_utc": "2026-07-12T03:00:01Z",
        "online": True,
        "cpu": {"usage_percent": 47, "temperature_c": 63, "power_w": None},
        "memory": {"usage_percent": 63},
        "gpu": [],
        "collector": {"version": "0.3.0", "errors": []},
    }
    value.update(changes)
    return value


def waiting(node_id: str = "waiting") -> dict:
    return {
        "node_id": node_id,
        "display_name": node_id,
        "cpu": {
            "usage_percent": None,
            "temperature_c": None,
            "power_w": None,
        },
        "memory": {"usage_percent": None},
        "gpu": [],
        "collector": {"version": None, "errors": []},
        "online": False,
        "waiting": True,
    }


def context(
    nodes: tuple[dict, ...] = (),
    *,
    pause: float = 30.0,
    detail: float = 45.0,
    menu: float = 15.0,
    rotate: float = 10.0,
) -> UiContext:
    return UiContext(nodes, pause, detail, menu, rotate)


class UiStateTests(unittest.TestCase):
    def test_exact_enums_and_future_defaults(self) -> None:
        self.assertEqual(
            {
                "OVERVIEW": "overview",
                "MAIN_MENU": "main_menu",
                "VALUES": "values",
                "GRAPH": "graph",
                "NODES": "nodes",
                "SYSTEM": "system",
                "POWER_CONFIRM": "power_confirm",
                "POWER_PENDING": "power_pending",
                "POWER_ERROR": "power_error",
            },
            {item.name: item.value for item in Screen},
        )
        self.assertEqual(
            {"REBOOT": "reboot", "POWEROFF": "poweroff"},
            {item.name: item.value for item in PowerAction},
        )
        self.assertEqual("none", UiEffect.NONE.value)
        self.assertIsNone(UiState().pending_power_action)

    def test_resolution_is_read_only_and_capability_aware(self) -> None:
        state = UiState(
            selected_category_id="storage",
            metric_by_category={"storage": "read"},
        )
        value = node(
            storage={"usage_percent": None},
            capabilities={
                "storage.usage_percent": {
                    "supported": True,
                    "source": "statvfs",
                    "reason": None,
                }
            },
        )
        before = copy.deepcopy(state)
        self.assertEqual("storage", state.category_id(value))
        self.assertEqual("read", state.metric_id(value))
        self.assertEqual(before, state)

        state.selected_category_id = "missing"
        self.assertEqual("cpu", state.category_id(value))
        state.selected_category_id = "storage"
        state.metric_by_category["storage"] = "missing"
        self.assertEqual("used", state.metric_id(value))
        state.selected_category_id = "memory"
        state.metric_by_category["memory"] = "ram_load"
        self.assertEqual("ram", state.metric_id(value))
        self.assertEqual("cpu", UiState().category_id(waiting()))

    def test_visible_action_resolves_values_and_preserves_inputs(self) -> None:
        value = node(
            gpu=[{"usage_percent": 50}],
            storage={"usage_percent": 50},
            network={"interface": "eth0"},
        )
        for category_id in ("cpu", "memory", "gpu", "storage", "network"):
            state = UiState(screen=Screen.VALUES, selected_category_id=category_id)
            with self.subTest(category=category_id):
                self.assertEqual("open_graph", visible_action_at(state, value, 160, 166))
        self.assertIsNone(visible_action_at(
            UiState(screen=Screen.VALUES, selected_category_id="health"),
            value,
            160,
            166,
        ))
        self.assertIsNone(visible_action_at(UiState(screen=Screen.VALUES), None, 160, 166))
        for screen in (Screen.GRAPH, Screen.OVERVIEW, Screen.MAIN_MENU):
            self.assertIsNone(visible_action_at(UiState(screen=screen), value, 160, 166))
        graph = UiState(screen=Screen.GRAPH)
        self.assertEqual("graph_previous_metric", visible_action_at(graph, value, 10, 210))
        self.assertEqual("graph_values", visible_action_at(graph, value, 160, 210))
        self.assertEqual("graph_next_metric", visible_action_at(graph, value, 300, 210))
        self.assertIsNone(visible_action_at(graph, value, 150, 40))
        for fallback_node in (None, value):
            fallback = UiState(
                screen=Screen.GRAPH,
                selected_category_id="health" if fallback_node else "cpu",
            )
            with self.subTest(fallback_node=fallback_node is not None):
                self.assertEqual("previous", visible_action_at(fallback, fallback_node, 10, 210))
                self.assertEqual("center", visible_action_at(fallback, fallback_node, 160, 210))
                self.assertEqual("next", visible_action_at(fallback, fallback_node, 300, 210))
        state = UiState(screen=Screen.VALUES, metric_by_category={"cpu": "temperature"})
        state_before = copy.deepcopy(state)
        node_before = copy.deepcopy(value)
        self.assertEqual("previous", visible_action_at(state, value, 10, 210))
        self.assertEqual("center", visible_action_at(state, value, 160, 210))
        self.assertEqual("next", visible_action_at(state, value, 300, 210))
        self.assertEqual(state_before, state)
        self.assertEqual(node_before, value)

    def test_reducer_copies_state_dictionary_and_does_not_mutate_inputs(self) -> None:
        value = node()
        state = UiState(metric_by_category={"cpu": "load"})
        event = DataRefreshed((value,), True, 1.0)
        ui_context = context((value,))
        state_before = copy.deepcopy(state)
        event_before = copy.deepcopy(event)
        context_before = copy.deepcopy(ui_context)
        transition = reduce_ui(state, event, ui_context)
        self.assertIsNot(state, transition.state)
        self.assertIsNot(state.metric_by_category, transition.state.metric_by_category)
        self.assertEqual(state_before, state)
        self.assertEqual(event_before, event)
        self.assertEqual(context_before, ui_context)
        self.assertEqual(node(), value)

    def test_refresh_selection_initial_reorder_hint_clamp_and_empty(self) -> None:
        nodes = (node("a"), node("b"), node("c"))
        selected = reduce_ui(UiState(), DataRefreshed(nodes, True, 1), context(nodes)).state
        self.assertEqual(("a", 0), (selected.selected_node_id, selected.node_index_hint))

        reordered = (nodes[2], nodes[1], nodes[0])
        selected = reduce_ui(
            UiState(selected_node_id="a", node_index_hint=0),
            DataRefreshed(reordered, True, 2),
            context(reordered),
        ).state
        self.assertEqual(("a", 2), (selected.selected_node_id, selected.node_index_hint))

        selected = reduce_ui(
            UiState(selected_node_id="missing", node_index_hint=99),
            DataRefreshed(nodes, True, 3),
            context(nodes),
        ).state
        self.assertEqual(("c", 2), (selected.selected_node_id, selected.node_index_hint))

        selected = reduce_ui(
            UiState(selected_node_id="a", node_index_hint=2),
            DataRefreshed((), False, 4),
            context(),
        ).state
        self.assertEqual((None, 0), (selected.selected_node_id, selected.node_index_hint))

    def test_empty_refresh_normalizes_node_dependent_screens_before_input(self) -> None:
        for screen in (Screen.MAIN_MENU, Screen.VALUES, Screen.GRAPH):
            with self.subTest(screen=screen):
                transition = reduce_ui(
                    UiState(screen=screen, selected_node_id="desktop", node_index_hint=3),
                    DataRefreshed((), False, 1),
                    context(),
                )
                self.assertEqual((None, 0, Screen.OVERVIEW), (
                    transition.state.selected_node_id,
                    transition.state.node_index_hint,
                    transition.state.screen,
                ))
                self.assertTrue(transition.changed and transition.full_refresh)
                for x in (10, 160, 300):
                    pressed = reduce_ui(
                        transition.state,
                        ShortPress(x, 210, 2),
                        context(),
                    )
                    self.assertEqual(Screen.OVERVIEW, pressed.state.screen)

    def test_waiting_restored_removal_and_addition_preserve_id_semantics(self) -> None:
        waiting_node = waiting("a")
        selected = reduce_ui(
            UiState(),
            DataRefreshed((waiting_node,), True, 1),
            context((waiting_node,)),
        ).state
        self.assertEqual("a", selected.selected_node_id)

        live = node("a")
        selected = reduce_ui(
            selected,
            DataRefreshed((live,), True, 2),
            context((live,)),
        ).state
        self.assertEqual("a", selected.selected_node_id)

        restored = node("a", online=False)
        selected = reduce_ui(
            selected,
            DataRefreshed((restored,), True, 3),
            context((restored,)),
        ).state
        self.assertEqual("a", selected.selected_node_id)

        values = (node("a"), node("b"), node("c"))
        selected = reduce_ui(
            UiState(selected_node_id="b", node_index_hint=1),
            DataRefreshed((values[0], values[2]), True, 4),
            context((values[0], values[2])),
        ).state
        self.assertEqual("c", selected.selected_node_id)

        nodes_with_new_waiting = (node("a"), waiting("z"))
        selected = reduce_ui(
            UiState(selected_node_id="a"),
            DataRefreshed(nodes_with_new_waiting, True, 5),
            context(nodes_with_new_waiting),
        ).state
        self.assertEqual("a", selected.selected_node_id)

    def test_refresh_category_validation_supported_unsupported_and_legacy(self) -> None:
        supported = node(
            storage={"usage_percent": None},
            capabilities={
                "storage.usage_percent": {
                    "supported": True,
                    "source": "statvfs",
                    "reason": None,
                }
            },
        )
        transition = reduce_ui(
            UiState(screen=Screen.VALUES, selected_category_id="storage"),
            DataRefreshed((supported,), True, 1),
            context((supported,)),
        )
        self.assertEqual(Screen.VALUES, transition.state.screen)

        unsupported = node(
            gpu=[{"usage_percent": 50}],
            capabilities={
                "gpu.usage_percent": {
                    "supported": False,
                    "source": None,
                    "reason": "sensor_not_found",
                }
            },
        )
        transition = reduce_ui(
            UiState(screen=Screen.GRAPH, selected_category_id="gpu"),
            DataRefreshed((unsupported,), True, 2),
            context((unsupported,)),
        )
        self.assertEqual(Screen.OVERVIEW, transition.state.screen)
        self.assertTrue(transition.changed and transition.full_refresh)

        legacy = node(storage={"usage_percent": 50})
        transition = reduce_ui(
            UiState(screen=Screen.VALUES, selected_category_id="storage"),
            DataRefreshed((legacy,), True, 3),
            context((legacy,)),
        )
        self.assertEqual(Screen.VALUES, transition.state.screen)

    def test_minimal_waiting_node_and_waiting_status_precedence(self) -> None:
        value = waiting()
        transition = reduce_ui(
            UiState(screen=Screen.VALUES, selected_category_id="cpu"),
            DataRefreshed((value,), True, 1),
            context((value,)),
        )
        self.assertEqual(Screen.VALUES, transition.state.screen)
        self.assertEqual("cpu", transition.state.category_id(value))
        self.assertEqual("WAITING", _status(value, True)[0])
        self.assertNotIn("timestamp_utc", value)
        for key in ("storage", "network", "health", "device", "os", "capabilities"):
            self.assertNotIn(key, value)

    def test_refresh_does_not_reset_gpu_index(self) -> None:
        value = node(gpu=[{"usage_percent": 20}])
        transition = reduce_ui(
            UiState(selected_gpu_index=2),
            DataRefreshed((value,), True, 1),
            context((value,)),
        )
        self.assertEqual(2, transition.state.selected_gpu_index)

    def test_previous_and_next_wrap_and_reset_gpu(self) -> None:
        nodes = (node("a"), node("b"))
        previous = reduce_ui(
            UiState(
                screen=Screen.VALUES,
                selected_node_id="a",
                selected_gpu_index=2,
            ),
            ShortPress(10, 210, 7),
            context(nodes),
        )
        self.assertEqual(("b", 1, 0), (
            previous.state.selected_node_id,
            previous.state.node_index_hint,
            previous.state.selected_gpu_index,
        ))
        self.assertEqual("previous", previous.completed_action)
        self.assertEqual(7, previous.state.last_rotation_at)
        self.assertEqual(Screen.VALUES, previous.state.screen)

        following = reduce_ui(
            previous.state,
            ShortPress(300, 210, 8),
            context(nodes),
        )
        self.assertEqual("a", following.state.selected_node_id)
        self.assertEqual("next", following.completed_action)

        single = reduce_ui(UiState(selected_gpu_index=2), ShortPress(10, 210, 9), context((node(),)))
        self.assertFalse(single.changed)
        self.assertEqual(2, single.state.selected_gpu_index)

    def test_node_switch_normalizes_detail_selection_before_refresh(self) -> None:
        gpu_node = node("gpu", gpu=[{"usage_percent": 50}])
        targets = {
            "legacy": node("legacy"),
            "capability_unsupported": node(
                "unsupported",
                gpu=[{"usage_percent": 50}],
                capabilities={
                    "gpu.usage_percent": {
                        "supported": False,
                        "source": None,
                        "reason": "sensor_not_found",
                    }
                },
            ),
        }
        events = {
            "next": ShortPress(300, 210, 10),
            "auto_rotation": AutoRotateTick(10, True),
        }
        for target_name, target in targets.items():
            nodes = (gpu_node, target)
            for screen in (Screen.VALUES, Screen.GRAPH, Screen.MAIN_MENU):
                for event_name, event in events.items():
                    if screen == Screen.GRAPH and event_name == "next":
                        continue
                    with self.subTest(
                        target=target_name,
                        screen=screen,
                        event=event_name,
                    ):
                        state = UiState(
                            screen=screen,
                            selected_node_id="gpu",
                            selected_category_id="gpu",
                            metric_by_category={"gpu": "load"},
                        )
                        selected = reduce_ui(state, event, context(nodes, rotate=10))
                        refreshed = reduce_ui(
                            selected.state,
                            DataRefreshed(nodes, True, 11),
                            context(nodes),
                        )
                        self.assertEqual(target["node_id"], refreshed.state.selected_node_id)
                        self.assertEqual(screen, refreshed.state.screen)
                        self.assertEqual("cpu", refreshed.state.selected_category_id)
                        self.assertEqual("load", refreshed.state.metric_by_category["cpu"])

    def test_gesture_timing_and_short_center_transitions(self) -> None:
        value = node()
        opened = reduce_ui(
            UiState(selected_node_id="desktop"),
            ShortPress(160, 210, 5),
            context((value,), pause=30),
        )
        self.assertEqual(Screen.VALUES, opened.state.screen)
        self.assertEqual((5, 35), (opened.state.last_interaction_at, opened.state.pause_until))
        self.assertEqual("cpu", opened.state.selected_category_id)
        self.assertEqual("load", opened.state.metric_by_category["cpu"])
        self.assertEqual("short_center", opened.completed_action)

        closed = reduce_ui(
            UiState(screen=Screen.VALUES),
            ShortPress(160, 210, 6),
            context((value,)),
        )
        self.assertEqual(Screen.OVERVIEW, closed.state.screen)
        graph_values = reduce_ui(
            UiState(screen=Screen.GRAPH),
            ShortPress(160, 210, 6),
            context((value,)),
        )
        self.assertEqual(Screen.VALUES, graph_values.state.screen)
        self.assertEqual("graph_values", graph_values.completed_action)

        menu = reduce_ui(
            UiState(screen=Screen.MAIN_MENU),
            ShortPress(160, 210, 7),
            context((value,)),
        )
        self.assertFalse(menu.changed)

    def test_long_center_transitions_and_outside_noop(self) -> None:
        for screen in (Screen.OVERVIEW, Screen.VALUES, Screen.GRAPH):
            transition = reduce_ui(
                UiState(screen=screen),
                LongPress(160, 210, 2),
                context(),
            )
            self.assertEqual(Screen.MAIN_MENU, transition.state.screen)
            self.assertEqual("long_menu", transition.completed_action)

        for state, event in (
            (UiState(screen=Screen.MAIN_MENU), LongPress(160, 210, 3)),
            (UiState(), LongPress(10, 100, 4)),
        ):
            transition = reduce_ui(state, event, context())
            self.assertFalse(transition.changed)
            self.assertEqual(event.now, transition.state.last_interaction_at)

    def test_menu_category_selection_and_unavailable_rejection(self) -> None:
        value = node()
        selected = reduce_ui(
            UiState(screen=Screen.MAIN_MENU, selected_node_id="desktop"),
            ShortPress(10, 40, 1),
            context((value,)),
        )
        self.assertEqual(Screen.VALUES, selected.state.screen)
        self.assertEqual("category_cpu", selected.completed_action)
        self.assertEqual("load", selected.state.metric_by_category["cpu"])

        rejected = reduce_ui(
            UiState(screen=Screen.MAIN_MENU, selected_node_id="desktop"),
            ShortPress(10, 120, 2),
            context((value,)),
        )
        self.assertFalse(rejected.changed)
        self.assertEqual(Screen.MAIN_MENU, rejected.state.screen)

    def test_values_open_graph_preserves_state_for_every_eligible_category(self) -> None:
        value = node(
            gpu=[{"usage_percent": 50}],
            storage={"usage_percent": 50},
            network={"interface": "eth0"},
        )
        metrics = {
            "cpu": "temperature",
            "memory": "psi",
            "gpu": "power",
            "storage": "read",
            "network": "up",
        }
        for category_id in metrics:
            state = UiState(
                screen=Screen.VALUES,
                selected_node_id="desktop",
                node_index_hint=0,
                selected_category_id=category_id,
                metric_by_category=dict(metrics),
                selected_gpu_index=2,
                menu_page=1,
                nodes_page=3,
                pending_power_action=PowerAction.REBOOT,
                confirmation_started_at=4.5,
            )
            with self.subTest(category=category_id):
                transition = reduce_ui(state, ShortPress(160, 166, 10), context((value,)))
                self.assertEqual(Screen.GRAPH, transition.state.screen)
                self.assertTrue(transition.changed and transition.full_refresh)
                self.assertEqual("open_graph", transition.completed_action)
                self.assertIs(UiEffect.NONE, transition.effect)
                self.assertEqual("desktop", transition.state.selected_node_id)
                self.assertEqual(0, transition.state.node_index_hint)
                self.assertEqual(category_id, transition.state.selected_category_id)
                self.assertEqual(metrics, transition.state.metric_by_category)
                self.assertEqual(2, transition.state.selected_gpu_index)
                self.assertEqual((1, 3), (transition.state.menu_page, transition.state.nodes_page))
                self.assertIs(PowerAction.REBOOT, transition.state.pending_power_action)
                self.assertEqual(4.5, transition.state.confirmation_started_at)

    def test_values_health_false_controls_and_long_open_graph_are_noops(self) -> None:
        value = node()
        health = reduce_ui(
            UiState(screen=Screen.VALUES, selected_category_id="health"),
            ShortPress(160, 166, 1),
            context((value,)),
        )
        self.assertEqual(Screen.VALUES, health.state.screen)
        self.assertFalse(health.changed)
        self.assertIsNone(health.completed_action)

        state = UiState(
            screen=Screen.VALUES,
            selected_node_id="desktop",
            metric_by_category={"cpu": "temperature"},
        )
        with patch("display.categories.metric_at") as metric, \
                patch("display.categories.detail_view_at") as detail_view:
            for event in (
                ShortPress(150, 40, 2),
                ShortPress(240, 68, 3),
                ShortPress(10, 100, 4),
                LongPress(160, 166, 5),
            ):
                with self.subTest(event=event):
                    transition = reduce_ui(state, event, context((value,)))
                    self.assertEqual(Screen.VALUES, transition.state.screen)
                    self.assertEqual("temperature", transition.state.metric_by_category["cpu"])
                    self.assertFalse(transition.changed)
                    self.assertIsNone(transition.completed_action)
                    self.assertEqual(event.now, transition.state.last_interaction_at)
            metric.assert_not_called()
            detail_view.assert_not_called()

    def test_graph_metric_navigation_wraps_in_declared_order(self) -> None:
        value = node(
            gpu=[{"usage_percent": 50}],
            storage={"usage_percent": 50},
            network={"interface": "eth0"},
        )
        for selected_category in CATEGORIES[:-1]:
            metrics = selected_category.chart_metrics
            state = UiState(
                screen=Screen.GRAPH,
                selected_node_id="desktop",
                selected_category_id=selected_category.id,
                metric_by_category={selected_category.id: metrics[0].id},
            )
            with self.subTest(category=selected_category.id, direction="previous"):
                previous = reduce_ui(state, ShortPress(10, 210, 1), context((value,)))
                self.assertEqual(metrics[-1].id, previous.state.metric_by_category[selected_category.id])
                self.assertEqual("previous_metric", previous.completed_action)
                self.assertTrue(previous.changed and previous.full_refresh)
                self.assertIs(UiEffect.NONE, previous.effect)
            with self.subTest(category=selected_category.id, direction="next"):
                following = reduce_ui(previous.state, ShortPress(300, 210, 2), context((value,)))
                self.assertEqual(metrics[0].id, following.state.metric_by_category[selected_category.id])
                self.assertEqual("next_metric", following.completed_action)

    def test_graph_navigation_preserves_state_and_ignores_legacy_controls(self) -> None:
        value = node()
        state = UiState(
            screen=Screen.GRAPH,
            selected_node_id="desktop",
            node_index_hint=0,
            selected_category_id="cpu",
            metric_by_category={"cpu": "temperature", "memory": "psi"},
            selected_gpu_index=2,
            menu_page=1,
            nodes_page=3,
            pending_power_action=PowerAction.REBOOT,
            confirmation_started_at=4.5,
            last_rotation_at=7,
        )
        following = reduce_ui(state, ShortPress(300, 210, 10), context((value,)))
        self.assertEqual("clock", following.state.metric_by_category["cpu"])
        self.assertEqual("psi", following.state.metric_by_category["memory"])
        self.assertEqual(
            ("desktop", 0, "cpu", 2, 1, 3, PowerAction.REBOOT, 4.5, 7),
            (
                following.state.selected_node_id,
                following.state.node_index_hint,
                following.state.selected_category_id,
                following.state.selected_gpu_index,
                following.state.menu_page,
                following.state.nodes_page,
                following.state.pending_power_action,
                following.state.confirmation_started_at,
                following.state.last_rotation_at,
            ),
        )
        self.assertEqual((10, 40), (following.state.last_interaction_at, following.state.pause_until))

        with patch("display.categories.metric_at") as metric, \
                patch("display.categories.detail_view_at") as detail_view:
            for event in (
                ShortPress(150, 43, 11),
                ShortPress(80, 68, 12),
                ShortPress(240, 68, 13),
                LongPress(150, 43, 14),
            ):
                transition = reduce_ui(state, event, context((value,)))
                self.assertEqual(Screen.GRAPH, transition.state.screen)
                self.assertEqual("temperature", transition.state.metric_by_category["cpu"])
                self.assertFalse(transition.changed)
                self.assertIsNone(transition.completed_action)
            metric.assert_not_called()
            detail_view.assert_not_called()

        nodes = (value, node("other"))
        previous = reduce_ui(state, ShortPress(10, 210, 15), context(nodes))
        following = reduce_ui(state, ShortPress(300, 210, 16), context(nodes))
        self.assertEqual("desktop", previous.state.selected_node_id)
        self.assertEqual("desktop", following.state.selected_node_id)

    def test_graph_values_and_long_press_actions_are_exact(self) -> None:
        value = node()
        state = UiState(
            screen=Screen.GRAPH,
            selected_node_id="desktop",
            selected_category_id="cpu",
            metric_by_category={"cpu": "temperature"},
            selected_gpu_index=2,
            menu_page=1,
            nodes_page=3,
            pending_power_action=PowerAction.REBOOT,
            confirmation_started_at=4.5,
        )
        values = reduce_ui(state, ShortPress(160, 210, 1), context((value,)))
        self.assertEqual(Screen.VALUES, values.state.screen)
        self.assertEqual("graph_values", values.completed_action)
        self.assertTrue(values.changed and values.full_refresh)
        self.assertEqual(state.metric_by_category, values.state.metric_by_category)
        self.assertEqual(state.selected_gpu_index, values.state.selected_gpu_index)
        self.assertEqual((1, 3), (values.state.menu_page, values.state.nodes_page))
        self.assertIs(PowerAction.REBOOT, values.state.pending_power_action)
        self.assertEqual(4.5, values.state.confirmation_started_at)

        menu = reduce_ui(state, LongPress(160, 210, 2), context((value,)))
        self.assertEqual(Screen.MAIN_MENU, menu.state.screen)
        self.assertEqual("long_menu", menu.completed_action)
        for x in (10, 300):
            with self.subTest(x=x):
                ignored = reduce_ui(state, LongPress(x, 210, 3), context((value,)))
                self.assertEqual("temperature", ignored.state.metric_by_category["cpu"])
                self.assertFalse(ignored.changed)
                self.assertIsNone(ignored.completed_action)

    def test_graph_metric_selection_does_not_filter_declared_metrics(self) -> None:
        value = node(
            network={"interface": "eth0", "down_bytes_per_second": None, "up_bytes_per_second": None},
            capabilities={
                "network.down_bytes_per_second": {"supported": True},
                "network.up_bytes_per_second": {"supported": False},
            },
        )
        state = UiState(
            screen=Screen.GRAPH,
            selected_node_id="desktop",
            selected_category_id="network",
            metric_by_category={"network": "down"},
        )
        following = reduce_ui(state, ShortPress(300, 210, 1), context((value,)))
        self.assertEqual("up", following.state.metric_by_category["network"])

        only_metric = category("network").chart_metrics[:1]
        fake_category = SimpleNamespace(
            id="cpu",
            available=lambda _: True,
            chart_metrics=only_metric,
        )
        with patch("display.ui_state.category", return_value=fake_category), \
                patch("display.ui_state.can_open_graph", return_value=True):
            single_state = UiState(metric_by_category={"cpu": only_metric[0].id})
            copied = _select_graph_metric(
                single_state,
                value,
                1,
            )
        self.assertEqual({"cpu": only_metric[0].id}, copied.metric_by_category)
        self.assertIsNot(single_state.metric_by_category, copied.metric_by_category)

    def test_invalid_graph_category_normalizes_to_values(self) -> None:
        value = node()
        fallback = UiState(
            screen=Screen.GRAPH,
            selected_node_id="desktop",
            selected_category_id="health",
        )
        short = reduce_ui(fallback, ShortPress(160, 210, 1), context((value,)))
        long = reduce_ui(fallback, LongPress(160, 210, 2), context((value,)))
        self.assertEqual((Screen.OVERVIEW, "short_center"), (
            short.state.screen,
            short.completed_action,
        ))
        self.assertEqual((Screen.MAIN_MENU, "long_menu"), (
            long.state.screen,
            long.completed_action,
        ))

        refreshed = reduce_ui(
            UiState(screen=Screen.GRAPH, selected_category_id="health"),
            DataRefreshed((value,), True, 1),
            context((value,)),
        )
        self.assertEqual(Screen.VALUES, refreshed.state.screen)
        self.assertTrue(refreshed.changed and refreshed.full_refresh)

        nodes = (node("a"), node("b"))
        rotated = reduce_ui(
            UiState(
                screen=Screen.GRAPH,
                selected_node_id="a",
                selected_category_id="health",
                last_rotation_at=0,
            ),
            AutoRotateTick(10, True),
            context(nodes, rotate=10),
        )
        self.assertEqual(("b", Screen.VALUES), (rotated.state.selected_node_id, rotated.state.screen))

    def test_timeout_boundaries_touch_suppression_and_zero_disable(self) -> None:
        cases = (
            (Screen.MAIN_MENU, 15.0),
            (Screen.VALUES, 45.0),
            (Screen.GRAPH, 45.0),
        )
        for screen, timeout in cases:
            state = UiState(screen=screen, last_interaction_at=10.0)
            before = reduce_ui(state, InactivityTick(10 + timeout - 0.1, False), context())
            self.assertEqual(screen, before.state.screen)
            expired = reduce_ui(state, InactivityTick(10 + timeout, False), context())
            self.assertEqual(Screen.OVERVIEW, expired.state.screen)
            self.assertEqual("timeout_overview", expired.completed_action)
            pressed = reduce_ui(state, InactivityTick(100, True), context())
            self.assertEqual(screen, pressed.state.screen)

        disabled = reduce_ui(
            UiState(screen=Screen.GRAPH),
            InactivityTick(100, False),
            context(detail=0),
        )
        self.assertEqual(Screen.GRAPH, disabled.state.screen)
        overview = reduce_ui(UiState(), InactivityTick(100, False), context())
        self.assertEqual(Screen.OVERVIEW, overview.state.screen)

    def test_auto_rotation_success_and_every_guard(self) -> None:
        nodes = (node("a"), node("b"))
        state = UiState(
            selected_node_id="a",
            selected_gpu_index=2,
            pause_until=5,
            last_rotation_at=10,
        )
        rotated = reduce_ui(state, AutoRotateTick(20, True), context(nodes, rotate=10))
        self.assertEqual(("b", 1, 0, 20), (
            rotated.state.selected_node_id,
            rotated.state.node_index_hint,
            rotated.state.selected_gpu_index,
            rotated.state.last_rotation_at,
        ))
        self.assertTrue(rotated.changed and rotated.full_refresh)
        self.assertIsNone(rotated.completed_action)

        blocked = (
            (state, AutoRotateTick(20, True), context(nodes, rotate=0)),
            (state, AutoRotateTick(20, True), context((nodes[0],), rotate=10)),
            (UiState(selected_node_id="a", pause_until=21), AutoRotateTick(20, True), context(nodes)),
            (UiState(selected_node_id="a", last_rotation_at=11), AutoRotateTick(20, True), context(nodes)),
            (state, AutoRotateTick(20, False), context(nodes)),
            (UiState(screen=Screen.NODES, selected_node_id="a"), AutoRotateTick(20, True), context(nodes)),
        )
        for blocked_state, event, blocked_context in blocked:
            transition = reduce_ui(blocked_state, event, blocked_context)
            self.assertFalse(transition.changed)
            self.assertEqual(blocked_state.selected_node_id, transition.state.selected_node_id)

    def test_all_events_have_no_effect_and_future_screens_are_unreachable(self) -> None:
        value = node()
        events = (
            DataRefreshed((value,), True, 1),
            ShortPress(10, 10, 2),
            LongPress(10, 10, 3),
            InactivityTick(4, False),
            AutoRotateTick(5, True),
        )
        for event in events:
            transition = reduce_ui(UiState(), event, context((value,)))
            self.assertIs(UiEffect.NONE, transition.effect)

        for screen in (
            Screen.NODES,
            Screen.SYSTEM,
            Screen.POWER_CONFIRM,
            Screen.POWER_PENDING,
            Screen.POWER_ERROR,
        ):
            state = UiState(screen=screen)
            transition = reduce_ui(state, ShortPress(160, 210, 10), context((value,)))
            self.assertEqual(screen, transition.state.screen)
            self.assertIsNone(transition.state.pending_power_action)
            self.assertIsNone(transition.state.confirmation_started_at)
            self.assertFalse(transition.changed)
            self.assertIs(UiEffect.NONE, transition.effect)


if __name__ == "__main__":
    unittest.main()
