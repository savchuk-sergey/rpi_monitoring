import asyncio
from dataclasses import dataclass
from pathlib import PurePosixPath

from display.ui_state import PowerAction, PowerRequestError


DEFAULT_POWER_SOCKET = "/run/homelab-resource-monitor/power.sock"
POWER_SOCKET_ROOT = "/run/homelab-resource-monitor"
POWER_CLIENT_TIMEOUT_SECONDS = 1.0
POWER_RESPONSE_LIMIT_BYTES = 64

_ACTION_PAYLOADS = {
    PowerAction.REBOOT: b"reboot\n",
    PowerAction.POWEROFF: b"poweroff\n",
}


@dataclass(frozen=True)
class PowerClientResult:
    accepted: bool
    error: PowerRequestError | None = None

    def __post_init__(self) -> None:
        if self.accepted == (self.error is not None):
            raise ValueError("accepted results cannot have an error")


def validate_power_socket_path(value: object) -> str:
    raw = str(value).strip()
    if not raw or "\x00" in raw:
        raise ValueError("invalid power socket path")
    if any(part in {".", ".."} for part in raw.split("/")):
        raise ValueError("invalid power socket path")

    path = PurePosixPath(raw)
    root = PurePosixPath(POWER_SOCKET_ROOT)
    if not path.is_absolute() or path == root or not path.is_relative_to(root):
        raise ValueError("invalid power socket path")
    return str(path)


async def request_power_action(
    socket_path: str,
    action: PowerAction,
    *,
    timeout_seconds: float = POWER_CLIENT_TIMEOUT_SECONDS,
) -> PowerClientResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    validated_socket_path = validate_power_socket_path(socket_path)
    if action not in _ACTION_PAYLOADS:
        raise ValueError("unsupported power action")

    writer = None
    try:
        async with asyncio.timeout(timeout_seconds):
            try:
                reader, writer = await asyncio.open_unix_connection(
                    validated_socket_path,
                    limit=POWER_RESPONSE_LIMIT_BYTES,
                )
                writer.write(_ACTION_PAYLOADS[action])
                await writer.drain()
                try:
                    response = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    return PowerClientResult(
                        accepted=False,
                        error=PowerRequestError.PROTOCOL_ERROR,
                    )
                if response != b"accepted\n" or await reader.read(1) != b"":
                    return PowerClientResult(
                        accepted=False,
                        error=PowerRequestError.PROTOCOL_ERROR,
                    )
                return PowerClientResult(accepted=True)
            finally:
                if writer is not None:
                    writer.close()
                    wait_closed = getattr(writer, "wait_closed", None)
                    if wait_closed is not None:
                        await wait_closed()
    except (FileNotFoundError, ConnectionRefusedError):
        return PowerClientResult(
            accepted=False,
            error=PowerRequestError.HELPER_UNAVAILABLE,
        )
    except PermissionError:
        return PowerClientResult(
            accepted=False,
            error=PowerRequestError.PERMISSION_DENIED,
        )
    except TimeoutError:
        return PowerClientResult(
            accepted=False,
            error=PowerRequestError.TIMEOUT,
        )
    except OSError:
        return PowerClientResult(
            accepted=False,
            error=PowerRequestError.IO_ERROR,
        )
