"""土豆List桌面客户端 - 入口文件"""
"""
限制与兼容说明:
1. 电脑与手机必须连接同一局域网 WiFi
2. 路由器需关闭「AP 隔离」功能，否则设备无法互通
3. 手机需允许 APP 局域网网络权限，禁止系统防火墙拦截
4. 手机锁屏省电策略可能终止服务，需保持 APP 后台运行
"""
import sys

import flet as ft

from src.app import create_app

# 打包模式下 WebView 子进程的重启标记（见 src/ui/web_page.py）
WEBVIEW_RUNNER_FLAG = "--webview-runner"


def main():
    """程序入口"""
    app = create_app()
    ft.run(app.main)


if __name__ == "__main__":
    if WEBVIEW_RUNNER_FLAG in sys.argv:
        # 打包模式：主程序以自身重启的方式拉起 WebView 子进程，
        # 此处去掉标记后交由 webview_runner 处理（argv: [exe, url, 标题]）
        sys.argv = [arg for arg in sys.argv if arg != WEBVIEW_RUNNER_FLAG]
        from src.webview_runner import main as _webview_main
        _webview_main()
    else:
        main()
