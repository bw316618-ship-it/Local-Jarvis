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
WM_NCLBUTTONDOWN = 0x00A1

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
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
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


user32.RegisterClassW.argtypes = [
    ctypes.POINTER(WNDCLASSW)
]
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

user32.ShowWindow.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
]
user32.ShowWindow.restype = wintypes.BOOL

user32.GetSystemMetrics.argtypes = [
    ctypes.c_int
]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.LoadCursorW.argtypes = [
    wintypes.HINSTANCE,
    wintypes.LPCWSTR,
]
user32.LoadCursorW.restype = HCURSOR

user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    WPARAM,
    LPARAM,
]
user32.DefWindowProcW.restype = LRESULT

user32.DispatchMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG)
]
user32.DispatchMessageW.restype = LRESULT

user32.GetDC.argtypes = [
    wintypes.HWND
]
user32.GetDC.restype = wintypes.HDC

user32.ReleaseDC.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
]
user32.ReleaseDC.restype = ctypes.c_int

user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int

user32.KillTimer.argtypes = [
    wintypes.HWND,
    ctypes.c_size_t,
]
user32.KillTimer.restype = wintypes.BOOL

user32.PostMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    WPARAM,
    LPARAM,
]
user32.PostMessageW.restype = wintypes.BOOL

user32.PostQuitMessage.argtypes = [
    ctypes.c_int
]
user32.PostQuitMessage.restype = None

user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wintypes.BOOL

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

user32.TranslateMessage.argtypes = [
    ctypes.POINTER(wintypes.MSG)
]
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

user32.GetWindowRect.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(RECT),
]
user32.GetWindowRect.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [
    wintypes.HDC
]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP

gdi32.DeleteDC.argtypes = [
    wintypes.HDC
]
gdi32.DeleteDC.restype = wintypes.BOOL

gdi32.DeleteObject.argtypes = [
    wintypes.HGDIOBJ
]
gdi32.DeleteObject.restype = wintypes.BOOL

gdi32.SelectObject.argtypes = [
    wintypes.HDC,
    wintypes.HGDIOBJ,
]
gdi32.SelectObject.restype = wintypes.HGDIOBJ

kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD

kernel32.GetModuleHandleW.argtypes = [
    wintypes.LPCWSTR
]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class NativeOverlay:
    WIDTH = 360
    HEIGHT = 132

    COLLAPSED_SIZE = 32

    MARGIN = 24

    BG_ALPHA = 178
    BORDER_ALPHA = 105

    RENDER_INTERVAL_MS = 50

    CYAN = (58, 214, 255, 255)
    TEXT = (216, 246, 255, 255)
    DATE = (143, 185, 196, 255)
    LABEL = (111, 151, 162, 255)

    # Exact RGB conversion of storm3d.js's own constants -- its
    # default themeColor ("#e08a2e") and HOT_COLOR (0xfff6e0) -- so
    # the miniature icon actually matches the real storm's palette
    # rather than an approximation.
    STORM_THEME = (224, 138, 46, 255)
    STORM_AMBER = (255, 246, 224, 255)

    TIMER_ID = 1

    def __init__(self, status_provider):
        self.status_provider = status_provider

        self._thread = None
        self._status_thread = None

        self._ready = threading.Event()
        self._stop = threading.Event()

        self._hwnd = None
        self._wnd_proc_ref = None

        self._class_name = "JarvisNativeOverlay"

        self._collapsed = False
        self._visible = True

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

        self._stop.clear()

        self._thread = threading.Thread(
            target=self._run,
            name="JarvisNativeOverlay",
            daemon=True,
        )

        self._thread.start()

        self._ready.wait(timeout=5)

        if not self._hwnd:
            return

        self._status_thread = threading.Thread(
            target=self._status_loop,
            name="JarvisNativeOverlayStatus",
            daemon=True,
        )

        self._status_thread.start()

    def stop(self):
        self._stop.set()

        hwnd = self._hwnd

        if hwnd:
            user32.PostMessageW(
                hwnd,
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

    def is_visible(self):
        return self._visible

    def toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self._apply_window_geometry()
        self._render()

    def _status_loop(self):
        while not self._stop.is_set():
            self._update_status()
            self._stop.wait(timeout=1)

    def _screen_geometry(self):
        return (
            user32.GetSystemMetrics(0),
            user32.GetSystemMetrics(1),
        )

    def _window_size(self):
        if self._collapsed:
            return (
                self.COLLAPSED_SIZE,
                self.COLLAPSED_SIZE,
            )

        return (
            self.WIDTH,
            self.HEIGHT,
        )

    def _position(self):
        if self._custom_position is not None:
            return self._custom_position

        screen_width, _ = self._screen_geometry()

        width, _ = self._window_size()

        return (
            screen_width - width - self.MARGIN,
            self.MARGIN,
        )

    def _apply_window_geometry(self):
        if not self._hwnd:
            return

        width, height = self._window_size()
        x, y = self._position()

        user32.SetWindowPos(
            self._hwnd,
            HWND_TOPMOST,
            x,
            y,
            width,
            height,
            SWP_NOACTIVATE,
        )

    def _load_font(self, size, bold=False):
        filename = (
            "segoeuib.ttf"
            if bold
            else "segoeui.ttf"
        )

        path = Path(
            "C:/Windows/Fonts"
        ) / filename

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

        rotation = (
            time.time() * 6
        ) % 360

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

        self._update_layered_window(image)

    def _draw_reactor_icon(
        self,
        draw,
        cx,
        cy,
        rotation,
    ):
        """
        A miniature 2D re-interpretation of the HUD's own storm3d.js
        "living core" -- the same layered core (hot white -> amber
        HOT_COLOR -> theme-color glow) and the same idea of
        concentric rings rotating at different speeds/directions,
        using the real storm's actual default colors (its Three.js
        scene inits themeColor to "#e08a2e", not the app chrome's
        cyan accent).

        storm3d.js itself can't run here -- it's a live WebGL scene
        (four independent GPU particle rings, ~50 orbiting fragment
        sprites, canvas-generated glow textures, UnrealBloomPass
        post-processing), and this overlay is raw GDI/ctypes with no
        browser engine at all, by design (that's what makes its
        transparency actually reliable, unlike the earlier
        WebView2-based attempt). So this is a hand-authored miniature
        matching its structure and palette, not a literal port.
        """
        theme = self.STORM_THEME
        amber = self.STORM_AMBER

        # Layered core glow: soft theme-color outer, amber mid, hot
        # white center -- flattened 2D version of buildCore()'s three
        # additively-blended sprites in storm3d.js.
        draw.ellipse(
            (
                cx - 10,
                cy - 10,
                cx + 10,
                cy + 10,
            ),
            fill=(
                theme[0],
                theme[1],
                theme[2],
                55,
            ),
        )

        draw.ellipse(
            (
                cx - 6,
                cy - 6,
                cx + 6,
                cy + 6,
            ),
            fill=(
                amber[0],
                amber[1],
                amber[2],
                140,
            ),
        )

        draw.ellipse(
            (
                cx - 2,
                cy - 2,
                cx + 2,
                cy + 2,
            ),
            fill=(255, 255, 255, 255),
        )

        # Two concentric rings of small dots, rotating at different
        # speeds and in different directions -- a compact stand-in
        # for the real version's four independently-rotating particle
        # rings (90-190 particles each, unreadable at icon scale, so
        # this keeps just the differential-rotation structure that
        # actually reads at ~20px).
        rings = (
            # (radius, dot_count, speed_multiplier, dot_radius)
            (7, 7, 1.0, 0.9),
            (11, 9, -0.6, 0.7),
        )

        for (
            radius,
            count,
            speed,
            dot_radius,
        ) in rings:
            for index in range(count):
                angle = math.radians(
                    rotation * speed
                    + (360 / count) * index
                )

                x = cx + radius * math.cos(angle)
                y = cy + radius * math.sin(angle)

                draw.ellipse(
                    (
                        x - dot_radius,
                        y - dot_radius,
                        x + dot_radius,
                        y + dot_radius,
                    ),
                    fill=(
                        theme[0],
                        theme[1],
                        theme[2],
                        220,
                    ),
                )

    def _draw_panel(
        self,
        draw,
        width,
        height,
        rotation,
    ):
        draw.rounded_rectangle(
            (
                0,
                0,
                width - 1,
                height - 1,
            ),
            radius=10,
            fill=(
                5,
                8,
                10,
                self.BG_ALPHA,
            ),
            outline=(
                58,
                214,
                255,
                self.BORDER_ALPHA,
            ),
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

        draw.text(
            (24, 20),
            now.strftime(
                "%I:%M:%S %p"
            ).lstrip("0"),
            font=time_font,
            fill=self.CYAN,
        )

        draw.text(
            (24, 59),
            now.strftime("%a, %d %b"),
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

        for x, (label, value) in zip(
            (24, 82, 139),
            stats,
        ):
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

    @staticmethod
    def _format_status(value):
        if value is None:
            return "--%"

        return f"{round(value)}%"

    def _update_status(self):
        try:
            snapshot = self.status_provider()

            values = {
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

            with self._status_lock:
                self._latest_status = values

        except Exception as exc:
            print(
                f"[Jarvis overlay] "
                f"Status update failed: {exc}"
            )

    def _read_status(self):
        with self._status_lock:
            return dict(
                self._latest_status
            )

    def _update_layered_window(self, image):
        width, height = image.size

        raw = image.tobytes(
            "raw",
            "BGRA",
        )

        bmi = BITMAPINFO()

        bmi.bmiHeader.biSize = (
            ctypes.sizeof(
                BITMAPINFOHEADER
            )
        )
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        screen_dc = user32.GetDC(None)

        if not screen_dc:
            return

        mem_dc = gdi32.CreateCompatibleDC(
            screen_dc
        )

        if not mem_dc:
            user32.ReleaseDC(
                None,
                screen_dc,
            )
            return

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

        try:
            ctypes.memmove(
                bits,
                raw,
                len(raw),
            )

            old_bitmap = gdi32.SelectObject(
                mem_dc,
                bitmap,
            )

            if not old_bitmap:
                return

            x, y = self._position()

            destination = POINT(x, y)
            size = SIZE(width, height)
            source = POINT(0, 0)

            blend = BLENDFUNCTION(
                AC_SRC_OVER,
                0,
                255,
                AC_SRC_ALPHA,
            )

            user32.UpdateLayeredWindow(
                self._hwnd,
                screen_dc,
                ctypes.byref(destination),
                ctypes.byref(size),
                mem_dc,
                ctypes.byref(source),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )

            gdi32.SelectObject(
                mem_dc,
                old_bitmap,
            )

        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(
                None,
                screen_dc,
            )

    def _drag_and_maybe_toggle(
        self,
        hwnd,
        is_icon_click,
    ):
        start_rect = RECT()

        if not user32.GetWindowRect(
            hwnd,
            ctypes.byref(start_rect),
        ):
            return

        user32.ReleaseCapture()

        user32.SendMessageW(
            hwnd,
            WM_NCLBUTTONDOWN,
            HTCAPTION,
            0,
        )

        end_rect = RECT()

        if not user32.GetWindowRect(
            hwnd,
            ctypes.byref(end_rect),
        ):
            return

        moved = (
            abs(
                end_rect.left
                - start_rect.left
            ) > 2
            or abs(
                end_rect.top
                - start_rect.top
            ) > 2
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

            is_icon = (
                self._collapsed
                or (
                    x >= self.WIDTH - 40
                    and y <= 40
                )
            )

            self._drag_and_maybe_toggle(
                hwnd,
                is_icon,
            )

            return 0

        if msg == WM_TIMER:
            self._render()
            return 0

        if msg == WM_DESTROY:
            self._stop.set()

            user32.KillTimer(
                hwnd,
                self.TIMER_ID,
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
        instance = (
            kernel32.GetModuleHandleW(None)
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
            ctypes.cast(
                IDC_ARROW,
                wintypes.LPCWSTR,
            ),
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
            error = kernel32.GetLastError()

            if error != 1410:
                print(
                    "[Jarvis overlay] "
                    f"RegisterClassW failed: {error}"
                )

        width, height = self._window_size()
        x, y = self._position()

        ex_style = (
            WS_EX_LAYERED
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )

        self._hwnd = (
            user32.CreateWindowExW(
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
        )

        if not self._hwnd:
            error = kernel32.GetLastError()

            print(
                "[Jarvis overlay] "
                f"CreateWindowExW failed: {error}"
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
            self.TIMER_ID,
            self.RENDER_INTERVAL_MS,
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