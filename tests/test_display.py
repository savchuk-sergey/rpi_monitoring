import unittest
from datetime import datetime, timezone

from PIL import Image, ImageColor

from display.drivers.ili9341 import ILI9341, rgb565
from display.navigation import (
    FOOTER_TOP,
    MODE_HITBOX,
    NAV_WIDTH,
    NEXT_HITBOX,
    PREVIOUS_HITBOX,
    TouchDebouncer,
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
    _format_power,
    _format_temperature,
    _number,
    _status,
    _value,
    render,
)
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
        self.assertEqual((320, 240), render(node(), mode="details").size)

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
            ("previous", "mode", "next"),
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
        self.assertEqual("gpu", touch_action(160, 110, details=True))

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

    def test_debounce_requires_release_and_time(self) -> None:
        debounce = TouchDebouncer(0.25)
        self.assertTrue(debounce.update(True, 1.0))
        self.assertFalse(debounce.update(True, 2.0))
        self.assertFalse(debounce.update(False, 2.1))
        self.assertFalse(debounce.update(True, 1.1))
        debounce.update(False, 2.2)
        self.assertTrue(debounce.update(True, 2.3))

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
