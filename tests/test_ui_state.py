import copy
import unittest

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
    reduce_ui,
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
            UiState(selected_node_id="a", selected_gpu_index=2),
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

        for screen in (Screen.VALUES, Screen.GRAPH):
            closed = reduce_ui(
                UiState(screen=screen),
                ShortPress(160, 210, 6),
                context((value,)),
            )
            self.assertEqual(Screen.OVERVIEW, closed.state.screen)

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

    def test_values_graph_tabs_and_metric_selection(self) -> None:
        value = node()
        graph = reduce_ui(
            UiState(screen=Screen.VALUES, selected_node_id="desktop"),
            ShortPress(240, 68, 1),
            context((value,)),
        )
        self.assertEqual(Screen.GRAPH, graph.state.screen)
        self.assertEqual("view_graph", graph.completed_action)
        values = reduce_ui(graph.state, ShortPress(80, 68, 2), context((value,)))
        self.assertEqual(Screen.VALUES, values.state.screen)
        self.assertEqual("view_values", values.completed_action)

        for screen in (Screen.VALUES, Screen.GRAPH):
            selected = reduce_ui(
                UiState(screen=screen, selected_node_id="desktop"),
                ShortPress(150, 40, 3),
                context((value,)),
            )
            self.assertEqual("temperature", selected.state.metric_by_category["cpu"])
            self.assertEqual("metric_temperature", selected.completed_action)
            self.assertFalse(selected.full_refresh)

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
