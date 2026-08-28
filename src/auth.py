"""设备授权连接模块"""
import threading
from enum import Enum
from typing import Optional, Callable
import requests
import urllib3

# 手机端使用自签名HTTPS证书，抑制证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .utils import get_computer_name, get_local_ip, get_pc_id


# 授权配置
# 安卓端授权弹窗最长等待 10 秒（ConnectionManager CountDownLatch.await(10)），请求超时略留余量
AUTH_TIMEOUT = 11.0
AUTH_REQUEST_PATH = "/api/auth/request"


class AuthStatus(Enum):
    """授权状态"""
    ACCEPT = "accept"
    REJECT = "reject"
    TIMEOUT = "timeout"
    ERROR = "error"


class AuthResult:
    """授权结果"""
    def __init__(
        self,
        status: AuthStatus,
        save: bool = False,
        message: str = ""
    ):
        self.status = status
        self.save = save
        self.message = message


class AuthManager:
    """设备授权管理器"""

    def __init__(self):
        self._is_authenticating = False
        self._lock = threading.Lock()

    def request_auth(
        self,
        device_url: str,
        on_status_change: Optional[Callable[[str], None]] = None
    ) -> AuthResult:
        """向设备发起一次阻塞式授权请求
        Args:
            device_url: 设备地址 (如 http://192.168.1.100:9527)
            on_status_change: 状态变化回调
        Returns:
            AuthResult: 授权结果
        """
        with self._lock:
            if self._is_authenticating:
                return AuthResult(
                    AuthStatus.ERROR,
                    message="正在进行其他授权请求"
                )
            self._is_authenticating = True

        try:
            # 准备请求参数
            # pc_id 为设备唯一标识（非IP），移动端信任列表按此确权：
            # 同一PC即使IP变化，已信任则不再弹窗要求重新授权
            pc_name = get_computer_name()
            pc_ip = get_local_ip()

            url = f"{device_url}{AUTH_REQUEST_PATH}"
            params = {
                "pc_id": get_pc_id(),
                "pc_name": pc_name,
                "pc_ip": pc_ip
            }

            if on_status_change:
                on_status_change("等待设备授权确认...")

            # 安卓端接口为一次性阻塞式：触发弹窗后等待用户操作（最长10秒）再返回
            # 手机端默认HTTPS+自签名证书，必须关闭证书校验，否则TLS握手即失败、请求无法到达手机
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=AUTH_TIMEOUT,
                    verify=False
                )
            except requests.RequestException:
                # 网络中断/长时间无响应 -> 授权超时
                return AuthResult(
                    AuthStatus.TIMEOUT,
                    message="授权超时，请重新连接"
                )

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    return AuthResult(
                        AuthStatus.ERROR,
                        message="设备端返回数据格式异常"
                    )

                auth_status = data.get("auth_status", "")

                if auth_status == "accept":
                    save = data.get("save", False)
                    return AuthResult(
                        AuthStatus.ACCEPT,
                        save=save,
                        message="授权成功"
                    )
                elif auth_status == "reject":
                    return AuthResult(
                        AuthStatus.REJECT,
                        message="设备端已拒绝本次连接请求"
                    )
                elif auth_status == "timeout":
                    return AuthResult(
                        AuthStatus.TIMEOUT,
                        message="授权超时，请重新连接"
                    )
                else:
                    return AuthResult(
                        AuthStatus.ERROR,
                        message=f"未预期的授权状态: {auth_status}"
                    )
            elif response.status_code == 408:
                # 安卓端未在10秒内收到用户操作，返回408 timeout
                return AuthResult(
                    AuthStatus.TIMEOUT,
                    message="授权超时，请重新连接"
                )
            else:
                return AuthResult(
                    AuthStatus.ERROR,
                    message=f"授权请求失败，状态码: {response.status_code}"
                )

        except Exception as e:
            return AuthResult(
                AuthStatus.ERROR,
                message=f"授权请求失败: {str(e)}"
            )
        finally:
            self._is_authenticating = False