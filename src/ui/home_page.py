"""首页 - 设备扫描列表页"""
import flet as ft
from typing import List, Optional
import threading
import time

from .. import APP_VERSION
from ..scanner import Scanner, Device
from ..auth import AuthManager, AuthStatus

# 自动扫描配置：挂载后延迟首次扫描，之后固定间隔触发
AUTO_SCAN_FIRST_DELAY = 0.5
AUTO_SCAN_INTERVAL = 6.0


# 安卓端拟物纸张风格配色
class Colors:
    PAPER_BG = "#F2EFE9"
    PAPER_BG_TOP = "#F8F6F1"
    PAPER_SURFACE_TOP = "#FDFCFA"
    PAPER_SURFACE_BOTTOM = "#F2EFE8"
    PAPER_BORDER = "#D9D4CB"
    PAPER_DIVIDER = "#E6E2D9"
    INK_STRONG = "#33302C"
    INK_SECONDARY = "#7A756C"
    INK_FAINT = "#A7A198"
    ACCENT_GREEN_TOP = "#87C057"
    ACCENT_GREEN_BOTTOM = "#6AA03C"
    DANGER_RED = "#C9574F"


class HomePage(ft.Column):
    """设备扫描列表首页"""

    def __init__(self, on_connect_device=None, on_focus_connected=None):
        super().__init__()
        self.on_connect_device = on_connect_device
        self.on_focus_connected = on_focus_connected  # 点击"已连接"时聚焦对应WebView窗口
        self.scanner = Scanner()
        self.auth_manager = AuthManager()
        self.devices: List[Device] = []
        self._page: Optional[ft.Page] = None
        self._loop = None  # Flet事件循环引用，用于跨线程安全调度UI更新
        self._connect_buttons = {}  # device.ip -> 一键连接按钮引用（控制Loading/已连接状态）
        self._connected_ips = set()  # WebView窗口处于打开状态的设备ip集合
        self._auto_scan_paused = threading.Event()  # set=暂停自动扫描（授权/连接期间）
        self._auto_scan_thread: Optional[threading.Thread] = None

        # UI组件
        self._status_text = ft.Text(
            "点击下方按钮扫描局域网设备",
            size=14,
            color=Colors.INK_SECONDARY,
            text_align=ft.TextAlign.CENTER
        )

        self._scan_button = ft.Button(
            content=ft.Text("开始扫描"),
            icon=ft.Icons.SEARCH,
            on_click=self._on_scan_click,
            style=ft.ButtonStyle(
                bgcolor=Colors.ACCENT_GREEN_TOP,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding.symmetric(horizontal=24, vertical=12)
            )
        )
        self._has_scanned = False

        self._device_list = ft.Column(
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True
        )

        self._empty_state = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(
                        ft.Icons.PHONE_ANDROID,
                        size=64,
                        color=Colors.INK_FAINT
                    ),
                    ft.Text(
                        "暂无在线共享设备",
                        size=16,
                        color=Colors.INK_FAINT,
                        text_align=ft.TextAlign.CENTER
                    ),
                    ft.Text(
                        "请检查手机WiFi和共享服务是否开启",
                        size=12,
                        color=Colors.INK_FAINT,
                        text_align=ft.TextAlign.CENTER
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8
            ),
            visible=True,
            expand=True,
            alignment=ft.Alignment.CENTER
        )

        # 构建布局
        self._build_layout()

    def _build_layout(self):
        """构建页面布局"""
        self.spacing = 0
        self.expand = True

        # 顶部区域
        header = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "土豆 List",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                        color=Colors.INK_STRONG
                    ),
                    self._status_text,
                    ft.Row(
                        [
                            self._scan_button
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10
                    )
                ],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER
            ),
            padding=ft.Padding.all(20),
            bgcolor=Colors.PAPER_BG_TOP,
            border=ft.Border.only(
                bottom=ft.BorderSide(1, Colors.PAPER_BORDER)
            )
        )

        # 设备列表区域
        list_container = ft.Container(
            content=ft.Column(
                [
                    self._empty_state,
                    self._device_list
                ],
                expand=True
            ),
            expand=True,
            padding=ft.Padding.all(20),
            bgcolor=Colors.PAPER_BG
        )

        # 底部版本号
        footer = ft.Container(
            content=ft.Text(
                APP_VERSION,
                size=12,
                color=Colors.INK_FAINT,
                text_align=ft.TextAlign.CENTER
            ),
            padding=ft.Padding.symmetric(vertical=8),
            alignment=ft.Alignment.CENTER,
            bgcolor=Colors.PAPER_BG_TOP,
            border=ft.Border.only(
                top=ft.BorderSide(1, Colors.PAPER_BORDER)
            )
        )

        self.controls = [
            header,
            list_container,
            footer
        ]

    def did_mount(self):
        self._page = self.page
        # did_mount 在事件循环线程内触发，此时可安全获取运行中的事件循环
        try:
            import asyncio
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        # 挂载完成后启动自动扫描（首次+每6秒）
        self.start_auto_scan()

    def start_auto_scan(self):
        """启动自动扫描线程：挂载后延迟0.5秒扫描一次，之后每6秒自动触发一次
        复用扫描按钮的点击处理函数（等价于自动点击按钮）；若上一次扫描
        尚未结束，_on_scan_click 开头的 is_scanning 守卫会跳过本次触发
        """
        if self._auto_scan_thread and self._auto_scan_thread.is_alive():
            return

        def _auto_scan_loop():
            time.sleep(AUTO_SCAN_FIRST_DELAY)
            while True:
                if not self._auto_scan_paused.is_set():
                    self._run_on_ui(lambda: self._on_scan_click(None))
                time.sleep(AUTO_SCAN_INTERVAL)

        self._auto_scan_thread = threading.Thread(
            target=_auto_scan_loop,
            daemon=True,
            name="auto-scan"
        )
        self._auto_scan_thread.start()

    def pause_auto_scan(self):
        """暂停自动扫描（授权/连接期间，避免状态文本被覆盖、设备列表被清空）"""
        self._auto_scan_paused.set()

    def resume_auto_scan(self):
        """恢复自动扫描"""
        self._auto_scan_paused.clear()

    def _set_button_scanning(self):
        """按钮切换为扫描中状态（Loading动画 + 禁用）"""
        self._scan_button.icon = ft.ProgressRing(width=16, height=16, stroke_width=2)
        self._scan_button.content = ft.Text("扫描中...")
        self._scan_button.disabled = True
        self._page_update()

    def _set_button_idle(self):
        """按钮恢复为空闲状态（扫描过后文案变为重新扫描）"""
        if self._has_scanned:
            self._scan_button.icon = ft.Icons.REFRESH
            self._scan_button.content = ft.Text("重新扫描")
        else:
            self._scan_button.icon = ft.Icons.SEARCH
            self._scan_button.content = ft.Text("开始扫描")
        self._scan_button.disabled = False
        self._page_update()

    def _on_scan_click(self, e):
        """点击扫描按钮"""
        if self.scanner.is_scanning:
            return

        self.devices.clear()
        self._device_list.controls.clear()
        self._empty_state.visible = False
        self._device_list.visible = True

        # 更新UI状态：按钮进入Loading状态
        self._status_text.value = "正在扫描局域网设备中..."
        self._set_button_scanning()

        # 开始扫描
        self.scanner.scan(
            on_device_found=self._on_device_found,
            on_scan_complete=self._on_scan_complete,
            on_scan_start=None,
            on_scan_error=self._on_scan_error
        )

    def _run_on_ui(self, fn):
        """线程安全：把任意UI操作调度回事件循环线程执行
        Flet 0.86 的 page.update() 从后台线程调用时，消息虽入队但无法可靠唤醒
        asyncio发送协程（asyncio.Queue非线程安全），导致渲染延迟到事件循环
        被其他事件唤醒才批量生效。所有后台线程的UI操作必须经此调度。
        """
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(fn)
        else:
            fn()

    def _page_update(self):
        """线程安全刷新页面"""
        self._run_on_ui(self._do_update)

    def _do_update(self):
        """在事件循环线程内执行实际更新"""
        try:
            if self._page:
                self._page.update()
            else:
                self.update()
        except Exception as ex:
            print(f"[page] update error: {ex}", flush=True)

    def _on_device_found(self, device: Device):
        """发现设备回调（逐台实时上屏，无需等待扫描结束）"""
        self.devices.append(device)
        card = self._create_device_card(device)
        self._device_list.controls.append(card)
        self._status_text.value = f"正在扫描... 已发现 {len(self.devices)} 台设备"
        self._page_update()

    def _on_scan_complete(self, devices: List[Device]):
        """扫描完成回调"""
        self._has_scanned = True
        self._set_button_idle()

        if not devices:
            self._empty_state.visible = True
            self._device_list.visible = False
            self._status_text.value = "未发现开启共享的安卓设备"
        else:
            self._status_text.value = f"扫描完成，共发现 {len(devices)} 台设备"

        self._page_update()

    def _on_scan_error(self, error: str):
        """扫描错误回调"""
        self._has_scanned = True
        self._set_button_idle()
        self._status_text.value = f"扫描出错: {error}"
        self._page_update()

    def _create_device_card(self, device: Device) -> ft.Card:
        """创建设备卡片"""
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        # 手机图标
                        ft.Container(
                            content=ft.Icon(
                                ft.Icons.PHONE_ANDROID,
                                size=32,
                                color=Colors.ACCENT_GREEN_TOP
                            ),
                            width=48,
                            height=48,
                            alignment=ft.Alignment.CENTER,
                            bgcolor=Colors.PAPER_SURFACE_TOP,
                            border_radius=8,
                            border=ft.Border.all(1, Colors.PAPER_BORDER)
                        ),
                        # 设备信息
                        ft.Column(
                            [
                                ft.Text(
                                    device.device_name,
                                    size=16,
                                    weight=ft.FontWeight.W_500,
                                    color=Colors.INK_STRONG
                                ),
                                ft.Text(
                                    device.display_address,
                                    size=12,
                                    color=Colors.INK_SECONDARY
                                ),
                            ],
                            spacing=4,
                            expand=True
                        ),
                        # 连接按钮
                        self._create_connect_button(device),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12
                ),
                padding=ft.Padding.all(16),
                border_radius=10,
                bgcolor=ft.LinearGradient(
                    begin=ft.Alignment.TOP_CENTER,
                    end=ft.Alignment.BOTTOM_CENTER,
                    colors=[Colors.PAPER_SURFACE_TOP, Colors.PAPER_SURFACE_BOTTOM]
                ),
                border=ft.Border.all(1, Colors.PAPER_BORDER),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=4,
                    color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
                    offset=ft.Offset(0, 2)
                )
            ),
            elevation=0,
            bgcolor=ft.Colors.TRANSPARENT,
            margin=ft.Margin.all(0)
        )

    def _create_connect_button(self, device: Device) -> ft.Button:
        """创建一键连接按钮并保存引用（用于控制Loading/已连接状态）"""
        btn = ft.Button(
            content=ft.Text("一键连接"),
            icon=ft.Icons.LINK,
            style=ft.ButtonStyle(
                bgcolor=Colors.ACCENT_GREEN_TOP,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=6),
                padding=ft.Padding.symmetric(horizontal=16, vertical=8)
            )
        )
        self._connect_buttons[device.ip] = btn
        self._bind_connect_click(btn, device)
        # 该设备窗口已处于打开状态时（如连接期间手动重扫重建卡片），直接呈现已连接态
        if device.ip in self._connected_ips:
            self._apply_connect_connected_style(btn)
            self._bind_open_click(btn, device)
        return btn

    def _bind_connect_click(self, btn: ft.Button, device: Device):
        """绑定按钮为“一键连接”授权流程"""
        btn.on_click = lambda e, d=device, b=btn: self._on_connect_click(d, b)

    def _bind_open_click(self, btn: ft.Button, device: Device):
        """绑定按钮为“已连接”聚焦流程"""
        btn.on_click = lambda e, d=device: self._on_open_connected_click(d)

    def _apply_connect_idle_style(self, btn: ft.Button):
        """一键连接按钮空闲态样式（绿色）"""
        btn.icon = ft.Icons.LINK
        btn.content = ft.Text("一键连接")
        btn.style = ft.ButtonStyle(
            bgcolor=Colors.ACCENT_GREEN_TOP,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=6),
            padding=ft.Padding.symmetric(horizontal=16, vertical=8)
        )
        btn.disabled = False

    def _apply_connect_connected_style(self, btn: ft.Button):
        """一键连接按钮已连接态样式（白色底+绿色描边，点击打开窗口）"""
        btn.icon = ft.Icons.OPEN_IN_NEW
        btn.content = ft.Text("已连接")
        btn.style = ft.ButtonStyle(
            bgcolor=ft.Colors.WHITE,
            color=Colors.INK_STRONG,
            side=ft.BorderSide(1, Colors.ACCENT_GREEN_TOP),
            shape=ft.RoundedRectangleBorder(radius=6),
            padding=ft.Padding.symmetric(horizontal=16, vertical=8)
        )
        btn.disabled = False

    def set_device_connected(self, device: Device):
        """设备WebView窗口已打开：该设备按钮切换为“已连接”（线程安全）"""
        def _apply():
            self._connected_ips.add(device.ip)
            btn = self._connect_buttons.get(device.ip)
            if btn:
                self._apply_connect_connected_style(btn)
                self._bind_open_click(btn, device)
            self._do_update()
        self._run_on_ui(_apply)

    def set_device_disconnected(self, device: Device):
        """设备WebView窗口已关闭：该设备按钮恢复“一键连接”（线程安全）"""
        def _apply():
            self._connected_ips.discard(device.ip)
            btn = self._connect_buttons.get(device.ip)
            if btn:
                self._apply_connect_idle_style(btn)
                self._bind_connect_click(btn, device)
            self._do_update()
        self._run_on_ui(_apply)

    def _on_open_connected_click(self, device: Device):
        """点击“已连接”：聚焦对应WebView窗口（不重新授权）"""
        if self.on_focus_connected:
            self.on_focus_connected(device)

    def _on_connect_click(self, device: Device, btn: ft.Button = None):
        """点击一键连接：按钮进入Loading状态，后台线程等待手机端授权操作"""
        self._status_text.value = "等待设备授权确认..."
        self._set_connect_loading(device, True)
        # 授权期间暂停自动扫描
        self.pause_auto_scan()

        # 在后台线程中进行授权请求
        def _auth_thread():
            result = self.auth_manager.request_auth(
                device.url,
                on_status_change=lambda msg: self._update_status(msg)
            )

            # 无论结果如何，先恢复按钮状态
            self._run_on_ui(lambda: self._set_connect_loading(device, False))

            # 处理授权结果
            if result.status == AuthStatus.ACCEPT:
                self._status_text.value = "授权成功，正在打开浏览器..."
                self._page_update()
                # 授权成功，打开WebView加载手机端共享网页（保持暂停，
                # WebView关闭时由 App._on_webview_closed 恢复自动扫描）
                if self.on_connect_device:
                    self.on_connect_device(device)
            elif result.status == AuthStatus.REJECT:
                # 手机端拒绝：弹窗提示
                self._run_on_ui(self._show_reject_dialog)
                self._status_text.value = "授权被拒绝"
                self._page_update()
                self.resume_auto_scan()
            elif result.status == AuthStatus.TIMEOUT:
                self._show_error("授权超时，请重新连接")
                self.resume_auto_scan()
            else:
                self._show_error(result.message)
                self.resume_auto_scan()

        thread = threading.Thread(target=_auth_thread, daemon=True)
        thread.start()

    def _set_connect_loading(self, device: Device, loading: bool):
        """切换一键连接按钮的Loading状态（须在UI线程调用）"""
        btn = self._connect_buttons.get(device.ip)
        if not btn:
            return
        if loading:
            btn.icon = ft.ProgressRing(width=16, height=16, stroke_width=2)
            btn.content = ft.Text("授权中...")
            btn.disabled = True
        else:
            self._apply_connect_idle_style(btn)
            self._bind_connect_click(btn, device)
        self._page_update()

    def _show_reject_dialog(self):
        """授权被拒绝弹窗（须在UI线程调用）"""
        if not self._page:
            return
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "授权被拒绝",
                weight=ft.FontWeight.BOLD,
                color=Colors.INK_STRONG
            ),
            content=ft.Text(
                "设备端已拒绝本次连接请求",
                color=Colors.INK_SECONDARY
            ),
            actions=[
                ft.Button(
                    content=ft.Text("知道了"),
                    on_click=lambda e: self._close_dialog(dlg)
                )
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        self._page.overlay.append(dlg)
        dlg.open = True
        self._page_update()

    def _close_dialog(self, dlg: ft.AlertDialog):
        """关闭弹窗并从overlay移除"""
        def _do():
            dlg.open = False
            self._do_update()
            try:
                self._page.overlay.remove(dlg)
            except Exception:
                pass
        self._run_on_ui(_do)

    def _update_status(self, text: str):
        """更新状态文本"""
        self._status_text.value = text
        self._page_update()

    def _show_error(self, message: str):
        """显示错误提示（SnackBar弹条）"""
        self._status_text.value = message
        self._page_update()

        def _do():
            if not self._page:
                return
            bar = ft.SnackBar(
                content=ft.Text(message, color=ft.Colors.WHITE),
                bgcolor=Colors.DANGER_RED,
                duration=3000
            )
            self._page.overlay.append(bar)
            bar.open = True
            self._do_update()
            # 3.5秒后从overlay清理（略长于SnackBar展示时长）
            threading.Timer(
                3.5,
                lambda: self._run_on_ui(
                    lambda: self._page.overlay.remove(bar) if bar in self._page.overlay else None
                )
            ).start()

        self._run_on_ui(_do)
