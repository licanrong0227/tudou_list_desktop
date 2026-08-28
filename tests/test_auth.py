"""自测：验证 AuthManager 阻塞式授权请求协议（模拟安卓端）"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import AuthManager, AuthStatus


RESPONSE_MODE = {"mode": "accept", "delay": 1.0}
SEEN_PC_IDS = []


class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/api/auth/request":
            assert params.get("pc_id"), "缺少 pc_id 参数"
            assert params.get("pc_name"), "缺少 pc_name 参数"
            assert params.get("pc_ip"), "缺少 pc_ip 参数"
            SEEN_PC_IDS.append(params.get("pc_id")[0])

            threading.Event().wait(RESPONSE_MODE["delay"])

            if RESPONSE_MODE["mode"] == "accept":
                body = json.dumps({"auth_status": "accept", "save": False}).encode()
                self.send_response(200)
            elif RESPONSE_MODE["mode"] == "reject":
                body = json.dumps({"auth_status": "reject"}).encode()
                self.send_response(200)
            else:
                body = json.dumps({"auth_status": "timeout"}).encode()
                self.send_response(408)

            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


def set_mode(mode, delay=0.5):
    RESPONSE_MODE["mode"] = mode
    RESPONSE_MODE["delay"] = delay


def main():
    server = HTTPServer(("127.0.0.1", 9527), AuthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    mgr = AuthManager()

    # 测试1: accept
    set_mode("accept")
    r = mgr.request_auth("http://127.0.0.1:9527")
    assert r.status == AuthStatus.ACCEPT, f"accept 测试失败: {r.status} {r.message}"
    print("[OK] accept: ", r.message)

    # 测试2: reject
    set_mode("reject")
    r = mgr.request_auth("http://127.0.0.1:9527")
    assert r.status == AuthStatus.REJECT, f"reject 测试失败: {r.status} {r.message}"
    print("[OK] reject: ", r.message)

    # 测试3: 408 timeout
    set_mode("timeout")
    r = mgr.request_auth("http://127.0.0.1:9527")
    assert r.status == AuthStatus.TIMEOUT, f"timeout 测试失败: {r.status} {r.message}"
    print("[OK] timeout: ", r.message)

    # 测试4: 端口不通 -> 超时
    r = mgr.request_auth("http://127.0.0.1:9999")
    assert r.status in (AuthStatus.TIMEOUT, AuthStatus.ERROR), f"不可达测试失败: {r.status} {r.message}"
    print("[OK] unreachable: ", r.status.value, r.message)

    # 测试5: pc_id 跨请求稳定（同一设备身份，与IP无关）
    assert SEEN_PC_IDS, "未收集到任何 pc_id"
    assert len(set(SEEN_PC_IDS)) == 1, f"pc_id 跨请求不一致: {SEEN_PC_IDS}"
    print("[OK] pc_id stable:", SEEN_PC_IDS[0])

    print("all auth tests passed")
    server.shutdown()


if __name__ == "__main__":
    main()