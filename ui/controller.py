"""
Phasm Controller Support
=================================
Reads gamepad input via evdev (preferred) or raw jsdev (/dev/input/js0).

All navigation signals are posted as synthetic QKeyEvent events to whatever
widget currently has keyboard focus — so all existing arrow-key logic works
automatically with the controller, no extra wiring needed.

Xbox controller mapping (Linux evdev):
  D-pad / Left stick  →  navigate
  A (BTN_SOUTH)       →  Enter (confirm/launch)
  B (BTN_EAST)        →  Escape (back)
  Y (BTN_NORTH)       →  F (favorite)
  X (BTN_WEST)        →  Context menu
  Menu/Start           →  quit confirmation
  LB (BTN_TL)         →  [ (tab left  / platform ←)
  RB (BTN_TR)         →  ] (tab right / platform →)
  View/Back           →  F11 (fullscreen toggle)
"""

import os
import struct
import select
import threading
import time

from PySide6.QtCore import QObject, QThread, Signal, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent


# ── Qt key injection ──────────────────────────────────────────────────────────

_key_dispatcher = None
_last_trigger_dispatch = {}
_last_axis_dispatch = {}
_TRIGGER_DEBOUNCE_SECONDS = 0.35
_AXIS_DEBOUNCE_SECONDS = 0.035


class _KeyDispatcher(QObject):
    """Moves controller key injection from the reader thread to Qt's GUI thread."""

    key_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.key_requested.connect(self._dispatch, Qt.QueuedConnection)

    def _dispatch(self, key_spec):
        key, modifier = key_spec
        _post_key_on_gui_thread(key, modifier)


def _post_key_on_gui_thread(key: Qt.Key, modifier: Qt.KeyboardModifier = Qt.NoModifier):
    """Synthesise a key press on whatever widget currently has focus.

    Falls back to the active window when focusWidget() is None — this happens
    when the OS hasn't granted the Qt window input focus yet (e.g. right after
    showing the home screen) or when focus is briefly between widgets.
    """
    ev = QKeyEvent(QEvent.Type.KeyPress, key, modifier)

    win = QApplication.activeWindow()
    if win is not None and hasattr(win, "_prepare_controller_input"):
        win._prepare_controller_input()

    # Popup menus must take precedence over the card that opened them. On
    # Wayland a QMenu can be the active popup without exposing itself as the
    # normal focus widget, which otherwise sends controller arrows back to the
    # card underneath the menu.
    target = QApplication.activePopupWidget() or QApplication.focusWidget()
    if target is None:
        # Try the active window's focus proxy, then the window itself
        if win:
            target = win.focusWidget() or win
    if target:
        QApplication.postEvent(target, ev)


def _post_key(key: Qt.Key, modifier: Qt.KeyboardModifier = Qt.NoModifier):
    """Queue a synthetic key event safely from any controller reader thread."""
    # LT/RT are analog inputs and can emit a second edge while the user is
    # still releasing the trigger. Coalesce those edges before they enter the
    # Qt event queue, where they would otherwise stack and skip a menu.
    if key in (Qt.Key_F6, Qt.Key_F7):
        now = time.monotonic()
        previous = _last_trigger_dispatch.get(key, 0.0)
        if now - previous < _TRIGGER_DEBOUNCE_SECONDS:
            return
        _last_trigger_dispatch[key] = now
    if _key_dispatcher is not None:
        _key_dispatcher.key_requested.emit((key, modifier))
    else:
        # Useful for direct/unit calls before the controller is started.
        _post_key_on_gui_thread(key, modifier)


def _post_axis_key(key_spec):
    # Many pads report the same physical direction through both the d-pad and
    # left stick.  Drop the duplicate edge before it reaches Qt; otherwise a
    # single controller nudge moves two cards and queues two expensive paints.
    key = key_spec[0] if isinstance(key_spec, tuple) else key_spec
    now = time.monotonic()
    if now - _last_axis_dispatch.get(key, 0.0) < _AXIS_DEBOUNCE_SECONDS:
        return
    _last_axis_dispatch[key] = now
    if isinstance(key_spec, tuple):
        _post_key(*key_spec)
    else:
        _post_key(key_spec)


# ── Analog stick config ───────────────────────────────────────────────────────

DEADZONE    = 12000   # out of 32767  (~37%)
FIRST_DELAY = 0.40    # seconds before first repeat
REPEAT_RATE = 0.14    # seconds between repeats


# ── evdev backend ─────────────────────────────────────────────────────────────

class _EvdevController(QThread):
    """Reads a gamepad via python-evdev and posts Qt key events."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            import evdev
            from evdev import ecodes
        except ImportError:
            return   # caller should never reach here without evdev

        # Find first device that has both buttons and absolute axes
        device = None
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
                caps = d.capabilities()
                if ecodes.EV_KEY in caps and ecodes.EV_ABS in caps:
                    device = d
                    break
            except Exception:
                continue

        if device is None:
            print("[CTRL] No gamepad found (evdev)")
            return

        print(f"[CTRL] Using: {device.name} ({device.path})")

        # Axis hold → repeat state
        # Maps axis_code → (direction, next_fire_time)
        axis_state: dict[int, tuple[int, float]] = {}

        BUTTON_MAP = {
            ecodes.BTN_SOUTH: (Qt.Key_Return,    Qt.NoModifier),
            ecodes.BTN_EAST:  (Qt.Key_Escape,    Qt.NoModifier),
            ecodes.BTN_NORTH: (Qt.Key_F,         Qt.NoModifier),        # favorite
            ecodes.BTN_WEST:  (Qt.Key_Menu,      Qt.NoModifier),        # context menu
            ecodes.BTN_START: (Qt.Key_Escape,    Qt.ControlModifier),  # menu → quit confirmation
            ecodes.BTN_TL:    (Qt.Key_BracketLeft, Qt.NoModifier),       # LB → collection/tab previous
            ecodes.BTN_TR:    (Qt.Key_BracketRight, Qt.NoModifier),      # RB → collection/tab next
            ecodes.BTN_SELECT:(Qt.Key_F11,        Qt.NoModifier),       # fullscreen
        }

        AXIS_DIR_MAP = {
            # code: {-1: key, +1: key}
            ecodes.ABS_HAT0X: {-1: Qt.Key_Left,  1: Qt.Key_Right},
            ecodes.ABS_HAT0Y: {-1: Qt.Key_Up,    1: Qt.Key_Down},
            ecodes.ABS_X:     {-1: Qt.Key_Left,  1: Qt.Key_Right},
            ecodes.ABS_Y:     {-1: Qt.Key_Up,    1: Qt.Key_Down},
            # Right stick is dedicated to scrolling; it never steals card focus.
            ecodes.ABS_RX:    {-1: (Qt.Key_Left, Qt.ShiftModifier), 1: (Qt.Key_Right, Qt.ShiftModifier)},
            ecodes.ABS_RY:    {-1: Qt.Key_PageUp, 1: Qt.Key_PageDown},
        }

        # LT/RT are analogue axes on many controllers.  Treat them as
        # edge-triggered navbar commands so holding a trigger does not cycle
        # through several entries.
        trigger_axes = {
            getattr(ecodes, "ABS_Z", -1): (Qt.Key_F6, Qt.ControlModifier),
            getattr(ecodes, "ABS_RZ", -2): (Qt.Key_F7, Qt.ControlModifier),
        }
        trigger_state = {}

        while not self._stop.is_set():
            try:
                r, _, _ = select.select([device.fd], [], [], 0.05)
            except Exception:
                break

            now = time.monotonic()

            # Fire repeats for held axes
            for code, (direction, fire_at) in list(axis_state.items()):
                if now >= fire_at:
                    key = AXIS_DIR_MAP.get(code, {}).get(direction)
                    if key:
                        _post_axis_key(key)
                    axis_state[code] = (direction, now + REPEAT_RATE)

            if not r:
                continue

            try:
                for event in device.read():
                    if event.type == ecodes.EV_ABS and event.code in trigger_axes:
                        threshold = 128 if event.value <= 255 else 16000
                        was_pressed = trigger_state.get(event.code, False)
                        # Use hysteresis: once pressed, a trigger stays latched
                        # until it is clearly released. Analog noise around
                        # the press threshold must not create extra menu steps.
                        release_threshold = max(1, threshold // 2)
                        pressed = event.value >= (release_threshold if was_pressed else threshold)
                        if pressed and not was_pressed:
                            _post_key(*trigger_axes[event.code])
                        trigger_state[event.code] = pressed

                    elif event.type == ecodes.EV_ABS and event.code in AXIS_DIR_MAP:
                        code = event.code
                        val  = event.value

                        # D-pad is digital (values: -1, 0, 1)
                        is_dpad = code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y)

                        if is_dpad:
                            if val == 0:
                                axis_state.pop(code, None)
                            else:
                                key = AXIS_DIR_MAP[code].get(val)
                                if key:
                                    _post_axis_key(key)
                                axis_state[code] = (val, time.monotonic() + FIRST_DELAY)
                        else:
                            # Analog stick with deadzone
                            if abs(val) < DEADZONE:
                                axis_state.pop(code, None)
                            else:
                                direction = -1 if val < 0 else 1
                                prev = axis_state.get(code)
                                if prev is None or prev[0] != direction:
                                    # New direction — fire immediately
                                    key = AXIS_DIR_MAP[code].get(direction)
                                    if key:
                                        _post_axis_key(key)
                                    axis_state[code] = (direction, time.monotonic() + FIRST_DELAY)

                    elif event.type == ecodes.EV_KEY:
                        if event.value == 0:   # dispatch button actions on release
                            mapping = BUTTON_MAP.get(event.code)
                            if mapping:
                                _post_key(*mapping)

            except Exception:
                break

        print("[CTRL] evdev controller thread stopped")


# ── jsdev fallback (raw /dev/input/jsX) ──────────────────────────────────────
#
# Reads 8-byte joystick events:  time(u32) value(s16) type(u8) number(u8)
# type 0x01 = button,  type 0x02 = axis
#
# Xbox One controller button numbers (jsdev):
#   0=A  1=B  2=X  3=Y  4=LB  5=RB  6=Back  7=Start  8=Guide  9=LStick  10=RStick
# Axis numbers:
#   0=LX  1=LY  2=LT  3=RX  4=RY  5=RT  6=DpadX  7=DpadY

JS_EVENT_FMT  = "IhBB"
JS_EVENT_SIZE = struct.calcsize(JS_EVENT_FMT)
JS_BUTTON     = 0x01
JS_AXIS       = 0x02
JS_INIT       = 0x80   # initial state events — ignore

_JS_BUTTON_MAP = {
    0: (Qt.Key_Return,       Qt.NoModifier),    # A
    1: (Qt.Key_Escape,       Qt.NoModifier),    # B
    2: (Qt.Key_Menu,         Qt.NoModifier),    # X → context menu
    3: (Qt.Key_F,            Qt.NoModifier),    # Y → favorite
    4: (Qt.Key_BracketLeft,  Qt.NoModifier),    # LB → collection/tab previous
    5: (Qt.Key_BracketRight, Qt.NoModifier),    # RB → collection/tab next
    6: (Qt.Key_F11,          Qt.NoModifier),    # Back → fullscreen
    7: (Qt.Key_Escape,       Qt.ControlModifier), # Menu/Start → quit confirmation
}

_JS_AXIS_MAP = {
    0: {-1: Qt.Key_Left,  1: Qt.Key_Right},    # Left stick X
    1: {-1: Qt.Key_Up,    1: Qt.Key_Down},      # Left stick Y
    6: {-1: Qt.Key_Left,  1: Qt.Key_Right},     # D-pad X
    7: {-1: Qt.Key_Up,    1: Qt.Key_Down},      # D-pad Y
    3: {-1: (Qt.Key_Left, Qt.ShiftModifier), 1: (Qt.Key_Right, Qt.ShiftModifier)}, # Right stick X
    4: {-1: Qt.Key_PageUp, 1: Qt.Key_PageDown}, # Right stick Y
}

_JS_TRIGGER_MAP = {
    2: (Qt.Key_F6, Qt.ControlModifier),  # LT → navbar previous
    5: (Qt.Key_F7, Qt.ControlModifier),  # RT → navbar next
}

_JS_AXIS_THRESHOLD = 16000   # out of 32767


class _JsdevController(QThread):
    """Zero-dependency fallback: reads /dev/input/js0 directly."""

    def __init__(self, path: str = "/dev/input/js0", parent=None):
        super().__init__(parent)
        self._path = path
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            fd = open(self._path, "rb")
        except PermissionError:
            print(f"[CTRL] Permission denied: {self._path}. Add user to 'input' group.")
            return
        except FileNotFoundError:
            print(f"[CTRL] No joystick at {self._path}")
            return

        print(f"[CTRL] Using jsdev: {self._path}")
        axis_state: dict[int, tuple[int, float]] = {}
        trigger_state = {}

        fd.read(JS_EVENT_SIZE * 20)   # drain initial state events

        while not self._stop.is_set():
            r, _, _ = select.select([fd], [], [], 0.05)
            now = time.monotonic()

            # Repeats
            for axis, (direction, fire_at) in list(axis_state.items()):
                if now >= fire_at:
                    key = _JS_AXIS_MAP.get(axis, {}).get(direction)
                    if key:
                        _post_axis_key(key)
                    axis_state[axis] = (direction, now + REPEAT_RATE)

            if not r:
                continue

            data = fd.read(JS_EVENT_SIZE)
            if len(data) < JS_EVENT_SIZE:
                break

            _, value, ev_type, number = struct.unpack(JS_EVENT_FMT, data)
            if ev_type & JS_INIT:
                continue

            if ev_type == JS_BUTTON and value == 0:
                mapping = _JS_BUTTON_MAP.get(number)
                if mapping:
                    _post_key(*mapping)

            elif ev_type == JS_AXIS and number in _JS_TRIGGER_MAP:
                was_pressed = trigger_state.get(number, False)
                release_threshold = _JS_AXIS_THRESHOLD // 2
                # Keep the trigger latched until it is well below the press
                # threshold, preventing analog noise from retriggering while
                # the user is still holding the button.
                pressed = value >= (release_threshold if was_pressed else _JS_AXIS_THRESHOLD)
                if pressed and not was_pressed:
                    _post_key(*_JS_TRIGGER_MAP[number])
                trigger_state[number] = pressed

            elif ev_type == JS_AXIS and number in _JS_AXIS_MAP:
                if abs(value) < _JS_AXIS_THRESHOLD:
                    axis_state.pop(number, None)
                else:
                    direction = -1 if value < 0 else 1
                    prev = axis_state.get(number)
                    if prev is None or prev[0] != direction:
                        key = _JS_AXIS_MAP[number].get(direction)
                        if key:
                            _post_axis_key(key)
                        axis_state[number] = (direction, now + FIRST_DELAY)

        fd.close()
        print("[CTRL] jsdev controller thread stopped")


# ── Public factory ────────────────────────────────────────────────────────────

    # No gamepad found right now, but return a dummy thread that polls for one? 
    # Or start a background thread that looks for one. 
    # The requirement says "poll in a loop every 5 seconds for new devices".
    # I'll modify start_controller to be a wrapper if needed or modify MainWindow.
    
    # Actually, simpler: return a polling thread that spawns the real one when found.
    # The user asked: "if the controller is disconnected and reconnected, try to reconnect automatically (poll in a loop every 5 seconds for new devices)."
    
class ControllerManager(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = threading.Event()
        self.active_controller = None

    def stop(self):
        self._stop.set()
        if self.active_controller:
            self.active_controller.stop()
            
    def run(self):
        while not self._stop.is_set():
            if not self.active_controller or not self.active_controller.isRunning():
                # try to find one
                c = self._try_find()
                if c:
                    self.active_controller = c
                    self.active_controller.start()
            
            # stop() sets the event, so this wait wakes immediately during
            # application shutdown instead of leaving the manager thread
            # alive until the five-second device poll expires.
            self._stop.wait(5.0)

        if self.active_controller and self.active_controller.isRunning():
            self.active_controller.stop()
            self.active_controller.wait(1000)

    def _try_find(self):
        try:
            import evdev
            from evdev import ecodes
            for path in evdev.list_devices():
                try:
                    d = evdev.InputDevice(path)
                    caps = d.capabilities()
                    if ecodes.EV_KEY in caps and ecodes.EV_ABS in caps:
                        d.close()
                        return _EvdevController()
                except Exception:
                    continue
        except ImportError:
            pass

        for js_path in ["/dev/input/js0", "/dev/input/js1"]:
            if os.path.exists(js_path):
                return _JsdevController(js_path)
        return None

def start_controller() -> QThread | None:
    global _key_dispatcher
    if _key_dispatcher is None:
        _key_dispatcher = _KeyDispatcher()
    manager = ControllerManager()
    manager.start()
    return manager
