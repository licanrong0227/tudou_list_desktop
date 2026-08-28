"""工具函数模块"""
import ipaddress
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import uuid
from typing import List, Optional, Tuple

# 子进程隐藏窗口标志：无控制台（打包exe）环境下调用 ipconfig/arp 等命令时，
# 若不指定该标志，每次调用都会闪现一个终端窗口
_SUBPROCESS_NO_WINDOW = (
    subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
)


def _get_private_ip_from_udp() -> Optional[str]:
    """通过UDP连接获取本机局域网IP（获取默认路由出口IP）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _get_ips_from_hostname() -> List[str]:
    """通过hostname获取本机IPv4地址列表"""
    ips: List[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            if ":" not in addr and not addr.startswith("127."):
                if addr not in ips:
                    ips.append(addr)
    except Exception:
        pass
    return ips


def _parse_ipconfig() -> List[Tuple[str, Optional[str]]]:
    """解析Windows ipconfig输出，返回 [(IPv4地址, 子网掩码)] 列表"""
    results: List[Tuple[str, Optional[str]]] = []
    try:
        if platform.system() != "Windows":
            return results

        output = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="ignore",
            timeout=5,
            creationflags=_SUBPROCESS_NO_WINDOW
        ).stdout

        # 按适配器块分割（空行分隔）
        blocks = re.split(r"\n\s*\n", output)
        for block in blocks:
            ip = None
            mask = None
            # 按行扫描块内所有 IPv4 形式的数值
            for line in block.splitlines():
                m = re.search(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})", line)
                if not m:
                    continue
                value = m.group(0)
                first = int(m.group(1))
                if first == 255:
                    mask = value
                elif first == 127:
                    continue
                elif ip is None and not value.startswith("169.254"):
                    # 网关IP排在掩码之后，此时ip已记录，不会误取网关
                    ip = value
            if ip:
                results.append((ip, mask))
    except Exception:
        pass
    return results


def get_all_local_ips() -> List[str]:
    """获取本机所有局域网IPv4地址（去重）"""
    ips: List[str] = []
    for ip, _ in _parse_ipconfig():
        if ip not in ips:
            ips.append(ip)

    if not ips:
        # 回退：UDP法 + hostname法
        udp_ip = _get_private_ip_from_udp()
        if udp_ip and udp_ip not in ips:
            ips.append(udp_ip)
        for ip in _get_ips_from_hostname():
            if ip not in ips:
                ips.append(ip)

    return ips


def _get_mask_for_ip(ip: str) -> Optional[str]:
    """从ipconfig结果中查找指定IP对应的子网掩码"""
    for addr, mask in _parse_ipconfig():
        if addr == ip and mask:
            return mask
    return None


def _ip_to_int(ip: str) -> int:
    """IPv4字符串转整数"""
    return int(ipaddress.IPv4Address(ip))


def _int_to_ip(value: int) -> str:
    """整数转IPv4字符串"""
    return str(ipaddress.IPv4Address(value))


def get_network_prefixes() -> List[str]:
    """获取本机所有网段前缀列表（基于真实子网掩码，去重）"""
    prefixes: List[str] = []

    for ip in get_all_local_ips():
        if ip == "127.0.0.1" or ip.startswith("169.254"):
            continue

        mask = _get_mask_for_ip(ip) or "255.255.255.0"
        try:
            net = _ip_to_int(ip) & _ip_to_int(mask)
            parts = _int_to_ip(net).split(".")
            prefix = ".".join(parts[:3])
        except Exception:
            prefix = ".".join(ip.split(".")[:3])

        if prefix not in prefixes:
            prefixes.append(prefix)

    if not prefixes:
        prefixes.append("192.168.1")

    return prefixes


def get_local_ip() -> str:
    """获取本机局域网IP地址（默认路由出口IP，兼容旧接口）"""
    ip = _get_private_ip_from_udp()
    if ip:
        return ip
    ips = get_all_local_ips()
    return ips[0] if ips else "127.0.0.1"


def get_computer_name() -> str:
    """获取计算机名称"""
    return platform.node()


def _get_machine_guid() -> Optional[str]:
    """读取 Windows 注册表 MachineGuid（系统级唯一标识，重装本软件不变）"""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            if value:
                return str(value)
    except Exception:
        pass
    return None


def _device_id_file_path() -> str:
    """兜底设备ID文件路径（%APPDATA% 优先，其他平台退回家目录）"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, "tudou-list", "device_id")
    return os.path.join(os.path.expanduser("~"), ".tudou-list", "device_id")


_pc_id_cache: Optional[str] = None
_pc_id_lock = threading.Lock()


def get_pc_id() -> str:
    """获取PC唯一标识（设备身份，与IP无关，移动端按此确权信任）
    优先注册表 MachineGuid；读不到时生成UUID并持久化到本地文件，之后固定复用
    """
    global _pc_id_cache
    with _pc_id_lock:
        if _pc_id_cache:
            return _pc_id_cache

        pc_id = _get_machine_guid()

        if not pc_id:
            # 文件兜底：读取已持久化的UUID
            path = _device_id_file_path()
            try:
                with open(path, "r", encoding="utf-8") as f:
                    pc_id = f.read().strip()
            except Exception:
                pc_id = None

            if not pc_id:
                # 首次运行：生成新UUID并持久化
                pc_id = str(uuid.uuid4())
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(pc_id)
                except Exception:
                    # 写入失败仅本次会话内存有效，不影响功能
                    pass

        if not pc_id:
            pc_id = str(uuid.uuid4())

        _pc_id_cache = pc_id
        return _pc_id_cache


def get_asset_path(filename: str) -> str:
    """获取资源文件路径（兼容源码运行与PyInstaller打包两种模式）

    打包模式：优先从 PyInstaller 解包目录（sys._MEIPASS）查找，
    其次从 exe 同级目录查找；源码模式：从项目根目录的 assets/ 查找。
    """
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(meipass, "assets", filename))
        candidates.append(
            os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "assets", filename)
        )
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(os.path.join(project_root, "assets", filename))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[-1]