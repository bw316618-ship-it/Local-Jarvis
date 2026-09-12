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

MVP scope: idle + run animation only (no fly/roll/drag physics/right-click
menu/moods -- those are Billo Rani features that don't matter for "lives in
a house until let out to roam the screen"). The frame-loading/animation
approach mirrors br.py's ANIMATION_DEFS pattern closely enough that jump/
fly/etc. could be layered on later without restructuring this file.
"""
import ctypes
import ctypes.wintypes as wintypes
import math
import random
import threading
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
WM_TIMER = 0x0113
WM_NCHITTEST = 0x0084
WM_MOUSEACTIVATE = 0x0021

HTCLIENT = 1
MA_NOACTIVATE = 3

SW_SHOWNOACTIVATE = 4
SW_HIDE = 0

SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

HWND_TOPMOST = -1

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1

IDC_ARROW = 32512


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


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
user32.SetTimer.argtypes = [
    wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID,
]
user32.SetTimer.restype = ctypes.c_size_t
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
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


# Animation defs, ported from Desktop-Pet/br.py's ANIMATION_DEFS. Only the
# states this module actually uses (idle, run) are kept; more (fly, jump,
# roll, ...) can be added later using the same "{side}" + frame-range shape.
ANIMATION_DEFS = {
    "idle": ("stand{side}", None),
    "run": ("run{side}", (1, 3)),
}

ASLEEP = "asleep"
ROAMING = "roaming"
RETURNING = "returning"


class DesktopPet:
    """A layered window that is the pet's house when ASLEEP and the pet
    itself when ROAMING/RETURNING. See module docstring for the state
    machine. All Win32 calls happen on self._thread; state-changing calls
    like release()/call_home() are safe to call from any thread -- they
    just flip a flag that the render tick picks up."""

    WINDOW_SIZE = 96          # fixed HWND size; house art and pet sprite both fit inside it
    SPRITE_SCALE = 4
    SPRITE_BASE = 18          # matches Desktop-Pet's BASE_SIZE
    SPRITE_SIZE = SPRITE_BASE * SPRITE_SCALE  # 72

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

    def is_out(self) -> bool:
        with self._state_lock:
            return self.state != ASLEEP

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

    def _current_anim_key(self):
        moving = abs(self.vx) > 0.5 or abs(self.vy) > 0.5
        side = "right" if self.facing_right else "left"
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
    # Window proc / message loop
    # -------------------------
    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_NCHITTEST:
            return HTCLIENT
        if msg == WM_LBUTTONDOWN:
            with self._state_lock:
                asleep = self.state == ASLEEP
                out = self.state == ROAMING
            if asleep:
                self.release()
            elif out:
                self.call_home()
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
            return 0
        if msg == WM_DESTROY:
            self._stop.set()
            user32.KillTimer(hwnd, self.TIMER_RENDER)
            user32.KillTimer(hwnd, self.TIMER_ANIM)
            user32.KillTimer(hwnd, self.TIMER_BEHAVIOR)
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

        self._ready.set()

        msg = wintypes.MSG()
        while not self._stop.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
