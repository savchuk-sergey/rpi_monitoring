import copy
import hashlib
import asyncio
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont

from display.drivers.ili9341 import ILI9341, rgb565
from display.app import run as run_display
from display.power_client import PowerClientResult
from display.categories import CATEGORIES, category, category_at, detail_view_at, metric_at
from display.gestures import GestureKind, GestureState, TouchRecognizer
from display.history import HistoryStore
from display.navigation import (
    FOOTER_TOP,
    GRAPH_NEXT_METRIC_HITBOX,
    GRAPH_PREVIOUS_METRIC_HITBOX,
    GRAPH_VALUES_HITBOX,
    MENU_BACK_HITBOX,
    MENU_NEXT_PAGE_HITBOX,
    MENU_PAGE_COUNT,
    MENU_PAGES,
    MENU_PREVIOUS_PAGE_HITBOX,
    MENU_TILE_RECTS,
    MODE_HITBOX,
    NAV_WIDTH,
    NEXT_HITBOX,
    NODES_BACK_HITBOX,
    NODES_NEXT_PAGE_HITBOX,
    NODES_PAGE_SIZE,
    NODES_PREVIOUS_PAGE_HITBOX,
    NODES_ROW_RECTS,
    POWER_CANCEL_CARD_RECT,
    POWER_CANCEL_HITBOX,
    POWER_HOLD_CARD_RECT,
    POWER_HOLD_HITBOX,
    POWER_HOLD_PROGRESS_RECT,
    POWER_ERROR_BACK_HITBOX,
    PREVIOUS_HITBOX,
    SYSTEM_BACK_HITBOX,
    SYSTEM_RESTART_AREA,
    SYSTEM_RESTART_CARD_RECT,
    SYSTEM_SHUTDOWN_AREA,
    SYSTEM_SHUTDOWN_CARD_RECT,
    VALUES_GRAPH_BUTTON_RECT,
    VALUES_GRAPH_HITBOX,
    graph_action_at,
    map_touch,
    menu_action_at,
    menu_page_for_category,
    menu_tile_id_at,
    move,
    nodes_action_at,
    nodes_page_count,
    nodes_page_items,
    normalize_menu_page,
    normalize_nodes_page,
    ordered_nodes,
    power_confirm_action_at,
    power_error_action_at,
    selected_index,
    system_action_at,
    touch_action,
    values_action_at,
)
from display.renderer import (
    FONT_PATH,
    AMBER,
    BACKGROUND,
    BRIGHT,
    GREEN,
    GRAPH_GRID_RECT,
    GRAPH_HEADER_BOTTOM,
    GRAPH_IDENTITY_POSITION,
    GRAPH_IDENTITY_WIDTH,
    GRAPH_META_POSITION,
    GRAPH_PLOT_RECT,
    GRAPH_STATUS_DOT,
    GRAPH_SUMMARY_Y,
    GRAPH_TITLE_POSITION,
    GRAPH_TITLE_WIDTH,
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
    _fit,
    _graph_footer,
    _nodes_footer,
    _number,
    _status,
    _value,
    render,
)
from display.ui_state import (
    DataRefreshed,
    PowerAction,
    PowerHoldStarted,
    PowerHoldTick,
    PowerRequestAccepted,
    PowerRequestError,
    PowerRequestFailed,
    PowerRequestStatus,
    ShortPress,
    Screen,
    UiContext,
    UiEffect,
    UiState,
    UiTransition,
    reduce_ui,
    visible_action_at,
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
    "overview_legacy": "7a64eb574d9d969407dec89fbf7ab8493a748dadec645124825d6e9cef15c9d4",
    "overview_waiting": "7064e7983ea4571ed55586a2d656d493bbce9032bb44374853015a5d7faac6d4",
}

OLD_MAIN_MENU_HASHES = {
    "main_menu_capabilities": "21b52b19516410dfed6b3946cbf9cc518fcf17d09c454d7728bcf237ea3db399",
    "main_menu_legacy": "a73cbc7872ebc0b018673c4409c0b0d5d2281cb7c16fc684c1f637246d9bd19b",
}

MENU_RENDER_HASHES = {
    "menu_page_1_back_pressed": "0945b1e836db6de7b483a18aac86ad093f10b034b7245ad2941f127e497b354e",
    "menu_page_1_capabilities": "779e77fb5582e89c474aa6fac739edab98f4006014fea2637cd5b657f4469883",
    "menu_page_1_cpu_pressed": "d6e2fc5e6dce08dc95d6936bb54a815de21942bc04d8b300d83bc42d63c3472b",
    "menu_page_1_gpu_pressed": "9ba441a2937ad58db5d7b82d8d968ae73bca17cbe139e83a23a4b1b73841c566",
    "menu_page_1_legacy": "779e77fb5582e89c474aa6fac739edab98f4006014fea2637cd5b657f4469883",
    "menu_page_1_memory_pressed": "17df54110f05a439769c6eafebd6b80769d9fd85930097e2f8927c7f6da28bd7",
    "menu_page_1_next_pressed": "8cf98b2076b6e0a5136c2dd169bb064217102a7e5f23fd744db020e3e7ff1475",
    "menu_page_1_nodes_pressed": "d4e2b8c0dcf33974026841a75cd9c941980874bc7eaab8c3450e0b5219db2d1d",
    "menu_page_1_previous_pressed": "4a8a962442e625b33d1988b7f8733e37ef120769319b25a8ed524e9656bca3bc",
    "menu_page_2_back_pressed": "aff2a6e5648b77b8517feb9048b7e2c2414dc7c195ab2df36dcd2669565c11c5",
    "menu_page_2_capabilities": "f236468dee1b9b4f246927bcda78a69559f6de05303fe7a94a1e0e1a96268319",
    "menu_page_2_health_errors": "122e8c9c6e1e85c01ae869177cdaac17a7c86728801853ba26738231a29489c5",
    "menu_page_2_health_pressed": "8fed416290e6956589b21287751a715ee531ef3669618f9f35590eb1fe8df3ad",
    "menu_page_2_legacy": "e78e8a85a26e5bda63e452a20227006289d64746dacb218b8323f82c417356d4",
    "menu_page_2_network_pressed": "6fbd87c87d684b4dd8e3cb8bbbff656a11ad9dfe317ef3f32fc728fec54d1ce7",
    "menu_page_2_next_pressed": "f2d0b041212ccadc5bb8f645783989b5921f66621beef33b9fcd6a968dcfbb55",
    "menu_page_2_previous_pressed": "a0513acfdddc0c0dd24f7efce2271f4ea5b1484aabeb6b10de695373515a913a",
    "menu_page_2_storage_pressed": "834dfa1dc4913f5384f9ba51ca9884f6cea88c02d9865727bb0b7df1be7ee447",
    "menu_page_2_system_pressed": "283d45a6e38552e4bed267911d6521df792d6ee4bbe008fe59e7d3e257dc234e",
}

SYSTEM_RENDER_HASHES = {
    "system_default": "59d803c84f6bdd4abbc4ae7cce4bc49ca87d5413ee5a0a90bbbcafb7c63b0bd3",
    "system_restart_pressed": "f618aaaafe2ae84c0ac2db59fadc9a629edc435d258ab71dfb512eded4417b44",
    "system_shutdown_pressed": "c872a329f551315ffd5bfc7dd146ef3f05f2ddf6a887900253c4217730dca8c7",
    "system_back_pressed": "6e80ecb7e0ab65d3a81efc7e9527ee793b22a84401e32d410e056bdf34b357e4",
    "system_no_nodes": "59d803c84f6bdd4abbc4ae7cce4bc49ca87d5413ee5a0a90bbbcafb7c63b0bd3",
    "system_hub_offline": "59d803c84f6bdd4abbc4ae7cce4bc49ca87d5413ee5a0a90bbbcafb7c63b0bd3",
}

CONFIRMATION_RENDER_HASHES = {
    "confirm_reboot_idle": "7f006d448a1d4bfc266a6a892c69e543e303f68f87d314de3795b44eaeff1edf",
    "confirm_shutdown_idle": "6d4dddc8f28c9fa173eae95b03863991120b48e7bf4574f69a8edacdc16fb9f0",
    "confirm_reboot_cancel_pressed": "3eff824a95b2cb9f87ae73ed2be3023718e82c5a8352938e2e4a00eb90ec10bb",
    "confirm_shutdown_cancel_pressed": "91d3b6fe928609e7341cd5a2f9bb825c51f8eca71b992c49a9b4fcaebc0d7d23",
    "confirm_reboot_hold_started": "dfc1f9115986fbc9f100511a908a5168194573709584c01ac86c707233a5a415",
    "confirm_shutdown_hold_started": "901cec5879443385e48e8c45eab41bfb074529ca48bf7642880a5e04099356a9",
    "confirm_reboot_progress_25": "710a9b98ed117d6e6efa74a949f5e5081f8df826b1e087051cfddcefc0f1fe19",
    "confirm_reboot_progress_50": "7348ea5b582f607e6a05df92c361feb58c0262222509b3dfc936cf849cd60b8a",
    "confirm_reboot_progress_75": "66bea1a49adcdab3ff9118bd20f31560f108adf5064a913f0a690697f9266363",
    "confirm_reboot_progress_99": "0d8b70310660605b15f04fb756c275bf0f3aa31bfa1b2a41b7b7f74751b8473e",
    "confirm_missing_action": "07e7ab90a853027c450f3d909c920f425d93f0f445c8a311900b9539ed7557d5",
    "confirm_no_nodes": "7f006d448a1d4bfc266a6a892c69e543e303f68f87d314de3795b44eaeff1edf",
    "confirm_hub_offline": "7f006d448a1d4bfc266a6a892c69e543e303f68f87d314de3795b44eaeff1edf",
}

PENDING_RENDER_HASHES = {
    "pending_reboot_sending": "51a2647f61590e59adc403fbd6aeb7498c686f0de1f695defaf69ea9ac8ceb86",
    "pending_shutdown_sending": "9fd965f0d0b402618a6429ec391b98c5c1c9ebdb57db3899de41996e093cbbc2",
    "pending_reboot_accepted": "2da17703e345d4a06f03516c8810623d369e332b1723d37581382c56acc86536",
    "pending_shutdown_accepted": "52b840fb45a68ed63ae6b3ccbf312348d602d4b1a1481ff7fab5584aa2f0fbb7",
    "pending_missing_status": "062bf4c45e5f04880e23b9fcb8981f43de250e8214ac300152f5bbb17aa23a50",
}

POWER_ERROR_RENDER_HASHES = {
    "error_reboot_helper_unavailable": "58bf1211f829d159aeef78e770f31742b7d0212c3edafb1800982a1105c94f4a",
    "error_shutdown_permission_denied": "d1621aecb7aafddc1ea9a83c2e828cb509f1d75341e6901d3ffd0ee1fb463a12",
    "error_reboot_timeout": "d64242b38e108aa235e774e3a39888c35e9d621057f3854495551587dc22b2fb",
    "error_shutdown_protocol": "00e98cfcf946ed30f800f56988629a5d9325dc90a9cb5eaf96dbf81850c85ec6",
    "error_reboot_io": "81b584d5a1c38f09c096e017c00b9005810e62c45f918d9fb1e3510b762c5de8",
    "error_missing_code": "81ba60f9f0768cf416876c4eb19d39c07dbe77d51e888a14ecda05e81b9ebc5b",
    "error_back_pressed": "724a09bef6519eed17a65cf6bbadb4c35275add3939a009ea13042a53e85847e",
}

SYSTEM_POWER_DISABLED_HASH = (
    "78cdffb961019c47414fbab3a1794e6e851210c0c4e0da6f7b06fe3d6b9f5517"
)

OLD_GRAPH_HASHES = {
    "graph_fullscreen_collecting": "66b0364742250623eb4d2522b1ac07a168c503658b16c1f00c84e92b565311ff",
    "graph_fullscreen_with_history": "b497c0beaddc5a3b04d785699cce705e5d7ea89862109cc5d7085eda29d48b8b",
}

GRAPH_RENDER_HASHES = {
    "graph_fullscreen_collecting": "5a6c6b75269e68671019ff9099eb2e0edacb194c6673561c75f66023a9814985",
    "graph_fullscreen_with_history": "3c0d304649dc3e32b97574cbf791b8b7551f6dc439b8142c068a581d62acbcf3",
    "graph_fullscreen_temperature": "f98bcfbbff8fe585a6f69ab28d825be10b2f6dac947ddc865542aeccb401afa8",
    "graph_fullscreen_dynamic_power": "31328abb060593eb5921754fdcdeaec58e9815f6dc62d3aaacf7bd6ac82dbc9c",
    "graph_fullscreen_null_gap": "2c0cb29812212ea2af906878af6d2c1fb2c7850054a4bf48c7cccd4900f585ce",
    "graph_footer_previous_pressed": "32179de3769e19f5af19417a64525e6890f710a3a8d84b788569781a9a50c9fe",
    "graph_footer_values_pressed": "2f8df73989620eb2709a71abd2baa6bcb37defc5dd37aeab44664049d6fc5810",
    "graph_footer_next_pressed": "b0bbeaad170f180a12b23b83be712bfba2a5481f4b44a014308aaccbe26b8ee4",
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

NODES_RENDER_HASHES = {
    "nodes_one_page_live": "8e02c2b4af6e8efdf02b37ac37b6a1a8d3d079990a3f16488ba808b297650e08",
    "nodes_two_pages_page_1": "526d4d0ecb842a7e4401a8eea34b939bb05e62fee00f511fb7bd65a3f68b38c3",
    "nodes_two_pages_page_2": "14703ea1447e6d3006480bad6cd0c66d11e8d9a4f6b98113b370d9fc85fa42bb",
    "nodes_mixed_waiting_offline": "dc7c4727e302243683adfcf9f5ee8eabbfd5afb6c43f73c46feea460e9246b55",
    "nodes_link_lost_stale": "391acb9277a77f3ca9eb5bffdb75205aabc262bdee541830f8d4181c8811407d",
    "nodes_selected_row": "a845cbc8fb69c6815bf340854adcba1438c44228fb18d375145346321bc18804",
    "nodes_row_1_pressed": "8ee94217a80955bdbf41fffdcc8490b47533177ce5371372f6be1fc4ab75a45f",
    "nodes_row_2_pressed": "2134dc458778892d98df00810bbc85b4405a389d9451f3c3a1b026a9092b704e",
    "nodes_row_3_pressed": "84d6623edfad47dbc7857ceb300b45b3659012e34546cdc95f05bce37f4929b2",
    "nodes_previous_pressed": "aca61b23b483c63c929d3cf284eb9a4f1317c8a7565a0c4377812160a7c41389",
    "nodes_back_pressed": "5eb86c5668de35232e9e6b853321b6e001a4d4738890efa0c6d54adb9924d6f0",
    "nodes_next_pressed": "0557218aeec6bcd623a11434552f9b6ebf8f4b90a52d32695079f4dc41e1bf67",
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


def phase_6_nodes() -> tuple[dict, ...]:
    waiting_value = waiting_node()
    waiting_value.update({"node_id": "node-b", "display_name": "Beta waiting"})
    return (
        complete_v2_node(
            node_id="node-c",
            display_name="Gamma restored",
            online=False,
            cpu={"usage_percent": 31, "temperature_c": None, "power_w": None},
            memory={"usage_percent": 52},
            gpu=[],
            storage={"usage_percent": 71},
            received_at_utc="2026-07-12T02:58:00Z",
        ),
        complete_v2_node(
            node_id="node-a",
            display_name="Alpha live",
            cpu={"usage_percent": 47, "temperature_c": 63, "power_w": 55},
            memory={"usage_percent": 63},
            gpu=[],
        ),
        waiting_value,
        complete_v2_node(
            node_id="node-d",
            display_name="Delta GPU",
            cpu={"usage_percent": 22, "temperature_c": None, "power_w": None},
            memory={"usage_percent": 44},
            gpu=[{"usage_percent": 81}],
            storage={"usage_percent": 12},
        ),
    )


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

    def test_graph_footer_geometry_and_boundaries_are_exact(self) -> None:
        hitboxes = (
            GRAPH_PREVIOUS_METRIC_HITBOX,
            GRAPH_VALUES_HITBOX,
            GRAPH_NEXT_METRIC_HITBOX,
        )
        self.assertEqual(
            ((0, 192, 64, 240), (64, 192, 256, 240), (256, 192, 320, 240)),
            hitboxes,
        )
        self.assertEqual((64, 192, 64), tuple(right - left for left, _, right, _ in hitboxes))
        self.assertTrue(all(bottom - top >= 48 for _, top, _, bottom in hitboxes))
        self.assertEqual(hitboxes[0][2], hitboxes[1][0])
        self.assertEqual(hitboxes[1][2], hitboxes[2][0])
        expected = {
            (0, 192): "graph_previous_metric",
            (63, 239): "graph_previous_metric",
            (64, 192): "graph_values",
            (255, 239): "graph_values",
            (256, 192): "graph_next_metric",
            (319, 239): "graph_next_metric",
        }
        for point, action in expected.items():
            with self.subTest(point=point):
                self.assertEqual(action, graph_action_at(*point))
        for point in ((0, 191), (319, 191), (0, 240), (319, 240), (-1, 210), (320, 210)):
            with self.subTest(point=point):
                self.assertIsNone(graph_action_at(*point))

    def test_phase_5_menu_navigation_geometry_and_boundaries_are_exact(self) -> None:
        self.assertEqual(2, MENU_PAGE_COUNT)
        self.assertEqual(
            ((0, 32, 160, 112), (160, 32, 320, 112),
             (0, 112, 160, 192), (160, 112, 320, 192)),
            MENU_TILE_RECTS,
        )
        self.assertEqual(
            (("cpu", "memory", "gpu", "nodes"),
             ("storage", "network", "health", "system")),
            MENU_PAGES,
        )
        self.assertTrue(all((right - left, bottom - top) == (160, 80)
                            for left, top, right, bottom in MENU_TILE_RECTS))
        self.assertEqual(320 * 160, sum(
            (right - left) * (bottom - top)
            for left, top, right, bottom in MENU_TILE_RECTS
        ))
        self.assertEqual(
            ((0, 192, 64, 240), (64, 192, 256, 240), (256, 192, 320, 240)),
            (MENU_PREVIOUS_PAGE_HITBOX, MENU_BACK_HITBOX, MENU_NEXT_PAGE_HITBOX),
        )
        self.assertEqual((64, 192, 64), tuple(
            right - left for left, _, right, _ in (
                MENU_PREVIOUS_PAGE_HITBOX,
                MENU_BACK_HITBOX,
                MENU_NEXT_PAGE_HITBOX,
            )
        ))
        self.assertEqual((48, 48, 48), tuple(
            bottom - top for _, top, _, bottom in (
                MENU_PREVIOUS_PAGE_HITBOX,
                MENU_BACK_HITBOX,
                MENU_NEXT_PAGE_HITBOX,
            )
        ))
        expected_tiles = {
            0: {(0, 32): "cpu", (159, 111): "cpu", (160, 32): "memory",
                (319, 111): "memory", (0, 112): "gpu", (159, 191): "gpu",
                (160, 112): "nodes", (319, 191): "nodes"},
            1: {(0, 32): "storage", (159, 111): "storage", (160, 32): "network",
                (319, 111): "network", (0, 112): "health", (159, 191): "health",
                (160, 112): "system", (319, 191): "system"},
        }
        for page, points in expected_tiles.items():
            for point, category_id in points.items():
                with self.subTest(page=page, point=point):
                    self.assertEqual(category_id, menu_tile_id_at(page, *point))
                    self.assertEqual(f"menu_tile_{category_id}", menu_action_at(page, *point))
        for page in (0, 1):
            for point in ((0, 31), (319, 31), (-1, 72), (320, 72)):
                self.assertIsNone(menu_tile_id_at(page, *point))
            self.assertEqual(
                ("menu_previous_page", "menu_back", "menu_next_page"),
                tuple(menu_action_at(page, x, 210) for x in (0, 64, 256)),
            )
        for point in ((-1, 210), (320, 210), (0, 240), (319, 240)):
            self.assertIsNone(menu_action_at(0, *point))
        self.assertEqual((0, 0, 1, 1), tuple(normalize_menu_page(page) for page in (-1, 0, 1, 2)))
        self.assertEqual(
            (0, 0, 0, 1, 1, 1, 0),
            tuple(menu_page_for_category(value) for value in (
                "cpu", "memory", "gpu", "storage", "network", "health", "unknown"
            )),
        )

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
        scenarios = {
            "overview_legacy": (node(), UiState(), None),
            "overview_waiting": (waiting_node(), UiState(), None),
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

    def test_phase_5_menu_rendering_geometry_availability_and_footer_are_exact(self) -> None:
        capabilities = {
            "cpu.usage_percent": {"supported": True, "source": "procfs", "reason": None},
            "storage.usage_percent": {"supported": True, "source": "statvfs", "reason": None},
            "gpu.usage_percent": {"supported": False, "source": None, "reason": "sensor_not_found"},
        }
        expected = {
            0: (
                ("CPU", "READY", BRIGHT),
                ("MEMORY", "READY", GREEN),
                ("GRAPHICS", "NO DATA", MUTED),
                ("NODES", "1 NODE", GREEN),
            ),
            1: (
                ("STORAGE", "READY", GREEN),
                ("NETWORK", "NO DATA", MUTED),
                ("HEALTH", "READY", GREEN),
                ("SYSTEM", "LOCAL", GREEN),
            ),
        }
        original_text = ImageDraw.ImageDraw.text
        original_rectangle = ImageDraw.ImageDraw.rectangle
        original_line = ImageDraw.ImageDraw.line
        for page, expected_tiles in expected.items():
            text_calls = []
            rectangle_calls = []
            line_calls = []

            def record_text(draw, xy, text, *args, **kwargs):
                text_calls.append((xy, text, kwargs))
                return original_text(draw, xy, text, *args, **kwargs)

            def record_rectangle(draw, xy, *args, **kwargs):
                rectangle_calls.append((xy, kwargs))
                return original_rectangle(draw, xy, *args, **kwargs)

            def record_line(draw, xy, *args, **kwargs):
                line_calls.append((xy, kwargs))
                return original_line(draw, xy, *args, **kwargs)

            with self.subTest(page=page), \
                    patch.object(ImageDraw.ImageDraw, "text", new=record_text), \
                    patch.object(ImageDraw.ImageDraw, "rectangle", new=record_rectangle), \
                    patch.object(ImageDraw.ImageDraw, "line", new=record_line), \
                    patch("display.renderer._footer") as standard_footer:
                render(
                    node(capabilities=capabilities),
                    ui_state=UiState(screen=Screen.MAIN_MENU, menu_page=page),
                )
            standard_footer.assert_not_called()
            self.assertIn(((10, 16), "MENU"), {(xy, text) for xy, text, _ in text_calls})
            self.assertIn((310, 16), {xy for xy, _, _ in text_calls})
            titles = tuple(
                (text, kwargs["fill"])
                for xy, text, kwargs in text_calls
                if xy in {(80, 87), (240, 87), (80, 167), (240, 167)}
            )
            subtitles = tuple(
                (text, kwargs["fill"])
                for xy, text, kwargs in text_calls
                if xy in {(80, 101), (240, 101), (80, 181), (240, 181)}
            )
            self.assertEqual(tuple((title, color) for title, _, color in expected_tiles), titles)
            self.assertEqual(tuple((subtitle, color) for _, subtitle, color in expected_tiles), subtitles)
            self.assertEqual(
                ("<", f"BACK {page + 1}/2", ">"),
                tuple(text for xy, text, _ in text_calls if xy[1] == 216),
            )
            self.assertIn(((0, 192, 319, 192), {"fill": MUTED}), line_calls)
            if page == 0:
                self.assertIn(((3, 35, 156, 108), {"outline": MUTED, "width": 1}), rectangle_calls)
                self.assertIn(((237, 123, 243, 129), {"outline": GREEN, "width": 2}), rectangle_calls)
                self.assertIn(((226, 144, 232, 150), {"outline": GREEN, "width": 2}), rectangle_calls)
                self.assertIn(((248, 144, 254, 150), {"outline": GREEN, "width": 2}), rectangle_calls)
            else:
                self.assertIn(((226, 125, 254, 149), {"outline": GREEN, "width": 2}), rectangle_calls)

        health_text = []

        def record_health_text(draw, xy, text, *args, **kwargs):
            health_text.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_health_text):
            render(
                complete_v2_node(collector={"version": "0.3.0", "errors": ["a", "b"]}),
                ui_state=UiState(
                    screen=Screen.MAIN_MENU,
                    menu_page=1,
                    selected_category_id="network",
                ),
            )
        health_title = next(call for call in health_text if call[1] == "HEALTH")
        health_subtitle = next(call for call in health_text if call[1] == "ERR 2")
        self.assertEqual((AMBER, AMBER), (
            health_title[2]["fill"], health_subtitle[2]["fill"]
        ))

    def test_phase_5_menu_pressed_feedback_is_localized_and_disabled_tiles_stay_idle(self) -> None:
        value = complete_v2_node()
        for page, actions in {
            0: ("menu_tile_cpu", "menu_tile_memory", "menu_tile_gpu", "menu_tile_nodes"),
            1: ("menu_tile_storage", "menu_tile_network", "menu_tile_health", "menu_tile_system"),
        }.items():
            state = UiState(screen=Screen.MAIN_MENU, menu_page=page)
            normal = render(value, ui_state=state)
            for action, hitbox in zip(actions, MENU_TILE_RECTS):
                with self.subTest(page=page, action=action):
                    pressed = render(value, ui_state=state, pressed_action=action)
                    difference = ImageChops.difference(normal, pressed).getbbox()
                    self.assertIsNotNone(difference)
                    self.assertGreaterEqual(difference[0], hitbox[0])
                    self.assertGreaterEqual(difference[1], hitbox[1])
                    self.assertLessEqual(difference[2], hitbox[2])
                    self.assertLessEqual(difference[3], hitbox[3])
                    self.assertEqual(
                        ImageColor.getrgb(MUTED),
                        pressed.getpixel((hitbox[0] + 4, hitbox[1] + 4)),
                    )

            footer_actions = (
                ("menu_previous_page", MENU_PREVIOUS_PAGE_HITBOX),
                ("menu_back", MENU_BACK_HITBOX),
                ("menu_next_page", MENU_NEXT_PAGE_HITBOX),
            )
            for action, hitbox in footer_actions:
                with self.subTest(page=page, action=action):
                    pressed = render(value, ui_state=state, pressed_action=action)
                    difference = ImageChops.difference(normal, pressed).getbbox()
                    self.assertIsNotNone(difference)
                    self.assertGreaterEqual(difference[0], hitbox[0])
                    self.assertGreaterEqual(difference[1], hitbox[1])
                    self.assertLessEqual(difference[2], hitbox[2])
                    self.assertLessEqual(difference[3], hitbox[3])

        unavailable = node()
        for page, point, forbidden_action in (
            (0, (80, 152), "menu_tile_gpu"),
            (1, (80, 72), "menu_tile_storage"),
        ):
            state = UiState(screen=Screen.MAIN_MENU, menu_page=page)
            with self.subTest(page=page, point=point):
                self.assertIsNone(visible_action_at(state, unavailable, *point))
                self.assertEqual(
                    render(unavailable, ui_state=state).tobytes(),
                    render(unavailable, ui_state=state, pressed_action=forbidden_action).tobytes(),
                )
        empty_state = UiState(screen=Screen.MAIN_MENU)
        self.assertIsNone(visible_action_at(
            empty_state,
            unavailable,
            240,
            152,
            (),
        ))
        self.assertEqual(
            render(unavailable, ui_state=empty_state, nodes=()).tobytes(),
            render(
                unavailable,
                ui_state=empty_state,
                pressed_action="menu_tile_nodes",
                nodes=(),
            ).tobytes(),
        )

    def test_phase_5_menu_render_hashes_are_exact(self) -> None:
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        capabilities = {
            "cpu.usage_percent": {"supported": True, "source": "procfs", "reason": None},
            "storage.usage_percent": {"supported": True, "source": "statvfs", "reason": None},
            "gpu.usage_percent": {"supported": False, "source": None, "reason": "sensor_not_found"},
        }
        legacy = node()
        capable = node(capabilities=capabilities)
        full = complete_v2_node()
        errors = complete_v2_node(collector={"version": "0.3.0", "errors": ["a", "b"]})
        scenarios = {
            "menu_page_1_legacy": (legacy, UiState(screen=Screen.MAIN_MENU), None),
            "menu_page_1_capabilities": (capable, UiState(screen=Screen.MAIN_MENU), None),
            "menu_page_2_legacy": (legacy, UiState(screen=Screen.MAIN_MENU, menu_page=1), None),
            "menu_page_2_capabilities": (capable, UiState(screen=Screen.MAIN_MENU, menu_page=1), None),
            "menu_page_2_health_errors": (
                errors,
                UiState(screen=Screen.MAIN_MENU, menu_page=1, selected_category_id="network"),
                None,
            ),
        }
        for category_id in ("cpu", "memory", "gpu", "nodes"):
            scenarios[f"menu_page_1_{category_id}_pressed"] = (
                full, UiState(screen=Screen.MAIN_MENU), f"menu_tile_{category_id}"
            )
        for category_id in ("storage", "network", "health", "system"):
            scenarios[f"menu_page_2_{category_id}_pressed"] = (
                full, UiState(screen=Screen.MAIN_MENU, menu_page=1), f"menu_tile_{category_id}"
            )
        for page in (1, 2):
            for suffix, action in (
                ("previous", "menu_previous_page"),
                ("back", "menu_back"),
                ("next", "menu_next_page"),
            ):
                scenarios[f"menu_page_{page}_{suffix}_pressed"] = (
                    full,
                    UiState(screen=Screen.MAIN_MENU, menu_page=page - 1),
                    action,
                )
        for name, (value, state, pressed_action) in scenarios.items():
            with self.subTest(name=name):
                digest = hashlib.sha256(render(
                    value,
                    (1, 4),
                    True,
                    state,
                    pressed_action=pressed_action,
                    now=now,
                ).tobytes()).hexdigest()
                self.assertEqual(MENU_RENDER_HASHES[name], digest)
        self.assertNotEqual(
            OLD_MAIN_MENU_HASHES["main_menu_legacy"],
            MENU_RENDER_HASHES["menu_page_1_legacy"],
        )
        self.assertNotEqual(
            OLD_MAIN_MENU_HASHES["main_menu_capabilities"],
            MENU_RENDER_HASHES["menu_page_1_capabilities"],
        )

    def test_phase_4_graph_render_hashes_are_exact(self) -> None:
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        history = HistoryStore(window_seconds=300, max_samples=180)
        history.add(node(
            timestamp_utc="2026-07-12T03:00:00Z",
            cpu={"usage_percent": 20, "temperature_c": 63, "power_w": None},
        ))
        history.add(node(timestamp_utc="2026-07-12T03:00:01Z", online=False))
        graph_node = node(
            timestamp_utc="2026-07-12T03:00:02Z",
            cpu={"usage_percent": 80, "temperature_c": 63, "power_w": None},
        )
        history.add(graph_node)

        null_history = HistoryStore(window_seconds=300, max_samples=180)
        for second, usage, online in (
            (0, 20, True),
            (1, 40, True),
            (2, 0, False),
            (3, 60, True),
            (4, 80, True),
        ):
            null_history.add(node(
                timestamp_utc=f"2026-07-12T03:00:0{second}Z",
                online=online,
                cpu={"usage_percent": usage, "temperature_c": 63, "power_w": None},
            ))
        null_node = node(
            timestamp_utc="2026-07-12T03:00:04Z",
            cpu={"usage_percent": 80, "temperature_c": 63, "power_w": None},
        )
        value = complete_v2_node()
        temperature = UiState(
            screen=Screen.GRAPH,
            metric_by_category={"cpu": "temperature"},
        )
        scenarios = {
            "graph_fullscreen_collecting": render(
                node(), (1, 4), True, UiState(screen=Screen.GRAPH), now=now
            ),
            "graph_fullscreen_with_history": render(
                graph_node,
                (1, 4),
                True,
                UiState(screen=Screen.GRAPH),
                history=history,
                now=now,
            ),
            "graph_fullscreen_temperature": render(value, (1, 1), True, temperature, now=now),
            "graph_fullscreen_dynamic_power": render(
                value,
                (1, 1),
                True,
                UiState(screen=Screen.GRAPH, metric_by_category={"cpu": "power"}),
                now=now,
            ),
            "graph_fullscreen_null_gap": render(
                null_node,
                (1, 1),
                True,
                UiState(screen=Screen.GRAPH),
                history=null_history,
                now=datetime(2026, 7, 12, 3, 0, 4, tzinfo=timezone.utc),
            ),
            "graph_footer_previous_pressed": render(
                value, (1, 1), True, temperature, pressed_action="graph_previous_metric", now=now
            ),
            "graph_footer_values_pressed": render(
                value, (1, 1), True, temperature, pressed_action="graph_values", now=now
            ),
            "graph_footer_next_pressed": render(
                value, (1, 1), True, temperature, pressed_action="graph_next_metric", now=now
            ),
        }
        for name, image in scenarios.items():
            with self.subTest(name=name):
                digest = hashlib.sha256(image.tobytes()).hexdigest()
                self.assertEqual(GRAPH_RENDER_HASHES[name], digest)
                if name in OLD_GRAPH_HASHES:
                    self.assertNotEqual(OLD_GRAPH_HASHES[name], digest)

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
        assert gesture is not None
        self.assertEqual(GestureKind.SHORT, gesture.kind)
        self.assertEqual((101, 210), (gesture.x, gesture.y))

    def test_long_gesture_emits_once_with_resistive_jitter(self) -> None:
        recognizer = TouchRecognizer()
        recognizer.update(True, 100, 210, 1.0)
        gesture = None
        for now, point in ((1.2, (108, 214)), (1.4, (92, 205)), (1.66, (105, 212))):
            gesture = recognizer.update(True, *point, now)
        assert gesture is not None
        self.assertEqual(GestureKind.LONG, gesture.kind)
        self.assertIsNone(recognizer.update(True, 103, 208, 2.0))
        self.assertEqual(GestureState.LONG_EMITTED, recognizer.state)
        self.assertIsNone(recognizer.update(False, now=2.1))
        self.assertIsNone(recognizer.update(True, 100, 210, 2.2))
        self.assertEqual(GestureState.IDLE, recognizer.state)

    def test_large_touch_movement_cancels_the_gesture(self) -> None:
        recognizer = TouchRecognizer()
        recognizer.update(True, 100, 210, 1.0)
        self.assertIsNone(recognizer.update(True, 130, 210, 1.2))
        self.assertIsNone(recognizer.update(True, 132, 211, 1.25))
        self.assertEqual(GestureState.WAIT_RELEASE, recognizer.state)
        self.assertIsNone(recognizer.update(False, now=1.3))

    def test_movement_after_long_cancels_without_second_gesture(self) -> None:
        recognizer = TouchRecognizer(long_press_seconds=0.5, movement_tolerance_pixels=10)
        self.assertIsNone(recognizer.update(True, 100, 210, 1.0))
        gesture = recognizer.update(True, 100, 210, 1.5)
        assert gesture is not None
        self.assertEqual(GestureKind.LONG, gesture.kind)
        for _ in range(4):
            self.assertIsNone(recognizer.update(True, 130, 210, 1.6))
        self.assertEqual(GestureState.WAIT_RELEASE, recognizer.state)
        self.assertIsNone(recognizer.update(True, 100, 210, 1.7))
        self.assertIsNone(recognizer.update(False, now=1.8))

    def test_category_registry_and_fixed_menu_geometry(self) -> None:
        value = node()
        cpu = category_at(10, 40)
        network = category_at(160, 120)
        assert cpu is not None and network is not None
        self.assertEqual("cpu", cpu.id)
        self.assertEqual("network", network.id)
        self.assertTrue(category("cpu").available(value))
        self.assertFalse(category("storage").available(value))
        capability = {"supported": True, "source": "statvfs", "reason": None}
        self.assertTrue(category("storage").available(node(capabilities={"storage.usage_percent": capability})))
        unsupported = {"supported": False, "source": None, "reason": "sensor_not_found"}
        self.assertFalse(category("gpu").available(node(gpu=[{}], capabilities={"gpu.usage_percent": unsupported})))
        self.assertEqual(100.0, category("cpu").chart_metrics[0].scale.maximum)
        temperature = metric_at("cpu", 150, 50)
        assert temperature is not None
        self.assertEqual("temperature", temperature.id)
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
        self.assertEqual(
            (320, 240),
            render(
                node(),
                ui_state=UiState(screen=Screen.NODES),
                nodes=(node(),),
            ).size,
        )
        for screen in (Screen.POWER_CONFIRM, Screen.POWER_PENDING):
            self.assertEqual((320, 240), render(node(), ui_state=UiState(screen=screen)).size)
            self.assertEqual((320, 240), render(None, ui_state=UiState(screen=screen)).size)
        self.assertEqual(
            (320, 240),
            render(node(), ui_state=UiState(screen=Screen.POWER_ERROR)).size,
        )
        self.assertEqual((320, 240), render(None, ui_state=UiState(screen=Screen.POWER_ERROR)).size)

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
        graph_text = []

        def record_graph_text(draw, xy, text, *args, **kwargs):
            graph_text.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_graph_text), \
                patch("display.renderer._chart", wraps=_chart) as chart:
            temperature_frame = render(value, ui_state=graph.state, now=now)
        self.assertEqual("temperature", chart.call_args.args[3].id)
        self.assertIn("CPU / TEMP", {text for _, text, _ in graph_text})
        self.assertFalse(any(text in {"LOAD", "TEMP", "POWER", "CLOCK"} and xy[1] == 43
                             for xy, text, _ in graph_text))
        self.assertFalse(any(text in {"VALUES", "GRAPH"} and xy[1] == 68
                             for xy, text, _ in graph_text))

        following = reduce_ui(graph.state, ShortPress(300, 210, 4), context)
        self.assertEqual("clock", following.state.metric_by_category["cpu"])
        clock_text = []

        def record_clock_text(draw, xy, text, *args, **kwargs):
            clock_text.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_clock_text):
            clock_frame = render(value, ui_state=following.state, now=now)
        self.assertIn("CPU / CLOCK", {text for _, text, _ in clock_text})
        self.assertNotEqual(temperature_frame.tobytes(), clock_frame.tobytes())

        previous = reduce_ui(following.state, ShortPress(10, 210, 5), context)
        self.assertEqual("temperature", previous.state.metric_by_category["cpu"])
        values = reduce_ui(previous.state, ShortPress(160, 210, 6), context)
        self.assertEqual(Screen.VALUES, values.state.screen)
        self.assertEqual("temperature", values.state.metric_by_category["cpu"])

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
        self.assertFalse(any(xy[1] == 43 for xy, _, _ in graph_text_calls))
        self.assertFalse(any(
            xy[1] == 68 and text in {"VALUES", "GRAPH"}
            for xy, text, _ in graph_text_calls
        ))
        self.assertFalse(any(
            len(xy) == 4 and xy[1] == xy[3] and xy[1] in {54, 78}
            for xy, _ in graph_line_calls
        ))

    def test_graph_route_header_plot_and_summary_geometry_are_exact(self) -> None:
        self.assertEqual(28, GRAPH_HEADER_BOTTOM)
        self.assertEqual((20, 28, 312, 184), GRAPH_PLOT_RECT)
        self.assertEqual((42, 32, 312, 162), GRAPH_GRID_RECT)
        self.assertEqual(178, GRAPH_SUMMARY_Y)
        self.assertEqual((6, 10, 12, 16), GRAPH_STATUS_DOT)
        self.assertEqual(((16, 14), 112), (GRAPH_IDENTITY_POSITION, GRAPH_IDENTITY_WIDTH))
        self.assertEqual(((186, 14), 118), (GRAPH_TITLE_POSITION, GRAPH_TITLE_WIDTH))
        self.assertEqual((310, 14), GRAPH_META_POSITION)

        text_calls = []
        line_calls = []
        rectangle_calls = []
        original_text = ImageDraw.ImageDraw.text
        original_line = ImageDraw.ImageDraw.line
        original_rectangle = ImageDraw.ImageDraw.rectangle

        def record_text(draw, xy, text, *args, **kwargs):
            text_calls.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        def record_line(draw, xy, *args, **kwargs):
            line_calls.append((xy, kwargs))
            return original_line(draw, xy, *args, **kwargs)

        def record_rectangle(draw, xy, *args, **kwargs):
            rectangle_calls.append((xy, kwargs))
            return original_rectangle(draw, xy, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text), \
                patch.object(ImageDraw.ImageDraw, "line", new=record_line), \
                patch.object(ImageDraw.ImageDraw, "rectangle", new=record_rectangle), \
                patch("display.renderer._detail_header") as detail_header, \
                patch("display.renderer._values_detail") as values_detail, \
                patch("display.renderer._open_graph_action") as open_graph, \
                patch("display.renderer._footer") as standard_footer, \
                patch("display.renderer._fit", wraps=_fit) as fit:
            render(
                node(),
                (1, 4),
                True,
                UiState(screen=Screen.GRAPH),
                now=datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc),
            )
        detail_header.assert_not_called()
        values_detail.assert_not_called()
        open_graph.assert_not_called()
        standard_footer.assert_not_called()
        self.assertIn((GRAPH_STATUS_DOT, {"fill": GREEN}), rectangle_calls)
        identity = next(call for call in text_calls if call[0] == GRAPH_IDENTITY_POSITION)
        self.assertIn("ONLINE", identity[1])
        self.assertEqual((GREEN, "lm", 13), (
            identity[2]["fill"], identity[2]["anchor"], identity[2]["font"].size
        ))
        title = next(call for call in text_calls if call[0] == GRAPH_TITLE_POSITION)
        self.assertEqual(("CPU / LOAD", BRIGHT, "mm", 15), (
            title[1], title[2]["fill"], title[2]["anchor"], title[2]["font"].size
        ))
        meta = next(call for call in text_calls if call[0] == GRAPH_META_POSITION)
        self.assertEqual(("1/4 2s", MUTED, "rm"), (
            meta[1], meta[2]["fill"], meta[2]["anchor"]
        ))
        self.assertTrue({112, 118, 56}.issubset({call.args[3] for call in fit.call_args_list}))
        for y in (32, 97, 162):
            self.assertIn(((42, y, 312, y), {"fill": MUTED}), line_calls)
        self.assertIn(((294, 58, 312, 58), {"fill": AMBER}), line_calls)
        self.assertIn(((294, 38, 312, 38), {"fill": RED}), line_calls)
        self.assertIn((38, 32), {xy for xy, _, _ in text_calls})
        self.assertIn((38, 162), {xy for xy, _, _ in text_calls})
        self.assertIn((177, 97), {xy for xy, _, _ in text_calls})
        self.assertEqual(
            {(10, 178), (160, 178), (310, 178)},
            {xy for xy, text, _ in text_calls if text.startswith(("NOW ", "MIN ", "MAX "))},
        )

    def test_invalid_graph_category_renders_values_safely(self) -> None:
        value = complete_v2_node()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        graph_state = UiState(screen=Screen.GRAPH, selected_category_id="health")
        graph_health = render(
            value,
            (1, 1),
            True,
            graph_state,
            now=now,
        )
        values_health = render(
            value,
            (1, 1),
            True,
            UiState(screen=Screen.VALUES, selected_category_id="health"),
            now=now,
        )
        self.assertEqual(values_health.tobytes(), graph_health.tobytes())
        self.assertEqual(VALUES_RENDER_HASHES["health"], hashlib.sha256(graph_health.tobytes()).hexdigest())
        self.assertEqual(("previous", "center", "next"), tuple(
            visible_action_at(graph_state, value, x, 210) for x in (10, 160, 300)
        ))

    def test_empty_refresh_aligns_rendered_overview_and_touch_contract(self) -> None:
        context = UiContext((), 30, 45, 15, 10)
        overview = render(None, ui_state=UiState(screen=Screen.OVERVIEW))
        for screen in (Screen.MAIN_MENU, Screen.VALUES, Screen.GRAPH):
            with self.subTest(screen=screen):
                transition = reduce_ui(
                    UiState(screen=screen, selected_node_id="desktop"),
                    DataRefreshed((), False, 1),
                    context,
                )
                self.assertEqual(Screen.OVERVIEW, transition.state.screen)
                self.assertEqual(
                    overview.tobytes(),
                    render(None, ui_state=transition.state).tobytes(),
                )
                self.assertEqual(("previous", "center", "next"), tuple(
                    visible_action_at(transition.state, None, x, 210)
                    for x in (10, 160, 300)
                ))

    def test_graph_footer_labels_wrap_fit_and_pressed_feedback(self) -> None:
        value = complete_v2_node()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        original_text = ImageDraw.ImageDraw.text
        expected_labels = {
            "temperature": ("< LOAD", "VALUES", "CLOCK >"),
            "load": ("< PWR", "VALUES", "TEMP >"),
            "power": ("< CLOCK", "VALUES", "LOAD >"),
        }
        for metric_id, expected in expected_labels.items():
            text_calls = []

            def record_text(draw, xy, text, *args, **kwargs):
                text_calls.append((xy, text, kwargs))
                return original_text(draw, xy, text, *args, **kwargs)

            with self.subTest(metric=metric_id), \
                    patch.object(ImageDraw.ImageDraw, "text", new=record_text), \
                    patch("display.renderer._fit", wraps=_fit) as fit:
                render(
                    value,
                    ui_state=UiState(
                        screen=Screen.GRAPH,
                        metric_by_category={"cpu": metric_id},
                    ),
                    now=now,
                )
            footer = tuple(text for xy, text, _ in text_calls if xy[1] == 216)
            self.assertEqual(expected, footer)
            self.assertEqual(2, sum(call.args[3] == 56 for call in fit.call_args_list))

        image = Image.new("RGB", (320, 240), BACKGROUND)
        draw = ImageDraw.Draw(image)
        fonts = {"small": ImageFont.truetype(FONT_PATH, 13)}
        one_metric_text = []

        def record_one_metric_text(draw, xy, text, *args, **kwargs):
            one_metric_text.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_one_metric_text):
            _graph_footer(draw, fonts, category("network").chart_metrics[:1], "down", None)
        self.assertEqual(("<", "VALUES", ">"), tuple(
            text for xy, text, _ in one_metric_text if xy[1] == 216
        ))

        normal = render(
            value,
            ui_state=UiState(screen=Screen.GRAPH, metric_by_category={"cpu": "temperature"}),
            now=now,
        )
        hitboxes = {
            "graph_previous_metric": GRAPH_PREVIOUS_METRIC_HITBOX,
            "graph_values": GRAPH_VALUES_HITBOX,
            "graph_next_metric": GRAPH_NEXT_METRIC_HITBOX,
        }
        for action, hitbox in hitboxes.items():
            with self.subTest(action=action):
                pressed_text = []

                def record_pressed_text(draw, xy, text, *args, **kwargs):
                    pressed_text.append((xy, text, kwargs))
                    return original_text(draw, xy, text, *args, **kwargs)

                with patch.object(ImageDraw.ImageDraw, "text", new=record_pressed_text):
                    pressed = render(
                        value,
                        ui_state=UiState(
                            screen=Screen.GRAPH,
                            metric_by_category={"cpu": "temperature"},
                        ),
                        pressed_action=action,
                        now=now,
                    )
                difference = ImageChops.difference(normal, pressed).getbbox()
                self.assertIsNotNone(difference)
                self.assertGreaterEqual(difference[0], hitbox[0])
                self.assertGreaterEqual(difference[1], hitbox[1])
                self.assertLessEqual(difference[2], hitbox[2])
                self.assertLessEqual(difference[3], hitbox[3])
                self.assertEqual(ImageColor.getrgb(MUTED), pressed.getpixel((hitbox[0] + 2, 200)))
                pressed_labels = [
                    kwargs for xy, _, kwargs in pressed_text
                    if xy[1] == 216 and kwargs.get("fill") == BACKGROUND
                ]
                self.assertEqual(1, len(pressed_labels))

    def test_graph_null_gap_is_not_bridged(self) -> None:
        history = HistoryStore(window_seconds=300, max_samples=180)
        for second, usage, online in (
            (0, 20, True),
            (1, 40, True),
            (2, 0, False),
            (3, 60, True),
            (4, 80, True),
        ):
            history.add(node(
                timestamp_utc=f"2026-07-12T03:00:0{second}Z",
                online=online,
                cpu={"usage_percent": usage, "temperature_c": 63, "power_w": None},
            ))
        segments = []
        original_line = ImageDraw.ImageDraw.line

        def record_line(draw, xy, *args, **kwargs):
            if isinstance(xy, list) and kwargs.get("fill") == GREEN and kwargs.get("width") == 2:
                segments.append(tuple(xy))
            return original_line(draw, xy, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "line", new=record_line):
            render(
                node(
                    timestamp_utc="2026-07-12T03:00:04Z",
                    cpu={"usage_percent": 80, "temperature_c": 63, "power_w": None},
                ),
                ui_state=UiState(screen=Screen.GRAPH),
                history=history,
                now=datetime(2026, 7, 12, 3, 0, 4, tzinfo=timezone.utc),
            )
        self.assertEqual(2, len(segments))
        self.assertLess(segments[0][-1][0], segments[1][0][0])

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
        self.assertIn("tuple(nodes)", source)
        self.assertIn("nodes=tuple(nodes)", source)
        self.assertIn("state.menu_page", source)
        self.assertIn("state.nodes_page", source)
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
        self.assertEqual([42, 312], [points[0][0], points[-1][0]])
        self.assertTrue(all(42 <= x <= 312 and 32 <= y <= 162 for x, y in points))

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

    def test_phase_6_nodes_navigation_geometry_ordering_and_actions_are_exact(self) -> None:
        self.assertEqual(3, NODES_PAGE_SIZE)
        self.assertEqual(
            ((0, 32, 320, 85), (0, 85, 320, 138), (0, 138, 320, 192)),
            NODES_ROW_RECTS,
        )
        self.assertEqual((53, 53, 54), tuple(
            bottom - top for _, top, _, bottom in NODES_ROW_RECTS
        ))
        self.assertEqual((32, 85, 138), tuple(top for _, top, _, _ in NODES_ROW_RECTS))
        self.assertEqual((85, 138, 192), tuple(bottom for _, _, _, bottom in NODES_ROW_RECTS))
        self.assertEqual(160, sum(bottom - top for _, top, _, bottom in NODES_ROW_RECTS))
        self.assertTrue(all(
            NODES_ROW_RECTS[index][3] == NODES_ROW_RECTS[index + 1][1]
            for index in range(2)
        ))
        footers = (
            NODES_PREVIOUS_PAGE_HITBOX,
            NODES_BACK_HITBOX,
            NODES_NEXT_PAGE_HITBOX,
        )
        self.assertEqual(
            ((0, 192, 64, 240), (64, 192, 256, 240), (256, 192, 320, 240)),
            footers,
        )
        self.assertEqual((64, 192, 64), tuple(right - left for left, _, right, _ in footers))
        self.assertEqual((48, 48, 48), tuple(bottom - top for _, top, _, bottom in footers))

        values = [node(node_id="node-c"), node(node_id="node-a"), node(node_id="node-b"), node(node_id="node-d")]
        before = copy.deepcopy(values)
        self.assertEqual(
            ("node-a", "node-b", "node-c", "node-d"),
            tuple(item["node_id"] for item in ordered_nodes(values)),
        )
        self.assertEqual(before, values)
        self.assertIsInstance(ordered_nodes(values), tuple)
        self.assertEqual(
            (1, 1, 1, 2, 2, 3),
            tuple(nodes_page_count(count) for count in (0, 1, 3, 4, 6, 7)),
        )
        self.assertEqual(
            (0, 0, 1, 1),
            tuple(normalize_nodes_page(page, 4) for page in (-1, 0, 1, 2)),
        )
        self.assertEqual(0, normalize_nodes_page(99, 0))
        self.assertEqual(
            ("node-a", "node-b", "node-c"),
            tuple(item["node_id"] for item in nodes_page_items(values, 0)),
        )
        self.assertEqual(
            ("node-d",),
            tuple(item["node_id"] for item in nodes_page_items(values, 1)),
        )
        self.assertEqual(
            ("nodes_select_0", "nodes_select_0", "nodes_select_1", "nodes_select_1",
             "nodes_select_2", "nodes_select_2"),
            tuple(nodes_action_at(0, 4, *point) for point in (
                (0, 32), (319, 84), (0, 85), (319, 137), (0, 138), (319, 191)
            )),
        )
        self.assertEqual("nodes_select_0", nodes_action_at(1, 4, 10, 40))
        self.assertIsNone(nodes_action_at(1, 4, 10, 90))
        self.assertEqual(
            ("nodes_previous_page", "nodes_back", "nodes_next_page"),
            tuple(nodes_action_at(0, 4, x, 210) for x in (10, 160, 300)),
        )
        self.assertEqual(
            (None, "nodes_back", None),
            tuple(nodes_action_at(0, 3, x, 210) for x in (10, 160, 300)),
        )
        for point in ((-1, 40), (320, 40), (0, 31), (319, 240)):
            self.assertIsNone(nodes_action_at(0, 4, *point))

    def test_phase_6_nodes_renderer_routing_header_rows_and_stale_status_are_exact(self) -> None:
        values = phase_6_nodes()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        text_calls = []
        rectangle_calls = []
        ellipse_calls = []
        line_calls = []
        original_text = ImageDraw.ImageDraw.text
        original_rectangle = ImageDraw.ImageDraw.rectangle
        original_ellipse = ImageDraw.ImageDraw.ellipse
        original_line = ImageDraw.ImageDraw.line

        def record_text(draw, xy, text, *args, **kwargs):
            text_calls.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        def record_rectangle(draw, xy, *args, **kwargs):
            rectangle_calls.append((xy, kwargs))
            return original_rectangle(draw, xy, *args, **kwargs)

        def record_ellipse(draw, xy, *args, **kwargs):
            ellipse_calls.append((xy, kwargs))
            return original_ellipse(draw, xy, *args, **kwargs)

        def record_line(draw, xy, *args, **kwargs):
            line_calls.append((xy, kwargs))
            return original_line(draw, xy, *args, **kwargs)

        state = UiState(screen=Screen.NODES, selected_node_id="node-b", nodes_page=0)
        with patch.object(ImageDraw.ImageDraw, "text", new=record_text), \
                patch.object(ImageDraw.ImageDraw, "rectangle", new=record_rectangle), \
                patch.object(ImageDraw.ImageDraw, "ellipse", new=record_ellipse), \
                patch.object(ImageDraw.ImageDraw, "line", new=record_line), \
                patch("display.renderer._menu") as menu, \
                patch("display.renderer._menu_footer") as menu_footer, \
                patch("display.renderer._footer") as footer, \
                patch("display.renderer._detail_header") as detail_header, \
                patch("display.renderer._values_detail") as values_detail, \
                patch("display.renderer._graph_footer") as graph_footer, \
                patch("display.renderer._fit", wraps=_fit) as fit:
            render(values[0], ui_state=state, nodes=values, now=now)
        for forbidden in (menu, menu_footer, footer, detail_header, values_detail, graph_footer):
            forbidden.assert_not_called()

        title = next(call for call in text_calls if call[0] == (10, 16))
        count = next(call for call in text_calls if call[0] == (310, 16))
        self.assertEqual(("NODES", GREEN, "lm", 15), (
            title[1], title[2]["fill"], title[2]["anchor"], title[2]["font"].size
        ))
        self.assertEqual(("4 NODES", MUTED, "rm", 13), (
            count[1], count[2]["fill"], count[2]["anchor"], count[2]["font"].size
        ))
        self.assertEqual(
            ("ALPHA LIVE", "BETA WAITING", "GAMMA RESTORED"),
            tuple(text for xy, text, _ in text_calls if xy[0] == 104),
        )
        self.assertEqual(
            ("ONLINE", "WAITING", "OFFLINE"),
            tuple(text for xy, text, _ in text_calls if xy[0] == 22),
        )
        self.assertEqual(("2s", "—", "2m"), tuple(
            text for xy, text, _ in text_calls if xy[0] == 310 and xy[1] in (45, 98, 151)
        ))
        self.assertEqual(
            ((10, 70), (112, 70), (220, 70)),
            tuple(xy for xy, text, _ in text_calls if text in {"CPU 47%", "RAM 63%", "TEMP 63°C"}),
        )
        self.assertTrue({
            "CPU 47%", "RAM 63%", "TEMP 63°C",
            "CPU —", "RAM —", "N/A",
            "CPU 31%", "RAM 52%", "DISK 71%",
        }.issubset({text for _, text, _ in text_calls}))
        self.assertIn(((3, 88, 316, 134), {"outline": MUTED, "width": 1}), rectangle_calls)
        self.assertEqual(
            {(8, 41, 16, 49), (8, 94, 16, 102), (8, 147, 16, 155)},
            {xy for xy, _ in ellipse_calls},
        )
        self.assertTrue({85, 138, 192}.issubset({xy[1] for xy, _ in line_calls if len(xy) == 4}))
        self.assertEqual(3, sum(call.args[3] == 76 for call in fit.call_args_list))
        self.assertEqual(3, sum(call.args[3] == 142 for call in fit.call_args_list))
        footer_calls = [(text, kwargs["fill"], kwargs["font"].size)
                        for xy, text, kwargs in text_calls if xy[1] == 216]
        self.assertEqual(
            [("<", GREEN, 18), ("BACK 1/2", GREEN, 13), (">", GREEN, 18)],
            footer_calls,
        )

        second_page_text = []

        def record_second_page_text(draw, xy, text, *args, **kwargs):
            second_page_text.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_second_page_text):
            render(
                values[0],
                ui_state=UiState(screen=Screen.NODES, selected_node_id="node-d", nodes_page=1),
                nodes=values,
                now=now,
            )
        self.assertEqual(("DELTA GPU",), tuple(
            text for xy, text, _ in second_page_text if xy[0] == 104
        ))
        self.assertIn("GPU 81%", {text for _, text, _ in second_page_text})

        link_lost_text = []

        def record_link_lost_text(draw, xy, text, *args, **kwargs):
            link_lost_text.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_link_lost_text):
            render(values[0], hub_online=False, ui_state=state, nodes=values, now=now)
        self.assertEqual(("LINK LOST",) * 3, tuple(
            text for xy, text, _ in link_lost_text if xy[0] == 22
        ))

    def test_phase_6_main_menu_nodes_count_and_phase_7_system_activation(self) -> None:
        values = phase_6_nodes()
        text_calls = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            text_calls.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        state = UiState(screen=Screen.MAIN_MENU)
        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            normal = render(values[0], ui_state=state, nodes=values)
        nodes_title = next(call for call in text_calls if call[1] == "NODES")
        nodes_count = next(call for call in text_calls if call[1] == "4 NODES")
        self.assertEqual((GREEN, GREEN), (
            nodes_title[2]["fill"], nodes_count[2]["fill"]
        ))
        self.assertEqual(
            "menu_tile_nodes",
            visible_action_at(state, values[0], 240, 152, values),
        )
        pressed = render(
            values[0],
            ui_state=state,
            pressed_action="menu_tile_nodes",
            nodes=values,
        )
        difference = ImageChops.difference(normal, pressed).getbbox()
        self.assertIsNotNone(difference)
        self.assertGreaterEqual(difference[0], MENU_TILE_RECTS[3][0])
        self.assertGreaterEqual(difference[1], MENU_TILE_RECTS[3][1])
        self.assertLessEqual(difference[2], MENU_TILE_RECTS[3][2])
        self.assertLessEqual(difference[3], MENU_TILE_RECTS[3][3])

        empty_text = []

        def record_empty_text(draw, xy, text, *args, **kwargs):
            empty_text.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_empty_text):
            empty = render(values[0], ui_state=state, nodes=())
        no_nodes = next(call for call in empty_text if call[1] == "NO NODES")
        self.assertEqual(MUTED, no_nodes[2]["fill"])
        self.assertEqual(
            empty.tobytes(),
            render(
                values[0],
                ui_state=state,
                pressed_action="menu_tile_nodes",
                nodes=(),
            ).tobytes(),
        )

        system_state = UiState(screen=Screen.MAIN_MENU, menu_page=1)
        system = render(values[0], ui_state=system_state, nodes=values)
        self.assertEqual(
            "menu_tile_system",
            visible_action_at(system_state, values[0], 240, 152, values),
        )
        pressed_system = render(
            values[0],
            ui_state=system_state,
            pressed_action="menu_tile_system",
            nodes=values,
        )
        difference = ImageChops.difference(system, pressed_system).getbbox()
        self.assertIsNotNone(difference)
        self.assertGreaterEqual(difference[0], MENU_TILE_RECTS[3][0])
        self.assertGreaterEqual(difference[1], MENU_TILE_RECTS[3][1])
        self.assertLessEqual(difference[2], MENU_TILE_RECTS[3][2])
        self.assertLessEqual(difference[3], MENU_TILE_RECTS[3][3])

    def test_phase_6_nodes_pressed_feedback_is_localized_and_actionable_only(self) -> None:
        values = phase_6_nodes()
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        state = UiState(screen=Screen.NODES, selected_node_id="node-d")
        normal = render(values[0], ui_state=state, nodes=values, now=now)
        original_text = ImageDraw.ImageDraw.text
        original_ellipse = ImageDraw.ImageDraw.ellipse
        for index, row in enumerate(NODES_ROW_RECTS):
            text_calls = []
            ellipse_calls = []

            def record_text(draw, xy, text, *args, **kwargs):
                text_calls.append((xy, text, kwargs))
                return original_text(draw, xy, text, *args, **kwargs)

            def record_ellipse(draw, xy, *args, **kwargs):
                ellipse_calls.append((xy, kwargs))
                return original_ellipse(draw, xy, *args, **kwargs)

            action = f"nodes_select_{index}"
            with patch.object(ImageDraw.ImageDraw, "text", new=record_text), \
                    patch.object(ImageDraw.ImageDraw, "ellipse", new=record_ellipse):
                pressed = render(
                    values[0],
                    ui_state=state,
                    pressed_action=action,
                    nodes=values,
                    now=now,
                )
            difference = ImageChops.difference(normal, pressed).getbbox()
            self.assertIsNotNone(difference)
            self.assertGreaterEqual(difference[0], row[0])
            self.assertGreaterEqual(difference[1], row[1])
            self.assertLessEqual(difference[2], row[2])
            self.assertLessEqual(difference[3], row[3])
            self.assertEqual(ImageColor.getrgb(MUTED), pressed.getpixel((4, row[1] + 4)))
            row_text = [
                kwargs["fill"]
                for xy, _, kwargs in text_calls
                if row[1] <= xy[1] < row[3]
            ]
            self.assertTrue(row_text and all(fill == BACKGROUND for fill in row_text))
            dot = next(call for call in ellipse_calls if call[0][1] == row[1] + 9)
            self.assertEqual(BACKGROUND, dot[1]["fill"])

        for action, hitbox in (
            ("nodes_previous_page", NODES_PREVIOUS_PAGE_HITBOX),
            ("nodes_back", NODES_BACK_HITBOX),
            ("nodes_next_page", NODES_NEXT_PAGE_HITBOX),
        ):
            pressed = render(
                values[0],
                ui_state=state,
                pressed_action=action,
                nodes=values,
                now=now,
            )
            difference = ImageChops.difference(normal, pressed).getbbox()
            self.assertIsNotNone(difference)
            self.assertGreaterEqual(difference[0], hitbox[0])
            self.assertGreaterEqual(difference[1], hitbox[1])
            self.assertLessEqual(difference[2], hitbox[2])
            self.assertLessEqual(difference[3], hitbox[3])

        one = (values[1],)
        one_state = UiState(screen=Screen.NODES, selected_node_id="node-a")
        one_normal = render(one[0], ui_state=one_state, nodes=one, now=now)
        for action in ("nodes_previous_page", "nodes_next_page"):
            self.assertEqual(
                one_normal.tobytes(),
                render(
                    one[0],
                    ui_state=one_state,
                    pressed_action=action,
                    nodes=one,
                    now=now,
                ).tobytes(),
            )

    def test_phase_6_nodes_and_changed_menu_hashes_are_exact(self) -> None:
        values = phase_6_nodes()
        one = (values[1],)
        mixed = values[:3]
        now = datetime(2026, 7, 12, 3, 0, 3, tzinfo=timezone.utc)
        scenarios = {
            "nodes_one_page_live": render(
                one[0], ui_state=UiState(screen=Screen.NODES, selected_node_id="node-a"),
                nodes=one, now=now,
            ),
            "nodes_two_pages_page_1": render(
                values[0], ui_state=UiState(screen=Screen.NODES, selected_node_id="node-a"),
                nodes=values, now=now,
            ),
            "nodes_two_pages_page_2": render(
                values[0], ui_state=UiState(screen=Screen.NODES, selected_node_id="node-d", nodes_page=1),
                nodes=values, now=now,
            ),
            "nodes_mixed_waiting_offline": render(
                mixed[0], ui_state=UiState(screen=Screen.NODES, selected_node_id="node-b"),
                nodes=mixed, now=now,
            ),
            "nodes_link_lost_stale": render(
                mixed[0], hub_online=False,
                ui_state=UiState(screen=Screen.NODES, selected_node_id="node-b"),
                nodes=mixed, now=now,
            ),
            "nodes_selected_row": render(
                values[0], ui_state=UiState(screen=Screen.NODES, selected_node_id="node-c"),
                nodes=values, now=now,
            ),
        }
        for index in range(3):
            scenarios[f"nodes_row_{index + 1}_pressed"] = render(
                values[0], ui_state=UiState(screen=Screen.NODES, selected_node_id="node-d"),
                pressed_action=f"nodes_select_{index}", nodes=values, now=now,
            )
        for name, action in (
            ("nodes_previous_pressed", "nodes_previous_page"),
            ("nodes_back_pressed", "nodes_back"),
            ("nodes_next_pressed", "nodes_next_page"),
        ):
            scenarios[name] = render(
                values[0], ui_state=UiState(screen=Screen.NODES, selected_node_id="node-a"),
                pressed_action=action, nodes=values, now=now,
            )
        self.assertEqual(set(NODES_RENDER_HASHES), set(scenarios))
        for name, image in scenarios.items():
            with self.subTest(name=name):
                self.assertEqual(
                    NODES_RENDER_HASHES[name],
                    hashlib.sha256(image.tobytes()).hexdigest(),
                )

    def test_phase_6_empty_nodes_snapshot_uses_overview_shell_and_footer(self) -> None:
        state = UiState(screen=Screen.NODES)
        self.assertEqual(
            render(None, ui_state=UiState()).tobytes(),
            render(None, ui_state=state, nodes=()).tobytes(),
        )

    def test_phase_8_power_geometry_and_action_boundaries_are_exact(self) -> None:
        self.assertEqual((0, 32, 320, 104), SYSTEM_RESTART_AREA)
        self.assertEqual((0, 112, 320, 184), SYSTEM_SHUTDOWN_AREA)
        self.assertEqual((64, 192, 256, 240), SYSTEM_BACK_HITBOX)
        self.assertEqual((8, 36, 312, 100), SYSTEM_RESTART_CARD_RECT)
        self.assertEqual((8, 116, 312, 180), SYSTEM_SHUTDOWN_CARD_RECT)
        self.assertEqual((72, 72), (
            SYSTEM_RESTART_AREA[3] - SYSTEM_RESTART_AREA[1],
            SYSTEM_SHUTDOWN_AREA[3] - SYSTEM_SHUTDOWN_AREA[1],
        ))
        self.assertEqual((64, 64), (
            SYSTEM_RESTART_CARD_RECT[3] - SYSTEM_RESTART_CARD_RECT[1],
            SYSTEM_SHUTDOWN_CARD_RECT[3] - SYSTEM_SHUTDOWN_CARD_RECT[1],
        ))
        self.assertEqual(8, SYSTEM_SHUTDOWN_AREA[1] - SYSTEM_RESTART_AREA[3])
        self.assertEqual((192, 48), (
            SYSTEM_BACK_HITBOX[2] - SYSTEM_BACK_HITBOX[0],
            SYSTEM_BACK_HITBOX[3] - SYSTEM_BACK_HITBOX[1],
        ))
        self.assertEqual("system_restart", system_action_at(0, 32))
        self.assertEqual("system_restart", system_action_at(319, 103))
        self.assertEqual("system_shutdown", system_action_at(0, 112))
        self.assertEqual("system_shutdown", system_action_at(319, 183))
        self.assertEqual("system_back", system_action_at(64, 192))
        for point in ((63, 210), (256, 210), (100, 191), (100, 240), (-1, 210), (320, 210)):
            self.assertIsNone(system_action_at(*point))

        self.assertEqual((0, 192, 112, 240), POWER_CANCEL_HITBOX)
        self.assertEqual((112, 192, 320, 240), POWER_HOLD_HITBOX)
        self.assertEqual((64, 192, 256, 240), POWER_ERROR_BACK_HITBOX)
        self.assertEqual((0, 192, 111, 239), POWER_CANCEL_CARD_RECT)
        self.assertEqual((112, 192, 319, 239), POWER_HOLD_CARD_RECT)
        self.assertEqual((124, 228, 308, 236), POWER_HOLD_PROGRESS_RECT)
        self.assertEqual((112, 48), (
            POWER_CANCEL_HITBOX[2] - POWER_CANCEL_HITBOX[0],
            POWER_CANCEL_HITBOX[3] - POWER_CANCEL_HITBOX[1],
        ))
        self.assertEqual((208, 48), (
            POWER_HOLD_HITBOX[2] - POWER_HOLD_HITBOX[0],
            POWER_HOLD_HITBOX[3] - POWER_HOLD_HITBOX[1],
        ))
        self.assertEqual(POWER_CANCEL_HITBOX[2], POWER_HOLD_HITBOX[0])
        self.assertLess(POWER_CANCEL_HITBOX[2] - POWER_CANCEL_HITBOX[0], POWER_HOLD_HITBOX[2] - POWER_HOLD_HITBOX[0])
        self.assertTrue(
            POWER_HOLD_HITBOX[0] <= POWER_HOLD_PROGRESS_RECT[0]
            < POWER_HOLD_PROGRESS_RECT[2] <= POWER_HOLD_HITBOX[2]
        )
        self.assertEqual(("power_cancel", "power_hold"), (
            power_confirm_action_at(0, 192), power_confirm_action_at(319, 239)
        ))
        self.assertEqual("power_error_back", power_error_action_at(64, 192))
        for resolver, points in (
            (power_confirm_action_at, ((-1, 210), (320, 210), (10, 191), (10, 240))),
            (power_error_action_at, ((63, 210), (256, 210), (160, 191), (160, 240))),
        ):
            for point in points:
                self.assertIsNone(resolver(*point))

    def test_phase_8_system_renderer_routing_identity_and_pressed_controls(self) -> None:
        state = UiState(screen=Screen.SYSTEM)
        for helper in (
            "_empty_state", "_header", "_footer", "_menu", "_menu_footer",
            "_nodes", "_nodes_footer", "_detail_header", "_values_detail", "_graph_footer",
        ):
            with self.subTest(helper=helper), patch(f"display.renderer.{helper}") as blocked:
                render(None, hub_online=False, ui_state=state, nodes=())
                blocked.assert_not_called()
        with patch("display.renderer._system") as system, patch(
            "display.renderer._system_footer"
        ) as footer:
            render(None, ui_state=state, local_target_name=" local pi ")
        self.assertEqual("local pi", system.call_args.args[2])
        footer.assert_called_once()

        first = node(node_id="selected-a", display_name="REMOTE A")
        second = node(node_id="selected-b", display_name="REMOTE B")
        frames = (
            render(first, ui_state=state, nodes=(first,), local_target_name="display-rpi"),
            render(second, ui_state=state, nodes=(second,), local_target_name="display-rpi"),
            render(None, ui_state=state, nodes=(), local_target_name="display-rpi"),
            render(None, hub_online=False, ui_state=state, nodes=(), local_target_name="display-rpi"),
        )
        self.assertTrue(all(frame.tobytes() == frames[0].tobytes() for frame in frames[1:]))
        default = render(None, ui_state=state)
        self.assertEqual(default.tobytes(), render(None, ui_state=state, local_target_name="  ").tobytes())
        changed = render(None, ui_state=state, local_target_name="display-rpi")
        difference = ImageChops.difference(default, changed).getbbox()
        self.assertIsNotNone(difference)
        self.assertGreaterEqual(difference[0], 120)
        self.assertLessEqual(difference[2], 320)
        self.assertLessEqual(difference[3], 32)
        for action, bounds in (
            ("system_restart", SYSTEM_RESTART_CARD_RECT),
            ("system_shutdown", SYSTEM_SHUTDOWN_CARD_RECT),
            ("system_back", SYSTEM_BACK_HITBOX),
        ):
            difference = ImageChops.difference(
                default,
                render(None, ui_state=state, pressed_action=action),
            ).getbbox()
            self.assertIsNotNone(difference)
            self.assertGreaterEqual(difference[0], bounds[0])
            self.assertGreaterEqual(difference[1], bounds[1])
            self.assertLessEqual(difference[2], bounds[2])
            self.assertLessEqual(difference[3], bounds[3])

        text_calls = []
        rectangle_calls = []
        arc_calls = []
        polygon_calls = []
        ellipse_calls = []
        line_calls = []
        originals = {
            name: getattr(ImageDraw.ImageDraw, name)
            for name in ("text", "rectangle", "arc", "polygon", "ellipse", "line")
        }

        def record(name):
            def recorder(draw, xy, *args, **kwargs):
                calls = {
                    "text": text_calls,
                    "rectangle": rectangle_calls,
                    "arc": arc_calls,
                    "polygon": polygon_calls,
                    "ellipse": ellipse_calls,
                    "line": line_calls,
                }[name]
                calls.append((xy, args, kwargs))
                return originals[name](draw, xy, *args, **kwargs)
            return recorder

        with patch.object(ImageDraw.ImageDraw, "text", new=record("text")), \
                patch.object(ImageDraw.ImageDraw, "rectangle", new=record("rectangle")), \
                patch.object(ImageDraw.ImageDraw, "arc", new=record("arc")), \
                patch.object(ImageDraw.ImageDraw, "polygon", new=record("polygon")), \
                patch.object(ImageDraw.ImageDraw, "ellipse", new=record("ellipse")), \
                patch.object(ImageDraw.ImageDraw, "line", new=record("line")):
            render(first, ui_state=state, local_target_name="display-rpi")
        drawn_text = {(xy, args[0], kwargs.get("fill"), kwargs.get("anchor")) for xy, args, kwargs in text_calls}
        self.assertIn(((10, 16), "SYSTEM", GREEN, "lm"), drawn_text)
        self.assertIn(((58, 56), "RESTART", AMBER, "lm"), drawn_text)
        self.assertIn(((58, 82), "TAP TO CONFIRM", AMBER, "lm"), drawn_text)
        self.assertIn(((58, 136), "SHUTDOWN", RED, "lm"), drawn_text)
        self.assertIn(((58, 162), "TAP TO CONFIRM", RED, "lm"), drawn_text)
        self.assertNotIn("REMOTE A", {args[0] for _, args, _ in text_calls})
        self.assertIn((SYSTEM_RESTART_CARD_RECT, (), {"fill": BACKGROUND, "outline": AMBER, "width": 2}), rectangle_calls)
        self.assertIn((SYSTEM_SHUTDOWN_CARD_RECT, (), {"fill": BACKGROUND, "outline": RED, "width": 2}), rectangle_calls)
        self.assertIn(((22, 50, 46, 74), (35, 330), {"fill": AMBER, "width": 2}), arc_calls)
        self.assertIn((((41, 49), (48, 50), (45, 57)), (), {"fill": AMBER}), polygon_calls)
        self.assertIn(((22, 130, 46, 154), (), {"outline": RED, "width": 2}), ellipse_calls)
        self.assertIn(((34, 127, 34, 141), (), {"fill": RED, "width": 3}), line_calls)
        self.assertIn(((0, 192, 319, 192), (), {"fill": MUTED}), line_calls)

        pressed = render(None, ui_state=state, pressed_action="system_back")
        difference = ImageChops.difference(default, pressed).getbbox()
        self.assertIsNotNone(difference)
        self.assertGreaterEqual(difference[0], SYSTEM_BACK_HITBOX[0])
        self.assertGreaterEqual(difference[1], SYSTEM_BACK_HITBOX[1])
        self.assertLessEqual(difference[2], SYSTEM_BACK_HITBOX[2])
        self.assertLessEqual(difference[3], SYSTEM_BACK_HITBOX[3])
        self.assertEqual(ImageColor.getrgb(MUTED), pressed.getpixel((65, 193)))

    def test_phase_8_system_hashes_are_exact(self) -> None:
        state = UiState(screen=Screen.SYSTEM)
        scenarios = {
            "system_default": render(None, ui_state=state),
            "system_restart_pressed": render(None, ui_state=state, pressed_action="system_restart"),
            "system_shutdown_pressed": render(None, ui_state=state, pressed_action="system_shutdown"),
            "system_back_pressed": render(None, ui_state=state, pressed_action="system_back"),
            "system_no_nodes": render(None, ui_state=state, nodes=()),
            "system_hub_offline": render(None, hub_online=False, ui_state=state, nodes=()),
        }
        self.assertEqual(set(SYSTEM_RENDER_HASHES), set(scenarios))
        for name, image in scenarios.items():
            self.assertEqual(
                SYSTEM_RENDER_HASHES[name],
                hashlib.sha256(image.tobytes()).hexdigest(),
            )
        self.assertEqual(
            scenarios["system_default"].tobytes(),
            scenarios["system_no_nodes"].tobytes(),
        )
        self.assertEqual(
            scenarios["system_default"].tobytes(),
            scenarios["system_hub_offline"].tobytes(),
        )

    def test_phase_9_disabled_system_is_muted_and_has_no_power_feedback(self) -> None:
        state = UiState(screen=Screen.SYSTEM)
        disabled = render(None, ui_state=state, power_actions_enabled=False)
        self.assertEqual(
            SYSTEM_POWER_DISABLED_HASH,
            hashlib.sha256(disabled.tobytes()).hexdigest(),
        )
        for action in ("system_restart", "system_shutdown"):
            self.assertEqual(
                disabled.tobytes(),
                render(
                    None,
                    ui_state=state,
                    pressed_action=action,
                    power_actions_enabled=False,
                ).tobytes(),
            )
        self.assertNotEqual(
            disabled.tobytes(),
            render(
                None,
                ui_state=state,
                pressed_action="system_back",
                power_actions_enabled=False,
            ).tobytes(),
        )
        calls = []
        original = ImageDraw.ImageDraw.text

        def record(draw, xy, text, *args, **kwargs):
            calls.append((text, kwargs.get("fill")))
            return original(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record):
            render(None, ui_state=state, power_actions_enabled=False)
        self.assertEqual(2, sum(text == "DISABLED BY CONFIG" for text, _ in calls))
        self.assertTrue(
            all(fill == MUTED for text, fill in calls if text == "DISABLED BY CONFIG")
        )

    def test_phase_8_confirmation_pending_routing_progress_and_target_isolation(self) -> None:
        value_a = node(node_id="a", display_name="REMOTE A")
        value_b = node(node_id="b", display_name="REMOTE B")
        confirm = UiState(screen=Screen.POWER_CONFIRM, pending_power_action=PowerAction.REBOOT)
        pending = UiState(
            screen=Screen.POWER_PENDING,
            pending_power_action=PowerAction.REBOOT,
            power_request_status=PowerRequestStatus.SENDING,
        )
        blocked_helpers = (
            "_empty_state", "_header", "_footer", "_menu", "_nodes",
            "_detail_header", "_values_detail", "_graph_footer",
        )
        for state in (confirm, pending):
            for helper in blocked_helpers:
                with self.subTest(screen=state.screen, helper=helper), patch(
                    f"display.renderer.{helper}"
                ) as blocked:
                    render(None, hub_online=False, ui_state=state, nodes=())
                    blocked.assert_not_called()

        frames = (
            render(value_a, ui_state=confirm, nodes=(value_a,), local_target_name="display-rpi"),
            render(value_b, ui_state=confirm, nodes=(value_b,), local_target_name="display-rpi"),
            render(None, ui_state=confirm, nodes=(), local_target_name="display-rpi"),
            render(None, hub_online=False, ui_state=confirm, nodes=(), local_target_name="display-rpi"),
        )
        self.assertTrue(all(frame.tobytes() == frames[0].tobytes() for frame in frames[1:]))

        for action, bounds in (
            ("power_cancel", POWER_CANCEL_CARD_RECT),
            ("power_hold", POWER_HOLD_CARD_RECT),
        ):
            difference = ImageChops.difference(
                frames[0],
                render(None, ui_state=confirm, pressed_action=action, local_target_name="display-rpi"),
            ).getbbox()
            self.assertIsNotNone(difference)
            self.assertGreaterEqual(difference[0], bounds[0])
            self.assertGreaterEqual(difference[1], bounds[1])
            self.assertLessEqual(difference[2], bounds[2] + 1)
            self.assertLessEqual(difference[3], bounds[3] + 1)

        original_rectangle = ImageDraw.ImageDraw.rectangle
        for progress, now in ((0, 10), (0.25, 10.375), (0.5, 10.75), (0.75, 11.125), (0.99, 11.485), (1, 11.5)):
            calls = []

            def record(draw, xy, *args, **kwargs):
                calls.append((xy, kwargs))
                return original_rectangle(draw, xy, *args, **kwargs)

            active = UiState(
                screen=Screen.POWER_CONFIRM,
                pending_power_action=PowerAction.REBOOT,
                confirmation_started_at=10,
            )
            with patch.object(ImageDraw.ImageDraw, "rectangle", new=record):
                render(
                    None,
                    ui_state=active,
                    interaction_now=now,
                    power_confirm_hold_seconds=1.5,
                )
            fills = [xy for xy, kwargs in calls if kwargs.get("fill") == AMBER]
            if progress == 0:
                self.assertEqual([], fills)
            else:
                self.assertEqual(1, len(fills))
                left, top, right, bottom = fills[0]
                self.assertEqual((125, 229, 235), (left, top, bottom))
                self.assertEqual(125 + round(182 * progress), right)
                self.assertLessEqual(right, 307)

        text_calls = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            text_calls.append((xy, text, kwargs))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            render(None, ui_state=pending, local_target_name="display-rpi")
        rendered = {text for _, text, _ in text_calls}
        for required in (
            "SENDING REQUEST",
            "WAITING FOR LOCAL HELPER",
            "PENDING FRAME DISPLAYED FIRST",
        ):
            self.assertIn(required, rendered)
        self.assertNotIn("REMOTE A", rendered)
        self.assertNotIn("BACK", rendered)

        normal_pending = render(None, ui_state=pending)
        pressed_pending = render(None, ui_state=pending, pressed_action="power_pending_back")
        self.assertEqual(normal_pending.tobytes(), pressed_pending.tobytes())

    def test_phase_8_confirmation_and_pending_hashes_are_exact(self) -> None:
        reboot = UiState(screen=Screen.POWER_CONFIRM, pending_power_action=PowerAction.REBOOT)
        shutdown = UiState(screen=Screen.POWER_CONFIRM, pending_power_action=PowerAction.POWEROFF)
        active = UiState(
            screen=Screen.POWER_CONFIRM,
            pending_power_action=PowerAction.REBOOT,
            confirmation_started_at=10,
        )
        value = complete_v2_node()
        confirmation = {
            "confirm_reboot_idle": render(None, ui_state=reboot, local_target_name="display-rpi"),
            "confirm_shutdown_idle": render(None, ui_state=shutdown, local_target_name="display-rpi"),
            "confirm_reboot_cancel_pressed": render(None, ui_state=reboot, pressed_action="power_cancel", local_target_name="display-rpi"),
            "confirm_shutdown_cancel_pressed": render(None, ui_state=shutdown, pressed_action="power_cancel", local_target_name="display-rpi"),
            "confirm_reboot_hold_started": render(None, ui_state=active, pressed_action="power_hold", interaction_now=10, local_target_name="display-rpi"),
            "confirm_shutdown_hold_started": render(None, ui_state=replace(active, pending_power_action=PowerAction.POWEROFF), pressed_action="power_hold", interaction_now=10, local_target_name="display-rpi"),
            "confirm_reboot_progress_25": render(None, ui_state=active, interaction_now=10.375, local_target_name="display-rpi"),
            "confirm_reboot_progress_50": render(None, ui_state=active, interaction_now=10.75, local_target_name="display-rpi"),
            "confirm_reboot_progress_75": render(None, ui_state=active, interaction_now=11.125, local_target_name="display-rpi"),
            "confirm_reboot_progress_99": render(None, ui_state=active, interaction_now=11.485, local_target_name="display-rpi"),
            "confirm_missing_action": render(None, ui_state=UiState(screen=Screen.POWER_CONFIRM), local_target_name="display-rpi"),
            "confirm_no_nodes": render(None, ui_state=reboot, nodes=(), local_target_name="display-rpi"),
            "confirm_hub_offline": render(None, hub_online=False, ui_state=reboot, nodes=(), local_target_name="display-rpi"),
        }
        self.assertEqual(set(CONFIRMATION_RENDER_HASHES), set(confirmation))
        for name, image in confirmation.items():
            self.assertEqual(CONFIRMATION_RENDER_HASHES[name], hashlib.sha256(image.tobytes()).hexdigest())
        self.assertEqual(
            confirmation["confirm_reboot_idle"].tobytes(),
            confirmation["confirm_no_nodes"].tobytes(),
        )
        self.assertEqual(
            confirmation["confirm_reboot_idle"].tobytes(),
            confirmation["confirm_hub_offline"].tobytes(),
        )

        pending = {
            "pending_reboot_sending": render(None, ui_state=UiState(screen=Screen.POWER_PENDING, pending_power_action=PowerAction.REBOOT, power_request_status=PowerRequestStatus.SENDING), local_target_name="display-rpi"),
            "pending_shutdown_sending": render(None, ui_state=UiState(screen=Screen.POWER_PENDING, pending_power_action=PowerAction.POWEROFF, power_request_status=PowerRequestStatus.SENDING), local_target_name="display-rpi"),
            "pending_reboot_accepted": render(None, ui_state=UiState(screen=Screen.POWER_PENDING, pending_power_action=PowerAction.REBOOT, power_request_status=PowerRequestStatus.ACCEPTED), local_target_name="display-rpi"),
            "pending_shutdown_accepted": render(None, ui_state=UiState(screen=Screen.POWER_PENDING, pending_power_action=PowerAction.POWEROFF, power_request_status=PowerRequestStatus.ACCEPTED), local_target_name="display-rpi"),
            "pending_missing_status": render(None, ui_state=UiState(screen=Screen.POWER_PENDING), local_target_name="display-rpi"),
        }
        self.assertEqual(set(PENDING_RENDER_HASHES), set(pending))
        for name, image in pending.items():
            self.assertEqual(PENDING_RENDER_HASHES[name], hashlib.sha256(image.tobytes()).hexdigest())

        errors = {
            "error_reboot_helper_unavailable": render(None, ui_state=UiState(screen=Screen.POWER_ERROR, pending_power_action=PowerAction.REBOOT, power_request_error=PowerRequestError.HELPER_UNAVAILABLE), local_target_name="display-rpi"),
            "error_shutdown_permission_denied": render(None, ui_state=UiState(screen=Screen.POWER_ERROR, pending_power_action=PowerAction.POWEROFF, power_request_error=PowerRequestError.PERMISSION_DENIED), local_target_name="display-rpi"),
            "error_reboot_timeout": render(None, ui_state=UiState(screen=Screen.POWER_ERROR, pending_power_action=PowerAction.REBOOT, power_request_error=PowerRequestError.TIMEOUT), local_target_name="display-rpi"),
            "error_shutdown_protocol": render(None, ui_state=UiState(screen=Screen.POWER_ERROR, pending_power_action=PowerAction.POWEROFF, power_request_error=PowerRequestError.PROTOCOL_ERROR), local_target_name="display-rpi"),
            "error_reboot_io": render(None, ui_state=UiState(screen=Screen.POWER_ERROR, pending_power_action=PowerAction.REBOOT, power_request_error=PowerRequestError.IO_ERROR), local_target_name="display-rpi"),
            "error_missing_code": render(None, ui_state=UiState(screen=Screen.POWER_ERROR), local_target_name="display-rpi"),
            "error_back_pressed": render(None, ui_state=UiState(screen=Screen.POWER_ERROR, pending_power_action=PowerAction.REBOOT, power_request_error=PowerRequestError.IO_ERROR), pressed_action="power_error_back", local_target_name="display-rpi"),
        }
        self.assertEqual(set(POWER_ERROR_RENDER_HASHES), set(errors))
        for name, image in errors.items():
            self.assertEqual(
                POWER_ERROR_RENDER_HASHES[name],
                hashlib.sha256(image.tobytes()).hexdigest(),
            )

    def test_phase_9_error_wording_mapping_and_target_isolation(self) -> None:
        expected = {
            PowerRequestError.HELPER_UNAVAILABLE: "HELPER UNAVAILABLE",
            PowerRequestError.PERMISSION_DENIED: "PERMISSION DENIED",
            PowerRequestError.TIMEOUT: "REQUEST TIMED OUT",
            PowerRequestError.PROTOCOL_ERROR: "INVALID HELPER RESPONSE",
            PowerRequestError.IO_ERROR: "LOCAL I/O ERROR",
            None: "UNKNOWN LOCAL ERROR",
        }
        original = ImageDraw.ImageDraw.text
        for error, label in expected.items():
            calls = []

            def record(draw, xy, text, *args, **kwargs):
                calls.append(text)
                return original(draw, xy, text, *args, **kwargs)

            with self.subTest(error=error), patch.object(
                ImageDraw.ImageDraw,
                "text",
                new=record,
            ):
                render(
                    node(display_name="REMOTE SECRET"),
                    ui_state=UiState(
                        screen=Screen.POWER_ERROR,
                        pending_power_action=PowerAction.REBOOT,
                        power_request_error=error,
                    ),
                    local_target_name="display-rpi",
                )
            self.assertIn(label, calls)
            self.assertIn("NO ACCEPTANCE RECEIVED", calls)
            self.assertIn("CHECK LOCAL POWER HELPER", calls)
            self.assertIn("BACK", calls)
            self.assertNotIn("NO COMMAND WAS SENT", calls)
            self.assertNotIn("REMOTE SECRET", calls)

    def test_phase_9_application_integrates_power_effect_dispatch(self) -> None:
        app_source = Path("display/app.py").read_text()
        self.assertIn('config.get("local_node_id")', app_source)
        self.assertIn('or "LOCAL DISPLAY"', app_source)
        self.assertIn("local_target_name=local_target_name", app_source)
        self.assertIn("local_target_name,", app_source)
        self.assertEqual(1, app_source.count('config.get(\n            "power_confirm_hold_seconds"'))
        self.assertIn("power_confirm_hold_seconds must be positive", app_source)
        self.assertIn("PowerHoldStarted(now)", app_source)
        self.assertIn("PowerHoldTick(now)", app_source)
        self.assertIn("PowerHoldCancelled(now)", app_source)
        self.assertIn("PowerHoldReleased(now)", app_source)
        self.assertIn("recognizer.consume_current_press()", app_source)
        self.assertIn("gesture = None", app_source)
        self.assertIn("interaction_now=now", app_source)
        self.assertIn("power_confirm_hold_seconds=power_confirm_hold_seconds", app_source)
        self.assertIn("power_hold_progress(", app_source)
        display_source = "\n".join(
            path.read_text() for path in Path("display").glob("*.py")
        )
        self.assertIn("request_power_action(", app_source)
        self.assertIn("PowerRequestAccepted", app_source)
        self.assertIn("PowerRequestFailed", app_source)
        self.assertIn("power_actions_enabled must be a boolean", app_source)
        for forbidden in ("subprocess", "os.system", "systemctl", "AF_UNIX"):
            self.assertNotIn(forbidden, display_source)
        hub_source = Path("hub/app.py").read_text()
        self.assertNotIn('"/api/v1/power', hub_source)
        self.assertNotIn('"/power', hub_source)

    def _assert_phase_9_application_full_refreshes_result(
        self,
        result: PowerClientResult,
    ) -> None:
        calls = []
        result_events = []

        class FakeLcd:
            last_timing_ms = (0, 0)

            def __init__(self, speed):
                pass

            def initialize(self):
                pass

            def show(self, image):
                calls.append(("show", image.getpixel((0, 0))))

            def show_region(self, image, box):
                calls.append(("show_region", image.getpixel((0, 0))))

            def close(self):
                pass

        class FakeTouch:
            pressed = False

            def __init__(self, speed):
                pass

            def close(self):
                pass

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def get(self, url):
                raise KeyError(url)

        def fake_render(*args, **kwargs):
            state = args[3] if len(args) > 3 else kwargs.get("ui_state")
            if (
                state is not None
                and state.screen == Screen.POWER_PENDING
                and state.power_request_status == PowerRequestStatus.SENDING
            ):
                label, color = "pending", "white"
            elif (
                state is not None
                and state.screen == Screen.POWER_PENDING
                and state.power_request_status == PowerRequestStatus.ACCEPTED
            ):
                label, color = "accepted", "green"
            elif state is not None and state.screen == Screen.POWER_ERROR:
                label, color = "error", "red"
            else:
                label, color = "other", "black"
            calls.append(("render", label))
            return Image.new("RGB", (320, 240), color)

        def fake_reduce(state, event, context):
            if isinstance(event, DataRefreshed):
                return UiTransition(
                    replace(
                        state,
                        screen=Screen.POWER_PENDING,
                        pending_power_action=PowerAction.REBOOT,
                        power_request_status=PowerRequestStatus.SENDING,
                    ),
                    changed=True,
                    full_refresh=True,
                    effect=UiEffect.REQUEST_POWER,
                )
            if isinstance(event, PowerRequestAccepted):
                result_events.append(event)
                return UiTransition(
                    replace(
                        state,
                        power_request_status=PowerRequestStatus.ACCEPTED,
                    ),
                    changed=True,
                    full_refresh=True,
                )
            if isinstance(event, PowerRequestFailed):
                result_events.append(event)
                return UiTransition(
                    replace(
                        state,
                        screen=Screen.POWER_ERROR,
                        power_request_status=None,
                        power_request_error=event.error,
                    ),
                    changed=True,
                    full_refresh=True,
                )
            return UiTransition(state)

        async def fake_request(socket_path, action):
            calls.append(("request", action))
            return result

        config = {
            "calibration_file": "ignored.json",
            "power_actions_enabled": True,
            "state_url": "http://unused",
        }
        calibration = json.dumps({
            "raw_x_min": 0,
            "raw_x_max": 1,
            "raw_y_min": 0,
            "raw_y_max": 1,
        })
        with patch("display.app.ILI9341", FakeLcd), patch(
            "display.app.XPT2046", FakeTouch
        ), patch("display.app.render", side_effect=fake_render), patch(
            "display.app.reduce_ui", side_effect=fake_reduce
        ), patch(
            "display.app.request_power_action", side_effect=fake_request
        ) as request, patch(
            "display.app.aiohttp.ClientSession", return_value=FakeSession()
        ), patch(
            "display.app.Path.read_text", return_value=calibration
        ), patch(
            "display.app.asyncio.sleep",
            new=AsyncMock(side_effect=(None, StopAsyncIteration)),
        ):
            with self.assertRaises(StopAsyncIteration):
                asyncio.run(run_display(config))

        pending_render = calls.index(("render", "pending"))
        pending_show = calls.index(("show", (255, 255, 255)))
        request_call = calls.index(("request", PowerAction.REBOOT))
        result_label = "accepted" if result.accepted else "error"
        result_color = (0, 128, 0) if result.accepted else (255, 0, 0)
        result_render = calls.index(("render", result_label))
        result_show = calls.index(("show", result_color))
        self.assertLess(pending_render, pending_show)
        self.assertLess(pending_show, request_call)
        self.assertLess(request_call, result_render)
        self.assertLess(result_render, result_show)
        self.assertNotIn(("show_region", result_color), calls)
        request.assert_awaited_once()
        self.assertEqual(1, len(result_events))

    def test_phase_9_application_full_refreshes_accepted_result(self) -> None:
        self._assert_phase_9_application_full_refreshes_result(
            PowerClientResult(accepted=True)
        )

    def test_phase_9_application_full_refreshes_failed_result(self) -> None:
        self._assert_phase_9_application_full_refreshes_result(
            PowerClientResult(False, PowerRequestError.TIMEOUT)
        )

    def test_phase_9_application_does_not_request_when_pending_show_fails(self) -> None:
        class FailingLcd:
            last_timing_ms = (0, 0)

            def __init__(self, speed):
                self.show_count = 0

            def initialize(self):
                pass

            def show(self, image):
                self.show_count += 1
                if self.show_count == 2:
                    raise RuntimeError("display failed")

            def show_region(self, image, box):
                raise AssertionError("full pending frame required")

            def close(self):
                pass

        class FakeTouch:
            pressed = False

            def __init__(self, speed):
                pass

            def close(self):
                pass

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def get(self, url):
                raise KeyError(url)

        def fake_reduce(state, event, context):
            if isinstance(event, DataRefreshed):
                return UiTransition(
                    replace(
                        state,
                        screen=Screen.POWER_PENDING,
                        pending_power_action=PowerAction.REBOOT,
                        power_request_status=PowerRequestStatus.SENDING,
                    ),
                    changed=True,
                    full_refresh=True,
                    effect=UiEffect.REQUEST_POWER,
                )
            return UiTransition(state)

        def fake_render(*args, **kwargs):
            state = args[3] if len(args) > 3 else kwargs.get("ui_state")
            color = "white" if state and state.screen == Screen.POWER_PENDING else "black"
            return Image.new("RGB", (320, 240), color)

        request = AsyncMock(return_value=PowerClientResult(accepted=True))
        calibration = json.dumps({
            "raw_x_min": 0,
            "raw_x_max": 1,
            "raw_y_min": 0,
            "raw_y_max": 1,
        })
        with patch("display.app.ILI9341", FailingLcd), patch(
            "display.app.XPT2046", FakeTouch
        ), patch("display.app.render", side_effect=fake_render), patch(
            "display.app.reduce_ui", side_effect=fake_reduce
        ), patch("display.app.request_power_action", new=request), patch(
            "display.app.aiohttp.ClientSession", return_value=FakeSession()
        ), patch("display.app.Path.read_text", return_value=calibration):
            with self.assertRaisesRegex(RuntimeError, "display failed"):
                asyncio.run(run_display({
                    "calibration_file": "ignored.json",
                    "power_actions_enabled": True,
                    "state_url": "http://unused",
                }))
        request.assert_not_awaited()

    def test_completed_fast_power_hold_consumes_release_at_every_hold_coordinate(self) -> None:
        for point in ((216, 210), (150, 210), (300, 210)):
            with self.subTest(point=point):
                recognizer = TouchRecognizer(
                    long_press_seconds=0.65,
                    minimum_short_press_seconds=0.05,
                )
                state = UiState(
                    screen=Screen.POWER_CONFIRM,
                    pending_power_action=PowerAction.REBOOT,
                )
                self.assertIsNone(recognizer.update(True, *point, 0.0))
                started = reduce_ui(
                    state,
                    PowerHoldStarted(0.0),
                    UiContext((), 0, 0, 15, 0, 0.2),
                )
                self.assertIsNone(recognizer.update(True, *point, 0.2))
                completed = reduce_ui(
                    started.state,
                    PowerHoldTick(0.2),
                    UiContext((), 0, 0, 15, 0, 0.2),
                )
                recognizer.consume_current_press()

                self.assertEqual(GestureState.WAIT_RELEASE, recognizer.state)
                self.assertIsNone(recognizer.update(False, now=0.21))
                self.assertEqual(
                    (Screen.POWER_PENDING, PowerAction.REBOOT, "power_confirmed"),
                    (
                        completed.state.screen,
                        completed.state.pending_power_action,
                        completed.completed_action,
                    ),
                )
                self.assertIs(UiEffect.REQUEST_POWER, completed.effect)
                self.assertIsNone(recognizer.update(True, *point, 0.22))
                self.assertEqual(GestureState.IDLE, recognizer.state)

    def test_phase_8_application_rejects_non_positive_hold_duration(self) -> None:
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError,
                "power_confirm_hold_seconds must be positive",
            ):
                asyncio.run(run_display({"power_confirm_hold_seconds": value}))
        with self.assertRaises(KeyError):
            asyncio.run(run_display({"power_confirm_hold_seconds": 0.1}))

    def test_phase_9_application_validates_power_configuration_before_hardware(self) -> None:
        for value in ("false", 0, 1, None, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError,
                "power_actions_enabled must be a boolean",
            ):
                asyncio.run(run_display({"power_actions_enabled": value}))
        for value in ("relative.sock", "/run/homelab-resource-monitor"):
            with self.subTest(socket=value), self.assertRaises(ValueError):
                asyncio.run(run_display({"power_socket": value}))
        with patch("display.app.validate_power_socket_path") as validate:
            validate.return_value = "/run/homelab-resource-monitor/power.sock"
            with self.assertRaises(KeyError):
                asyncio.run(run_display({}))
        validate.assert_called_once_with(
            "/run/homelab-resource-monitor/power.sock"
        )

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
        lcd._command = lambda value: calls.append((value, b""))
        lcd._data = lambda data: calls.append((-1, bytes(data)))
        lcd.show_region(Image.new("RGB", (320, 240)), (10, 20, 12, 22))
        self.assertEqual((0x2A, bytes.fromhex("000a000b")), calls[0])
        self.assertEqual((0x2B, bytes.fromhex("00140015")), calls[1])
        self.assertEqual(8, len(calls[-1][1]))
        self.assertGreaterEqual(lcd.last_timing_ms[0], 0)


if __name__ == "__main__":
    unittest.main()
