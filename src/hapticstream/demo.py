"""Interactive terminal smoke test for an XInput controller."""

import argparse
import sys
import time

from .xinput import XInputDriver, XInputError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find a controller and test its rumble motors."
    )
    parser.add_argument(
        "--index",
        type=int,
        help="Controller index 0–3; defaults to the first detected.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="Rumble pulse duration in seconds (default: 1).",
    )
    args = parser.parse_args()

    if args.duration <= 0:
        parser.error("--duration must be greater than zero")

    try:
        with XInputDriver() as driver:
            controllers = driver.connected_controllers()

            if not controllers:
                print("No XInput controller detected. Connect one and try again.")
                return 1

            indices = [controller.index for controller in controllers]
            print(f"Connected controller indices: {indices}")

            index = args.index if args.index is not None else indices[0]

            if index not in indices:
                print(
                    f"Controller {index} is not connected.",
                    file=sys.stderr,
                )
                return 2

            print(f"Testing controller {index}...")
            driver.set_vibration(index, left=0.65, right=0.9)

            try:
                time.sleep(args.duration)
            finally:
                driver.stop(index)

            print("Test complete. The motors have stopped.")
            return 0

    except (XInputError, ValueError) as exc:
        print(f"HapticStream: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())