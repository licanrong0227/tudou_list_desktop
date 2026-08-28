"""局域网扫描模块"""
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Callable, Optional
import requests
import urllib3

# 抑制自签名HTTPS证书的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .utils import get_network_prefixes, get_all_local_ips


# 扫描配置
SCAN_PORT = 9527
MAX_CONCURRENT = 100
CONNECT_TIMEOUT = 0.4
REQUEST_TIMEOUT = 1.0
PING_PATH = "/api/ping"
DEVICE_TYPE_KEY = "android_share"


@dataclass
class Device:
    """设备信息"""
    ip: str
    port: int
    device_name: str
    device_type: str
    timestamp: str
    scheme: str = "http"  # http 或 https

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.ip}:{self.port}"

    @property
    def display_address(self) -> str:
        return f"{self.scheme}://{self.ip}:{self.port}"


class Scanner:
    """局域网设备扫描器"""

    def __init__(self):
        self._is_scanning = False
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._own_ips: set = set()

    @property
    def is_scanning(self) -> bool:
        return self._is_scanning

    def _check_port(self, ip: str, port: int) -> bool:
        """检查端口是否开放"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _ping_device(self, ip: str, port: int) -> Optional[Device]:
        """通过/api/ping接口识别设备
        同一IP只会是HTTP或HTTPS其中一种（安卓端服务二选一启动，不会两者皆是），
        因此并行发起两种协议探测，任一协议识别成功立即返回，不等待另一协议超时
        """
        if self._cancel_event.is_set():
            return None

        success = threading.Event()
        found: List[Device] = []

        def _try(scheme: str):
            if self._cancel_event.is_set() or success.is_set():
                return
            try:
                url = f"{scheme}://{ip}:{port}{PING_PATH}"
                # HTTPS 使用自签名证书，需关闭证书校验
                response = requests.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    verify=False
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("device_type") == DEVICE_TYPE_KEY and not success.is_set():
                        found.append(Device(
                            ip=ip,
                            port=port,
                            device_name=data.get("device_name", "未知设备"),
                            device_type=data.get("device_type", ""),
                            timestamp=data.get("timestamp", ""),
                            scheme=scheme
                        ))
                        success.set()
            except (requests.RequestException, ValueError, KeyError):
                pass

        # HTTP 与 HTTPS 并行探测（端口协议二选一，仅一个会成功）
        threads = [
            threading.Thread(target=_try, args=(scheme,), daemon=True)
            for scheme in ("http", "https")
        ]
        for t in threads:
            t.start()

        # 任一协议成功立即返回；上限略大于单请求超时，兜底防挂起
        success.wait(timeout=REQUEST_TIMEOUT + 0.5)
        return found[0] if found else None

    def _scan_single_ip(self, ip: str) -> Optional[Device]:
        """扫描单个IP"""
        if self._cancel_event.is_set():
            return None

        # 先检查端口
        if not self._check_port(ip, SCAN_PORT):
            return None

        # 端口开放，尝试ping识别
        return self._ping_device(ip, SCAN_PORT)

    def _build_scan_ips(self) -> List[str]:
        """构建待扫描IP列表（遍历所有网段，去重）
        全段扫描 + 高并发（实测254 IP约1.2秒），不依赖ARP表（ARP会漏掉未通信过的设备）
        """
        scan_ips: List[str] = []
        for prefix in get_network_prefixes():
            for i in range(1, 255):
                ip = f"{prefix}.{i}"
                if ip not in scan_ips:
                    scan_ips.append(ip)
        return scan_ips

    def scan(
        self,
        on_device_found: Callable[[Device], None],
        on_scan_complete: Callable[[List[Device]], None],
        on_scan_start: Optional[Callable[[], None]] = None,
        on_scan_error: Optional[Callable[[str], None]] = None
    ):
        """开始扫描局域网设备"""
        with self._lock:
            if self._is_scanning:
                return
            self._is_scanning = True

        # 重置取消事件
        self._cancel_event.clear()

        # 记录本机IP，扫描时跳过自身
        self._own_ips = set(get_all_local_ips())

        # 通知扫描开始
        if on_scan_start:
            on_scan_start()

        def _scan_thread():
            try:
                scan_ips = [ip for ip in self._build_scan_ips()
                            if ip not in self._own_ips]

                devices: List[Device] = []

                # 使用线程池并发扫描
                with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
                    future_to_ip = {
                        executor.submit(self._scan_single_ip, ip): ip
                        for ip in scan_ips
                    }

                    for future in as_completed(future_to_ip):
                        if self._cancel_event.is_set():
                            break

                        try:
                            device = future.result()
                            if device:
                                devices.append(device)
                                on_device_found(device)
                        except Exception as ex:
                            print(f"[scanner] scan error: {ex}", flush=True)

                # 扫描完成
                on_scan_complete(devices)

            except Exception as e:
                if on_scan_error:
                    on_scan_error(str(e))
            finally:
                self._is_scanning = False

        # 启动扫描线程
        thread = threading.Thread(target=_scan_thread, daemon=True)
        thread.start()