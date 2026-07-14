import copy
import hashlib
import unittest
from datetime import datetime, timezone

from PIL import Image, ImageColor

from display.drivers.ili9341 import ILI9341, rgb565
from display.categories import category, category_at, detail_view_at, metric_at
from display.gestures import GestureKind, TouchRecognizer
from display.history import HistoryStore
from display.navigation import (
    FOOTER_TOP,
    MODE_HITBOX,
    NAV_WIDTH,
    NEXT_HITBOX,
    PREVIOUS_HITBOX,
    map_touch,
    move,
    selected_index,
    touch_action,
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
from display.ui_state import Screen, UiState
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


RENDER_HASHES = {
    "graph": "66b0364742250623eb4d2522b1ac07a168c503658b16c1f00c84e92b565311ff",
    "graph_with_history": "b497c0beaddc5a3b04d785699cce705e5d7ea89862109cc5d7085eda29d48b8b",
    "main_menu_capabilities": "21b52b19516410dfed6b3946cbf9cc518fcf17d09c454d7728bcf237ea3db399",
    "main_menu_legacy": "a73cbc7872ebc0b018673c4409c0b0d5d2281cb7c16fc684c1f637246d9bd19b",
    "overview_legacy": "7a64eb574d9d969407dec89fbf7ab8493a748dadec645124825d6e9cef15c9d4",
    "overview_waiting": "7064e7983ea4571ed55586a2d656d493bbce9032bb44374853015a5d7faac6d4",
    "values": "fd5a1de62d72977ab5a49e5ea83584b9a535033d80f07ac30f441e9d100ba928",
}


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

    def test_release_0_03_render_hashes_are_unchanged(self) -> None:
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
            "values": (node(), UiState(screen=Screen.VALUES), None),
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
                self.assertEqual(RENDER_HASHES[name], digest)

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
        self.assertEqual(100.0, category("cpu").metrics[0].maximum)
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
