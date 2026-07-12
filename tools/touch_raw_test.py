import argparse
import json
import time
from pathlib import Path

from display.drivers.xpt2046 import XPT2046
from display.navigation import map_touch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed-hz", type=int, default=2_000_000)
    parser.add_argument("--calibration", type=Path)
    args = parser.parse_args()
    calibration = json.loads(args.calibration.read_text()) if args.calibration else None
    touch = XPT2046(args.speed_hz)
    print("Touch the panel; Ctrl-C stops.", flush=True)
    try:
        while True:
            if touch.pressed:
                x, y = touch.read()
                mapped = f" mapped={map_touch(x, y, calibration)}" if calibration else ""
                print(f"raw_x={x} raw_y={y}{mapped}", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        touch.close()


if __name__ == "__main__":
    main()
