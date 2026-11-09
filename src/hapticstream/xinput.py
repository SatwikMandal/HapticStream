"""Small, dependency-free XInput vibration driver for Windows."""

from __future__ import annotations

import atexit
import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

ERROR_DEVICE_NOT_CONNECTED = 1167
MAX_CONTROLLERS = 4


class XInputError(RuntimeError):
    """An XInput operation failed or the driver is unavailable."""


class _XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ("wLeftMotorSpeed", wintypes.WORD),
        ("wRightMotorSpeed", wintypes.WORD),
    ]


class _XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", _XINPUT_GAMEPAD),
    ]


@dataclass(frozen=True)
class Controller:
    """A connected XInput controller, identified by its zero-based index."""

    index: int
    packet_number: int


class XInputDriver:
    """Detect XInput controllers and control their left/right rumble motors."""

    DLL_CANDIDATES = (
        "xinput1_4.dll",
        "xinput1_3.dll",
        "xinput9_1_0.dll",
    )

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise XInputError("XInput vibration is available only on Windows.")

        self._dll = self._load_dll()
        self._get_state = self._dll.XInputGetState
        self._get_state.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(_XINPUT_STATE),
        ]
        self._get_state.restype = wintypes.DWORD

        self._set_state = self._dll.XInputSetState
        self._set_state.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(_XINPUT_VIBRATION),
        ]
        self._set_state.restype = wintypes.DWORD

        self._active: set[int] = set()
        self._closed = False
        atexit.register(self.close)

    @classmethod
    def _load_dll(cls):
        errors = []

        for name in cls.DLL_CANDIDATES:
            try:
                return ctypes.WinDLL(name)
            except OSError as exc:
                errors.append(f"{name}: {exc}")

        details = "; ".join(errors)
        raise XInputError(f"Could not load an XInput DLL. Tried {details}")

    def _ensure_open(self) -> None:
        if self._closed:
            raise XInputError("The XInput driver has already been closed.")

    def connected_controllers(self) -> list[Controller]:
        """Return connected controllers in XInput slots 0 through 3."""
        self._ensure_open()
        found = []

        for index in range(MAX_CONTROLLERS):
            state = _XINPUT_STATE()
            result = int(self._get_state(index, ctypes.byref(state)))

            if result == 0:
                found.append(
                    Controller(index, int(state.dwPacketNumber))
                )
            elif result != ERROR_DEVICE_NOT_CONNECTED:
                raise XInputError(
                    f"XInputGetState failed for controller {index} "
                    f"(code {result})."
                )

        return found

    @staticmethod
    def _motor_value(value: float, motor: str) -> int:
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{motor} motor intensity must be a number from 0.0 to 1.0."
            ) from exc

        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{motor} motor intensity must be from 0.0 to 1.0."
            )

        return round(value * 65535)

    def set_vibration(
        self,
        index: int,
        left: float,
        right: float,
    ) -> None:
        """Set motor intensity from 0.0 (off) to 1.0 (maximum)."""
        self._ensure_open()

        if not isinstance(index, int) or not 0 <= index < MAX_CONTROLLERS:
            raise ValueError("Controller index must be an integer from 0 to 3.")

        left_speed = self._motor_value(left, "Left")
        right_speed = self._motor_value(right, "Right")
        vibration = _XINPUT_VIBRATION(left_speed, right_speed)

        result = int(self._set_state(index, ctypes.byref(vibration)))

        if result == ERROR_DEVICE_NOT_CONNECTED:
            self._active.discard(index)
            raise XInputError(f"Controller {index} is not connected.")

        if result != 0:
            raise XInputError(
                f"XInputSetState failed for controller {index} "
                f"(code {result})."
            )

        if left_speed or right_speed:
            self._active.add(index)
        else:
            self._active.discard(index)

    def stop(self, index: int) -> None:
        """Stop both motors."""
        self.set_vibration(index, 0.0, 0.0)

    def close(self) -> None:
        """Best-effort stop for active controllers; safe to call repeatedly."""
        if self._closed:
            return

        for index in tuple(self._active):
            try:
                vibration = _XINPUT_VIBRATION(0, 0)
                self._set_state(index, ctypes.byref(vibration))
            except Exception:
                # Keep cleaning up other controllers if one stop fails.
                pass

        self._active.clear()
        self._closed = True

        try:
            atexit.unregister(self.close)
        except Exception:
            pass

    def __enter__(self) -> XInputDriver:
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()