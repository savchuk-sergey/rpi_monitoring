import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from aiohttp.test_utils import AioHTTPTestCase

from hub.app import HubState, create_local_app, create_public_app


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
