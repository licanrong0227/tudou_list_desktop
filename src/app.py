"""应用主模块 - 路由管理和页面切换"""
import flet as ft
from typing import Optional

from .scanner import Device
from .ui.home_page import HomePage, Colors
from .ui.web_page import WebViewWindow
from .utils import get_asset_path

# 应用图标（所有系统窗口共用；Windows 下 Flet 窗口图标必须是 .ico）
APP_ICON_PATH = get_asset_path("app_icon.ico")


class App:
    """土豆List桌面客户端主应用"""

    def __init__(self):
        self.page: Optional[ft.Page] = None
        self._home_page: Optional[HomePage] = None
        self._web_view: Optional[WebViewWindow] = None

    def main(self, page: ft.Page):
        """应用主入口"""
        self.page = page

        # 配置窗口
        page.title = "土豆 List 桌面客户端"
        page.window.width = 900
        page.window.height = 700
        page.window.min_width = 600
        page.window.min_height = 500
        page.window.icon = APP_ICON_PATH
        page.bgcolor = Colors.PAPER_BG
        page.padding = 0
        # 打开时位于屏幕正中（Flet 0.86 中 center 为异步方法，需以任务方式调用；
        # main 保持同步，避免 async 入口影响窗口尺寸等属性的生效时序）
        page.run_task(page.window.center)

        # 创建WebView管理器
        self._web_view = WebViewWindow()

        # 创建首页
        self._home_page = HomePage(
            on_connect_device=self._on_connect_device,
            on_focus_connected=self._on_focus_connected
        )

        # 设置页面内容
        page.add(self._home_page)

    def _on_connect_device(self, device: Device):
        """连接设备回调"""
        # 打开WebView窗口（独立窗口）；返回False表示该设备窗口已处于打开状态
        opened = self._web_view.open_device(
            device,
            on_close=self._on_webview_closed
        )
        if opened:
            # 窗口真正启动：该设备按钮切换为“已连接”
            self._home_page.set_device_connected(device)
        else:
            # 防御：窗口已存在时直接聚焦
            self._web_view.focus(device)

    def _on_focus_connected(self, device: Device):
        """点击“已连接”：聚焦对应设备的WebView窗口"""
        self._web_view.focus(device)

    def _on_webview_closed(self, device: Device):
        """WebView窗口关闭回调（device为本次关闭的窗口对应设备）"""
        if self._home_page:
            # 恢复该设备的“一键连接”按钮
            self._home_page.set_device_disconnected(device)
            if not self._web_view.has_open_windows():
                # 全部窗口已关闭：回到首页状态并恢复自动扫描
                self._home_page._status_text.value = "点击下方按钮扫描局域网设备"
                self._home_page._set_button_idle()
                self._home_page.resume_auto_scan()


def create_app() -> App:
    """创建应用实例"""
    return App()
