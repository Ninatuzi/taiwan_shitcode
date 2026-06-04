"""
BMS FW Validation Tool — GUI 版（PySide6 QWebEngineView）
"""
import os
import sys
import threading
import urllib.request

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QFileDialog
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtCore import QUrl, Qt, QTimer, QStandardPaths


def _resource(relative: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)


def _load_dotenv():
    exe_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    env_file = os.path.join(exe_dir, ".env")
    if not os.path.exists(env_file):
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def _get_log_path() -> str:
    exe_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(exe_dir, "bms_error.log")


def _start_backend():
    # windowed exe 的 stdout/stderr 為 None，需要導向避免套件寫入時 crash
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(_get_log_path(), "a", encoding="utf-8")
    try:
        import uvicorn
        uvicorn.run(
            "backend.main:app",
            host="127.0.0.1",
            port=8000,
            log_level="warning",
        )
    except Exception as e:
        with open(_get_log_path(), "a", encoding="utf-8") as f:
            import traceback
            f.write(f"\n[Backend Error]\n{traceback.format_exc()}\n")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BMS FW Validation")
        self.resize(1440, 900)

        # Loading 畫面
        self._loading = QLabel("正在啟動後端，請稍候…")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet(
            "background:#0D1421; color:#A8B8D0; font-size:16px;"
            "font-family:'Microsoft JhengHei', sans-serif;"
        )
        self.setCentralWidget(self._loading)

        # WebView（預先建立，但還沒放進視窗）
        self._webview = QWebEngineView()
        s = self._webview.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        # 攔截下載事件（QWebEngine 預設不會處理 a.click() 觸發的下載）
        self._webview.page().profile().downloadRequested.connect(self._on_download)

        # 主執行緒 QTimer 輪詢後端是否 ready（每 500ms 一次）
        self._attempts = 0
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._check_backend)
        self._poll.start()

    def _check_backend(self):
        self._attempts += 1
        try:
            # 非阻塞：timeout 設 0.3 秒，不會 hang UI
            urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=0.3)
            self._poll.stop()
            self._show_app()
        except Exception:
            # 超過 90 秒仍未就緒則直接切換（讓 webview 顯示錯誤）
            if self._attempts >= 180:
                self._poll.stop()
                self._show_app()

    def _show_app(self):
        self._webview.setUrl(QUrl("http://127.0.0.1:8000"))
        self.setCentralWidget(self._webview)

    def _on_download(self, download):
        """彈出存檔對話框讓使用者選擇位置。"""
        suggested = download.suggestedFileName() or "BMS_TestCards.html"
        downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        default_path = os.path.join(downloads_dir, suggested) if downloads_dir else suggested

        path, _ = QFileDialog.getSaveFileName(self, "儲存檔案", default_path, "HTML 檔案 (*.html);;所有檔案 (*.*)")
        if path:
            download.setDownloadDirectory(os.path.dirname(path))
            download.setDownloadFileName(os.path.basename(path))
            download.accept()
        else:
            download.cancel()


if __name__ == "__main__":
    _load_dotenv()
    os.environ["FRONTEND_DIST"] = _resource("frontend/dist")

    # 啟動後端（背景執行緒）
    threading.Thread(target=_start_backend, daemon=True).start()

    app = QApplication(sys.argv)
    app.setApplicationName("BMS FW Validation")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
