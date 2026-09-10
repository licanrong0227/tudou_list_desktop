"""剪贴板同步模块
仅保留移动端→PC端的图片接收功能。
适配移动端新接口：心跳检测 + 最新图片查询。
"""
import ctypes
import io
import threading
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

POLL_INTERVAL = 2.0
REQUEST_TIMEOUT = 5.0
IMAGE_DOWNLOAD_TIMEOUT = 30.0

HEARTBEAT_PATH = "/api/heartbeat"
LATEST_PHOTO_PATH = "/api/photos/latest"
DOWNLOAD_IMAGE_PATH = "/api/photos/{photo_id}/full"

CF_DIB = 8
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.EmptyClipboard.argtypes = []
_user32.EmptyClipboard.restype = wintypes.BOOL
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.CloseClipboard.argtypes = []
_user32.CloseClipboard.restype = wintypes.BOOL

_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalUnlock.restype = wintypes.BOOL
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalFree.restype = wintypes.HGLOBAL


def _log(msg: str):
    print(f"[clipboard] {msg}", flush=True)


@dataclass
class _DeviceSession:
    device_url: str
    device_name: str
    stop_event: threading.Event
    last_photo_count: int = -1
    poll_thread: Optional[threading.Thread] = None


class ClipboardSyncManager:
    def __init__(self, on_image_received: Optional[Callable[[str, bytes], None]] = None):
        self._sessions: Dict[str, _DeviceSession] = {}
        self._lock = threading.Lock()
        self._on_image_received = on_image_received

    def start_device(self, device_url: str, device_name: str):
        with self._lock:
            if device_url in self._sessions:
                return
            stop_event = threading.Event()
            session = _DeviceSession(device_url=device_url, device_name=device_name, stop_event=stop_event)
            poll_thread = threading.Thread(
                target=self._poll_phone_clipboard, args=(session,),
                daemon=True, name=f"clip-{device_name}",
            )
            session.poll_thread = poll_thread
            self._sessions[device_url] = session
        poll_thread.start()
        _log(f"开始同步: {device_name} ({device_url})")

    def stop_device(self, device_url: str):
        with self._lock:
            session = self._sessions.pop(device_url, None)
        if session:
            session.stop_event.set()
            _log(f"停止同步: {session.device_name}")

    def stop_all(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.stop_event.set()

    def _poll_phone_clipboard(self, session: _DeviceSession):
        _log(f"轮询线程启动: {session.device_name}")
        while not session.stop_event.is_set():
            try:
                hb_resp = requests.get(
                    f"{session.device_url}{HEARTBEAT_PATH}",
                    timeout=REQUEST_TIMEOUT, verify=False,
                )
                if hb_resp.status_code == 200:
                    hb_data = hb_resp.json()
                    current_count = hb_data.get("pc", -1)

                    if current_count > 0 and current_count != session.last_photo_count:
                        session.last_photo_count = current_count
                        latest_resp = requests.get(
                            f"{session.device_url}{LATEST_PHOTO_PATH}",
                            timeout=REQUEST_TIMEOUT, verify=False,
                        )
                        if latest_resp.status_code == 200:
                            latest_data = latest_resp.json()
                            photo_id = latest_data.get("id", "")
                            if photo_id:
                                file_name = latest_data.get("name", f"{photo_id}.jpg")
                                image_bytes = _download_image(session.device_url, photo_id)
                                if image_bytes:
                                    ok = _win_set_clipboard_image(image_bytes)
                                    _log(f"收到图片 → 写入剪贴板{'成功' if ok else '失败'}: {file_name}")
                                    if ok and self._on_image_received:
                                        try:
                                            self._on_image_received(session.device_name, image_bytes)
                                        except Exception as ex:
                                            _log(f"on_image_received 回调异常: {ex}")
            except requests.RequestException as ex:
                _log(f"轮询网络异常: {ex}")
            except Exception as ex:
                _log(f"轮询未知异常: {ex}")
            session.stop_event.wait(POLL_INTERVAL)
        _log(f"轮询线程退出: {session.device_name}")


def _download_image(device_url: str, photo_id: str) -> Optional[bytes]:
    try:
        url = f"{device_url}{DOWNLOAD_IMAGE_PATH.format(photo_id=photo_id)}"
        resp = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT, verify=False)
        if resp.status_code == 200:
            return resp.content
    except requests.RequestException as ex:
        _log(f"下载图片失败: {ex}")
    return None


def _win_set_clipboard_image(image_bytes: bytes) -> bool:
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(image_bytes))
        output = io.BytesIO()
        image.convert("RGB").save(output, "BMP")
        dib_data = output.getvalue()[14:]
        output.close()

        if not _user32.OpenClipboard(None):
            return False
        try:
            _user32.EmptyClipboard()
            h_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(dib_data))
            if not h_mem:
                return False
            ptr = _kernel32.GlobalLock(h_mem)
            if not ptr:
                _kernel32.GlobalFree(h_mem)
                return False
            ctypes.memmove(ptr, dib_data, len(dib_data))
            _kernel32.GlobalUnlock(h_mem)
            _user32.SetClipboardData(CF_DIB, h_mem)
            return True
        finally:
            _user32.CloseClipboard()
    except Exception as ex:
        _log(f"写入图片剪贴板异常: {ex}")
        return False
