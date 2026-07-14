import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from display.power_client import (
    DEFAULT_POWER_SOCKET,
    POWER_RESPONSE_LIMIT_BYTES,
    PowerClientResult,
    request_power_action,
    validate_power_socket_path,
)
from display.ui_state import PowerAction, PowerRequestError


class PowerClientTests(unittest.IsolatedAsyncioTestCase):
    def _stream(self, response=b"accepted\n", trailing=b""):
        reader = Mock()
        reader.readline = AsyncMock(return_value=response)
        reader.read = AsyncMock(return_value=trailing)
        writer = Mock()
        writer.can_write_eof.return_value = True
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        return reader, writer

    def test_path_validation_accepts_default_and_valid_child(self) -> None:
        self.assertEqual(DEFAULT_POWER_SOCKET, validate_power_socket_path(DEFAULT_POWER_SOCKET))
        self.assertEqual(
            "/run/homelab-resource-monitor/nested/power.sock",
            validate_power_socket_path(
                "  /run/homelab-resource-monitor/nested//power.sock  "
            ),
        )

    def test_path_validation_rejects_invalid_values(self) -> None:
        invalid = (
            "",
            "relative.sock",
            "/run/homelab-resource-monitor",
            "/run/other/power.sock",
            "/run/homelab-resource-monitor/./power.sock",
            "/run/homelab-resource-monitor/../power.sock",
            "/run/homelab-resource-monitor/power\x00.sock",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_power_socket_path(value)

    async def test_non_positive_timeout_is_rejected_without_connection(self) -> None:
        for timeout in (0, -1):
            with self.subTest(timeout=timeout), patch(
                "display.power_client.asyncio.open_unix_connection",
                new_callable=AsyncMock,
                create=True,
            ) as connect, self.assertRaises(ValueError):
                await request_power_action(
                    DEFAULT_POWER_SOCKET,
                    PowerAction.REBOOT,
                    timeout_seconds=timeout,
                )
            connect.assert_not_awaited()

    async def test_actions_write_exact_bounded_payloads(self) -> None:
        for action, payload in (
            (PowerAction.REBOOT, b"reboot\n"),
            (PowerAction.POWEROFF, b"poweroff\n"),
        ):
            reader, writer = self._stream()
            with self.subTest(action=action), patch(
                "display.power_client.asyncio.open_unix_connection",
                new=AsyncMock(return_value=(reader, writer)),
                create=True,
            ) as connect:
                result = await request_power_action(DEFAULT_POWER_SOCKET, action)
            self.assertTrue(result.accepted)
            writer.write.assert_called_once_with(payload)
            self.assertLessEqual(len(payload), 9)
            writer.drain.assert_awaited_once()
            connect.assert_awaited_once_with(
                DEFAULT_POWER_SOCKET,
                limit=POWER_RESPONSE_LIMIT_BYTES,
            )


    async def test_unsupported_half_close_returns_io_error_and_closes(self) -> None:
        reader, writer = self._stream()
        writer.can_write_eof.return_value = False
        connect = AsyncMock(return_value=(reader, writer))
        with patch(
            "display.power_client.asyncio.open_unix_connection",
            new=connect,
            create=True,
        ):
            result = await request_power_action(
                DEFAULT_POWER_SOCKET,
                PowerAction.REBOOT,
            )
        self.assertEqual(PowerRequestError.IO_ERROR, result.error)
        writer.drain.assert_awaited_once()
        writer.write_eof.assert_not_called()
        reader.readline.assert_not_awaited()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()
        connect.assert_awaited_once()

    async def test_request_is_drained_and_half_closed_before_response_read(self) -> None:
        reader, writer = self._stream()
        events = []
        writer.write.side_effect = lambda payload: events.append("write")

        async def drain():
            events.append("drain")

        def write_eof():
            events.append("write_eof")

        async def readline():
            events.append("readline")
            return b"accepted\n"

        async def read(size):
            events.append("read")
            return b""

        writer.drain.side_effect = drain
        writer.write_eof.side_effect = write_eof
        reader.readline.side_effect = readline
        reader.read.side_effect = read
        with patch(
            "display.power_client.asyncio.open_unix_connection",
            new=AsyncMock(return_value=(reader, writer)),
            create=True,
        ):
            result = await request_power_action(
                DEFAULT_POWER_SOCKET,
                PowerAction.POWEROFF,
            )
        self.assertTrue(result.accepted)
        self.assertEqual(
            ["write", "drain", "write_eof", "readline", "read"],
            events,
        )
        writer.can_write_eof.assert_called_once_with()
        writer.write_eof.assert_called_once_with()

    async def test_only_exact_accepted_response_succeeds(self) -> None:
        responses = (
            (b"accepted\n", True),
            (b"accepted\nextra", False),
            (b"accepted\n\n", False),
            (b"accepted\nrejected", False),
            (b"accepted\n\x00", False),
            (b"", False),
            (b"accepted", False),
            (b"ACCEPTED\n", False),
            (b" accepted\n", False),
            (b"accepted \n", False),
            (b"ok\n", False),
        )
        for raw_response, accepted in responses:
            line, separator, trailing = raw_response.partition(b"\n")
            response = line + separator
            reader, writer = self._stream(response, trailing[:1])
            with self.subTest(response=raw_response), patch(
                "display.power_client.asyncio.open_unix_connection",
                new=AsyncMock(return_value=(reader, writer)),
                create=True,
            ):
                result = await request_power_action(DEFAULT_POWER_SOCKET, PowerAction.REBOOT)
            self.assertEqual(accepted, result.accepted)
            self.assertEqual(
                None if accepted else PowerRequestError.PROTOCOL_ERROR,
                result.error,
            )
            writer.close.assert_called_once()
            writer.wait_closed.assert_awaited_once()

    async def test_accepted_without_eof_times_out_and_closes_writer(self) -> None:
        reader, writer = self._stream()

        async def wait_for_eof(size):
            await asyncio.sleep(1)

        reader.read.side_effect = wait_for_eof
        connect = AsyncMock(return_value=(reader, writer))
        with patch(
            "display.power_client.asyncio.open_unix_connection",
            new=connect,
            create=True,
        ):
            result = await request_power_action(
                DEFAULT_POWER_SOCKET,
                PowerAction.REBOOT,
                timeout_seconds=0.001,
            )
        self.assertEqual(PowerRequestError.TIMEOUT, result.error)
        connect.assert_awaited_once()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_oversized_response_is_protocol_error_and_writer_closes(self) -> None:
        reader, writer = self._stream()
        reader.readline.side_effect = ValueError("line exceeds limit")
        with patch(
            "display.power_client.asyncio.open_unix_connection",
            new=AsyncMock(return_value=(reader, writer)),
            create=True,
        ):
            result = await request_power_action(DEFAULT_POWER_SOCKET, PowerAction.POWEROFF)
        self.assertEqual(PowerRequestError.PROTOCOL_ERROR, result.error)
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_connection_failures_map_without_retry(self) -> None:
        mappings = (
            (FileNotFoundError(), PowerRequestError.HELPER_UNAVAILABLE),
            (ConnectionRefusedError(), PowerRequestError.HELPER_UNAVAILABLE),
            (PermissionError(), PowerRequestError.PERMISSION_DENIED),
            (OSError(), PowerRequestError.IO_ERROR),
        )
        for exception, error in mappings:
            connect = AsyncMock(side_effect=exception)
            with self.subTest(error=error), patch(
                "display.power_client.asyncio.open_unix_connection",
                new=connect,
                create=True,
            ):
                result = await request_power_action(DEFAULT_POWER_SOCKET, PowerAction.REBOOT)
            self.assertEqual(error, result.error)
            connect.assert_awaited_once()

    async def test_timeout_maps_and_does_not_retry(self) -> None:
        async def wait_forever(*args, **kwargs):
            await asyncio.sleep(1)

        with patch(
            "display.power_client.asyncio.open_unix_connection",
            new=AsyncMock(side_effect=wait_forever),
            create=True,
        ) as connect:
            result = await request_power_action(
                DEFAULT_POWER_SOCKET,
                PowerAction.REBOOT,
                timeout_seconds=0.001,
            )
        self.assertEqual(PowerRequestError.TIMEOUT, result.error)
        connect.assert_awaited_once()

    async def test_writer_closes_after_read_oserror(self) -> None:
        reader, writer = self._stream()
        reader.readline.side_effect = OSError("read failed")
        with patch(
            "display.power_client.asyncio.open_unix_connection",
            new=AsyncMock(return_value=(reader, writer)),
            create=True,
        ):
            result = await request_power_action(DEFAULT_POWER_SOCKET, PowerAction.REBOOT)
        self.assertEqual(PowerRequestError.IO_ERROR, result.error)
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_tcp_client_is_never_used(self) -> None:
        reader, writer = self._stream()
        with patch(
            "display.power_client.asyncio.open_unix_connection",
            new=AsyncMock(return_value=(reader, writer)),
            create=True,
        ), patch("asyncio.open_connection", new_callable=AsyncMock) as tcp:
            await request_power_action(DEFAULT_POWER_SOCKET, PowerAction.REBOOT)
        tcp.assert_not_awaited()

    def test_result_invariants(self) -> None:
        self.assertEqual(PowerClientResult(True), PowerClientResult(accepted=True))
        self.assertEqual(
            PowerRequestError.IO_ERROR,
            PowerClientResult(False, PowerRequestError.IO_ERROR).error,
        )
        for accepted, error in ((True, PowerRequestError.IO_ERROR), (False, None)):
            with self.subTest(accepted=accepted), self.assertRaises(ValueError):
                PowerClientResult(accepted, error)

    def test_module_contains_no_server_or_command_execution(self) -> None:
        source = Path("display/power_client.py").read_text()
        self.assertNotIn("start_unix_server", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("systemctl", source)
        self.assertEqual(1, source.count("asyncio.open_unix_connection"))


if __name__ == "__main__":
    unittest.main()
