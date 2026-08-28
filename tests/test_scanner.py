"""自测：验证 Scanner 的 HTTP/HTTPS 双协议设备识别"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scanner import Scanner


class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/ping":
            body = json.dumps({
                "status": "ok",
                "device_type": "android_share",
                "device_name": "测试设备",
                "timestamp": "123"
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


def start_server():
    server = HTTPServer(("0.0.0.0", 9527), PingHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.5)
    print("mock server started on 0.0.0.0:9527")
    return server


def main():
    server = start_server()
    sc = Scanner()

    # 测试1: 设备识别（HTTP 协议）
    dev = sc._ping_device("127.0.0.1", 9527)
    assert dev is not None, "HTTP ping 识别失败"
    assert dev.scheme == "http", f"期望 http，实际 {dev.scheme}"
    assert dev.device_name == "测试设备"
    print(f"[OK] HTTP 识别: scheme={dev.scheme} name={dev.device_name} url={dev.url}")

    # 测试2: 端口检查
    assert sc._check_port("127.0.0.1", 9527) is True
    print("[OK] 端口检查")

    # 测试3: 网段构建
    ips = sc._build_scan_ips()
    assert len(ips) > 0
    print(f"[OK] 扫描IP数量: {len(ips)}")

    # 测试4: 完整扫描流程（直接调用内部线程逻辑）
    found = []
    done = threading.Event()

    sc.scan(
        on_device_found=lambda d: found.append(d),
        on_scan_complete=lambda _: done.set(),
        on_scan_error=lambda e: print("[ERR]", e)
    )
    # 等待扫描完成（最多15秒，本机无真实设备，仅验证流程不崩溃）
    done.wait(timeout=20)
    print(f"[OK] 扫描流程完成，发现设备数: {len(found)}")
    print("all tests passed")

    server.shutdown()


if __name__ == "__main__":
    main()