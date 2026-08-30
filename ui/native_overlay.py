import ctypes
import ctypes.wintypes as wintypes
import math
import threading
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32


# ctypes.wintypes doesn't reliably define LRESULT across Python
# versions (confirmed missing on at least one install this app was
# tested on), and WPARAM/LPARAM have historically had pointer-size
# inconsistencies on 64-bit Python in older stdlib versions. Defining
# these ourselves as the real Win32 typedefs -- WPARAM = UINT_PTR,
# LPARAM/LRESULT = LONG_PTR, i.e. pointer-sized -- sidesteps relying
# on stdlib completeness for exactly the three types a WNDPROC
# callback signature needs.
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t

# HCURSOR is also missing from stdlib wintypes on at least this
# Python install (confirmed via direct inspection, not assumption --
# see the audit below). Every real Win32 handle type is just an alias
# for HANDLE (c_void_p), so this is the correct definition.
HCURSOR = wintypes.HANDLE


WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

WM_DESTROY = 0x0002
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
WM_TIMER = 0x0113
WM_NCHITTEST = 0x0084
WM_MOUSEACTIVATE = 0x0021

HTCLIENT = 1
HTCAPTION = 2

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
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class SIZE(ctypes.Structure):
    _fields_ = [
        ("cx", wintypes.LONG),
        ("cy", wintypes.LONG),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE),
        ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE),
        ("AlphaFormat", wintypes.BYTE),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    WPARAM,
    LPARAM,
)


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


# Explicit argtypes/restype for every Win32 call this module makes.
# Left unset, ctypes marshals every argument and return value of an
# untyped foreign call as a 32-bit c_int. That's silent, not an
# exception: on 64-bit Windows it truncates any HWND/HDC/HBITMAP or
# other pointer-sized handle that happens to fall outside the 32-bit
# range, corrupting it. The window wouldn't necessarily crash --
# subsequent calls using the corrupted handle would just silently
# fail (UpdateLayeredWindow returning False, the window never
# appearing), which is a far harder bug to diagnose than an
# AttributeError. Declaring these removes that whole class of risk.

user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadCursorW.restype = HCURSOR

user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    WPARAM,
    LPARAM,
]
user32.DefWindowProcW.restype = LRESULT

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC

# GetMessageW can return -1 on error (not just 0/nonzero), so restype
# is a signed c_int rather than BOOL to preserve that distinction.
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int

user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wintypes.BOOL

user32.PostMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    WPARAM,
    LPARAM,
]
user32.PostMessageW.restype = wintypes.BOOL

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wintypes.BOOL

user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

user32.SendMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    WPARAM,
    LPARAM,
]
user32.SendMessageW.restype = LRESULT

user32.SetTimer.argtypes = [
    wintypes.HWND,
    ctypes.c_size_t,
    wintypes.UINT,
    wintypes.LPVOID,
]
user32.SetTimer.restype = ctypes.c_size_t

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

# pbmi is declared as a generic void pointer rather than
# POINTER(BITMAPINFO): the real BITMAPINFO/BITMAPINFOHEADER classes
# are defined locally inside _update_layered_window (not at module
# scope), and ctypes can raise ArgumentError if a byref() target's
# exact type doesn't match a strictly-typed POINTER(...) argtype.
# c_void_p accepts any byref()/pointer value without that check.
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
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

user32.GetWindowRect.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(RECT),
]
user32.GetWindowRect.restype = wintypes.BOOL


class NativeOverlay:
    WIDTH = 360
    HEIGHT = 132

    COLLAPSED_SIZE = 32

    MARGIN = 24

    BG_ALPHA = 178
    BORDER_ALPHA = 105

    CYAN = (58, 214, 255, 255)
    TEXT = (216, 246, 255, 255)
    DATE = (143, 185, 196, 255)
    LABEL = (111, 151, 162, 255)

    def __init__(self, status_provider):
        self.status_provider = status_provider

        self._thread = None
        self._status_thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()

        self._hwnd = None
        self._class_name = "JarvisNativeOverlay"

        self._collapsed = False
        self._visible = True

        # None means "use the auto-anchored top-right corner" (see
        # _position()). Once the user drags the window, this holds
        # the real on-screen (x, y) so subsequent repaints don't
        # silently snap it back to the anchor -- which is exactly
        # what was happening before: _position() was being
        # recomputed from scratch on every single repaint (including
        # the once-a-second status tick), with no memory of anywhere
        # the user had moved it.
        self._custom_position = None

        self._status_lock = threading.Lock()
        self._latest_status = {
            "cpu": None,
            "ram": None,
            "disk": None,
        }

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._run,
            name="JarvisNativeOverlay",
            daemon=True,
        )

        self._thread.start()

        self._ready.wait(timeout=5)

        # Runs on its own thread, separate from the window's message
        # pump. system_status_snapshot() calls psutil.cpu_percent with
        # interval=0.5, which blocks for half a second -- if that ran
        # from inside the WM_TIMER handler (on the message-pump thread,
        # as it originally did), the window would be unable to process
        # WM_LBUTTONDOWN/drag/click messages for 500ms out of every
        # 1000ms tick, making it feel laggy or drop clicks. Polling
        # here and just reading the cached result in WM_TIMER keeps
        # the message pump free to stay responsive at all times.
        self._status_thread = threading.Thread(
            target=self._status_loop,
            name="JarvisNativeOverlayStatus",
            daemon=True,
        )

        self._status_thread.start()

    def _status_loop(self):
        while not self._stop.is_set():
            self._update_status()
            self._stop.wait(timeout=1)

    def stop(self):
        self._stop.set()

        if self._hwnd:
            user32.PostMessageW(
                self._hwnd,
                WM_DESTROY,
                0,
                0,
            )

    def show(self):
        self._visible = True

        if self._hwnd:
            user32.ShowWindow(
                self._hwnd,
                SW_SHOWNOACTIVATE,
            )

    def hide(self):
        self._visible = False

        if self._hwnd:
            user32.ShowWindow(
                self._hwnd,
                SW_HIDE,
            )

    def toggle_visible(self):
        if self._visible:
            self.hide()
        else:
            self.show()

    def toggle_collapsed(self):
        self._collapsed = not self._collapsed

        self._render()

    def _screen_geometry(self):
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)

        return width, height

    def _window_size(self):
        if self._collapsed:
            return (
                self.COLLAPSED_SIZE,
                self.COLLAPSED_SIZE,
            )

        return self.WIDTH, self.HEIGHT

    def _position(self):
        if self._custom_position is not None:
            return self._custom_position

        screen_width, _ = self._screen_geometry()

        width, _ = self._window_size()

        x = (
            screen_width
            - width
            - self.MARGIN
        )

        y = self.MARGIN

        return x, y

    def _load_font(self, size, bold=False):
        candidates = [
            Path("C:/Windows/Fonts/segoeui.ttf"),
            Path("C:/Windows/Fonts/segoeuib.ttf"),
        ]

        if bold:
            path = candidates[1]
        else:
            path = candidates[0]

        try:
            return ImageFont.truetype(
                str(path),
                size,
            )
        except OSError:
            return ImageFont.load_default()

    def _render(self):
        if not self._hwnd:
            return

        width, height = self._window_size()

        image = Image.new(
            "RGBA",
            (width, height),
            (0, 0, 0, 0),
        )

        draw = ImageDraw.Draw(image)

        # A single continuous rotation phase, shared by both draw
        # calls below, so the icon's spin stays consistent whether
        # it's being drawn as the whole collapsed window or as the
        # small status indicator in the corner of the expanded panel.
        # Driven by wall-clock time rather than a per-render counter
        # so its speed doesn't change when extra renders happen (e.g.
        # right after a collapse/expand click) on top of the regular
        # 1-second timer tick.
        rotation = (time.time() * 6) % 360

        if self._collapsed:
            self._draw_reactor_icon(
                draw,
                width // 2,
                height // 2,
                rotation,
            )
        else:
            self._draw_panel(
                draw,
                width,
                height,
                rotation,
            )

        self._update_layered_window(
            image
        )

    def _draw_reactor_icon(self, draw, cx, cy, rotation):
        """
        A miniature arc-reactor-style icon -- soft glow, a thin
        containment ring, four rotating spike triangles, and a
        white-hot core -- used both as the panel's small status
        indicator and as the overlay's entire visual identity when
        collapsed. Replaces the earlier flat dot to match the app's
        existing Iron-Man/reactor aesthetic (see the HUD's own
        Three.js reactor visualization).

        The first version of this used thin 1px semi-transparent
        rays, which at this icon's actual on-screen size (~20px)
        were too faint to read as anything but a plain circle --
        solid triangular spikes plus a stroked ring read clearly even
        this small.
        """
        color = self.CYAN

        # Soft outer glow: PIL's ImageDraw has no built-in radial
        # gradient fill, so this fakes one with a couple of
        # concentric, decreasing-alpha circles.
        for radius, alpha in ((12, 40), (9, 70)):
            draw.ellipse(
                (
                    cx - radius,
                    cy - radius,
                    cx + radius,
                    cy + radius,
                ),
                fill=(color[0], color[1], color[2], alpha),
            )

        # Containment ring -- an outline, not a fill, so it reads as
        # a ring rather than another solid disc.
        ring_radius = 9

        draw.ellipse(
            (
                cx - ring_radius,
                cy - ring_radius,
                cx + ring_radius,
                cy + ring_radius,
            ),
            outline=color,
            width=1,
        )

        # Spikes: solid triangles radiating outward from the ring,
        # evenly spaced, slowly rotating (see `rotation` in
        # _render()). Filled triangles instead of thin lines so
        # they're actually visible at this icon's small size.
        spike_count = 4
        spike_length = 5
        spike_half_width = 2

        for i in range(spike_count):
            angle = math.radians(
                rotation + (360 / spike_count) * i
            )
            perpendicular = angle + (math.pi / 2)

            base_x = cx + ring_radius * math.cos(angle)
            base_y = cy + ring_radius * math.sin(angle)

            tip_x = cx + (
                ring_radius + spike_length
            ) * math.cos(angle)
            tip_y = cy + (
                ring_radius + spike_length
            ) * math.sin(angle)

            side1 = (
                base_x
                + spike_half_width * math.cos(perpendicular),
                base_y
                + spike_half_width * math.sin(perpendicular),
            )
            side2 = (
                base_x
                - spike_half_width * math.cos(perpendicular),
                base_y
                - spike_half_width * math.sin(perpendicular),
            )

            draw.polygon(
                [(tip_x, tip_y), side1, side2],
                fill=color,
            )

        # White-hot core, drawn last so it sits on top of everything.
        core_radius = 3

        draw.ellipse(
            (
                cx - core_radius,
                cy - core_radius,
                cx + core_radius,
                cy + core_radius,
            ),
            fill=(255, 255, 255, 255),
        )

    def _draw_panel(self, draw, width, height, rotation):
        radius = 10

        bg = (
            5,
            8,
            10,
            self.BG_ALPHA,
        )

        border = (
            58,
            214,
            255,
            self.BORDER_ALPHA,
        )

        draw.rounded_rectangle(
            (
                0,
                0,
                width - 1,
                height - 1,
            ),
            radius=radius,
            fill=bg,
            outline=border,
            width=1,
        )

        time_font = self._load_font(
            28,
            bold=True,
        )

        date_font = self._load_font(12)

        label_font = self._load_font(11)

        value_font = self._load_font(
            15,
            bold=True,
        )

        now = datetime.now()

        time_text = now.strftime(
            "%I:%M:%S %p"
        ).lstrip("0")

        date_text = now.strftime(
            "%a, %d %b"
        )

        draw.text(
            (24, 20),
            time_text,
            font=time_font,
            fill=self.CYAN,
        )

        draw.text(
            (24, 59),
            date_text,
            font=date_font,
            fill=self.DATE,
        )

        status = self._read_status()

        stats = [
            (
                "CPU",
                self._format_status(
                    status["cpu"]
                ),
            ),
            (
                "RAM",
                self._format_status(
                    status["ram"]
                ),
            ),
            (
                "DISK",
                self._format_status(
                    status["disk"]
                ),
            ),
        ]

        x_positions = [
            24,
            82,
            139,
        ]

        for index, (label, value) in enumerate(stats):
            x = x_positions[index]

            draw.text(
                (x, 96),
                label,
                font=label_font,
                fill=self.LABEL,
            )

            draw.text(
                (x, 111),
                value,
                font=value_font,
                fill=self.TEXT,
            )

        self._draw_reactor_icon(
            draw,
            width - 21,
            19,
            rotation,
        )

    def _format_status(self, value):
        if value is None:
            return "--%"

        return f"{round(value)}%"

    def _update_status(self):
        try:
            snapshot = self.status_provider()

            with self._status_lock:
                self._latest_status = {
                    "cpu": snapshot.get(
                        "cpu_percent"
                    ),
                    "ram": snapshot.get(
                        "memory_percent"
                    ),
                    "disk": snapshot.get(
                        "disk_percent"
                    ),
                }

        except Exception:
            pass

    def _read_status(self):
        with self._status_lock:
            return dict(self._latest_status)

    def _update_layered_window(self, image):
        width, height = image.size

        raw = image.tobytes(
            "raw",
            "BGRA",
        )

        class BITMAPINFOHEADER(
            ctypes.Structure
        ):
            _fields_ = [
                (
                    "biSize",
                    wintypes.DWORD,
                ),
                (
                    "biWidth",
                    wintypes.LONG,
                ),
                (
                    "biHeight",
                    wintypes.LONG,
                ),
                (
                    "biPlanes",
                    wintypes.WORD,
                ),
                (
                    "biBitCount",
                    wintypes.WORD,
                ),
                (
                    "biCompression",
                    wintypes.DWORD,
                ),
                (
                    "biSizeImage",
                    wintypes.DWORD,
                ),
                (
                    "biXPelsPerMeter",
                    wintypes.LONG,
                ),
                (
                    "biYPelsPerMeter",
                    wintypes.LONG,
                ),
                (
                    "biClrUsed",
                    wintypes.DWORD,
                ),
                (
                    "biClrImportant",
                    wintypes.DWORD,
                ),
            ]

        class BITMAPINFO(
            ctypes.Structure
        ):
            _fields_ = [
                (
                    "bmiHeader",
                    BITMAPINFOHEADER,
                ),
                (
                    "bmiColors",
                    wintypes.DWORD * 3,
                ),
            ]

        bmi = BITMAPINFO()

        bmi.bmiHeader.biSize = ctypes.sizeof(
            BITMAPINFOHEADER
        )
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        screen_dc = user32.GetDC(None)

        mem_dc = gdi32.CreateCompatibleDC(
            screen_dc
        )

        bits = ctypes.c_void_p()

        bitmap = gdi32.CreateDIBSection(
            screen_dc,
            ctypes.byref(bmi),
            0,
            ctypes.byref(bits),
            None,
            0,
        )

        if not bitmap:
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(
                None,
                screen_dc,
            )
            return

        ctypes.memmove(
            bits,
            raw,
            len(raw),
        )

        old_bitmap = gdi32.SelectObject(
            mem_dc,
            bitmap,
        )

        x, y = self._position()

        dst = POINT(x, y)
        size = SIZE(width, height)
        src = POINT(0, 0)

        blend = BLENDFUNCTION(
            AC_SRC_OVER,
            0,
            255,
            AC_SRC_ALPHA,
        )

        user32.UpdateLayeredWindow(
            self._hwnd,
            screen_dc,
            ctypes.byref(dst),
            ctypes.byref(size),
            mem_dc,
            ctypes.byref(src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )

        gdi32.SelectObject(
            mem_dc,
            old_bitmap,
        )

        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)

        user32.ReleaseDC(
            None,
            screen_dc,
        )

    def _drag_and_maybe_toggle(self, hwnd, is_icon_click):
        """
        Hands off to Windows' own window-move loop -- the standard
        trick for dragging a frameless window is faking a click on a
        title bar it doesn't actually have (WM_NCLBUTTONDOWN with
        HTCAPTION). That call blocks until the mouse is released
        regardless of whether the user actually moved it, so a
        before/after GetWindowRect comparison is what distinguishes a
        real drag from a stationary click here -- there's no other
        signal available from a single blocking call like this one.

        A drag updates _custom_position so future repaints keep the
        window where the user put it. A stationary click on the icon
        toggles collapsed/expanded, same as before; a stationary
        click elsewhere in the panel body does nothing, unchanged.
        """
        start_rect = RECT()
        user32.GetWindowRect(
            hwnd,
            ctypes.byref(start_rect),
        )

        user32.ReleaseCapture()

        user32.SendMessageW(
            hwnd,
            0x00A1,
            HTCAPTION,
            0,
        )

        end_rect = RECT()
        user32.GetWindowRect(
            hwnd,
            ctypes.byref(end_rect),
        )

        moved = (
            abs(end_rect.left - start_rect.left) > 2
            or abs(end_rect.top - start_rect.top) > 2
        )

        if moved:
            self._custom_position = (
                end_rect.left,
                end_rect.top,
            )
        elif is_icon_click:
            self.toggle_collapsed()

    def _window_proc(
        self,
        hwnd,
        msg,
        wparam,
        lparam,
    ):
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE

        if msg == WM_NCHITTEST:
            return HTCLIENT

        if msg == WM_LBUTTONDOWN:
            x = lparam & 0xFFFF
            y = (lparam >> 16) & 0xFFFF

            is_icon = self._collapsed or (
                x >= self.WIDTH - 40
                and y <= 40
            )

            self._drag_and_maybe_toggle(
                hwnd,
                is_icon,
            )

            return 0

        if msg == WM_TIMER:
            # Status is polled on a separate thread (see start() /
            # _status_loop()) precisely so this handler never blocks
            # on the 500ms psutil call -- it only needs to repaint
            # with whatever the latest cached reading is.
            self._render()
            return 0

        if msg == WM_DESTROY:
            self._stop.set()

            user32.KillTimer(
                hwnd,
                1,
            )

            user32.PostQuitMessage(0)

            return 0

        return user32.DefWindowProcW(
            hwnd,
            msg,
            wparam,
            lparam,
        )

    def _run(self):
        instance = kernel32.GetModuleHandleW(
            None
        )

        @WNDPROC
        def wnd_proc(
            hwnd,
            msg,
            wparam,
            lparam,
        ):
            return self._window_proc(
                hwnd,
                msg,
                wparam,
                lparam,
            )

        self._wnd_proc_ref = wnd_proc

        cursor = user32.LoadCursorW(
            None,
            ctypes.cast(IDC_ARROW, wintypes.LPCWSTR),
        )

        wnd_class = WNDCLASSW(
            0,
            wnd_proc,
            0,
            0,
            instance,
            None,
            cursor,
            None,
            None,
            self._class_name,
        )

        atom = user32.RegisterClassW(
            ctypes.byref(wnd_class)
        )

        if not atom:
            # ERROR_CLASS_ALREADY_EXISTS (1410) is harmless -- it just
            # means a previous run's class is still registered under
            # this process; CreateWindowExW works fine with it. Any
            # other error means CreateWindowExW is about to fail too,
            # so surface it now instead of failing silently below.
            error = kernel32.GetLastError()
            if error != 1410:
                print(
                    "[Jarvis overlay] RegisterClassW failed "
                    f"(error {error}) -- the overlay window will "
                    "not appear."
                )

        width, height = self._window_size()

        x, y = self._position()

        ex_style = (
            WS_EX_LAYERED
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )

        self._hwnd = user32.CreateWindowExW(
            ex_style,
            self._class_name,
            "Jarvis Overlay",
            WS_POPUP,
            x,
            y,
            width,
            height,
            None,
            None,
            instance,
            None,
        )

        if not self._hwnd:
            error = kernel32.GetLastError()
            print(
                "[Jarvis overlay] CreateWindowExW failed "
                f"(error {error}) -- the overlay window will "
                "not appear."
            )
            self._ready.set()
            return

        user32.SetWindowPos(
            self._hwnd,
            HWND_TOPMOST,
            x,
            y,
            width,
            height,
            SWP_NOACTIVATE
            | SWP_SHOWWINDOW,
        )

        self._update_status()
        self._render()

        user32.SetTimer(
            self._hwnd,
            1,
            1000,
            None,
        )

        self._ready.set()

        msg = wintypes.MSG()

        while not self._stop.is_set():
            result = user32.GetMessageW(
                ctypes.byref(msg),
                None,
                0,
                0,
            )

            if result <= 0:
                break

            user32.TranslateMessage(
                ctypes.byref(msg)
            )

            user32.DispatchMessageW(
                ctypes.byref(msg)
            )