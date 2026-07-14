import socket
import struct
import subprocess
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

power_helper = import_module("display.power_helper")


class FakeConnection:
    def __init__(self, chunks=(), *, family=power_helper.AF_UNIX, type_=socket.SOCK_STREAM):
        self.family = family
        self.type = type_
        self.chunks = list(chunks)
        self.sent = []
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv(self, size):
        chunk = self.chunks.pop(0)
        return chunk[:size]

    def sendall(self, payload):
        self.sent.append(payload)

    def close(self):
        self.closed = True


class PowerHelperTests(unittest.TestCase):
    def test_standard_input_must_be_unix_stream(self) -> None:
        for family, type_ in (
            (socket.AF_INET, socket.SOCK_STREAM),
            (power_helper.AF_UNIX, socket.SOCK_DGRAM),
        ):
            with self.subTest(family=family, type=type_), self.assertRaises(ValueError):
                power_helper._validate_connection(FakeConnection(family=family, type_=type_))
        power_helper._validate_connection(FakeConnection())

    def test_peer_credentials_require_supported_exact_native_structure(self) -> None:
        connection = Mock()
        credentials = struct.pack("3i", 123, 456, 789)
        connection.getsockopt.return_value = credentials
        with patch.object(socket, "SO_PEERCRED", 17, create=True):
            self.assertEqual(
                (123, 456, 789),
                power_helper._read_peer_credentials(connection),
            )
        connection.getsockopt.return_value = credentials[:-1]
        with patch.object(socket, "SO_PEERCRED", 17, create=True), self.assertRaises(ValueError):
            power_helper._read_peer_credentials(connection)
        with patch.object(socket, "SO_PEERCRED", None, create=True), self.assertRaises(RuntimeError):
            power_helper._read_peer_credentials(connection)

    def test_peer_authorization_is_root_or_exact_display_identity(self) -> None:
        user = lambda name: SimpleNamespace(pw_uid=1001)
        group = lambda name: SimpleNamespace(gr_gid=1002)
        for uid, gid, accepted in (
            (0, 0, True),
            (1001, 1002, True),
            (1001, 9999, False),
            (9999, 1002, False),
            (9999, 9999, False),
        ):
            with self.subTest(uid=uid, gid=gid):
                self.assertEqual(
                    accepted,
                    power_helper._is_authorized_peer(
                        uid,
                        gid,
                        user_lookup=user,
                        group_lookup=group,
                    ),
                )
        for failing_lookup in (
            (Mock(side_effect=KeyError), group),
            (user, Mock(side_effect=KeyError)),
        ):
            with self.assertRaises(KeyError):
                power_helper._is_authorized_peer(
                    1001,
                    1002,
                    user_lookup=failing_lookup[0],
                    group_lookup=failing_lookup[1],
                )

    def test_request_reader_requires_eof_and_bounds_retained_bytes(self) -> None:
        for chunks, expected in (
            ([b"reboot\n", b""], b"reboot\n"),
            ([b"power", b"off\n", b""], b"poweroff\n"),
            ([b"",], b""),
            ([b"reboot", b""], b"reboot"),
            ([b"reboot\nX", b""], b"reboot\nX"),
            ([b"re\x00boot\n", b""], b"re\x00boot\n"),
        ):
            connection = FakeConnection(chunks)
            with self.subTest(chunks=chunks):
                self.assertEqual(expected, power_helper._read_request(connection))
                self.assertEqual(power_helper.READ_TIMEOUT_SECONDS, connection.timeout)
        with self.assertRaises(ValueError):
            power_helper._read_request(FakeConnection([b"0123456789"]))
        timeout = FakeConnection([])
        timeout.recv = Mock(side_effect=socket.timeout)
        with self.assertRaises(socket.timeout):
            power_helper._read_request(timeout)

    def test_only_exact_actions_reach_execution(self) -> None:
        invalid = (
            b"",
            b"reboot",
            b"reboot\nextra",
            b"reboot\n\n",
            b"reboot\x00\n",
            b"poweroff",
            b"power\n",
        )
        for payload in invalid:
            connection = FakeConnection()
            execute = Mock(return_value=True)
            with self.subTest(payload=payload), patch.multiple(
                power_helper,
                _read_peer_credentials=Mock(return_value=(1, 0, 0)),
                _is_authorized_peer=Mock(return_value=True),
                _read_request=Mock(return_value=payload),
                execute_action=execute,
            ):
                self.assertEqual(1, power_helper.handle_connection(connection))
                execute.assert_not_called()
            self.assertEqual([power_helper.REJECTED_RESPONSE], connection.sent)
            self.assertTrue(connection.closed)

    def test_fixed_commands_and_runner_contract(self) -> None:
        for payload, command in power_helper._ACTION_COMMANDS.items():
            runner = Mock(return_value=SimpleNamespace(returncode=0))
            with self.subTest(payload=payload):
                self.assertTrue(power_helper.execute_action(payload, runner=runner))
            runner.assert_called_once_with(
                command,
                shell=False,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=power_helper.COMMAND_TIMEOUT_SECONDS,
            )
            self.assertIsInstance(runner.call_args.args[0], tuple)
            self.assertNotIn("env", runner.call_args.kwargs)
        for outcome in (
            SimpleNamespace(returncode=1),
            subprocess.TimeoutExpired(("fixed",), 2),
            OSError("failed"),
        ):
            runner = Mock(
                return_value=outcome if isinstance(outcome, SimpleNamespace) else None,
                side_effect=None if isinstance(outcome, SimpleNamespace) else outcome,
            )
            self.assertFalse(
                power_helper.execute_action(b"reboot\n", runner=runner)
            )
            runner.assert_called_once()
        runner = Mock()
        self.assertFalse(power_helper.execute_action(b"invalid\n", runner=runner))
        runner.assert_not_called()

    def test_connection_responses_exit_codes_and_lifecycle(self) -> None:
        scenarios = (
            (False, b"reboot\n", True, 1, power_helper.REJECTED_RESPONSE),
            (True, b"reboot\n", True, 0, power_helper.ACCEPTED_RESPONSE),
            (True, b"poweroff\n", False, 1, power_helper.REJECTED_RESPONSE),
        )
        for authorized, payload, executed, exit_code, response in scenarios:
            connection = FakeConnection()
            execute = Mock(return_value=executed)
            with self.subTest(payload=payload, authorized=authorized), patch.multiple(
                power_helper,
                _read_peer_credentials=Mock(return_value=(1, 1001, 1002)),
                _is_authorized_peer=Mock(return_value=authorized),
                _read_request=Mock(return_value=payload),
                execute_action=execute,
            ):
                self.assertEqual(exit_code, power_helper.handle_connection(connection))
            self.assertEqual([response], connection.sent)
            self.assertTrue(connection.closed)
            self.assertEqual(authorized, bool(execute.call_count))

    def test_timeout_and_internal_failures_reject_without_exception_text(self) -> None:
        for failure, exit_code in ((socket.timeout(), 1), (RuntimeError("secret"), 2)):
            connection = FakeConnection()
            with self.subTest(failure=type(failure).__name__), patch.multiple(
                power_helper,
                _read_peer_credentials=Mock(return_value=(1, 1001, 1002)),
                _is_authorized_peer=Mock(return_value=True),
                _read_request=Mock(side_effect=failure),
            ):
                self.assertEqual(exit_code, power_helper.handle_connection(connection))
            self.assertEqual([power_helper.REJECTED_RESPONSE], connection.sent)
            self.assertNotIn(b"secret", b"".join(connection.sent))
            self.assertTrue(connection.closed)

    def test_helper_contains_no_server_loop_shell_or_retry(self) -> None:
        source = Path("display/power_helper.py").read_text()
        for forbidden in (
            ".bind(",
            ".listen(",
            ".accept(",
            "shell=True",
            "os.system",
            "sudo",
            "while connection",
        ):
            self.assertNotIn(forbidden, source)
        self.assertEqual(1, source.count("runner("))


if __name__ == "__main__":
    unittest.main()
