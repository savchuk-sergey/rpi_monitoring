import logging
import os
import socket
import struct
import subprocess
import sys

try:
    import grp
    import pwd
except ModuleNotFoundError:  # Linux-only modules; tests run on Windows too.
    grp = None
    pwd = None


DISPLAY_SERVICE_USER = "homelab-monitor-display"
DISPLAY_SERVICE_GROUP = "homelab-monitor-display"
MAX_REQUEST_BYTES = 9
READ_TIMEOUT_SECONDS = 1.0
COMMAND_TIMEOUT_SECONDS = 2.0
ACCEPTED_RESPONSE = b"accepted\n"
REJECTED_RESPONSE = b"rejected\n"

_ACTION_COMMANDS = {
    b"reboot\n": (
        "/usr/bin/systemctl",
        "--no-block",
        "reboot",
    ),
    b"poweroff\n": (
        "/usr/bin/systemctl",
        "--no-block",
        "poweroff",
    ),
}

LOG = logging.getLogger("homelab-resource-monitor-power")
AF_UNIX = getattr(socket, "AF_UNIX", -1)


def _validate_connection(connection: socket.socket) -> None:
    if connection.family != AF_UNIX or connection.type != socket.SOCK_STREAM:
        raise ValueError("standard input is not an AF_UNIX stream socket")


def _read_peer_credentials(connection: socket.socket) -> tuple[int, int, int]:
    peer_option = getattr(socket, "SO_PEERCRED", None)
    if peer_option is None:
        raise RuntimeError("SO_PEERCRED is unavailable")
    size = struct.calcsize("3i")
    credentials = connection.getsockopt(socket.SOL_SOCKET, peer_option, size)
    if len(credentials) != size:
        raise ValueError("malformed peer credentials")
    return struct.unpack("3i", credentials)


def _is_authorized_peer(
    uid: int,
    gid: int,
    *,
    user_lookup=None,
    group_lookup=None,
) -> bool:
    if user_lookup is None or group_lookup is None:
        if pwd is None or grp is None:
            raise RuntimeError("Linux account lookup is unavailable")
        user_lookup = getattr(pwd, "getpwnam", None)
        group_lookup = getattr(grp, "getgrnam", None)
        if user_lookup is None or group_lookup is None:
            raise RuntimeError("Linux account lookup is unavailable")
    display_uid = user_lookup(DISPLAY_SERVICE_USER).pw_uid
    display_gid = group_lookup(DISPLAY_SERVICE_GROUP).gr_gid
    return uid == 0 or (uid == display_uid and gid == display_gid)


def _read_request(connection: socket.socket) -> bytes:
    connection.settimeout(READ_TIMEOUT_SECONDS)
    buffer = bytearray()
    while True:
        chunk = connection.recv(MAX_REQUEST_BYTES + 1 - len(buffer))
        if not chunk:
            return bytes(buffer)
        buffer.extend(chunk)
        if len(buffer) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds limit")


def execute_action(
    payload: bytes,
    *,
    runner=subprocess.run,
) -> bool:
    command = _ACTION_COMMANDS.get(payload)
    if command is None:
        return False
    try:
        result = runner(
            command,
            shell=False,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def _log_result(uid: int, gid: int, action: str, result: str) -> None:
    LOG.info(
        "power_helper peer_uid=%s peer_gid=%s action=%s result=%s",
        uid,
        gid,
        action,
        result,
    )


def _reject(connection: socket.socket) -> None:
    try:
        connection.sendall(REJECTED_RESPONSE)
    except OSError:
        pass


def handle_connection(connection: socket.socket) -> int:
    uid = gid = -1
    action = "none"
    try:
        _validate_connection(connection)
        _, uid, gid = _read_peer_credentials(connection)
        if not _is_authorized_peer(uid, gid):
            _reject(connection)
            _log_result(uid, gid, action, "unauthorized")
            return 1
        try:
            payload = _read_request(connection)
        except (TimeoutError, socket.timeout):
            _reject(connection)
            _log_result(uid, gid, action, "timeout")
            return 1
        if payload not in _ACTION_COMMANDS:
            _reject(connection)
            _log_result(uid, gid, action, "rejected")
            return 1
        action = "reboot" if payload == b"reboot\n" else "poweroff"
        if not execute_action(payload):
            _reject(connection)
            _log_result(uid, gid, action, "command_failed")
            return 1
        connection.sendall(ACCEPTED_RESPONSE)
        _log_result(uid, gid, action, "accepted")
        return 0
    except (KeyError, LookupError, OSError, RuntimeError, ValueError, struct.error):
        _reject(connection)
        _log_result(uid, gid, action, "internal_error")
        return 2
    except Exception:
        _reject(connection)
        LOG.exception(
            "power_helper peer_uid=%s peer_gid=%s action=%s result=internal_error",
            uid,
            gid,
            action,
        )
        return 2
    finally:
        connection.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        connection = socket.socket(fileno=os.dup(0))
    except (OSError, ValueError):
        _log_result(-1, -1, "none", "internal_error")
        raise SystemExit(2)
    raise SystemExit(handle_connection(connection))


if __name__ == "__main__":
    main()
