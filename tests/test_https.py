"""自测：验证 Scanner 的 HTTPS 自签名证书设备识别"""
import json
import os
import ssl
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
                "device_name": "HTTPS设备",
                "timestamp": "456"
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


def generate_self_signed():
    """使用openssl生成自签名证书（若存在openssl）"""
    cert = os.path.join(os.environ.get("TEMP", "."), "test_cert.pem")
    key = os.path.join(os.environ.get("TEMP", "."), "test_key.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        os.system(
            f'openssl req -x509 -newkey rsa:2048 -nodes '
            f'-keyout "{key}" -out "{cert}" -days 1 -subj "/CN=test" 2>nul'
        )
    return cert, key


def main():
    cert, key = generate_self_signed()
    if not (os.path.exists(cert) and os.path.exists(key)):
        print("SKIP: openssl not available for HTTPS test")
        return

    server = HTTPServer(("0.0.0.0", 9527), PingHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.5)

    sc = Scanner()
    dev = sc._ping_device("127.0.0.1", 9527)
    assert dev is not None, "HTTPS ping 识别失败"
    assert dev.scheme == "https", f"期望 https，实际 {dev.scheme}"
    assert dev.device_name == "HTTPS设备"
    print(f"[OK] HTTPS 识别: scheme={dev.scheme} name={dev.device_name} url={dev.url}")
    print("all tests passed")
    server.shutdown()


if __name__ == "__main__":
    main()