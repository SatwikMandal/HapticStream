# HapticStream — Sprint 1: XInput controller

This milestone provides Windows XInput controller detection and vibration control. It does not capture or analyze game audio/video.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- An Xbox or XInput-compatible controller connected over USB or Bluetooth

The driver uses only Python's standard library. It loads the first available system XInput DLL from `xinput1_4.dll`, `xinput1_3.dll`, and `xinput9_1_0.dll`.

## Setup

From the project directory, create and activate a virtual environment, then install the local package:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

If PowerShell blocks activation, run the test directly as `\.venv\Scripts\python.exe -m hapticstream.demo` after installation.

## Hardware smoke test

1. Connect or pair the controller and close games or remapping tools that may interfere with it.
2. Run `python -m hapticstream.demo` (or `hapticstream-test`).
3. The script lists detected XInput indices, then pulses both motors for one second. Use `--index 0` to select a specific controller or `--duration 2` for a longer pulse.
4. Confirm both motors vibrate and stop when the script reports completion or exits.

Example: `python -m hapticstream.demo --index 0 --duration 1.5`

The driver checks all four XInput slots (0–3). Its context manager and process-exit cleanup send a zero-vibration command to every controller activated by that driver instance. Cleanup is best effort if a controller disconnects or Windows refuses the stop request.

## Using the driver

```python
from hapticstream import XInputDriver

with XInputDriver() as driver:
    controllers = driver.connected_controllers()
    if controllers:
        driver.set_vibration(controllers[0].index, left=0.4, right=0.8)
        # Call stop(index) when the effect ends.
```

Motor values are floats from `0.0` (off) to `1.0` (maximum). Controller indices follow XInput's 0–3 numbering and may change between connections.

## Current scope and next step

This milestone covers controller access and a manual hardware test only. Audio/video ingestion, game-event detection, AI inference, configuration UI, and haptic mapping are future work.
