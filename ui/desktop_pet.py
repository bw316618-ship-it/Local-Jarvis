"""
DesktopPet -- a raw-Win32 layered window that is Jarvis's desktop pet AND
its house, in the same spirit as ui/native_overlay.py (UpdateLayeredWindow
via ctypes, PIL-rendered frames, one thread with its own message loop).

Why not just embed the Billo Rani PyQt5 widget (github.com/bw316618-ship-it
/Desktop-Pet)? That project uses QApplication + QWidget for its window and
event loop. Running a second GUI toolkit's message pump alongside the raw
ctypes overlay thread would work (Windows message queues are per-thread)
but means carrying PyQt5 as a dependency and reasoning about two totally
different windowing systems side by side, for something that is fundamentally
just "move a sprite around and swap frames". Since native_overlay.py already
solved transparent, click-driven, draggable layered windows with plain
ctypes + PIL (chosen specifically because pywebview/WebView2 transparency
was unreliable), this module reuses that exact approach instead. Only the
*behavior* -- wandering/steering/edge-bounce and frame-cycling -- is ported
from Desktop-Pet's br.py; none of its Qt code is used.

States
------
ASLEEP     Parked at a fixed "house" position, house sprite shown, pet
           hidden. Nothing pet-related runs. Click on the window -> release.
ROAMING    Free-roaming: same wander/edge-bounce steering as Billo Rani,
           idle/run animation, click to send it home early.
RETURNING  Steers toward the house position; on arrival, transitions back
           to ASLEEP and redraws the house.

Personality (ported from Desktop-Pet's br.py, movement/menu subset only --
none of the Chrome-launching, notepad, or love-letter actions, which don't
fit a pet that lives in Jarvis's own tool-driven sandbox): while ROAMING,
right-click opens a context menu with Fly, Jump, and Roll, layered as
sub-states on top of the existing wander/steer loop rather than replacing
it -- the pet still has a target and still edge-bounces, fly/jump/roll just
change how _current_frame and the position update behave for their
duration. Fly is a toggle (sine-wave vertical bob while wandering, same
amplitude/speed constants as br.py); jump is a one-shot vertical arc; roll
is a brief in-place reaction (dizzy roll) that pauses target-seeking. The
sprite frames for all three already ship in assets/desktop_pet/ (flying{l,
r}1-3, jump{l,r}, roll1-4) -- only ANIMATION_DEFS wasn't pointing at them.
"""
import ctypes
import ctypes.wintypes as wintypes
import math
import random
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
HCURSOR = wintypes.HANDLE

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

WM_DESTROY = 0x0002
WM_LBUTTONDOWN = 0x0201
WM_NCLBUTTONDOWN = 0x00A1
WM_RBUTTONUP = 0x0205
WM_TIMER = 0x0113
WM_NCHITTEST = 0x0084
WM_MOUSEACTIVATE = 0x0021
WM_COMMAND = 0x0111

HTCLIENT = 1
HTCAPTION = 2
MA_NOACTIVATE = 3

MF_STRING = 0x00000000
MF_GRAYED = 0x00000001
MF_SEPARATOR = 0x00000800
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

# Right-click context menu item IDs (WM_COMMAND wparam low word)
MENU_ID_TOGGLE = 1001   # "Let out to roam" / "Call home", label depends on state
MENU_ID_FLY = 1002
MENU_ID_JUMP = 1003
MENU_ID_ROLL = 1004

SW_SHOWNOACTIVATE = 4
SW_HIDE = 0

SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001

HWND_TOPMOST = -1

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1

IDC_ARROW = 32512


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE),
        ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE),
        ("AlphaFormat", wintypes.BYTE),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadCursorW.restype = HCURSOR
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None
user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.SendMessageW.restype = LRESULT
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetTimer.argtypes = [
    wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID,
]
user32.SetTimer.restype = ctypes.c_size_t
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR,
]
user32.AppendMenuW.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.TrackPopupMenuEx.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.LPVOID,
]
user32.TrackPopupMenuEx.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
    wintypes.HDC, ctypes.POINTER(POINT), wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ

kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


# Animation defs, ported from Desktop-Pet/br.py's ANIMATION_DEFS.
# "roll" has no {side}-specific art (br.py: "not side-specific -- same
# frames both ways") -- template.format(side=...) is a no-op when the
# template has no {side} token, so it naturally loads the same roll*.png
# frames under both roll_left and roll_right without special-casing.
ANIMATION_DEFS = {
    "idle": ("stand{side}", None),
    "run": ("run{side}", (1, 3)),
    "fly": ("flying{side}", (1, 3)),
    "jump": ("jump{side}", None),
    "roll": ("roll", (1, 4)),
}

# Fly bob (ported from br.py FLY_WAVE_AMPLITUDE/FLY_WAVE_SPEED)
FLY_WAVE_AMPLITUDE = 2
FLY_WAVE_SPEED = 0.12

# Jump arc: simple symmetric parabola, apex at JUMP_HEIGHT px after half of
# JUMP_DURATION_MS, back to baseline at the end. Not a physics sim like
# br.py's JUMP_IMPULSE + gravity integration -- a fixed-duration arc is
# enough for a menu-triggered flourish and can't get stuck mid-air.
JUMP_HEIGHT = 40
JUMP_DURATION_MS = 500

# Roll (ported from br.py's ANNOY_ROLL_MS -- the shorter "reaction" roll,
# not the 3s dizzy-drag or 800ms self-destruct variants, neither of which
# have an equivalent trigger here)
ROLL_DURATION_MS = 1200

ASLEEP = "asleep"
ROAMING = "roaming"
RETURNING = "returning"


class DesktopPet:
    """A layered window that is the pet's house when ASLEEP and the pet
    itself when ROAMING/RETURNING. See module docstring for the state
    machine. All Win32 calls happen on self._thread; state-changing calls
    like release()/call_home() are safe to call from any thread -- they
    just flip a flag that the render tick picks up."""

    WINDOW_SIZE = 180         # fixed HWND size; house art and pet sprite both fit inside it
    SPRITE_SCALE = 8
    SPRITE_BASE = 18          # matches Desktop-Pet's BASE_SIZE
    SPRITE_SIZE = SPRITE_BASE * SPRITE_SCALE  # 144

    MAX_SPEED = 3.0
    STEER_SMOOTHING = 0.2
    EDGE_BOUNCE_DAMPING = 0.6
    ARRIVE_THRESHOLD = 6       # px distance from house center that counts as "home"

    RENDER_INTERVAL_MS = 50
    ANIM_INTERVAL_MS = 110
    BEHAVIOR_INTERVAL_MS = 4000  # how often a new wander target is chosen

    TIMER_RENDER = 1
    TIMER_ANIM = 2
    TIMER_BEHAVIOR = 3
    TIMER_TOPMOST = 4
    TOPMOST_INTERVAL_MS = 2000  # periodically re-assert topmost; some apps steal the topmost band

    HOUSE_MARGIN = 24  # distance from bottom-right corner, matches native_overlay's MARGIN

    def __init__(self, assets_dir: str, on_release=None, on_home=None):
        """
        assets_dir: path to the vendored Desktop-Pet sprite PNGs
                    (e.g. Path(__file__).parent.parent / "assets" / "desktop_pet").
        on_release / on_home: optional callbacks fired when the pet leaves
                    or returns to the house (e.g. to log to the audit trail).
        """
        self.assets_dir = Path(assets_dir)
        self.on_release = on_release
        self.on_home = on_home

        self._thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._hwnd = None
        self._wnd_proc_ref = None
        self._class_name = "JarvisDesktopPet"

        self._state_lock = threading.Lock()
        self.state = ASLEEP

        # position is the top-left of the WINDOW_SIZE x WINDOW_SIZE box
        self._x = 0
        self._y = 0
        self._house_x = 0
        self._house_y = 0

        self.vx, self.vy = 0.0, 0.0
        self.target_x = None
        self.target_y = None
        self.facing_right = True
        self.frame_index = 0

        # Personality sub-states (toggled/triggered from the right-click
        # menu; layered on top of ROAMING, see module docstring)
        self.is_flying = False
        self._fly_phase = 0.0
        self.is_rolling = False
        self._roll_end_at = 0.0
        self.is_jumping = False
        self._jump_start_at = 0.0
        self._jump_base_y = 0.0

        self.house_image = None      # PIL RGBA, WINDOW_SIZE^2, door-closed art
        self.house_open_image = None  # door-open art, shown briefly on release
        self.anim = {}               # "idle_left"/"idle_right"/"run_left"/"run_right" -> [PIL frames]

        self._load_assets()

    # -------------------------
    # Lifecycle
    # -------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="JarvisDesktopPet", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self):
        self._stop.set()
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)

    # -------------------------
    # Public state control (thread-safe; called from tools/voice/tray)
    # -------------------------
    def release(self):
        """Open the door and let the pet out to roam. No-op if already out."""
        with self._state_lock:
            if self.state != ASLEEP:
                return
            self.state = ROAMING
            self._x, self._y = self._house_x, self._house_y
            self._choose_target()
        if self.on_release:
            self.on_release()

    def call_home(self):
        """Recall the pet: it stops wandering and steers back to the house.
        No-op if it's already home or already on its way."""
        with self._state_lock:
            if self.state != ROAMING:
                return
            self.state = RETURNING
            # Personality sub-states only make sense while ROAMING -- drop
            # them so RETURNING's plain steer-home isn't mid-arc/mid-bob.
            self.is_flying = False
            self.is_rolling = False
            self.is_jumping = False

    def is_out(self) -> bool:
        with self._state_lock:
            return self.state != ASLEEP

    def toggle_fly(self):
        """Toggle the flying bob on/off. Only meaningful while ROAMING;
        no-op otherwise (asleep/returning have their own movement)."""
        with self._state_lock:
            if self.state != ROAMING:
                return
            self.is_flying = not self.is_flying
            self._fly_phase = 0.0

    def jump(self):
        """Trigger a one-shot vertical hop. No-op if already jumping or
        not ROAMING -- see JUMP_HEIGHT/JUMP_DURATION_MS for the arc."""
        with self._state_lock:
            if self.state != ROAMING or self.is_jumping:
                return
            self.is_jumping = True
            self._jump_start_at = time.monotonic()
            self._jump_base_y = self._y

    def roll(self):
        """Trigger a brief in-place roll reaction. No-op if already
        rolling or not ROAMING."""
        with self._state_lock:
            if self.state != ROAMING or self.is_rolling:
                return
            self.is_rolling = True
            self._roll_end_at = time.monotonic() + ROLL_DURATION_MS / 1000.0

    # -------------------------
    # Asset loading (ported from br.py's _load_pm / ANIMATION_DEFS expansion)
    # -------------------------
    def _load_sprite(self, filename: str):
        path = self.assets_dir / filename
        if not path.exists():
            print(f"[Jarvis pet] missing sprite {filename}")
            return None
        img = Image.open(path).convert("RGBA")
        img.thumbnail((self.SPRITE_SIZE, self.SPRITE_SIZE), Image.LANCZOS)
        canvas = Image.new("RGBA", (self.WINDOW_SIZE, self.WINDOW_SIZE), (0, 0, 0, 0))
        ox = (self.WINDOW_SIZE - img.width) // 2
        oy = (self.WINDOW_SIZE - img.height) // 2
        canvas.alpha_composite(img, (ox, oy))
        return canvas

    def _load_assets(self):
        for key, (template, frame_range) in ANIMATION_DEFS.items():
            for side, suffix in (("l", "left"), ("r", "right")):
                name = template.format(side=side)
                if frame_range is None:
                    names = [f"{name}.png"]
                else:
                    lo, hi = frame_range
                    names = [f"{name}{i}.png" for i in range(lo, hi + 1)]
                frames = [f for f in (self._load_sprite(n) for n in names) if f is not None]
                self.anim[f"{key}_{suffix}"] = frames

        self.house_image = self._draw_house(door_open=False)
        self.house_open_image = self._draw_house(door_open=True)

    def _draw_house(self, door_open: bool) -> "Image.Image":
        """Simple procedural house-with-door placeholder, drawn with PIL the
        same way native_overlay.py draws its HUD panel. Swap this for real
        art later by loading a PNG here instead."""
        size = self.WINDOW_SIZE
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        wall_color = (58, 74, 92, 235)
        roof_color = (58, 214, 255, 235)
        outline = (216, 246, 255, 160)
        door_color = (18, 24, 32, 240) if not door_open else (10, 200, 120, 200)

        margin = 10
        wall_top = size * 0.42
        wall_rect = [margin, wall_top, size - margin, size - margin]
        draw.rectangle(wall_rect, fill=wall_color, outline=outline, width=2)

        roof_pts = [
            (size * 0.5, size * 0.08),
            (size - margin + 4, wall_top + 2),
            (margin - 4, wall_top + 2),
        ]
        draw.polygon(roof_pts, fill=roof_color, outline=outline)

        door_w, door_h = size * 0.22, size * 0.30
        door_x0 = size / 2 - door_w / 2
        door_y0 = size - margin - door_h
        if door_open:
            # skewed parallelogram to suggest a swung-open door
            draw.polygon(
                [
                    (door_x0, door_y0),
                    (door_x0 + door_w * 0.4, door_y0),
                    (door_x0 + door_w * 0.7, door_y0 + door_h),
                    (door_x0 + door_w * 0.1, door_y0 + door_h),
                ],
                fill=door_color, outline=outline,
            )
        else:
            draw.rectangle(
                [door_x0, door_y0, door_x0 + door_w, door_y0 + door_h],
                fill=door_color, outline=outline, width=2,
            )
        return img

    # -------------------------
    # Wander behavior (ported from br.py: choose_target / update_position,
    # minus flying/dizzy/drag/skid -- see module docstring)
    # -------------------------
    def _screen_geometry(self):
        return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))

    def _choose_target(self):
        sw, sh = self._screen_geometry()
        self.target_x = random.randint(0, max(0, sw - self.WINDOW_SIZE))
        self.target_y = random.randint(int(sh * 0.5), max(0, sh - self.WINDOW_SIZE))

    def _step_toward(self, tx, ty):
        dx = tx - self._x
        dy = ty - self._y
        desired_vx = max(-self.MAX_SPEED, min(self.MAX_SPEED, dx))
        desired_vy = max(-self.MAX_SPEED, min(self.MAX_SPEED, dy))
        self.vx += (desired_vx - self.vx) * self.STEER_SMOOTHING
        self.vy += (desired_vy - self.vy) * self.STEER_SMOOTHING
        if abs(self.vx) > 0.3:
            self.facing_right = self.vx > 0
        return dx, dy

    def _update_roaming(self):
        now = time.monotonic()

        # Roll: a brief in-place reaction. Pause target-seeking entirely
        # for its duration, then fall through to normal movement once it
        # ends (no separate "resume" step needed).
        if self.is_rolling:
            if now >= self._roll_end_at:
                self.is_rolling = False
            else:
                return

        if self.target_x is None:
            self._choose_target()
        dx, dy = self._step_toward(self.target_x, self.target_y)

        sw, sh = self._screen_geometry()
        nx = self._x + self.vx
        ny = self._y + self.vy
        if nx < 0:
            nx = 0
            self.vx = -self.vx * self.EDGE_BOUNCE_DAMPING
        elif nx > sw - self.WINDOW_SIZE:
            nx = sw - self.WINDOW_SIZE
            self.vx = -self.vx * self.EDGE_BOUNCE_DAMPING
        if ny < 0:
            ny = 0
            self.vy = -self.vy * self.EDGE_BOUNCE_DAMPING
        elif ny > sh - self.WINDOW_SIZE:
            ny = sh - self.WINDOW_SIZE
            self.vy = -self.vy * self.EDGE_BOUNCE_DAMPING
        self._x, self._y = nx, ny

        # Fly: sine-wave vertical bob layered on top of the normal
        # steered position, same constants as br.py. Purely cosmetic --
        # doesn't change vx/vy or the arrival check below.
        if self.is_flying:
            self._fly_phase += FLY_WAVE_SPEED
            self._y += math.sin(self._fly_phase) * FLY_WAVE_AMPLITUDE

        # Jump: fixed-duration parabolic arc, independent of the normal
        # y position computed above -- overrides it for the arc's
        # duration, then hands back to normal movement automatically.
        if self.is_jumping:
            elapsed_ms = (now - self._jump_start_at) * 1000.0
            if elapsed_ms >= JUMP_DURATION_MS:
                self.is_jumping = False
                self._y = self._jump_base_y
            else:
                progress = elapsed_ms / JUMP_DURATION_MS  # 0..1
                arc = 4 * progress * (1 - progress)  # 0 at ends, 1 at apex
                self._y = self._jump_base_y - arc * JUMP_HEIGHT

        if abs(dx) < self.ARRIVE_THRESHOLD and abs(dy) < self.ARRIVE_THRESHOLD:
            self._choose_target()

    def _update_returning(self):
        dx, dy = self._step_toward(self._house_x, self._house_y)
        self._x += self.vx
        self._y += self.vy
        if abs(dx) < self.ARRIVE_THRESHOLD and abs(dy) < self.ARRIVE_THRESHOLD:
            with self._state_lock:
                self.state = ASLEEP
            self._x, self._y = self._house_x, self._house_y
            self.vx = self.vy = 0.0
            if self.on_home:
                self.on_home()

    # -------------------------
    # Dragging (ported from native_overlay.py's _drag_and_maybe_toggle:
    # ReleaseCapture + WM_NCLBUTTONDOWN/HTCAPTION hands the drag off to
    # Windows itself, since a borderless WS_POPUP has no caption to grab.
    # Comparing the window rect before/after tells us drag vs. plain click.)
    # -------------------------
    def _drag_and_maybe_act(self, hwnd):
        start_rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(start_rect)):
            return

        user32.ReleaseCapture()
        user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)

        end_rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(end_rect)):
            return

        moved = (
            abs(end_rect.left - start_rect.left) > 2
            or abs(end_rect.top - start_rect.top) > 2
        )

        with self._state_lock:
            state = self.state

        if moved:
            self._x, self._y = end_rect.left, end_rect.top
            if state == ASLEEP:
                # dragging while asleep repositions the house itself
                self._house_x, self._house_y = end_rect.left, end_rect.top
            return

        # not a drag -- treat as a click
        if state == ASLEEP:
            self.release()
        elif state == ROAMING:
            self.call_home()

    def _current_anim_key(self):
        side = "right" if self.facing_right else "left"
        # Priority: roll/jump are brief reactions that override whatever
        # locomotion animation would otherwise play; fly overrides run/idle
        # since it's still steering toward a target, just airborne.
        if self.is_rolling:
            return f"roll_{side}"
        if self.is_jumping:
            return f"jump_{side}"
        if self.is_flying:
            return f"fly_{side}"
        moving = abs(self.vx) > 0.5 or abs(self.vy) > 0.5
        return f"{'run' if moving else 'idle'}_{side}"

    # -------------------------
    # Frame composition -> UpdateLayeredWindow (same technique as
    # native_overlay.py's _update_layered_window)
    # -------------------------
    def _current_frame(self):
        state = self.state  # read without lock; used for display only, benign race
        if state == ASLEEP:
            return self.house_image
        frames = self.anim.get(self._current_anim_key()) or self.anim.get("idle_right", [])
        if not frames:
            return self.house_image
        return frames[self.frame_index % len(frames)]

    def _update_layered_window(self, image):
        width, height = image.size
        raw = image.tobytes("raw", "BGRA")

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        screen_dc = user32.GetDC(None)
        if not screen_dc:
            return
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not mem_dc:
            user32.ReleaseDC(None, screen_dc)
            return

        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not bitmap:
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(None, screen_dc)
            return

        try:
            ctypes.memmove(bits, raw, len(raw))
            old_bitmap = gdi32.SelectObject(mem_dc, bitmap)
            if not old_bitmap:
                return

            destination = POINT(int(self._x), int(self._y))
            size = SIZE(width, height)
            source = POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

            user32.UpdateLayeredWindow(
                self._hwnd, screen_dc, ctypes.byref(destination), ctypes.byref(size),
                mem_dc, ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA,
            )
            gdi32.SelectObject(mem_dc, old_bitmap)
        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(None, screen_dc)

    def _render(self):
        self._update_layered_window(self._current_frame())

    def _tick_render(self):
        with self._state_lock:
            state = self.state
        if state == ROAMING:
            self._update_roaming()
        elif state == RETURNING:
            self._update_returning()
        # ASLEEP: parked at house position, nothing to update
        self._render()

    def _tick_anim(self):
        self.frame_index += 1

    # -------------------------
    # Right-click context menu
    # -------------------------
    def _show_context_menu(self, hwnd):
        with self._state_lock:
            state = self.state
            flying = self.is_flying

        menu = user32.CreatePopupMenu()
        if not menu:
            return

        try:
            if state == ASLEEP:
                user32.AppendMenuW(menu, MF_STRING, MENU_ID_TOGGLE, "Let out to roam")
            elif state == ROAMING:
                user32.AppendMenuW(menu, MF_STRING, MENU_ID_TOGGLE, "Call home")
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                fly_label = "Stop flying" if flying else "Fly"
                user32.AppendMenuW(menu, MF_STRING, MENU_ID_FLY, fly_label)
                user32.AppendMenuW(menu, MF_STRING, MENU_ID_JUMP, "Jump")
                user32.AppendMenuW(menu, MF_STRING, MENU_ID_ROLL, "Roll")
            else:  # RETURNING -- already headed home, nothing to offer
                user32.AppendMenuW(
                    menu, MF_STRING | MF_GRAYED, MENU_ID_TOGGLE, "Coming home..."
                )

            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))

            # SetForegroundWindow + the WM_NULL-after-TrackPopupMenu dance
            # is the documented workaround for a popup menu not dismissing
            # itself when the owner window can't take focus (we're
            # WS_EX_NOACTIVATE, same as native_overlay.py's icon).
            user32.SetForegroundWindow(hwnd)
            user32.TrackPopupMenuEx(
                menu, TPM_RIGHTBUTTON, pt.x, pt.y, hwnd, None,
            )
            user32.PostMessageW(hwnd, 0, 0, 0)  # WM_NULL, completes the dance
        finally:
            user32.DestroyMenu(menu)

    def _handle_menu_command(self, command_id):
        if command_id == MENU_ID_TOGGLE:
            with self._state_lock:
                state = self.state
            if state == ASLEEP:
                self.release()
            elif state == ROAMING:
                self.call_home()
        elif command_id == MENU_ID_FLY:
            self.toggle_fly()
        elif command_id == MENU_ID_JUMP:
            self.jump()
        elif command_id == MENU_ID_ROLL:
            self.roll()

    # -------------------------
    # Window proc / message loop
    # -------------------------
    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_NCHITTEST:
            return HTCLIENT
        if msg == WM_LBUTTONDOWN:
            self._drag_and_maybe_act(hwnd)
            return 0
        if msg == WM_RBUTTONUP:
            self._show_context_menu(hwnd)
            return 0
        if msg == WM_COMMAND:
            self._handle_menu_command(wparam & 0xFFFF)
            return 0
        if msg == WM_TIMER:
            if wparam == self.TIMER_RENDER:
                self._tick_render()
            elif wparam == self.TIMER_ANIM:
                self._tick_anim()
            elif wparam == self.TIMER_BEHAVIOR:
                with self._state_lock:
                    if self.state == ROAMING:
                        self._choose_target()
            elif wparam == self.TIMER_TOPMOST:
                user32.SetWindowPos(
                    hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE,
                )
            return 0
        if msg == WM_DESTROY:
            self._stop.set()
            user32.KillTimer(hwnd, self.TIMER_RENDER)
            user32.KillTimer(hwnd, self.TIMER_ANIM)
            user32.KillTimer(hwnd, self.TIMER_BEHAVIOR)
            user32.KillTimer(hwnd, self.TIMER_TOPMOST)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        instance = kernel32.GetModuleHandleW(None)

        @WNDPROC
        def wnd_proc(hwnd, msg, wparam, lparam):
            return self._window_proc(hwnd, msg, wparam, lparam)

        self._wnd_proc_ref = wnd_proc
        cursor = user32.LoadCursorW(None, ctypes.cast(IDC_ARROW, wintypes.LPCWSTR))

        wnd_class = WNDCLASSW(0, wnd_proc, 0, 0, instance, None, cursor, None, None, self._class_name)
        atom = user32.RegisterClassW(ctypes.byref(wnd_class))
        if not atom:
            error = kernel32.GetLastError()
            if error != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                print(f"[Jarvis pet] RegisterClassW failed: {error}")

        sw, sh = self._screen_geometry()
        self._house_x = sw - self.WINDOW_SIZE - self.HOUSE_MARGIN
        self._house_y = sh - self.WINDOW_SIZE - self.HOUSE_MARGIN
        self._x, self._y = self._house_x, self._house_y

        ex_style = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self._hwnd = user32.CreateWindowExW(
            ex_style, self._class_name, "Jarvis Desktop Pet", WS_POPUP,
            int(self._x), int(self._y), self.WINDOW_SIZE, self.WINDOW_SIZE,
            None, None, instance, None,
        )
        if not self._hwnd:
            print(f"[Jarvis pet] CreateWindowExW failed: {kernel32.GetLastError()}")
            self._ready.set()
            return

        user32.SetWindowPos(
            self._hwnd, HWND_TOPMOST, int(self._x), int(self._y),
            self.WINDOW_SIZE, self.WINDOW_SIZE, SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

        self._render()
        user32.SetTimer(self._hwnd, self.TIMER_RENDER, self.RENDER_INTERVAL_MS, None)
        user32.SetTimer(self._hwnd, self.TIMER_ANIM, self.ANIM_INTERVAL_MS, None)
        user32.SetTimer(self._hwnd, self.TIMER_BEHAVIOR, self.BEHAVIOR_INTERVAL_MS, None)
        user32.SetTimer(self._hwnd, self.TIMER_TOPMOST, self.TOPMOST_INTERVAL_MS, None)

        self._ready.set()

        msg = wintypes.MSG()
        while not self._stop.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
