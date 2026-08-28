"""冒烟测试：验证子进程方式打开WebView窗口完整链路（多窗口并存）"""
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scanner import Device
from src.ui.web_page import WebViewWindow

closed_devices = []  # on_close 收到的设备ip（按触发顺序）
closed_lock = threading.Lock()


class PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><body><h1>mock device page</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    server_a = HTTPServer(("127.0.0.1", 19527), PageHandler)
    server_b = HTTPServer(("127.0.0.1", 19528), PageHandler)
    for s in (server_a, server_b):
        threading.Thread(target=s.serve_forever, daemon=True).start()

    # 127.0.0.2 同属回环段（Windows 默认可用），用于让两台设备 ip 不同、窗口可并存
    device_a = Device(
        ip="127.0.0.1", port=19527,
        device_name="MockDeviceA", device_type="android_share",
        timestamp="0", scheme="http"
    )
    device_b = Device(
        ip="127.0.0.2", port=19528,
        device_name="MockDeviceB", device_type="android_share",
        timestamp="0", scheme="http"
    )

    wv = WebViewWindow()

    def on_close(device):
        with closed_lock:
            closed_devices.append(device.ip)

    opened_a = wv.open_device(device_a, on_close=on_close)
    opened_b = wv.open_device(device_b, on_close=on_close)
    print(f"open A -> {opened_a} (expect True)")
    print(f"open B -> {opened_b} (expect True)")
    time.sleep(3)  # 等待两个窗口出现

    # 重复打开同一设备应返回 False
    opened_dup = wv.open_device(device_a, on_close=on_close)
    print(f"open A again -> {opened_dup} (expect False)")

    alive_a = wv.is_device_open(device_a)
    alive_b = wv.is_device_open(device_b)
    print(f"A alive after 3s: {alive_a}")
    print(f"B alive after 3s: {alive_b}")

    # 聚焦冒烟（Win32 按PID定位 + 还原/前置）
    wv.focus(device_a)
    wv.focus(device_b)
    print("focus A/B called")

    # 关闭 A：仅 A 触发回调，B 不受影响
    wv.close(device_a)
    time.sleep(2)
    print(f"closed after A close: {closed_devices} (expect ['127.0.0.1'])")
    print(f"A is_open after close: {wv.is_device_open(device_a)} (expect False)")
    print(f"B still open: {wv.is_device_open(device_b)} (expect True)")
    print(f"has_open_windows: {wv.has_open_windows()} (expect True)")

    # 关闭 B：全部窗口退出
    wv.close(device_b)
    time.sleep(2)
    print(f"closed after B close: {closed_devices} (expect both)")
    print(f"has_open_windows: {wv.has_open_windows()} (expect False)")

    ok = (
        opened_a and opened_b and not opened_dup
        and alive_a and alive_b
        and closed_devices == [device_a.ip, device_b.ip]
        and not wv.is_device_open(device_a)
        and not wv.is_device_open(device_b)
        and not wv.has_open_windows()
    )

    if ok:
        print("WEBVIEW SUBPROCESS TEST PASSED")
    else:
        print("WEBVIEW SUBPROCESS TEST FAILED")
        sys.exit(1)
    server_a.shutdown()
    server_b.shutdown()


if __name__ == "__main__":
    main()
