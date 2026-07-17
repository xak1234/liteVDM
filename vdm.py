"""
vdm.py - Floating Virtual Desktop Manager for Windows 10/11
Left-click pane: switch | Double-click: restore saved apps | Middle-click: close desktop
Right-click pane: move open windows here | "+": new desktop | Drag: move manager
Sessions (open apps per desktop) auto-saved to sessions.json every few seconds.
Run via vdm.cmd or directly with Python 3.
"""

import ctypes
import json
import os
import subprocess
import sys
import time
import tkinter as tk
from ctypes import wintypes

import mss
from PIL import Image, ImageTk, ImageDraw, ImageFont
from pyvda import AppView, VirtualDesktop, get_virtual_desktops, get_apps_by_z_order

# ---------- config ----------
PANE_W, PANE_H = 160, 90
PAD            = 4
POLL_MS        = 1000
SNAPSHOT_EVERY = 5          # save sessions every N ticks
ALPHA          = 0.93
BORDER_ACTIVE  = "#00b7ff"
BORDER_IDLE    = "#3a3a3a"
BG             = "#1e1e1e"
DRAG_THRESHOLD = 6
LAUNCH_WATCH_SECONDS = 12
SESSIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "sessions.json")
EXE_BLOCKLIST = {"applicationframehost.exe", "textinputhost.exe",
                 "systemsettings.exe", "searchhost.exe",
                 "shellexperiencehost.exe", "startmenuexperiencehost.exe",
                 "lockapp.exe"}
# ----------------------------

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GW_OWNER = 4

# ctypes defaults pointer-sized Win32 return values to 32-bit integers unless
# told otherwise, which can truncate HWND/HANDLE values on 64-bit Windows.
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = (
    wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
kernel32.OpenProcess.argtypes = (
    wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD))
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL


def pid_exe_for_hwnd(hwnd):
    """Return (pid, full exe path) for a window handle, or (None, None)."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None, None
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFO
    if not h:
        return pid.value, None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return pid.value, buf.value
    finally:
        kernel32.CloseHandle(h)
    return pid.value, None


def title_for_hwnd(hwnd):
    """Return a useful, single-line label for a window."""
    length = user32.GetWindowTextLengthW(hwnd)
    if length:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = " ".join(buf.value.split())
        if title:
            return title
    _pid, exe = pid_exe_for_hwnd(hwnd)
    return os.path.basename(exe) if exe else f"Window {hwnd}"


def movable_windows(switcher_windows=True):
    """Return user windows as (AppView, desktop number, exe, title)."""
    result = []
    me = os.getpid()
    try:
        apps = get_apps_by_z_order(switcher_windows=switcher_windows,
                                   current_desktop=False)
    except Exception:
        return result
    for app in apps:
        pid, exe = pid_exe_for_hwnd(app.hwnd)
        if not exe or pid == me:
            continue
        if os.path.basename(exe).lower() in EXE_BLOCKLIST:
            continue
        try:
            desktop = app.desktop.number
        except Exception:
            continue                    # pinned / all-desktops windows
        result.append((app, desktop, exe, title_for_hwnd(app.hwnd)))
    return result


def apps_by_desktop():
    """Map desktop number -> ordered unique exe list, skipping self/junk."""
    out = {}
    for _app, n, exe, _title in movable_windows():
        lst = out.setdefault(n, [])
        if exe not in lst:
            lst.append(exe)
    return out


class VDM:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", ALPHA)
        self.root.configure(bg=BG)
        self.root.geometry("+40+40")

        self.sct = mss.MSS()
        self.mon = self.sct.monitors[1]

        self.thumbs = {}
        self.photos = {}
        self.panes  = {}
        self.count  = 0
        self._ticks = 0
        self._last_external_hwnd = None
        self._launch_watches = []

        self.sessions = {}
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                self.sessions = json.load(f)
        except Exception:
            pass

        self._press = None
        self._dragging = False

        self.frame = tk.Frame(self.root, bg=BG)
        self.frame.pack(padx=PAD, pady=PAD)

        self.root.bind("<Button-3>", self.on_context)
        self.tick()
        self.root.mainloop()

    def placeholder(self, n):
        img = Image.new("RGB", (PANE_W, PANE_H), "#2b2b2b")
        d = ImageDraw.Draw(img)
        try:
            f = ImageFont.truetype("segoeui.ttf", 36)
        except OSError:
            f = ImageFont.load_default()
        txt = str(n)
        bbox = d.textbbox((0, 0), txt, font=f)
        d.text(((PANE_W - bbox[2]) / 2, (PANE_H - bbox[3]) / 2),
               txt, fill="#777777", font=f)
        return img

    def rebuild(self, count):
        for w in self.frame.winfo_children():
            w.destroy()
        self.panes.clear()
        for i in range(1, count + 1):
            lbl = tk.Label(self.frame, bd=2, relief="solid", bg=BORDER_IDLE)
            lbl.grid(row=0, column=i - 1, padx=(0 if i == 1 else PAD, 0))
            lbl.desktop_number = i
            lbl.bind("<ButtonPress-1>",    self.on_press)
            lbl.bind("<B1-Motion>",        self.on_motion)
            lbl.bind("<ButtonRelease-1>",  self.on_release)
            lbl.bind("<Double-Button-1>",  self.on_double)
            lbl.bind("<Button-2>",         self.on_middle)
            lbl.bind("<Button-3>",         self.on_context)
            self.panes[i] = lbl
        add = tk.Label(self.frame, text="+", font=("Segoe UI", 22, "bold"),
                       fg="#888888", bg="#2b2b2b", width=2,
                       height=1, bd=2, relief="solid")
        add.grid(row=0, column=count, padx=(PAD, 0), sticky="ns")
        add.is_add = True
        add.bind("<ButtonPress-1>",   self.on_press)
        add.bind("<B1-Motion>",       self.on_motion)
        add.bind("<ButtonRelease-1>", self.on_release)
        add.bind("<Button-3>",        self.on_context)
        self.count = count

    def on_press(self, e):
        self._press = (e.x_root, e.y_root,
                       self.root.winfo_x(), self.root.winfo_y())
        self._dragging = False

    def on_motion(self, e):
        if not self._press:
            return
        px, py, wx, wy = self._press
        dx, dy = e.x_root - px, e.y_root - py
        if abs(dx) > DRAG_THRESHOLD or abs(dy) > DRAG_THRESHOLD:
            self._dragging = True
        if self._dragging:
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def on_release(self, e):
        if not self._dragging and getattr(e.widget, "is_add", False):
            try:
                VirtualDesktop.create()
            except Exception as ex:
                print("create failed:", ex)
            self._press = None
            return
        if not self._dragging and hasattr(e.widget, "desktop_number"):
            n = e.widget.desktop_number
            try:
                if VirtualDesktop.current().number != n:
                    VirtualDesktop(n).go()
            except Exception as ex:
                print("switch failed:", ex)
        self._press = None
        self._dragging = False

    def on_double(self, e):
        """Double-click a pane: restore that desktop's saved apps."""
        if hasattr(e.widget, "desktop_number"):
            self.restore(e.widget.desktop_number)

    def on_middle(self, e):
        """Middle-click a pane to close that desktop (never the last one)."""
        if not hasattr(e.widget, "desktop_number"):
            return
        self.remove_desktop(e.widget.desktop_number)

    def move_window(self, hwnd, target):
        """Move one window to a desktop without switching desktops."""
        try:
            AppView(hwnd=hwnd).move(VirtualDesktop(target))
        except Exception as ex:
            print("move failed:", hwnd, "to desktop", target, ex)

    def move_desktop_windows(self, source, target):
        for app, desktop, _exe, _title in movable_windows():
            if desktop == source:
                self.move_window(app.hwnd, target)

    def remove_desktop(self, n):
        try:
            if len(get_virtual_desktops()) <= 1:
                return
            VirtualDesktop(n).remove()
            self.thumbs.pop(n, None)
            self.thumbs = {(k - 1 if k > n else k): v
                           for k, v in self.thumbs.items()}
        except Exception as ex:
            print("remove failed:", ex)

    def on_context(self, e):
        """Right-click a desktop to send any open window to it."""
        menu = tk.Menu(self.root, tearoff=False)
        target = getattr(e.widget, "desktop_number", None)
        if target is not None:
            menu.add_command(label=f"Desktop {target}", state="disabled")
            if self._last_external_hwnd:
                label = title_for_hwnd(self._last_external_hwnd)
                menu.add_command(
                    label=f"Move active here: {label[:45]}",
                    command=lambda h=self._last_external_hwnd, n=target:
                        self.move_window(h, n))

            window_menu = tk.Menu(menu, tearoff=False)
            candidates = [item for item in movable_windows()
                          if item[1] != target]
            if candidates:
                for app, desktop, _exe, title in candidates:
                    window_menu.add_command(
                        label=f"D{desktop}  {title[:60]}",
                        command=lambda h=app.hwnd, n=target:
                            self.move_window(h, n))
            else:
                window_menu.add_command(label="No windows on other desktops",
                                        state="disabled")
            menu.add_cascade(label="Move a window here", menu=window_menu)

            source_menu = tk.Menu(menu, tearoff=False)
            sources = sorted({desktop for _app, desktop, _exe, _title
                              in candidates})
            if sources:
                for source in sources:
                    source_menu.add_command(
                        label=f"Desktop {source}",
                        command=lambda s=source, n=target:
                            self.move_desktop_windows(s, n))
            else:
                source_menu.add_command(label="No other desktops with windows",
                                        state="disabled")
            menu.add_cascade(label="Move all windows here from",
                             menu=source_menu)
            menu.add_separator()
            menu.add_command(label="Close this desktop",
                             command=lambda n=target: self.remove_desktop(n))
        else:
            menu.add_command(label="New desktop", command=VirtualDesktop.create)
        menu.add_separator()
        menu.add_command(label="Quit VDM", command=self.root.destroy)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()
        return "break"

    def keep_owned_windows_together(self):
        """Move dialogs/response windows back beside their owner window."""
        for app, desktop, _exe, _title in movable_windows(
                switcher_windows=False):
            owner = user32.GetWindow(app.hwnd, GW_OWNER)
            if not owner:
                continue
            try:
                owner_desktop = AppView(hwnd=owner).desktop.number
            except Exception:
                continue
            if desktop != owner_desktop:
                self.move_window(app.hwnd, owner_desktop)

    def watch_launch(self, exe, target):
        """Track new windows from a restore launch and force their desktop."""
        norm = os.path.normcase(os.path.abspath(exe))
        existing = {app.hwnd for app, _desktop, path, _title
                    in movable_windows(switcher_windows=False)
                    if os.path.normcase(os.path.abspath(path)) == norm}
        self._launch_watches.append({
            "exe": norm,
            "target": target,
            "known": existing,
            "until": time.monotonic() + LAUNCH_WATCH_SECONDS,
        })

    def enforce_launch_desktops(self):
        now = time.monotonic()
        windows = movable_windows(switcher_windows=False)
        active = []
        for watch in self._launch_watches:
            if watch["until"] < now:
                continue
            for app, desktop, exe, _title in windows:
                if os.path.normcase(os.path.abspath(exe)) != watch["exe"]:
                    continue
                if app.hwnd not in watch["known"]:
                    watch["known"].add(app.hwnd)
                    if desktop != watch["target"]:
                        self.move_window(app.hwnd, watch["target"])
            active.append(watch)
        self._launch_watches = active

    def restore(self, n):
        saved = self.sessions.get(str(n), [])
        if not saved:
            return
        try:
            if VirtualDesktop.current().number != n:
                VirtualDesktop(n).go()
        except Exception:
            return
        open_windows = movable_windows()
        already = {os.path.normcase(exe) for _app, desktop, exe, _title
                   in open_windows if desktop == n}
        for exe in saved:
            norm = os.path.normcase(exe)
            if norm in already or not os.path.exists(exe):
                continue
            # Singleton apps often reactivate a window on another desktop.
            # Reuse that window directly instead of asking the app to launch it.
            elsewhere = next((app for app, _desktop, path, _title
                              in open_windows
                              if os.path.normcase(path) == norm), None)
            if elsewhere:
                self.move_window(elsewhere.hwnd, n)
                already.add(norm)
                continue
            try:
                self.watch_launch(exe, n)
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
            except Exception as ex:
                print("launch failed:", exe, ex)

    def snapshot(self):
        """Merge live app map into sessions; never wipe a desktop's saved
        list just because it's momentarily empty. Persist if changed."""
        live = apps_by_desktop()
        changed = False
        for n, exes in live.items():
            if exes and self.sessions.get(str(n)) != exes:
                self.sessions[str(n)] = exes
                changed = True
        if changed:
            try:
                with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.sessions, f, indent=1)
            except Exception as ex:
                print("session save failed:", ex)

    def tick(self):
        try:
            desktops = get_virtual_desktops()
            cur = VirtualDesktop.current().number
        except Exception as ex:
            print("pyvda error:", ex)
            self.root.after(POLL_MS * 3, self.tick)
            return

        if len(desktops) != self.count:
            self.rebuild(len(desktops))

        foreground = user32.GetForegroundWindow()
        pid, _exe = (pid_exe_for_hwnd(foreground)
                     if foreground else (None, None))
        if foreground and pid and pid != os.getpid():
            self._last_external_hwnd = foreground

        self.keep_owned_windows_together()
        self.enforce_launch_desktops()

        try:
            shot = self.sct.grab(self.mon)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            img.thumbnail((PANE_W, PANE_H))
            self.thumbs[cur] = img
        except Exception:
            pass

        self._ticks += 1
        if self._ticks % SNAPSHOT_EVERY == 0:
            self.snapshot()

        for n, lbl in self.panes.items():
            img = self.thumbs.get(n) or self.placeholder(n)
            self.photos[n] = ImageTk.PhotoImage(img)
            lbl.configure(image=self.photos[n],
                          bg=BORDER_ACTIVE if n == cur else BORDER_IDLE)

        self.root.after(POLL_MS, self.tick)


if __name__ == "__main__":
    VDM()
