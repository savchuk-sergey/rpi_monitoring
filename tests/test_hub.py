import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from hub.app import HubState, create_local_app, create_public_app, load_config


TOKEN = "a" * 43


def sample(node_id: str = "desktop", age: timedelta = timedelta()) -> dict:
    timestamp = datetime.now(timezone.utc) - age
    return {
        "schema_version": 1,
        "node_id": node_id,
        "display_name": "Desktop",
        "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "os": {"family": "windows", "version": "11"},
        "cpu": {
            "usage_percent": 10,
            "temperature_c": None,
            "power_w": None,
        },
        "memory": {"usage_percent": 20},
        "gpu": [],
        "collector": {"version": "0.1.0", "errors": []},
    }



class HubStatePersistenceTests(unittest.TestCase):
    def test_registry_waits_and_last_sample_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            hashes = {
                "desktop": hashlib.sha256(TOKEN.encode()).hexdigest(),
                "waiting": hashlib.sha256(("b" * 43).encode()).hexdigest(),
            }
            state = HubState(hashes, database_path=database)
            nodes = {node["node_id"]: node for node in state.current()["nodes"]}
            self.assertTrue(nodes["desktop"]["waiting"])
            self.assertTrue(nodes["waiting"]["waiting"])

            first = sample()
            first["display_name"] = "First"
            state.accept(first)
            second = sample()
            second["display_name"] = "Second"
            second["timestamp_utc"] = (
                datetime.fromisoformat(first["timestamp_utc"].replace("Z", "+00:00"))
                + timedelta(seconds=1)
            ).isoformat().replace("+00:00", "Z")
            state.accept(second)

            restored = HubState(hashes, offline_seconds=0, database_path=database)
            nodes = {node["node_id"]: node for node in restored.current()["nodes"]}
            self.assertEqual("First", nodes["desktop"]["display_name"])
            self.assertFalse(nodes["desktop"]["online"])
            self.assertNotIn("waiting", nodes["desktop"])

    def test_config_hot_reloads_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "hub.json"
            database = root / "state.sqlite3"
            config_path.write_text(
                json.dumps(
                    {
                        "state_database": str(database),
                        "token_sha256": {
                            "desktop": hashlib.sha256(TOKEN.encode()).hexdigest()
                        },
                    }
                )
            )
            state = load_config(config_path)
            self.assertTrue(state.authenticate("desktop", TOKEN))

            other_token = "b" * 43
            config_path.write_text(
                json.dumps(
                    {
                        "state_database": str(database),
                        "token_sha256": {
                            "other": hashlib.sha256(other_token.encode()).hexdigest()
                        },
                    }
                )
            )
            self.assertTrue(state.authenticate("other", other_token))
            self.assertFalse(state.authenticate("desktop", TOKEN))
            self.assertEqual(["other"], [node["node_id"] for node in state.current()["nodes"]])


def sample_v2() -> dict:
    value = sample()
    value["schema_version"] = 2
    value["cpu"]["clock_mhz"] = 4700
    value["memory"].update({
        "used_bytes": 24,
        "total_bytes": 32,
        "swap_used_bytes": 2,
        "swap_total_bytes": 8,
        "swap_usage_percent": 25,
        "pressure_some_percent": None,
    })
    value["health"] = {"uptime_seconds": 86400, "undervoltage": None, "throttled": None}
    value["storage"] = {
        "name": "C:\\", "usage_percent": 60, "used_bytes": 60, "total_bytes": 100,
        "read_bytes_per_second": 1, "write_bytes_per_second": 2, "temperature_c": None,
    }
    value["network"] = {
        "interface": "Ethernet", "link_up": True,
        "down_bytes_per_second": 3, "up_bytes_per_second": 4,
    }
    value["collector"]["version"] = "0.2.0"
    return value


class HubHttpTests(AioHTTPTestCase):
    async def get_application(self):
        token_hash = hashlib.sha256(TOKEN.encode()).hexdigest()
        self.state = HubState(
            {"desktop": token_hash, "other": hashlib.sha256(b"b" * 43).hexdigest()}
        )
        return create_public_app(self.state)

    async def post(self, body: dict, token: str = TOKEN):
        return await self.client.post(
            "/api/v1/telemetry",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def test_authentication_success_and_failure(self) -> None:
        response = await self.post(sample())
        self.assertEqual(200, response.status)
        response = await self.post(sample(), "wrong-token")
        self.assertEqual(403, response.status)
        response = await self.client.post("/api/v1/telemetry", json=sample())
        self.assertEqual(401, response.status)

    async def test_v2_uses_existing_ingest_endpoint(self) -> None:
        response = await self.post(sample_v2())
        self.assertEqual(200, response.status)
        self.assertEqual(2, self.state.current()["nodes"][0]["schema_version"])

    async def test_token_cannot_write_another_node(self) -> None:
        body = sample("other")
        response = await self.post(body)
        self.assertEqual(403, response.status)

    async def test_latest_replaces_current_and_older_is_ignored(self) -> None:
        newest = sample()
        self.assertEqual(200, (await self.post(newest)).status)
        older = copy.deepcopy(newest)
        older["timestamp_utc"] = (
            datetime.fromisoformat(newest["timestamp_utc"].replace("Z", "+00:00"))
            - timedelta(seconds=1)
        ).isoformat().replace("+00:00", "Z")
        older["memory"]["usage_percent"] = 99
        self.assertEqual(202, (await self.post(older)).status)
        self.assertEqual(20, self.state.samples["desktop"]["sample"]["memory"]["usage_percent"])

    async def test_offline_and_recovery(self) -> None:
        self.assertEqual(200, (await self.post(sample())).status)
        self.state.samples["desktop"]["received_at"] -= timedelta(seconds=11)
        self.assertFalse(self.state.current()["nodes"][0]["online"])
        self.assertEqual(200, (await self.post(sample())).status)
        self.assertTrue(self.state.current()["nodes"][0]["online"])

    async def test_too_old_timestamp_is_rejected(self) -> None:
        response = await self.post(sample(age=timedelta(minutes=6)))
        self.assertEqual(422, response.status)

    async def test_malformed_request_does_not_stop_server(self) -> None:
        response = await self.client.post(
            "/api/v1/telemetry",
            data="{",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        self.assertEqual(400, response.status)
        self.assertEqual(200, (await self.client.get("/healthz")).status)


class LocalStateHttpTests(AioHTTPTestCase):
    async def get_application(self):
        self.state = HubState({"desktop": hashlib.sha256(TOKEN.encode()).hexdigest()})
        self.state.accept(sample())
        return create_local_app(self.state)

    async def test_state_endpoint_returns_current_nodes_without_tokens(self) -> None:
        response = await self.client.get("/api/v1/state")
        self.assertEqual(200, response.status)
        body = await response.json()
        self.assertEqual("desktop", body["nodes"][0]["node_id"])
        self.assertNotIn("token", json.dumps(body).lower())


if __name__ == "__main__":
    unittest.main()
