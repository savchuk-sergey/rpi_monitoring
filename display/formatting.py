from typing import Any


def number(value: Any) -> str:
    number_value = float(value)
    return f"{number_value:.0f}" if number_value.is_integer() else f"{number_value:.1f}"


def percent(value: Any) -> str:
    return "—" if value is None else f"{float(value):.0f}%"


def temperature(value: Any, unsupported: bool = False) -> str:
    if value is None:
        return "N/A" if unsupported else "—"
    number_value = float(value)
    return f"{number_value:.0f}°C" if number_value.is_integer() else f"{number_value:.1f}°C"


def power(value: Any, unsupported: bool = False) -> str:
    if value is None:
        return "N/A" if unsupported else "—"
    number_value = float(value)
    return f"{number_value:.1f}W" if abs(number_value) < 10 else f"{number_value:.0f}W"


def clock(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) / 1000:.2f}G"


def bytes_pair(used: Any, total: Any, zero_is_off: bool = False) -> str:
    if used is None or total is None:
        return "N/A"
    if zero_is_off and not total:
        return "OFF"
    gib = 1024 ** 3
    return f"{float(used) / gib:.1f}/{float(total) / gib:.1f}GiB"


def boolean(value: Any) -> str:
    return "N/A" if value is None else "YES" if value else "NO"


def uptime(value: Any) -> str:
    if value is None:
        return "N/A"
    days, remainder = divmod(max(0, int(value)), 86400)
    return f"{days}d{remainder // 3600:02d}h"


def rate(value: Any) -> str:
    if value is None:
        return "N/A"
    number_value = float(value)
    for divisor, suffix in ((1024 ** 2, "M"), (1024, "K")):
        if number_value >= divisor:
            return f"{number_value / divisor:.1f}{suffix}/s"
    return f"{number_value:.0f}B/s"
