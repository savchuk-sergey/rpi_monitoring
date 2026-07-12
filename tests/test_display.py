import unittest

from PIL import Image

from display.drivers.ili9341 import rgb565
from display.navigation import NAV_WIDTH, TouchDebouncer, map_touch, move, touch_action
from display.renderer import FONT_PATH, _number, _value, render
from tools.touch_calibrate import calculate


def node(**changes):
    value = {
        "node_id": "desktop",
        "display_name": "A very long desktop display name that must fit safely",
        "online": True,
        "cpu": {"usage_percent": 47, "temperature_c": 63, "power_w": None},
        "memory": {"usage_percent": 63},
        "gpu": [],
    }
    value.update(changes)
    return value


class DisplayTests(unittest.TestCase):
    def test_matrix_font_is_bundled(self) -> None:
        self.assertTrue(FONT_PATH.is_file())

    def test_measurements_have_fixed_two_decimal_format(self) -> None:
        self.assertEqual("00.70", _number(0.7))
        self.assertEqual("05.00", _number(5))
        self.assertEqual("100.00 %", _value(100, "%"))
        self.assertEqual("N/A", _value(None, "W"))

    def test_renderer_is_320_by_240_for_waiting_and_node_states(self) -> None:
        self.assertEqual((320, 240), render(None).size)
        self.assertEqual((320, 240), render(node(), (1, 4)).size)

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

    def test_navigation_wraps_and_empty_state_is_safe(self) -> None:
        self.assertEqual(0, move(3, 4, 1))
        self.assertEqual(3, move(0, 4, -1))
        self.assertEqual(0, move(0, 0, 1))
        self.assertEqual((-1, 0, 1), (touch_action(0), touch_action(160), touch_action(319)))
        self.assertEqual(
            (-1, 0, 0, 1),
            (
                touch_action(NAV_WIDTH - 1),
                touch_action(NAV_WIDTH),
                touch_action(319 - NAV_WIDTH),
                touch_action(320 - NAV_WIDTH),
            ),
        )

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


if __name__ == "__main__":
    unittest.main()
