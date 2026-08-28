"""pywebview子进程入口
必须以独立进程运行：webview.start() 强制要求主线程调用
（webview/__init__.py: 主线程校验），而主进程主线程已被Flet占用。
用法: python -m src.webview_runner <url> <标题>
"""
import ctypes
import os
import sys

import clr
import webview
from System import Action

from .utils import get_asset_path

# 手机端共享页面使用自签名HTTPS证书，必须允许WebView忽略SSL错误
webview.settings["IGNORE_SSL_ERRORS"] = True

# 显式设置进程 AppUserModelID（必须在创建任何窗口之前）：
# 否则任务栏按 python.exe 归组并使用其自带图标，导致任务栏图标不生效
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("tudou.list.desktop.webview")

# 应用图标（与主窗口共用；必须是真正的 .ico 文件，System.Drawing.Icon 不支持 PNG）
_APP_ICON_PATH = get_asset_path("app_icon.ico")


def _bring_to_front():
    """窗口显示后将置顶切换派发到 UI 线程执行，强制其位于最前（仅打开时）。
    跨线程直接设置 TopMost 会同步发送窗口消息（SetWindowPos 阻塞式跨线程调用），
    与 WebView2 初始化竞态会导致 UI 线程死锁（白屏卡死）；
    BeginInvoke 仅向 UI 线程投递消息、不阻塞，竞态下最多延迟执行。
    取消置顶后窗口仍保留在 Z 序最前，可被其他窗口正常遮挡。
    """
    window = webview.windows[0]
    window.events.shown.wait(15)  # 等待窗口显示（native 句柄就绪）
    form = window.native
    if form is None:
        return

    def _toggle():
        form.TopMost = True
        form.TopMost = False

    form.BeginInvoke(Action(_toggle))


def main():
    if len(sys.argv) < 2:
        print("[webview_runner] missing url argument", flush=True)
        sys.exit(1)

    url = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "土豆 List"

    webview.create_window(
        title=title,
        url=url,
        width=900,
        height=700,
        resizable=True,
        min_size=(600, 500),
        maximized=True,   # 打开时自动最大化
        focus=True        # 打开时置于最前并获得焦点（非永久置顶）
    )
    # 阻塞直到窗口关闭；icon 参数在 Windows WinForms 后端同样生效
    # （BrowserForm 构造函数中 Show 之前设置，标题栏+任务栏都会应用）
    if os.path.isfile(_APP_ICON_PATH):
        webview.start(func=_bring_to_front, icon=_APP_ICON_PATH, debug=False)
    else:
        webview.start(func=_bring_to_front, debug=False)


if __name__ == "__main__":
    main()