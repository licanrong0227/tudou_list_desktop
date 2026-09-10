"""剪贴板浮窗通知组件
使用 Flet SnackBar 在应用窗口右下角显示通知，稳定可靠。
"""
import base64
import flet as ft
import threading


class ClipboardToast:
    """应用内右下角浮窗通知"""

    def __init__(self, page: ft.Page):
        self._page = page

    def show_image(self, title: str, image_bytes: bytes):
        """显示图片通知（带缩略图）"""
        self._page.run_task(self._show_image_async, title, image_bytes)

    async def _show_image_async(self, title: str, image_bytes: bytes):
        try:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            thumb = ft.Image(
                src_base64=b64,
                width=280,
                fit=ft.ImageFit.CONTAIN,
                border_radius=6,
            )
        except Exception:
            thumb = ft.Text("[图片]", size=12, color="#7A756C")

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color="#33302C"),
                    thumb,
                ],
                spacing=6,
                tight=True,
            ),
            padding=14,
            border_radius=10,
            bgcolor="#FDFCFA",
            border=ft.Border.all(1, "#D9D4CB"),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.12, ft.Colors.BLACK),
                offset=ft.Offset(0, 2),
            ),
        )

        bar = ft.SnackBar(
            content=card,
            bgcolor="#F2EFE9",
            duration=3000,
            width=340,
        )
        self._page.overlay.append(bar)
        bar.open = True
        self._page.update()

        def _remove():
            try:
                self._page.run_task(self._remove_bar, bar)
            except Exception:
                pass
        threading.Timer(3.5, _remove).start()

    async def _remove_bar(self, bar: ft.SnackBar):
        try:
            bar.open = False
            self._page.update()
            self._page.overlay.remove(bar)
        except Exception:
            pass
