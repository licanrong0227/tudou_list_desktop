"""WebView浏览器页面 - 独立子进程pywebview
pywebview 的 webview.start() 强制要求主线程调用，而主进程主线程已被Flet
事件循环占用，因此以独立子进程方式启动WebView窗口（WebView2渲染）。
子进程退出即视为窗口关闭。支持多台设备的窗口并存（按 device.ip 会话隔离）。
"""
import ctypes
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from ctypes import wintypes
from typing import Callable, Dict, List, Optional

from ..scanner import Device

# 项目根目录（web_page.py 位于 <root>/src/ui/ 下，需向上三级；保证子进程能以 -m src.webview_runner 方式导入包）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Win32 常量
_SW_RESTORE = 9


@dataclass
class _Session:
    """单个设备的WebView窗口会话"""
    proc: subprocess.Popen
    device: Device
    title: str


class WebViewWindow:
    """WebView窗口管理器（子进程方式，多窗口并存）"""

    def __init__(self):
        self._sessions: Dict[str, _Session] = {}  # device.ip -> 会话
        self._lock = threading.Lock()

    def is_device_open(self, device: Device) -> bool:
        """指定设备的WebView窗口是否处于打开状态"""
        with self._lock:
            session = self._sessions.get(device.ip)
            return session is not None and session.proc.poll() is None

    def has_open_windows(self) -> bool:
        """是否存在任一打开的WebView窗口"""
        with self._lock:
            return any(s.proc.poll() is None for s in self._sessions.values())

    def open_device(self, device: Device, on_close: Optional[Callable[[Device], None]] = None) -> bool:
        """打开设备共享页面（独立WebView子进程）

        返回 True 表示窗口真正启动；该设备窗口已处于打开状态时返回 False。
        on_close 在窗口关闭（子进程退出）时被调用，参数为对应的 device。

        注：打包EXE时（frozen）改为重启自身+参数判断（见 main.py 入口分发），
        开发阶段使用 sys.executable + -m 方式。
        """
        with self._lock:
            session = self._sessions.get(device.ip)
            if session is not None and session.proc.poll() is None:
                return False

        title = f"土豆 List - {device.device_name}"
        try:
            if getattr(sys, "frozen", False):
                # 打包模式：重启自身（exe），由 main.py 入口分发到 webview_runner
                proc = subprocess.Popen(
                    [sys.executable, "--webview-runner", device.url, title]
                )
            else:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "src.webview_runner",
                        device.url,
                        title
                    ],
                    cwd=_PROJECT_ROOT
                )
        except Exception as ex:
            # 不再静默吞异常：打印日志便于排查
            print(f"[webview] open error: {ex}", flush=True)
            return False

        with self._lock:
            self._sessions[device.ip] = _Session(proc=proc, device=device, title=title)

        def _wait():
            try:
                # 阻塞直到子进程退出（窗口关闭）
                proc.wait()
            except Exception as ex:
                print(f"[webview] wait error: {ex}", flush=True)
            finally:
                with self._lock:
                    # 仅当会话仍指向本进程时移除（防御：同IP新窗口已重建会话则保留）
                    current = self._sessions.get(device.ip)
                    if current is not None and current.proc is proc:
                        self._sessions.pop(device.ip, None)
                if on_close:
                    on_close(device)

        # 后台线程等待子进程，不阻塞调用方
        thread = threading.Thread(target=_wait, daemon=True, name=f"webview-wait-{device.ip}")
        thread.start()
        return True

    def focus(self, device: Device):
        """将指定设备的WebView窗口前置并获得焦点（不改变其尺寸状态）"""
        with self._lock:
            session = self._sessions.get(device.ip)
            if session is None or session.proc.poll() is not None:
                return
            pid = session.proc.pid

        hwnd = _find_main_window_by_pid(pid)
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        # 仅最小化时才还原（否则窗口不可见、聚焦无效果）；
        # 底层Z序/最大化的后台窗口保持原尺寸状态，只前置+获焦
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(hwnd)

    def close(self, device: Optional[Device] = None):
        """关闭WebView窗口（终止子进程）；device为None时关闭全部"""
        with self._lock:
            if device is None:
                sessions: List[_Session] = list(self._sessions.values())
            else:
                session = self._sessions.get(device.ip)
                sessions = [session] if session is not None else []
        for session in sessions:
            if session.proc.poll() is None:
                try:
                    session.proc.terminate()
                except Exception:
                    pass


def _find_main_window_by_pid(pid: int) -> int:
    """枚举顶层可见窗口，返回属于指定进程且带标题的主窗口句柄（无则返回0）

    按PID而非窗口标题定位：不同设备可能重名导致标题相同。
    顶层窗口（含WebView2宿主窗体）归属于python子进程本身。
    """
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(_callback, 0)
    return found[0] if found else 0
