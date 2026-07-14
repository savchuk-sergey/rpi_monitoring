import copy
import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageColor, ImageDraw

from display.drivers.ili9341 import ILI9341, rgb565
from display.categories import CATEGORIES, category, category_at, detail_view_at, metric_at
from display.gestures import GestureKind, TouchRecognizer
from display.history import HistoryStore
from display.navigation import (
    FOOTER_TOP,
    MODE_HITBOX,
    NAV_WIDTH,
    NEXT_HITBOX,
    PREVIOUS_HITBOX,
    VALUES_GRAPH_BUTTON_RECT,
    VALUES_GRAPH_HITBOX,
    map_touch,
    move,
    selected_index,
    touch_action,
    values_action_at,
)
from display.renderer import (
    FONT_PATH,
    AMBER,
    BACKGROUND,
    BRIGHT,
    GREEN,
    MUTED,
    RED,
    _age,
    _chart,
    _format_bytes_pair,
    _format_clock,
    _format_power,
    _format_rate,
    _format_temperature,
    _format_uptime,
    _number,
    _status,
    _value,
    render,
)
from display.ui_state import ShortPress, Screen, UiContext, UiState, reduce_ui
from tools.touch_calibrate import calculate


def node(**changes):
    value = {
        "node_id": "desktop",
        "display_name": "A very long desktop display name that must fit safely",
        "timestamp_utc": "2026-07-12T03:00:00Z",
        "received_at_utc": "2026-07-12T03:00:01Z",
        "online": True,
        "cpu": {"usage_percent": 47, "temperature_c": 63, "power_w": None},
        "memory": {"usage_percent": 63},
        "gpu": [],
        "collector": {"version": "0.1.0", "errors": []},
    }
    value.update(changes)
    return value


def waiting_node():
    return {
        "node_id": "waiting-node",
        "display_name": "waiting-node",
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


UNCHANGED_RENDER_HASHES = {
    "graph": "66b0364742250623eb4d2522b1ac07a168c503658b16c1f00c84e92b565311ff",
    "graph_with_history": "b497c0beaddc5a3b04d785699cce705e5d7ea89862109cc5d7085eda29d48b8b",
    "main_menu_capabilities": "21b52b19516410dfed6b3946cbf9cc518fcf17d09c454d7728bcf237ea3db399",
    "main_menu_legacy": "a73cbc7872ebc0b018673c4409c0b0d5d2281cb7c16fc684c1f637246d9bd19b",
    "overview_legacy": "7a64eb574d9d969407dec89fbf7ab8493a748dadec645124825d6e9cef15c9d4",
    "overview_waiting": "7064e7983ea4571ed55586a2d656d493bbce9032bb44374853015a5d7faac6d4",
}

BASELINE_VALUES_HASHES = {
    "default": "fd5a1de62d72977ab5a49e5ea83584b9a535033d80f07ac30f441e9d100ba928",
    "cpu": "533e2a325278ea7d3e11f2e3d2c8af5115727e48ec87ee3f27e7066416ec2e89",
    "memory": "1065d393117aaa84c532ad08e445b9c06caeccf691984d12dd654ad930485291",
    "gpu": "c64fa3bd2e601dbf61bb08b5e0a51a4b21f749fb434048cc1a84db1e3f61b9eb",
    "storage": "aa1a2645e314dad9a80a553cc00108d565b3c2759d1b9d57804ba0c8db2bf465",
    "network": "6662bee7c7150e22c93b0c49a4b3cd7b593c29c1508e74d6aaf4bf3c4a0f836a",
    "health": "44c16e21b0339f08419a689908303c9400d1488d6cea2f5522e7d9b3bd4a2d8c",
}

VALUES_RENDER_HASHES = {
    "default": "60cceb645e7ec66977fdd73c8d82113b508e9fae723ef7006a067a3a9ee4e2a0",
    "cpu": "41e20290d043d8b120eef2f4f22b4833df0cbb9624d5f1224c3c0de45dfbbae7",
    "memory": "e903f17c4a689499ef081197f897c43d84d8016dd7904bba67f138bc0f8086a3",
    "gpu": "462acb84a84384d342ac2f9ad42a2bc935dabd1000ed657f28b4df3297caff32",
    "storage": "c5e7e553d2432067547333721a135a84de4747caa0b15ab617eb025ec7449dc4",
    "network": "6a9431b6fedc4d807f636c82392ea0d1f1ea72cb59b84a519160ad02e7a866d8",
    "health": "44c16e21b0339f08419a689908303c9400d1488d6cea2f5522e7d9b3bd4a2d8c",
    "cpu_open_graph_pressed": "fe74a79dc01231277ea74759ce8af49e1967a14921832f55f0d3083e419c001f",
}


def complete_v2_node(**changes) -> dict:
    value = node(
        cpu={"usage_percent": 47, "temperature_c": 63, "power_w": 55, "clock_mhz": 4725},
        memory={
            "usage_percent": 63,
            "used_bytes": 24 * 1024**3,
            "total_bytes": 32 * 1024**3,
            "swap_used_bytes": 2 * 1024**3,
            "swap_total_bytes": 8 * 1024**3,
            "swap_usage_percent": 25,
            "pressure_some_percent": 1.25,
        },
        gpu=[{
            "id": "0", "name": "RTX", "usage_percent": 81, "temperature_c": 69,
            "power_w": 117, "memory_used_bytes": 6 * 1024**3,
            "memory_total_bytes": 12 * 1024**3, "memory_usage_percent": 50,
            "fan_percent": 74, "clock_mhz": 2625,
        }],
        health={"uptime_seconds": 90000, "undervoltage": False, "throttled": False},
        storage={
            "name": "/", "usage_percent": 60, "used_bytes": 60 * 1024**3,
            "total_bytes": 100 * 1024**3, "read_bytes_per_second": 1250000,
            "write_bytes_per_second": 640000, "temperature_c": 42,
        },
        network={
            "interface": "eth0", "link_up": True,
            "down_bytes_per_second": 12500000, "up_bytes_per_second": 2500000,
        },
        device={"power_w": 6.2},
    )
    value.update(changes)
    return value


class DisplayTests(unittest.TestCase):
    def test_matrix_font_is_bundled(self) -> None:
        self.assertTrue(FONT_PATH.is_file())
        self.assertEqual(
            ("#000400", "#43ff6b", "#c4ffcf", "#438d50", "#ff5c5c", "#ffb84d"),
            (BACKGROUND, GREEN, BRIGHT, MUTED, RED, AMBER),
        )

    def test_footer_hitboxes_are_at_least_48_pixels(self) -> None:
        for left, top, right, bottom in (
            PREVIOUS_HITBOX,
            MODE_HITBOX,
            NEXT_HITBOX,
        ):
            self.assertGreaterEqual(right - left, 48)
            self.assertGreaterEqual(bottom - top, 48)

    def test_open_graph_geometry_and_boundaries_are_exact(self) -> None:
        self.assertEqual((0, 140, 320, 192), VALUES_GRAPH_HITBOX)
        self.assertEqual((8, 142, 312, 190), VALUES_GRAPH_BUTTON_RECT)
        left, top, right, bottom = VALUES_GRAPH_HITBOX
        self.assertGreaterEqual(right - left, 48)
        self.assertGreaterEqual(bottom - top, 48)
        self.assertLessEqual(bottom, FOOTER_TOP)
        self.assertEqual(48, VALUES_GRAPH_BUTTON_RECT[3] - VALUES_GRAPH_BUTTON_RECT[1])
        for point in ((0, 140), (319, 140), (0, 191), (319, 191)):
            with self.subTest(point=point):
                self.assertEqual("open_graph", values_action_at(*point))
        for point in ((0, 139), (319, 139), (0, 192), (319, 192), (-1, 166), (320, 166)):
            with self.subTest(point=point):
                self.assertIsNone(values_action_at(*point))

    def test_measurements_are_compact_and_semantic(self) -> None:
        self.assertEqual("0.7", _number(0.7))
        self.assertEqual("5", _number(5))
        self.assertEqual("100%", _value(100, "%"))
        self.assertEqual("—", _value(None, "W"))
        self.assertEqual("63°C", _format_temperature(63))
        self.assertEqual("63.5°C", _format_temperature(63.5))
        self.assertEqual("6.2W", _format_power(6.2))
        self.assertEqual("117W", _format_power(117))

    def test_renderer_is_320_by_240_for_waiting_and_node_states(self) -> None:
        self.assertEqual((320, 240), render(None).size)
        self.assertEqual((320, 240), render(node(), (1, 4)).size)
        state = UiState(screen=Screen.VALUES)
        self.assertEqual((320, 240), render(node(), ui_state=state).size)
        state.screen = Screen.MAIN_MENU
        self.assertEqual((320, 240), render(node(), ui_state=state).size)

    def test_unaffected_render_hashes_are_unchanged(self) -> None:
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        capabilities = {
            "cpu.usage_percent": {
                "supported": True,
                "source": "procfs",
                "reason": None,
            },
            "storage.usage_percent": {
                "supported": True,
                "source": "statvfs",
                "reason": None,
            },
            "gpu.usage_percent": {
                "supported": False,
                "source": None,
                "reason": "sensor_not_found",
            },
        }
        history = HistoryStore(window_seconds=300, max_samples=180)
        history.add(
            node(
                timestamp_utc="2026-07-12T03:00:00Z",
                cpu={"usage_percent": 20, "temperature_c": 63, "power_w": None},
            )
        )
        history.add(node(timestamp_utc="2026-07-12T03:00:01Z", online=False))
        graph_node = node(
            timestamp_utc="2026-07-12T03:00:02Z",
            cpu={"usage_percent": 80, "temperature_c": 63, "power_w": None},
        )
        history.add(graph_node)
        scenarios = {
            "overview_legacy": (node(), UiState(), None),
            "overview_waiting": (waiting_node(), UiState(), None),
            "main_menu_legacy": (node(), UiState(screen=Screen.MAIN_MENU), None),
            "main_menu_capabilities": (
                node(capabilities=capabilities),
                UiState(screen=Screen.MAIN_MENU),
                None,
            ),
            "graph": (node(), UiState(screen=Screen.GRAPH), None),
            "graph_with_history": (
                graph_node,
                UiState(screen=Screen.GRAPH),
                history,
            ),
        }
        for name, (value, state, history_store) in scenarios.items():
            with self.subTest(name=name):
                digest = hashlib.sha256(
                    render(
                        value,
                        (1, 4),
                        True,
                        state,
                        history=history_store,
                        now=now,
                    ).tobytes()
                ).hexdigest()
                self.assertEqual(UNCHANGED_RENDER_HASHES[name], digest)

    def test_values_render_hashes_match_phase_3_targets(self) -> None:
        value = complete_v2_node()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        default_digest = hashlib.sha256(
            render(
                node(),
                (1, 4),
                True,
                UiState(screen=Screen.VALUES),
                now=now,
            ).tobytes()
        ).hexdigest()
        self.assertEqual(VALUES_RENDER_HASHES["default"], default_digest)
        self.assertNotEqual(BASELINE_VALUES_HASHES["default"], default_digest)
        for category_id in ("cpu", "memory", "gpu", "storage", "network", "health"):
            with self.subTest(category=category_id):
                state = UiState(screen=Screen.VALUES, selected_category_id=category_id)
                digest = hashlib.sha256(
                    render(value, (1, 1), True, state, now=now).tobytes()
                ).hexdigest()
                self.assertEqual(VALUES_RENDER_HASHES[category_id], digest)
                if category_id == "health":
                    self.assertEqual(BASELINE_VALUES_HASHES[category_id], digest)
                else:
                    self.assertNotEqual(BASELINE_VALUES_HASHES[category_id], digest)
        pressed_digest = hashlib.sha256(
            render(
                value,
                (1, 1),
                True,
                UiState(screen=Screen.VALUES),
                pressed_action="open_graph",
                now=now,
            ).tobytes()
        ).hexdigest()
        self.assertEqual(VALUES_RENDER_HASHES["cpu_open_graph_pressed"], pressed_digest)

    def test_renderer_distinguishes_empty_offline_and_stale_states(self) -> None:
        self.assertNotEqual(render(None).tobytes(), render(None, hub_online=False).tobytes())
        self.assertNotEqual(
            render(node(), (1, 1)).tobytes(),
            render(node(), (1, 1), hub_online=False).tobytes(),
        )

    def test_renderer_handles_offline_nulls_long_name_and_multiple_gpus(self) -> None:
        value = node(
            online=False,
            gpu=[
                {"usage_percent": 81, "temperature_c": 71, "power_w": 112},
                {"usage_percent": 20, "temperature_c": None, "power_w": None},
            ],
        )
        image = render(value, (2, 2))
        self.assertEqual("RGB", image.mode)

    def test_renderer_handles_device_power(self) -> None:
        self.assertEqual((320, 240), render(node(device={"power_w": 6.2})).size)

    def test_renderer_has_visible_footer_feedback_and_percentage_bar(self) -> None:
        image = render(node(), pressed_action="previous")
        self.assertEqual(ImageColor.getrgb(MUTED), image.getpixel((0, FOOTER_TOP)))
        self.assertEqual(ImageColor.getrgb(GREEN), image.getpixel((76, 86)))
        self.assertNotEqual(image.tobytes(), render(node()).tobytes())

    def test_status_priority_and_freshness(self) -> None:
        degraded = node(collector={"version": "0.1.0", "errors": ["a", "b"]})
        self.assertEqual("LINK LOST", _status(degraded, False)[0])
        self.assertEqual("WAITING", _status(node(online=False, waiting=True), True)[0])
        self.assertEqual("OFFLINE", _status(node(online=False), True)[0])
        self.assertEqual("DEGRADED ERR 2", _status(degraded, True)[0])
        self.assertEqual("ONLINE", _status(node(), True)[0])
        now = datetime(2026, 7, 12, 3, 3, tzinfo=timezone.utc)
        self.assertEqual("3m", _age("2026-07-12T03:00:00Z", now))

    def test_navigation_wraps_and_empty_state_is_safe(self) -> None:
        self.assertEqual(0, move(3, 4, 1))
        self.assertEqual(3, move(0, 4, -1))
        self.assertEqual(0, move(0, 0, 1))
        self.assertEqual(
            ("previous", "center", "next"),
            (touch_action(0, 239), touch_action(160, 239), touch_action(319, 239)),
        )
        self.assertEqual(
            ("previous", None, None, "next"),
            (
                touch_action(NAV_WIDTH - 4, FOOTER_TOP),
                touch_action(NAV_WIDTH, FOOTER_TOP),
                touch_action(319 - NAV_WIDTH, FOOTER_TOP),
                touch_action(320 - NAV_WIDTH + 3, FOOTER_TOP),
            ),
        )
        self.assertIsNone(touch_action(0, FOOTER_TOP - 1))
        self.assertIsNone(touch_action(160, 110))

    def test_selection_tracks_node_id_across_reordering(self) -> None:
        nodes = [node(node_id="a"), node(node_id="b"), node(node_id="c")]
        self.assertEqual(1, selected_index(nodes, "b"))
        self.assertEqual(2, selected_index(list(reversed(nodes)), "a"))
        self.assertEqual(1, selected_index(nodes[:2], "missing", 1))

    def test_one_hundred_navigation_steps_are_deterministic(self) -> None:
        index = 0
        for _ in range(100):
            index = move(index, 4, 1)
        self.assertEqual(0, index)

    def test_short_gesture_only_emits_after_release(self) -> None:
        recognizer = TouchRecognizer()
        self.assertIsNone(recognizer.update(True, 100, 210, 1.0))
        self.assertIsNone(recognizer.update(True, 102, 211, 1.2))
        gesture = recognizer.update(False, now=1.3)
        self.assertEqual(GestureKind.SHORT, gesture.kind)
        self.assertEqual((101, 210), (gesture.x, gesture.y))

    def test_long_gesture_emits_once_with_resistive_jitter(self) -> None:
        recognizer = TouchRecognizer()
        recognizer.update(True, 100, 210, 1.0)
        for now, point in ((1.2, (108, 214)), (1.4, (92, 205)), (1.66, (105, 212))):
            gesture = recognizer.update(True, *point, now)
        self.assertEqual(GestureKind.LONG, gesture.kind)
        self.assertIsNone(recognizer.update(True, 103, 208, 2.0))
        self.assertIsNone(recognizer.update(False, now=2.1))

    def test_large_touch_movement_cancels_the_gesture(self) -> None:
        recognizer = TouchRecognizer()
        recognizer.update(True, 100, 210, 1.0)
        self.assertIsNone(recognizer.update(True, 130, 210, 1.2))
        self.assertIsNone(recognizer.update(True, 132, 211, 1.25))
        self.assertIsNone(recognizer.update(False, now=1.3))

    def test_category_registry_and_fixed_menu_geometry(self) -> None:
        value = node()
        self.assertEqual("cpu", category_at(10, 40).id)
        self.assertEqual("network", category_at(160, 120).id)
        self.assertTrue(category("cpu").available(value))
        self.assertFalse(category("storage").available(value))
        capability = {"supported": True, "source": "statvfs", "reason": None}
        self.assertTrue(category("storage").available(node(capabilities={"storage.usage_percent": capability})))
        unsupported = {"supported": False, "source": None, "reason": "sensor_not_found"}
        self.assertFalse(category("gpu").available(node(gpu=[{}], capabilities={"gpu.usage_percent": unsupported})))
        self.assertEqual(100.0, category("cpu").chart_metrics[0].scale.maximum)
        self.assertEqual("temperature", metric_at("cpu", 150, 50).id)
        self.assertEqual("values", detail_view_at(80, 68))
        self.assertEqual("graph", detail_view_at(240, 68))

    def test_ui_state_keeps_available_category_across_nodes(self) -> None:
        state = UiState()
        first = node(node_id="a", gpu=[{"usage_percent": 20}])
        second = node(node_id="b")
        state.selected_category_id = "health"
        self.assertEqual("health", state.category_id(first))
        self.assertEqual("health", state.category_id(second))

    def test_future_screens_reject_real_nodes_but_keep_empty_state_safe(self) -> None:
        for screen in (
            Screen.NODES,
            Screen.SYSTEM,
            Screen.POWER_CONFIRM,
            Screen.POWER_PENDING,
            Screen.POWER_ERROR,
        ):
            with self.subTest(screen=screen):
                with self.assertRaises(ValueError):
                    render(node(), ui_state=UiState(screen=screen))
                self.assertEqual((320, 240), render(None, ui_state=UiState(screen=screen)).size)

    def test_renderer_does_not_mutate_ui_state(self) -> None:
        state = UiState(
            screen=Screen.VALUES,
            selected_category_id="missing",
            metric_by_category={"cpu": "missing"},
        )
        before = copy.deepcopy(state)
        render(node(), ui_state=state)
        self.assertEqual(before, state)

    def test_history_deduplicates_timestamps_and_keeps_null_gaps(self) -> None:
        history = HistoryStore(window_seconds=300, max_samples=3)
        first = node(timestamp_utc="2026-07-12T03:00:00Z")
        self.assertTrue(history.add(first))
        self.assertFalse(history.add(first))
        offline = node(
            timestamp_utc="2026-07-12T03:00:02Z",
            online=False,
        )
        self.assertTrue(history.add(offline))
        samples = history.series("desktop", "cpu", "load")
        self.assertEqual((47.0, None), tuple(sample.value for sample in samples))
        self.assertFalse(history.add(node(timestamp_utc="2026-07-12T03:00:04Z"), False))

        short_window = HistoryStore(window_seconds=3, max_samples=10)
        for second in (0, 2, 4):
            short_window.add(node(timestamp_utc=f"2026-07-12T03:00:0{second}Z"))
        self.assertEqual(
            2,
            len(short_window.series("desktop", "cpu", "load")),
        )

    def test_detail_graph_renders_history_without_treating_null_as_zero(self) -> None:
        history = HistoryStore()
        value = node(timestamp_utc="2026-07-12T03:00:00Z")
        history.add(value)
        history.add(node(timestamp_utc="2026-07-12T03:00:02Z", online=False))
        state = UiState(screen=Screen.GRAPH)
        graph = render(
            value,
            ui_state=state,
            history=history,
            now=datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc),
        )
        state.screen = Screen.VALUES
        values = render(value, ui_state=state, history=history)
        self.assertEqual((320, 240), graph.size)
        self.assertNotEqual(graph.tobytes(), values.tobytes())

    def test_values_rendering_does_not_depend_on_selected_metric(self) -> None:
        value = complete_v2_node()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        values_frames = [
            render(
                value,
                ui_state=UiState(
                    screen=Screen.VALUES,
                    metric_by_category={"cpu": metric_id},
                ),
                now=now,
            )
            for metric_id in ("load", "temperature", "power")
        ]
        self.assertEqual(1, len({frame.tobytes() for frame in values_frames}))

        history = HistoryStore()
        history.add(complete_v2_node(timestamp_utc="2026-07-12T03:00:00Z"))
        graph_frames = {
            render(
                value,
                ui_state=UiState(
                    screen=Screen.GRAPH,
                    metric_by_category={"cpu": metric_id},
                ),
                history=history,
                now=now,
            ).tobytes()
            for metric_id in ("load", "temperature")
        }
        self.assertEqual(2, len(graph_frames))

    def test_values_to_graph_preserves_metric_end_to_end(self) -> None:
        value = complete_v2_node()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        context = UiContext((value,), 30, 45, 15, 10)
        values_state = UiState(
            screen=Screen.VALUES,
            selected_node_id=value["node_id"],
            metric_by_category={"cpu": "temperature"},
        )
        text_calls = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            text_calls.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            render(value, ui_state=values_state, now=now)
        self.assertIn("OPEN GRAPH", {text for _, text, _ in text_calls})
        self.assertTrue({"LOAD", "TEMP", "POWER", "CLOCK"}.issubset(
            {text for _, text, _ in text_calls}
        ))
        self.assertFalse(any(xy[1] == 43 for xy, _, _ in text_calls))
        self.assertFalse(any(xy[1] == 68 and text in {"VALUES", "GRAPH"} for xy, text, _ in text_calls))

        after_selector = reduce_ui(values_state, ShortPress(150, 40, 1), context)
        self.assertEqual("temperature", after_selector.state.metric_by_category["cpu"])
        self.assertEqual(Screen.VALUES, after_selector.state.screen)
        after_old_tab = reduce_ui(after_selector.state, ShortPress(240, 68, 2), context)
        self.assertEqual(Screen.VALUES, after_old_tab.state.screen)
        graph = reduce_ui(after_old_tab.state, ShortPress(160, 166, 3), context)
        self.assertEqual(Screen.GRAPH, graph.state.screen)
        self.assertEqual("temperature", graph.state.metric_by_category["cpu"])
        self.assertEqual("open_graph", graph.completed_action)
        with patch("display.renderer._chart", wraps=_chart) as chart:
            render(value, ui_state=graph.state, now=now)
        self.assertEqual("temperature", chart.call_args.args[3].id)

    def test_values_renderer_geometry_and_graph_controls_are_separated(self) -> None:
        value = complete_v2_node()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        expected_positions = {
            "cpu": (48, 74, 100, 126),
            "memory": (48, 74, 100, 126),
            "gpu": (42, 63, 84, 105, 126),
            "storage": (42, 63, 84, 105, 126),
            "network": (48, 74, 100, 126),
            "health": (80, 103, 126, 149, 172),
        }
        original_text = ImageDraw.ImageDraw.text
        original_line = ImageDraw.ImageDraw.line
        original_rectangle = ImageDraw.ImageDraw.rectangle

        for category_id, positions in expected_positions.items():
            text_calls = []
            line_calls = []
            rectangle_calls = []

            def record_text(draw, xy, text, *args, **kwargs):
                text_calls.append((xy, text, kwargs))
                return original_text(draw, xy, text, *args, **kwargs)

            def record_line(draw, xy, *args, **kwargs):
                line_calls.append((xy, kwargs))
                return original_line(draw, xy, *args, **kwargs)

            def record_rectangle(draw, xy, *args, **kwargs):
                rectangle_calls.append((xy, kwargs))
                return original_rectangle(draw, xy, *args, **kwargs)

            with self.subTest(category=category_id), \
                    patch.object(ImageDraw.ImageDraw, "text", new=record_text), \
                    patch.object(ImageDraw.ImageDraw, "line", new=record_line), \
                    patch.object(ImageDraw.ImageDraw, "rectangle", new=record_rectangle):
                state = UiState(screen=Screen.VALUES, selected_category_id=category_id)
                render(value, (1, 1), True, state, now=now)

            row_titles = {row.title for row in category(category_id).value_rows}
            row_calls = [
                (xy, text)
                for xy, text, _ in text_calls
                if xy[0] == 10 and text in row_titles
            ]
            self.assertEqual(positions, tuple(xy[1] for xy, _ in row_calls))
            self.assertFalse(any(xy[1] == 43 for xy, _, _ in text_calls))
            self.assertFalse(any(
                xy[1] == 68 and text in {"VALUES", "GRAPH"}
                for xy, text, _ in text_calls
            ))
            self.assertFalse(any(
                isinstance(xy, tuple) and len(xy) == 4 and xy[1] == xy[3] and xy[1] in {54, 78}
                for xy, _ in line_calls
            ))
            action_rectangles = [
                kwargs for xy, kwargs in rectangle_calls if xy == VALUES_GRAPH_BUTTON_RECT
            ]
            action_labels = [
                (xy, kwargs) for xy, text, kwargs in text_calls if text == "OPEN GRAPH"
            ]
            if category_id == "health":
                self.assertEqual([], action_rectangles)
                self.assertEqual([], action_labels)
            else:
                self.assertEqual(
                    [{"fill": None, "outline": GREEN, "width": 1}],
                    action_rectangles,
                )
                self.assertEqual(1, len(action_labels))
                self.assertEqual((160, 166), action_labels[0][0])
                self.assertEqual(GREEN, action_labels[0][1]["fill"])
                self.assertEqual("mm", action_labels[0][1]["anchor"])
                self.assertEqual(15, action_labels[0][1]["font"].size)

        graph_text_calls = []
        graph_line_calls = []

        def record_graph_text(draw, xy, text, *args, **kwargs):
            graph_text_calls.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        def record_graph_line(draw, xy, *args, **kwargs):
            graph_line_calls.append((xy, kwargs))
            return original_line(draw, xy, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_graph_text), \
                patch.object(ImageDraw.ImageDraw, "line", new=record_graph_line):
            render(value, ui_state=UiState(screen=Screen.GRAPH), now=now)
        self.assertEqual(
            {metric.title for metric in category("cpu").chart_metrics},
            {text for xy, text, _ in graph_text_calls if xy[1] == 43},
        )
        self.assertEqual(
            {"VALUES", "GRAPH"},
            {text for xy, text, _ in graph_text_calls if xy[1] == 68},
        )
        self.assertTrue(any(xy[1] == xy[3] == 54 for xy, _ in graph_line_calls if len(xy) == 4))
        self.assertTrue(any(xy[1] == xy[3] == 78 for xy, _ in graph_line_calls if len(xy) == 4))

    def test_open_graph_pressed_feedback_is_exact_and_localized(self) -> None:
        value = complete_v2_node()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        state = UiState(screen=Screen.VALUES)
        normal = render(value, ui_state=state, now=now)
        pressed = render(value, ui_state=state, pressed_action="open_graph", now=now)
        self.assertNotEqual(normal.tobytes(), pressed.tobytes())
        left, top, right, bottom = ImageChops.difference(normal, pressed).getbbox()
        self.assertGreaterEqual(left, VALUES_GRAPH_BUTTON_RECT[0])
        self.assertGreaterEqual(top, VALUES_GRAPH_BUTTON_RECT[1])
        self.assertLessEqual(right, VALUES_GRAPH_BUTTON_RECT[2] + 1)
        self.assertLessEqual(bottom, VALUES_GRAPH_BUTTON_RECT[3] + 1)

        rectangle_calls = []
        text_calls = []
        original_rectangle = ImageDraw.ImageDraw.rectangle
        original_text = ImageDraw.ImageDraw.text

        def record_rectangle(draw, xy, *args, **kwargs):
            rectangle_calls.append((xy, kwargs))
            return original_rectangle(draw, xy, *args, **kwargs)

        def record_text(draw, xy, text, *args, **kwargs):
            text_calls.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "rectangle", new=record_rectangle), \
                patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            render(value, ui_state=state, pressed_action="open_graph", now=now)
        self.assertIn(
            (VALUES_GRAPH_BUTTON_RECT, {"fill": MUTED, "outline": None, "width": 1}),
            rectangle_calls,
        )
        action_label = next(call for call in text_calls if call[1] == "OPEN GRAPH")
        self.assertEqual((160, 166), action_label[0])
        self.assertEqual(BACKGROUND, action_label[2]["fill"])
        self.assertEqual("mm", action_label[2]["anchor"])
        self.assertEqual(15, action_label[2]["font"].size)

    def test_application_uses_shared_visible_action_resolver(self) -> None:
        source = (Path(__file__).parents[1] / "display" / "app.py").read_text(encoding="utf-8")
        self.assertIn("visible_action_at", source)
        self.assertNotIn("pressed_action = touch_action", source)
        for duplicated_authority in (
            "VALUES_GRAPH_HITBOX",
            "VALUES_GRAPH_BUTTON_RECT",
            "values_action_at",
            "can_open_graph",
        ):
            self.assertNotIn(duplicated_authority, source)

    def test_graph_uses_history_window_seconds_for_chart_bounds(self) -> None:
        history = HistoryStore(window_seconds=42)
        history.add(complete_v2_node(timestamp_utc="2026-07-12T03:00:00Z"))
        history.add(complete_v2_node(timestamp_utc="2026-07-12T03:00:42Z"))
        points = []
        original_line = ImageDraw.ImageDraw.line

        def record_line(draw, xy, *args, **kwargs):
            if isinstance(xy, list) and kwargs.get("fill") == GREEN and kwargs.get("width") == 2:
                points.extend(xy)
            return original_line(draw, xy, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "line", new=record_line):
            render(
                complete_v2_node(timestamp_utc="2026-07-12T03:00:42Z"),
                ui_state=UiState(screen=Screen.GRAPH),
                history=history,
                now=datetime(2026, 7, 12, 3, 0, 42, tzinfo=timezone.utc),
            )
        self.assertEqual([28, 310], [points[0][0], points[-1][0]])
        self.assertTrue(all(28 <= x <= 310 and 82 <= y <= 160 for x, y in points))

    def test_v2_values_and_history_use_extended_metrics(self) -> None:
        value = node(
            cpu={"usage_percent": 47, "temperature_c": 63, "power_w": 55, "clock_mhz": 4725},
            memory={
                "usage_percent": 63,
                "used_bytes": 24 * 1024**3,
                "total_bytes": 32 * 1024**3,
                "swap_used_bytes": 2 * 1024**3,
                "swap_total_bytes": 8 * 1024**3,
                "swap_usage_percent": 25,
                "pressure_some_percent": 1.25,
            },
            gpu=[{
                "id": "0", "name": "RTX", "usage_percent": 81, "temperature_c": 69,
                "power_w": 117, "memory_used_bytes": 6 * 1024**3,
                "memory_total_bytes": 12 * 1024**3, "memory_usage_percent": 50,
                "fan_percent": 74, "clock_mhz": 2625,
            }],
            health={"uptime_seconds": 90000, "undervoltage": False, "throttled": False},
            storage={
                "name": "/", "usage_percent": 60, "used_bytes": 60 * 1024**3,
                "total_bytes": 100 * 1024**3, "read_bytes_per_second": 1250000,
                "write_bytes_per_second": 640000, "temperature_c": 42,
            },
            network={
                "interface": "eth0", "link_up": True,
                "down_bytes_per_second": 12500000, "up_bytes_per_second": 2500000,
            },
        )
        history = HistoryStore()
        history.add(value)
        self.assertEqual(4725, history.series("desktop", "cpu", "clock")[0].value)
        self.assertEqual(25, history.series("desktop", "memory", "swap")[0].value)
        self.assertEqual(50, history.series("desktop", "gpu", "vram")[0].value)
        self.assertEqual(60, history.series("desktop", "storage", "used")[0].value)
        self.assertEqual(12500000, history.series("desktop", "network", "down")[0].value)

        state = UiState(screen=Screen.VALUES)
        cpu = render(value, ui_state=state, history=history)
        state.selected_category_id = "memory"
        memory = render(value, ui_state=state, history=history)
        state.selected_category_id = "gpu"
        gpu = render(value, ui_state=state, history=history)
        state.selected_category_id = "health"
        health = render(value, ui_state=state, history=history)
        state.selected_category_id = "storage"
        storage = render(value, ui_state=state, history=history)
        state.selected_category_id = "network"
        network = render(value, ui_state=state, history=history)
        frames = (cpu, memory, gpu, health, storage, network)
        self.assertEqual({(320, 240)}, {frame.size for frame in frames})
        self.assertEqual(6, len({frame.tobytes() for frame in frames}))
        self.assertEqual("4.72G", _format_clock(4725))
        self.assertEqual("24.0/32.0GiB", _format_bytes_pair(24 * 1024**3, 32 * 1024**3))
        self.assertEqual("1d01h", _format_uptime(90000))
        self.assertEqual("11.9M/s", _format_rate(12500000))

    def test_history_contains_chart_metrics_only_and_keeps_existing_semantics(self) -> None:
        value = complete_v2_node()
        value["gpu"].append({
            "id": "1",
            "name": "SECOND",
            "usage_percent": 9,
            "temperature_c": 30,
            "power_w": 10,
            "memory_usage_percent": 20,
        })
        history = HistoryStore()
        self.assertTrue(history.add(value))
        for item in CATEGORIES:
            for metric in item.chart_metrics:
                with self.subTest(category=item.id, metric=metric.id):
                    self.assertEqual(1, len(history.series("desktop", item.id, metric.id)))
        self.assertEqual(55, history.series("desktop", "cpu", "power")[0].value)
        self.assertEqual(63, history.series("desktop", "memory", "ram")[0].value)
        self.assertEqual(25, history.series("desktop", "memory", "swap")[0].value)
        self.assertEqual(1.25, history.series("desktop", "memory", "psi")[0].value)
        self.assertEqual(81, history.series("desktop", "gpu", "load")[0].value)
        self.assertEqual((), history.series("desktop", "memory", "ram_load"))
        self.assertEqual((), history.series("desktop", "gpu", "gpu_name"))
        self.assertEqual((), history.series("desktop", "storage", "capacity"))

        offline = complete_v2_node(
            timestamp_utc="2026-07-12T03:00:02Z",
            online=False,
        )
        self.assertTrue(history.add(offline))
        for item in CATEGORIES:
            for metric in item.chart_metrics:
                self.assertIsNone(history.series("desktop", item.id, metric.id)[-1].value)

    def test_calibration_maps_and_clamps_coordinates(self) -> None:
        calibration = {
            "swap_xy": False,
            "invert_x": True,
            "invert_y": False,
            "raw_x_min": 100,
            "raw_x_max": 3900,
            "raw_y_min": 200,
            "raw_y_max": 3800,
        }
        self.assertEqual((319, 0), map_touch(100, 200, calibration))
        self.assertEqual((0, 239), map_touch(5000, 5000, calibration))

    def test_calibration_detects_axis_direction(self) -> None:
        calibration = calculate(
            {
                "left": (3500, 2000),
                "right": (500, 2000),
                "top": (2000, 400),
                "bottom": (2000, 3600),
            }
        )
        self.assertTrue(calibration["invert_x"])
        self.assertFalse(calibration["invert_y"])
        self.assertEqual((20, 120), map_touch(3500, 2000, calibration))

    def test_rgb565_conversion(self) -> None:
        image = Image.new("RGB", (3, 1))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        self.assertEqual(bytes.fromhex("f80007e0001f"), rgb565(image))

    def test_partial_transfer_sets_the_requested_window(self) -> None:
        lcd = object.__new__(ILI9341)
        calls = []
        lcd._write = lambda command, data=b"": calls.append((command, bytes(data)))
        lcd._command = lambda command: calls.append((command, b""))
        lcd._data = lambda data: calls.append((-1, bytes(data)))
        lcd.show_region(Image.new("RGB", (320, 240)), (10, 20, 12, 22))
        self.assertEqual((0x2A, bytes.fromhex("000a000b")), calls[0])
        self.assertEqual((0x2B, bytes.fromhex("00140015")), calls[1])
        self.assertEqual(8, len(calls[-1][1]))
        self.assertGreaterEqual(lcd.last_timing_ms[0], 0)


if __name__ == "__main__":
    unittest.main()
