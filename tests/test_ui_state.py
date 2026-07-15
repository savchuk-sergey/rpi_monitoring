import copy
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from display.categories import CATEGORIES, category
from display.navigation import NODES_PAGE_SIZE, nodes_page_count
from display.renderer import _status
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
    PowerRequestError,
    PowerRequestFailed,
    PowerRequestStatus,
    Screen,
    ShortPress,
    UiContext,
    UiEffect,
    UiState,
    _select_graph_metric,
    power_hold_progress,
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
    hold: float = 1.5,
    power_enabled: bool = True,
) -> UiContext:
    return UiContext(
        nodes,
        pause,
        detail,
        menu,
        rotate,
        hold,
        power_actions_enabled=power_enabled,
    )


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
        self.assertEqual(
            {"NONE": "none", "REQUEST_POWER": "request_power"},
            {item.name: item.value for item in UiEffect},
        )
        self.assertEqual(
            {"SENDING": "sending", "ACCEPTED": "accepted"},
            {item.name: item.value for item in PowerRequestStatus},
        )
        self.assertIsNone(UiState().pending_power_action)
        self.assertEqual(1.5, UiContext((), 1, 2, 3, 4).power_confirm_hold_seconds)

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
        for screen in (Screen.GRAPH, Screen.OVERVIEW):
            self.assertIsNone(visible_action_at(UiState(screen=screen), value, 160, 166))
        self.assertEqual(
            "menu_tile_nodes",
            visible_action_at(UiState(screen=Screen.MAIN_MENU), value, 160, 166),
        )
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

        menu_value = node(
            gpu=[{"usage_percent": 50}],
            storage={"usage_percent": 50},
            network={"interface": "eth0"},
        )
        expected = {
            0: ((80, 72, "menu_tile_cpu"), (240, 72, "menu_tile_memory"),
                (80, 152, "menu_tile_gpu"), (240, 152, "menu_tile_nodes")),
            1: ((80, 72, "menu_tile_storage"), (240, 72, "menu_tile_network"),
                (80, 152, "menu_tile_health"), (240, 152, "menu_tile_system")),
        }
        for page, points in expected.items():
            menu = UiState(screen=Screen.MAIN_MENU, menu_page=page)
            for x, y, action in points:
                with self.subTest(page=page, point=(x, y)):
                    self.assertEqual(action, visible_action_at(menu, menu_value, x, y))
            self.assertEqual(
                ("menu_previous_page", "menu_back", "menu_next_page"),
                tuple(visible_action_at(menu, menu_value, x, 210) for x in (10, 160, 300)),
            )
        unavailable = UiState(screen=Screen.MAIN_MENU, menu_page=1)
        unavailable_node = node()
        self.assertEqual(
            "menu_hint_storage",
            visible_action_at(unavailable, unavailable_node, 80, 72),
        )
        self.assertEqual(
            "menu_hint_network",
            visible_action_at(unavailable, unavailable_node, 240, 72),
        )
        self.assertEqual(
            "menu_hint_nodes",
            visible_action_at(
                UiState(screen=Screen.MAIN_MENU),
                unavailable_node,
                240,
                152,
                (),
            ),
        )
        self.assertEqual(
            ("previous", "center", "next"),
            tuple(visible_action_at(unavailable, None, x, 210) for x in (10, 160, 300)),
        )

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
        for screen in (Screen.MAIN_MENU, Screen.VALUES, Screen.GRAPH, Screen.NODES):
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
                    if screen in {Screen.GRAPH, Screen.MAIN_MENU} and event_name == "next":
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
        self.assertEqual((Screen.OVERVIEW, "menu_back"), (
            menu.state.screen,
            menu.completed_action,
        ))
        self.assertTrue(menu.changed and menu.full_refresh)

    def test_long_center_transitions_and_outside_noop(self) -> None:
        value = node()
        for screen in (Screen.OVERVIEW, Screen.VALUES, Screen.GRAPH):
            transition = reduce_ui(
                UiState(screen=screen),
                LongPress(160, 210, 2),
                context((value,)),
            )
            self.assertEqual(Screen.MAIN_MENU, transition.state.screen)
            self.assertEqual(0, transition.state.menu_page)
            self.assertEqual("cpu", transition.state.selected_category_id)
            self.assertEqual("load", transition.state.metric_by_category["cpu"])
            self.assertEqual("long_menu", transition.completed_action)

        for state, event, ui_context in (
            (UiState(), LongPress(160, 210, 1), context()),
            (UiState(screen=Screen.MAIN_MENU), LongPress(160, 210, 3), context((value,))),
            (UiState(), LongPress(10, 100, 4), context((value,))),
        ):
            transition = reduce_ui(state, event, ui_context)
            self.assertFalse(transition.changed)
            self.assertEqual(event.now, transition.state.last_interaction_at)

    def test_menu_category_selection_and_unavailable_rejection(self) -> None:
        value = node(
            gpu=[{"usage_percent": 50}],
            storage={"usage_percent": 50},
            network={"interface": "eth0"},
        )
        targets = {
            "cpu": (0, 80, 72),
            "memory": (0, 240, 72),
            "gpu": (0, 80, 152),
            "storage": (1, 80, 72),
            "network": (1, 240, 72),
            "health": (1, 80, 152),
        }
        for category_id, (page, x, y) in targets.items():
            with self.subTest(category=category_id):
                selected = reduce_ui(
                    UiState(
                        screen=Screen.MAIN_MENU,
                        selected_node_id="desktop",
                        menu_page=page,
                    ),
                    ShortPress(x, y, 1),
                    context((value,)),
                )
                self.assertEqual(Screen.VALUES, selected.state.screen)
                self.assertEqual(category_id, selected.state.selected_category_id)
                self.assertEqual(
                    category(category_id).chart_metrics[0].id,
                    selected.state.metric_by_category[category_id],
                )
                self.assertEqual(page, selected.state.menu_page)
                self.assertEqual(f"category_{category_id}", selected.completed_action)

        system = reduce_ui(
            UiState(screen=Screen.MAIN_MENU, selected_node_id="desktop", menu_page=1),
            ShortPress(240, 152, 2),
            context((value,)),
        )
        self.assertEqual((Screen.SYSTEM, "open_system"), (
            system.state.screen, system.completed_action
        ))

        unavailable = node(storage={})
        rejected = reduce_ui(
            UiState(screen=Screen.MAIN_MENU, selected_node_id="desktop", menu_page=1),
            ShortPress(80, 72, 3),
            context((unavailable,)),
        )
        self.assertFalse(rejected.changed)
        self.assertEqual(Screen.MAIN_MENU, rejected.state.screen)

    def test_menu_entry_pagination_back_and_state_preservation(self) -> None:
        value = node(network={"interface": "eth0"})
        for screen in (Screen.OVERVIEW, Screen.VALUES, Screen.GRAPH):
            state = UiState(
                screen=screen,
                selected_node_id="desktop",
                selected_category_id="network",
                metric_by_category={"network": "up"},
                selected_gpu_index=2,
                nodes_page=3,
            )
            with self.subTest(entry_screen=screen):
                opened = reduce_ui(state, LongPress(160, 210, 1), context((value,)))
                self.assertEqual((Screen.MAIN_MENU, 1, "network", "up"), (
                    opened.state.screen,
                    opened.state.menu_page,
                    opened.state.selected_category_id,
                    opened.state.metric_by_category["network"],
                ))

        state = UiState(
            screen=Screen.MAIN_MENU,
            selected_node_id="desktop",
            selected_category_id="network",
            metric_by_category={"network": "up"},
            selected_gpu_index=2,
            menu_page=0,
            nodes_page=3,
        )
        for x, expected_page, action in (
            (10, 1, "menu_previous_page"),
            (300, 0, "menu_next_page"),
            (300, 1, "menu_next_page"),
            (10, 0, "menu_previous_page"),
        ):
            transition = reduce_ui(state, ShortPress(x, 210, 2), context((value,)))
            self.assertEqual(expected_page, transition.state.menu_page)
            self.assertEqual(action, transition.completed_action)
            self.assertEqual(("desktop", "network", {"network": "up"}, 2, 3), (
                transition.state.selected_node_id,
                transition.state.selected_category_id,
                transition.state.metric_by_category,
                transition.state.selected_gpu_index,
                transition.state.nodes_page,
            ))
            state = transition.state

        back = reduce_ui(state, ShortPress(160, 210, 3), context((value,)))
        self.assertEqual((Screen.OVERVIEW, "menu_back"), (
            back.state.screen,
            back.completed_action,
        ))
        self.assertEqual(state.menu_page, back.state.menu_page)

    def test_main_menu_refresh_and_auto_rotation_normalize_page(self) -> None:
        network_node = node("a", network={"interface": "eth0"})
        same_category = node("b", network={"interface": "eth1"})
        no_network = node("c")
        state = UiState(
            screen=Screen.MAIN_MENU,
            selected_node_id="a",
            selected_category_id="network",
            metric_by_category={"network": "up"},
            menu_page=1,
        )
        refreshed = reduce_ui(
            state,
            DataRefreshed((network_node,), True, 1),
            context((network_node,)),
        )
        self.assertEqual(("network", 1), (
            refreshed.state.selected_category_id,
            refreshed.state.menu_page,
        ))

        rotated_same = reduce_ui(
            state,
            AutoRotateTick(10, True),
            context((network_node, same_category), rotate=10),
        )
        self.assertEqual(("b", "network", 1), (
            rotated_same.state.selected_node_id,
            rotated_same.state.selected_category_id,
            rotated_same.state.menu_page,
        ))
        rotated_fallback = reduce_ui(
            state,
            AutoRotateTick(10, True),
            context((network_node, no_network), rotate=10),
        )
        self.assertEqual(("c", "cpu", 0, Screen.MAIN_MENU), (
            rotated_fallback.state.selected_node_id,
            rotated_fallback.state.selected_category_id,
            rotated_fallback.state.menu_page,
            rotated_fallback.state.screen,
        ))

        invalid = reduce_ui(
            UiState(
                screen=Screen.MAIN_MENU,
                selected_node_id="c",
                selected_category_id="network",
                menu_page=1,
            ),
            DataRefreshed((no_network,), True, 11),
            context((no_network,)),
        )
        self.assertEqual(("cpu", "load", 0), (
            invalid.state.selected_category_id,
            invalid.state.metric_by_category["cpu"],
            invalid.state.menu_page,
        ))
        self.assertTrue(invalid.changed and invalid.full_refresh)

    def test_main_menu_end_to_end_sequence(self) -> None:
        value = node(network={"interface": "eth0"})
        ui_context = context((value,))
        state = UiState(selected_node_id="desktop")
        state = reduce_ui(state, LongPress(160, 210, 1), ui_context).state
        self.assertEqual((Screen.MAIN_MENU, 0), (state.screen, state.menu_page))
        state = reduce_ui(state, ShortPress(300, 210, 2), ui_context).state
        self.assertEqual((Screen.MAIN_MENU, 1), (state.screen, state.menu_page))
        selected = reduce_ui(state, ShortPress(240, 72, 3), ui_context)
        self.assertEqual((Screen.VALUES, "network", "category_network"), (
            selected.state.screen,
            selected.state.selected_category_id,
            selected.completed_action,
        ))
        state = reduce_ui(selected.state, LongPress(160, 210, 4), ui_context).state
        self.assertEqual((Screen.MAIN_MENU, 1), (state.screen, state.menu_page))
        state = reduce_ui(state, ShortPress(160, 210, 5), ui_context).state
        self.assertEqual(Screen.OVERVIEW, state.screen)

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
            (Screen.NODES, 15.0),
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
            (UiState(screen=Screen.SYSTEM, selected_node_id="a"), AutoRotateTick(20, True), context(nodes)),
        )
        for blocked_state, event, blocked_context in blocked:
            transition = reduce_ui(blocked_state, event, blocked_context)
            self.assertFalse(transition.changed)
            self.assertEqual(blocked_state.selected_node_id, transition.state.selected_node_id)

    def test_phase_6_nodes_resolver_uses_full_snapshot_without_mutation(self) -> None:
        nodes = (node("node-c"), node("node-a"), node("node-b"), node("node-d"))
        state = UiState(screen=Screen.MAIN_MENU)
        state_before = copy.deepcopy(state)
        nodes_before = copy.deepcopy(nodes)
        selected_before = copy.deepcopy(nodes[0])
        self.assertEqual(
            "menu_tile_nodes",
            visible_action_at(state, nodes[0], 240, 152, nodes),
        )
        self.assertEqual(
            "menu_hint_nodes",
            visible_action_at(state, nodes[0], 240, 152, ()),
        )
        system = UiState(screen=Screen.MAIN_MENU, menu_page=1)
        self.assertEqual("menu_tile_system", visible_action_at(system, nodes[0], 240, 152, nodes))

        browser = UiState(screen=Screen.NODES)
        self.assertEqual(
            ("nodes_select_0", "nodes_select_1", "nodes_select_2"),
            tuple(visible_action_at(browser, nodes[0], 10, y, nodes) for y in (40, 90, 150)),
        )
        self.assertEqual(
            ("nodes_previous_page", "nodes_back", "nodes_next_page"),
            tuple(visible_action_at(browser, nodes[0], x, 210, nodes) for x in (10, 160, 300)),
        )
        one = nodes[:1]
        self.assertEqual(
            (None, "nodes_back", None),
            tuple(visible_action_at(browser, one[0], x, 210, one) for x in (10, 160, 300)),
        )
        two = nodes[:2]
        self.assertIsNone(visible_action_at(browser, two[0], 10, 150, two))
        self.assertEqual(
            ("previous", "center", "next"),
            tuple(visible_action_at(browser, None, x, 210, ()) for x in (10, 160, 300)),
        )
        self.assertEqual(state_before, state)
        self.assertEqual(nodes_before, nodes)
        self.assertEqual(selected_before, nodes[0])

    def test_phase_6_nodes_menu_entry_pagination_and_one_page_defense(self) -> None:
        nodes = (node("node-c"), node("node-a"), node("node-b"), node("node-d"))
        preserved = UiState(
            screen=Screen.MAIN_MENU,
            selected_node_id="node-d",
            node_index_hint=3,
            selected_category_id="health",
            metric_by_category={"health": "power"},
            selected_gpu_index=2,
            menu_page=0,
        )
        opened = reduce_ui(preserved, ShortPress(240, 152, 1), context(nodes))
        self.assertEqual(
            (Screen.NODES, "node-d", 3, 1, "open_nodes"),
            (
                opened.state.screen,
                opened.state.selected_node_id,
                opened.state.node_index_hint,
                opened.state.nodes_page,
                opened.completed_action,
            ),
        )
        self.assertEqual(("health", {"health": "power"}, 2), (
            opened.state.selected_category_id,
            opened.state.metric_by_category,
            opened.state.selected_gpu_index,
        ))

        missing = reduce_ui(
            UiState(screen=Screen.MAIN_MENU, selected_node_id="missing"),
            ShortPress(240, 152, 2),
            context(nodes),
        )
        self.assertEqual(("node-a", 1, 0), (
            missing.state.selected_node_id,
            missing.state.node_index_hint,
            missing.state.nodes_page,
        ))

        page_zero = replace(opened.state, nodes_page=0)
        previous = reduce_ui(page_zero, ShortPress(10, 210, 3), context(nodes))
        following = reduce_ui(page_zero, ShortPress(300, 210, 4), context(nodes))
        wrapped = reduce_ui(following.state, ShortPress(300, 210, 5), context(nodes))
        self.assertEqual((1, "nodes_previous_page"), (
            previous.state.nodes_page, previous.completed_action
        ))
        self.assertEqual((1, "nodes_next_page"), (
            following.state.nodes_page, following.completed_action
        ))
        self.assertEqual((0, "nodes_next_page"), (
            wrapped.state.nodes_page, wrapped.completed_action
        ))
        self.assertEqual("node-d", previous.state.selected_node_id)
        self.assertEqual("node-d", following.state.selected_node_id)

        for x in (10, 300):
            defensive = reduce_ui(
                UiState(screen=Screen.NODES, selected_node_id="node-a"),
                ShortPress(x, 210, 6),
                context((nodes[1],)),
            )
            self.assertFalse(defensive.changed)
            self.assertIsNone(defensive.completed_action)
            self.assertEqual(0, defensive.state.nodes_page)

        back = reduce_ui(page_zero, ShortPress(160, 210, 7), context(nodes))
        self.assertEqual((Screen.MAIN_MENU, 0, "node-d", "nodes_back"), (
            back.state.screen,
            back.state.menu_page,
            back.state.selected_node_id,
            back.completed_action,
        ))

    def test_phase_6_nodes_row_selection_uses_sorted_rows_and_original_index(self) -> None:
        nodes = (
            node("node-c"),
            node("node-a"),
            node("node-b"),
            node("node-d"),
        )
        for row, expected_id, expected_index, y in (
            (0, "node-a", 1, 40),
            (1, "node-b", 2, 90),
            (2, "node-c", 0, 150),
        ):
            with self.subTest(row=row):
                selected = reduce_ui(
                    UiState(
                        screen=Screen.NODES,
                        selected_node_id="node-d",
                        selected_gpu_index=2,
                    ),
                    ShortPress(10, y, 10 + row),
                    context(nodes),
                )
                self.assertEqual(
                    (Screen.OVERVIEW, expected_id, expected_index, 0, "select_node", 10 + row),
                    (
                        selected.state.screen,
                        selected.state.selected_node_id,
                        selected.state.node_index_hint,
                        selected.state.selected_gpu_index,
                        selected.completed_action,
                        selected.state.last_rotation_at,
                    ),
                )

        page_two = reduce_ui(
            UiState(screen=Screen.NODES, selected_node_id="node-a", nodes_page=1),
            ShortPress(10, 40, 20),
            context(nodes),
        )
        self.assertEqual(("node-d", 3, Screen.OVERVIEW), (
            page_two.state.selected_node_id,
            page_two.state.node_index_hint,
            page_two.state.screen,
        ))
        absent = reduce_ui(
            UiState(screen=Screen.NODES, selected_node_id="node-a", nodes_page=1),
            ShortPress(10, 90, 21),
            context(nodes),
        )
        self.assertFalse(absent.changed)
        self.assertIsNone(absent.completed_action)
        long_row = reduce_ui(
            UiState(screen=Screen.NODES, selected_node_id="node-a"),
            LongPress(10, 40, 22),
            context(nodes),
        )
        long_footer = reduce_ui(
            UiState(screen=Screen.NODES, selected_node_id="node-a"),
            LongPress(160, 210, 23),
            context(nodes),
        )
        for transition, now in ((long_row, 22), (long_footer, 23)):
            self.assertFalse(transition.changed)
            self.assertIsNone(transition.completed_action)
            self.assertEqual((Screen.NODES, now), (
                transition.state.screen, transition.state.last_interaction_at
            ))

    def test_phase_6_nodes_refresh_preserves_identity_clamps_and_keeps_stale_list(self) -> None:
        nodes = (node("node-c"), node("node-a"), node("node-b"), node("node-d"))
        reordered = (nodes[3], nodes[2], nodes[0], nodes[1])
        state = UiState(
            screen=Screen.NODES,
            selected_node_id="node-c",
            node_index_hint=0,
            nodes_page=1,
        )
        refreshed = reduce_ui(state, DataRefreshed(reordered, True, 1), context(reordered))
        self.assertEqual(("node-c", 2, 1), (
            refreshed.state.selected_node_id,
            refreshed.state.node_index_hint,
            refreshed.state.nodes_page,
        ))
        self.assertTrue(refreshed.changed and refreshed.full_refresh)

        status_changed = tuple(
            node(item["node_id"], online=False) if item["node_id"] == "node-c" else item
            for item in reordered
        )
        stable = reduce_ui(
            refreshed.state,
            DataRefreshed(status_changed, True, 2),
            context(status_changed),
        )
        self.assertFalse(stable.changed)
        self.assertEqual(("node-c", 2, 1), (
            stable.state.selected_node_id,
            stable.state.node_index_hint,
            stable.state.nodes_page,
        ))

        added = status_changed + (node("node-z"),)
        with_new = reduce_ui(stable.state, DataRefreshed(added, True, 3), context(added))
        self.assertEqual(1, with_new.state.nodes_page)
        self.assertEqual("node-c", with_new.state.selected_node_id)

        shrunk = (node("node-a"), node("node-b"), node("node-c"))
        clamped = reduce_ui(
            UiState(screen=Screen.NODES, selected_node_id="node-c", node_index_hint=2, nodes_page=9),
            DataRefreshed(shrunk, True, 4),
            context(shrunk),
        )
        self.assertEqual(("node-c", 2, 0), (
            clamped.state.selected_node_id,
            clamped.state.node_index_hint,
            clamped.state.nodes_page,
        ))

        remaining = (node("node-c"), node("node-a"))
        disappeared = reduce_ui(
            UiState(screen=Screen.NODES, selected_node_id="node-d", nodes_page=1),
            DataRefreshed(remaining, True, 5),
            context(remaining),
        )
        self.assertEqual(("node-a", 1, 0), (
            disappeared.state.selected_node_id,
            disappeared.state.node_index_hint,
            disappeared.state.nodes_page,
        ))

        stale = reduce_ui(
            state,
            DataRefreshed(nodes, False, 6),
            context(nodes),
        )
        self.assertEqual((Screen.NODES, "node-c", 0, 1), (
            stale.state.screen,
            stale.state.selected_node_id,
            stale.state.node_index_hint,
            stale.state.nodes_page,
        ))
        self.assertFalse(stale.changed)

        empty = reduce_ui(state, DataRefreshed((), False, 7), context())
        self.assertEqual((Screen.OVERVIEW, None, 0, 0), (
            empty.state.screen,
            empty.state.selected_node_id,
            empty.state.node_index_hint,
            empty.state.nodes_page,
        ))
        self.assertTrue(empty.changed and empty.full_refresh)

    def test_phase_6_nodes_end_to_end_sequence_and_link_loss(self) -> None:
        nodes = (node("node-c"), node("node-a"), node("node-b"), node("node-d"))
        ui_context = context(nodes)
        state = UiState(selected_node_id="node-b", node_index_hint=2)
        state = reduce_ui(state, LongPress(160, 210, 1), ui_context).state
        self.assertEqual((Screen.MAIN_MENU, 0), (state.screen, state.menu_page))
        opened = reduce_ui(state, ShortPress(240, 152, 2), ui_context)
        self.assertEqual((Screen.NODES, 0, "open_nodes"), (
            opened.state.screen, opened.state.nodes_page, opened.completed_action
        ))
        following = reduce_ui(opened.state, ShortPress(300, 210, 3), ui_context)
        self.assertEqual(1, following.state.nodes_page)
        selected = reduce_ui(following.state, ShortPress(10, 40, 4), ui_context)
        self.assertEqual((Screen.OVERVIEW, "node-d", "select_node"), (
            selected.state.screen,
            selected.state.selected_node_id,
            selected.completed_action,
        ))
        state = reduce_ui(selected.state, LongPress(160, 210, 5), ui_context).state
        reopened = reduce_ui(state, ShortPress(240, 152, 6), ui_context)
        self.assertEqual((Screen.NODES, 1, "node-d"), (
            reopened.state.screen,
            reopened.state.nodes_page,
            reopened.state.selected_node_id,
        ))
        stale = reduce_ui(
            reopened.state,
            DataRefreshed(nodes, False, 7),
            ui_context,
        )
        self.assertEqual((Screen.NODES, 1, "node-d"), (
            stale.state.screen,
            stale.state.nodes_page,
            stale.state.selected_node_id,
        ))
        back = reduce_ui(stale.state, ShortPress(160, 210, 8), ui_context)
        self.assertEqual((Screen.MAIN_MENU, 0, "nodes_back"), (
            back.state.screen,
            back.state.menu_page,
            back.completed_action,
        ))
        self.assertEqual(3, NODES_PAGE_SIZE)
        self.assertEqual(2, nodes_page_count(len(nodes)))

    def test_phase_8_system_opens_local_power_confirmation_and_cancel_is_safe(self) -> None:
        nodes = (node("a"), node("b"))
        system = UiState(
            screen=Screen.SYSTEM,
            selected_node_id="a",
            node_index_hint=0,
            selected_category_id="network",
            metric_by_category={"network": "up"},
            selected_gpu_index=2,
            menu_page=1,
            nodes_page=3,
            last_rotation_at=9,
        )
        for selected, snapshot in ((nodes[0], nodes), (None, ()), (None, None)):
            self.assertEqual("system_restart", visible_action_at(system, selected, 0, 32, snapshot))
            self.assertEqual("system_shutdown", visible_action_at(system, selected, 319, 183, snapshot))
            self.assertEqual("system_back", visible_action_at(system, selected, 64, 192, snapshot))

        for point, action, power_action, completed in (
            ((20, 50), "system_restart", PowerAction.REBOOT, "open_reboot_confirmation"),
            ((20, 130), "system_shutdown", PowerAction.POWEROFF, "open_poweroff_confirmation"),
        ):
            with self.subTest(action=action):
                opened = reduce_ui(system, ShortPress(*point, 10), context(nodes))
                self.assertEqual((Screen.POWER_CONFIRM, power_action, completed, True, True), (
                    opened.state.screen,
                    opened.state.pending_power_action,
                    opened.completed_action,
                    opened.changed,
                    opened.full_refresh,
                ))
                self.assertIsNone(opened.state.confirmation_started_at)
                for field in (
                    "selected_node_id", "node_index_hint", "selected_category_id",
                    "metric_by_category", "selected_gpu_index", "menu_page", "nodes_page",
                    "last_rotation_at",
                ):
                    self.assertEqual(getattr(system, field), getattr(opened.state, field))
                cancelled = reduce_ui(opened.state, ShortPress(50, 210, 11), context(nodes))
                self.assertEqual((Screen.SYSTEM, None, None, "power_cancel"), (
                    cancelled.state.screen,
                    cancelled.state.pending_power_action,
                    cancelled.state.confirmation_started_at,
                    cancelled.completed_action,
                ))
                self.assertIs(UiEffect.NONE, cancelled.effect)

        for point in ((20, 50), (20, 130)):
            held = reduce_ui(system, LongPress(*point, 12), context(nodes))
            self.assertEqual(Screen.SYSTEM, held.state.screen)
            self.assertFalse(held.changed)

    def test_phase_8_hold_progress_completion_release_and_movement_cancellation(self) -> None:
        base = UiState(screen=Screen.POWER_CONFIRM, pending_power_action=PowerAction.REBOOT)
        before = copy.deepcopy(base)
        self.assertEqual(0.0, power_hold_progress(base, 10, 1.5))
        started = reduce_ui(base, PowerHoldStarted(10.0), context(hold=1.5))
        self.assertEqual(before, base)
        self.assertEqual((10.0, 10.0, True, False), (
            started.state.confirmation_started_at,
            started.state.last_interaction_at,
            started.changed,
            started.full_refresh,
        ))
        for now, expected in ((10.0, 0.0), (10.375, 0.25), (10.75, 0.5), (11.125, 0.75)):
            self.assertEqual(expected, power_hold_progress(started.state, now, 1.5))
            tick = reduce_ui(started.state, PowerHoldTick(now), context(hold=1.5))
            self.assertFalse(tick.changed)
        self.assertLess(power_hold_progress(started.state, 11.49, 1.5), 1.0)
        completed = reduce_ui(started.state, PowerHoldTick(11.5), context(hold=1.5))
        self.assertEqual((Screen.POWER_PENDING, PowerAction.REBOOT, None, 11.5, "power_confirmed"), (
            completed.state.screen,
            completed.state.pending_power_action,
            completed.state.confirmation_started_at,
            completed.state.last_interaction_at,
            completed.completed_action,
        ))
        second_tick = reduce_ui(completed.state, PowerHoldTick(12), context(hold=1.5))
        self.assertFalse(second_tick.changed)
        self.assertIsNone(second_tick.completed_action)

        for event, completed_action in (
            (PowerHoldReleased(10.5), "power_hold_released"),
            (PowerHoldCancelled(10.5), "power_hold_cancelled"),
        ):
            transition = reduce_ui(started.state, event, context(hold=1.5))
            self.assertEqual((Screen.POWER_CONFIRM, None, completed_action), (
                transition.state.screen,
                transition.state.confirmation_started_at,
                transition.completed_action,
            ))
            self.assertEqual(0.0, power_hold_progress(transition.state, 20, 1.5))

        short_hold = reduce_ui(base, ShortPress(200, 210, 1), context())
        long_hold = reduce_ui(base, LongPress(200, 210, 1), context())
        self.assertFalse(short_hold.changed)
        self.assertFalse(long_hold.changed)
        self.assertIsNone(short_hold.state.confirmation_started_at)
        missing = UiState(screen=Screen.POWER_CONFIRM)
        self.assertIsNone(visible_action_at(missing, None, 200, 210, ()))
        self.assertFalse(reduce_ui(missing, PowerHoldStarted(1), context()).changed)
        for hold_seconds in (0, -1):
            self.assertEqual(0.0, power_hold_progress(started.state, 100, hold_seconds))
            self.assertEqual(
                Screen.POWER_CONFIRM,
                reduce_ui(started.state, PowerHoldTick(100), context(hold=hold_seconds)).state.screen,
            )

    def test_phase_9_power_screens_refresh_timeout_rotation_and_navigation(self) -> None:
        nodes = (node("a"), node("b"))
        for screen in (Screen.POWER_CONFIRM, Screen.POWER_PENDING, Screen.POWER_ERROR):
            state = UiState(
                screen=screen,
                selected_node_id="a",
                pending_power_action=PowerAction.POWEROFF,
                confirmation_started_at=1 if screen == Screen.POWER_CONFIRM else None,
                power_request_status=(
                    PowerRequestStatus.SENDING
                    if screen == Screen.POWER_PENDING
                    else None
                ),
                power_request_error=(
                    PowerRequestError.TIMEOUT
                    if screen == Screen.POWER_ERROR
                    else None
                ),
                last_interaction_at=0,
            )
            for refreshed_nodes, online in (((), True), ((), False), (nodes, True), (nodes, False)):
                refreshed = reduce_ui(
                    state,
                    DataRefreshed(refreshed_nodes, online, 2),
                    context(refreshed_nodes),
                )
                self.assertEqual(screen, refreshed.state.screen)
                self.assertEqual(PowerAction.POWEROFF, refreshed.state.pending_power_action)
            rotated = reduce_ui(state, AutoRotateTick(30, True), context(nodes, rotate=1))
            self.assertEqual((screen, "a"), (rotated.state.screen, rotated.state.selected_node_id))
            suppressed = reduce_ui(state, InactivityTick(15, True), context(nodes, menu=15))
            self.assertEqual(screen, suppressed.state.screen)
            timed_out = reduce_ui(state, InactivityTick(15, False), context(nodes, menu=15))
            if screen == Screen.POWER_PENDING:
                self.assertEqual(state, timed_out.state)
                self.assertIsNone(timed_out.completed_action)
            else:
                self.assertEqual((Screen.SYSTEM, None, None, None, None, "timeout_system"), (
                    timed_out.state.screen,
                    timed_out.state.pending_power_action,
                    timed_out.state.confirmation_started_at,
                    timed_out.state.power_request_status,
                    timed_out.state.power_request_error,
                    timed_out.completed_action,
                ))

        pending = UiState(screen=Screen.POWER_PENDING, pending_power_action=PowerAction.REBOOT)
        back = reduce_ui(pending, ShortPress(160, 210, 20), context(nodes))
        self.assertEqual((Screen.POWER_PENDING, PowerAction.REBOOT, None), (
            back.state.screen, back.state.pending_power_action, back.completed_action
        ))
        self.assertFalse(reduce_ui(pending, PowerHoldReleased(21), context(nodes)).changed)

        error = UiState(
            screen=Screen.POWER_ERROR,
            pending_power_action=PowerAction.REBOOT,
            power_request_error=PowerRequestError.IO_ERROR,
        )
        cleared = reduce_ui(error, ShortPress(160, 210, 20), context(nodes))
        self.assertEqual(
            (Screen.SYSTEM, None, None, None, None, "power_error_back"),
            (
                cleared.state.screen,
                cleared.state.pending_power_action,
                cleared.state.confirmation_started_at,
                cleared.state.power_request_status,
                cleared.state.power_request_error,
                cleared.completed_action,
            ),
        )

    def test_phase_8_pending_timeout_starts_at_hold_completion(self) -> None:
        confirmation = UiState(
            screen=Screen.POWER_CONFIRM,
            pending_power_action=PowerAction.POWEROFF,
        )
        started = reduce_ui(
            confirmation,
            PowerHoldStarted(0),
            context(menu=15, hold=20),
        )
        completed = reduce_ui(
            started.state,
            PowerHoldTick(20),
            context(menu=15, hold=20),
        )
        released = reduce_ui(
            completed.state,
            PowerHoldReleased(20.05),
            context(menu=15, hold=20),
        )
        active = reduce_ui(
            released.state,
            InactivityTick(20.1, False),
            context(menu=15, hold=20),
        )

        self.assertEqual(20, completed.state.last_interaction_at)
        self.assertFalse(released.changed)
        self.assertEqual(
            (Screen.POWER_PENDING, PowerAction.POWEROFF, None),
            (
                active.state.screen,
                active.state.pending_power_action,
                active.completed_action,
            ),
        )
        self.assertIs(UiEffect.REQUEST_POWER, completed.effect)

    def test_phase_9_effect_and_typed_result_lifecycle(self) -> None:
        value = node()
        events = (
            DataRefreshed((value,), True, 1),
            ShortPress(10, 10, 2),
            LongPress(10, 10, 3),
            InactivityTick(4, False),
            AutoRotateTick(5, True),
            PowerHoldStarted(6),
            PowerHoldTick(7),
            PowerHoldCancelled(8),
            PowerHoldReleased(9),
        )
        for event in events:
            transition = reduce_ui(UiState(), event, context((value,)))
            self.assertIs(UiEffect.NONE, transition.effect)

        system = UiState(screen=Screen.SYSTEM)
        confirmation = reduce_ui(system, ShortPress(20, 50, 10), context((value,)))
        pending = reduce_ui(
            reduce_ui(confirmation.state, PowerHoldStarted(11), context((value,), hold=1)).state,
            PowerHoldTick(12),
            context((value,), hold=1),
        )
        self.assertEqual(Screen.POWER_CONFIRM, confirmation.state.screen)
        self.assertEqual(Screen.POWER_PENDING, pending.state.screen)
        self.assertIs(UiEffect.REQUEST_POWER, pending.effect)
        self.assertIs(PowerRequestStatus.SENDING, pending.state.power_request_status)
        self.assertIs(PowerAction.REBOOT, pending.state.pending_power_action)
        self.assertIs(
            UiEffect.NONE,
            reduce_ui(pending.state, PowerHoldTick(12.1), context((value,), hold=1)).effect,
        )

        accepted = reduce_ui(
            pending.state,
            PowerRequestAccepted(13),
            context((value,)),
        )
        self.assertEqual(
            (Screen.POWER_PENDING, PowerRequestStatus.ACCEPTED, "power_request_accepted"),
            (
                accepted.state.screen,
                accepted.state.power_request_status,
                accepted.completed_action,
            ),
        )
        self.assertIs(UiEffect.NONE, accepted.effect)
        self.assertFalse(
            reduce_ui(
                accepted.state,
                PowerRequestAccepted(14),
                context((value,)),
            ).changed
        )

        failed = reduce_ui(
            pending.state,
            PowerRequestFailed(PowerRequestError.TIMEOUT, 13),
            context((value,)),
        )
        self.assertEqual(
            (Screen.POWER_ERROR, PowerRequestError.TIMEOUT, "power_request_failed"),
            (
                failed.state.screen,
                failed.state.power_request_error,
                failed.completed_action,
            ),
        )
        self.assertIs(UiEffect.NONE, failed.effect)
        self.assertFalse(
            reduce_ui(
                failed.state,
                PowerRequestFailed(PowerRequestError.IO_ERROR, 14),
                context((value,)),
            ).changed
        )

    def test_phase_9_disabled_power_configuration_is_fail_closed(self) -> None:
        system = UiState(screen=Screen.SYSTEM)
        disabled = context((node(),), power_enabled=False)
        for point in ((20, 50), (20, 130)):
            transition = reduce_ui(system, ShortPress(*point, 1), disabled)
            self.assertEqual(system, transition.state)
            self.assertIs(UiEffect.NONE, transition.effect)
        confirm = UiState(
            screen=Screen.POWER_CONFIRM,
            pending_power_action=PowerAction.REBOOT,
        )
        started = reduce_ui(confirm, PowerHoldStarted(1), disabled)
        completed = reduce_ui(
            replace(confirm, confirmation_started_at=0),
            PowerHoldTick(10),
            disabled,
        )
        self.assertEqual(confirm, started.state)
        self.assertEqual(Screen.POWER_CONFIRM, completed.state.screen)
        self.assertIs(UiEffect.NONE, completed.effect)


if __name__ == "__main__":
    unittest.main()
