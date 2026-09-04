"""
CosyVoice TTS 服务管理器 - 独立服务进程生命周期（单例）

复刻 core/server_manager.py 骨架：状态信号 + 子进程监控线程 + 健康检查线程。
区别：启动命令是 <conda env python> server.py，健康语义要求 model_loaded=true。
"""
import atexit
import os
import subprocess
import threading
import time
from typing import Optional, Tuple

from PyQt5.QtCore import QObject, pyqtSignal

from core.config import get_config_manager
from core.tts_installer import TTSInstaller, _decode_output, _CREATE_NO_WINDOW


def _server_script() -> str:
    """cosyvoice_service/server.py 绝对路径"""
    core_dir = os.path.dirname(os.path.abspath(__file__))
    program_root = os.path.dirname(core_dir)
    return os.path.join(program_root, "cosyvoice_service", "server.py")


class TtsServerManager(QObject):
    """CosyVoice TTS 服务管理器"""

    status_changed = pyqtSignal(str)  # stopped, starting, running, error
    log_received = pyqtSignal(str)

    MAX_START_WAIT_SEC = 180  # 模型加载约 10-60s，留足余量

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config_manager()
        self.installer = TTSInstaller(self)
        self._process: Optional[subprocess.Popen] = None
        self._status = "stopped"
        self._monitor_thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        self._start_time = 0.0
        self._health_retry_count = 0
        self._external_alive = False  # 复用外部已跑服务
        atexit.register(self._atexit_stop)

    @property
    def status(self) -> str:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status == "running"

    def _set_status(self, status: str):
        if self._status != status:
            self._status = status
            self.status_changed.emit(status)

    # ---------- 运行时解析 ----------

    def resolve_runtime(self) -> Tuple[str, str, str, str, int]:
        """→ (env_python, repo_dir, model_dir, host, port)；缺失时返回空并记日志"""
        cfg = self.config.load()
        tts_cfg = cfg.get("tts", {})
        host = tts_cfg.get("host", "127.0.0.1")
        port = int(tts_cfg.get("port", 8901))

        model = self.config.get_tts_ready_model()
        if not model:
            model = self.config.get_tts_models()[0] if self.config.get_tts_models() else None
        if not model:
            self.log_received.emit("[错误] 配置中找不到 TTS 模型条目")
            return "", "", "", host, port

        env_python = self.installer.env_python()
        repo = model.get("repo_dir", "") or self.installer.repo_dir()

        # 模型目录按当前选择的 model_key 解析（支持多模型切换）
        model_key = model.get("model_key", "")
        by_key = os.path.join(repo, "pretrained_models", model_key) if model_key else ""
        entry_dir = model.get("model_dir", "")
        if by_key and os.path.isdir(by_key):
            model_dir = by_key
        elif entry_dir and os.path.isdir(entry_dir) \
                and os.path.basename(entry_dir) == model_key:
            model_dir = entry_dir
        else:
            self.log_received.emit(
                f"[错误] 所选模型 {model_key} 未下载，请先完成安装步骤 2"
                + (f"（已下载可用: {os.path.basename(entry_dir)}）" if entry_dir and os.path.isdir(entry_dir) else ""))
            return "", "", "", host, port

        if not env_python:
            self.log_received.emit("[错误] 找不到 conda 环境 python，请先完成安装步骤 1")
            return "", "", "", host, port
        if not os.path.isdir(repo):
            self.log_received.emit("[错误] CosyVoice 仓库不存在，请先完成安装步骤 0")
            return "", "", "", host, port
        if not model_dir or not os.path.isdir(model_dir):
            self.log_received.emit("[错误] 预训练模型未下载，请先完成安装步骤 2")
            return "", "", "", host, port

        return env_python, repo, model_dir, host, port

    # ---------- 启动 / 停止 ----------

    def start_service(self) -> bool:
        """启动 TTS 服务（同模型运行中直接复用；模型变更时自动重启以切换）"""
        env_python, repo, model_dir, host, port = self.resolve_runtime()
        if not env_python:
            self._set_status("error")
            return False
        want_model = os.path.basename(model_dir)

        # 已在运行（或启动中）：同模型 → 复用；不同模型 → 先停止再重启
        if self._status in ("starting", "running"):
            cur = self._running_model_name(host, port)
            if cur == want_model:
                return True
            self.log_received.emit(
                f"[切换] 检测到模型变更（{cur or '未知'} → {want_model}），正在重启语音服务...")
            self.stop_service()

        # 端口复用探测
        if self._probe_external(host, port):
            cur = self._running_model_name(host, port)
            if cur and cur != want_model:
                self.log_received.emit(
                    f"[错误] 端口 {port} 已被模型 {cur} 的外部服务占用，"
                    f"无法切换到 {want_model}，请先停止该服务")
                self._set_status("error")
                return False
            self.log_received.emit(f"[启动] 端口 {port} 已有 CosyVoice 服务在运行，直接复用")
            self._external_alive = True
            self._set_status("running")
            return True

        script = _server_script()
        if not os.path.exists(script):
            self.log_received.emit(f"[错误] 服务脚本缺失: {script}")
            self._set_status("error")
            return False

        cmd = [
            env_python, script,
            "--host", host,
            "--port", str(port),
            "--repo", repo,
            "--model-dir", model_dir,
        ]

        self._start_time = time.time()
        self._health_retry_count = 0
        self._external_alive = False
        self._set_status("starting")
        self.log_received.emit("[启动] 正在启动 CosyVoice 语音服务...")
        self.log_received.emit(f"  模型: {os.path.basename(model_dir)}")
        self.log_received.emit(f"  地址: http://{host}:{port}")
        self.log_received.emit("  加载模型中（首次约 10-60 秒，CPU 推理较慢）...")

        try:
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            matcha = os.path.join(repo, "third_party", "Matcha-TTS")
            if os.path.isdir(matcha):
                env["PYTHONPATH"] = matcha

            flags = _CREATE_NO_WINDOW
            self._process = subprocess.Popen(
                cmd,
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=flags,
            )

            self._monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
            self._monitor_thread.start()
            self._health_thread = threading.Thread(target=self._health_check_loop, daemon=True)
            self._health_thread.start()
            return True
        except Exception as e:
            self.log_received.emit(f"[错误] 启动失败: {e}")
            self._set_status("error")
            self._process = None
            return False

    def stop_service(self):
        """停止服务（复用外部服务时只改状态，不动别人进程）"""
        if self._external_alive:
            self._external_alive = False
            self._set_status("stopped")
            return

        proc = self._process
        if proc and proc.poll() is None:
            try:
                self.log_received.emit("[停止] 正在停止语音服务...")
                proc.terminate()
                time.sleep(1)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass

        self._set_status("stopped")
        self._process = None

    def _atexit_stop(self):
        try:
            proc = self._process
            if proc and proc.poll() is None:
                proc.terminate()
                time.sleep(0.5)
                if proc.poll() is None:
                    proc.kill()
        except Exception:
            pass

    # ---------- 监控 / 健康检查 ----------

    def _monitor_process(self):
        """读取子进程输出转发日志（utf-8/gbk 双试解码）"""
        proc = self._process
        if not proc:
            return
        try:
            for raw in iter(proc.stdout.readline, b""):
                line = _decode_output(raw).rstrip("\r\n")
                if line:
                    self.log_received.emit(line)
        except Exception:
            pass

        proc.wait()
        if self._status in ("starting", "running") and not self._external_alive:
            self.log_received.emit(f"[停止] 语音服务已退出 (code: {proc.returncode})")
            self._set_status("stopped")
        self._process = None

    def _health_check_loop(self):
        """每 3s GET /health，model_loaded=true 才置 running"""
        time.sleep(1.5)

        import requests

        cfg = self.config.get_tts_config()
        host = cfg.get("host", "127.0.0.1")
        port = int(cfg.get("port", 8901))
        url = f"http://{host}:{port}/health"

        while self._status == "starting":
            proc = self._process
            if proc is not None and proc.poll() is not None:
                self.log_received.emit(
                    f"[错误] 语音服务进程异常退出 (exit={proc.returncode})")
                self._set_status("error")
                return

            elapsed = time.time() - self._start_time
            if elapsed > self.MAX_START_WAIT_SEC:
                self.log_received.emit(
                    f"[错误] 语音服务启动超时（{int(elapsed)}s），请查看日志")
                self._set_status("error")
                return

            try:
                resp = requests.get(url, timeout=2)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "error":
                        self.log_received.emit(f"[错误] 模型加载失败: {data.get('error', '')}")
                        self._set_status("error")
                        return
                    if data.get("model_loaded"):
                        device = data.get("device", "")
                        self.log_received.emit(
                            f"[就绪] 语音服务已就绪（{int(elapsed)}s，device={device}）")
                        if device == "cpu":
                            self.log_received.emit("[提示] 当前为 CPU 推理，合成速度较慢")
                        self._set_status("running")
                        return
            except Exception:
                pass

            self._health_retry_count += 1
            if self._health_retry_count % 8 == 0:
                self.log_received.emit(f"  ...模型仍在加载（已等待 {int(elapsed)}s）…")
            time.sleep(3)

    def _running_model_name(self, host: str, port: int) -> str:
        """查询运行中服务加载的模型名（/health 的 model 字段；查询失败返回 ''）"""
        import requests
        try:
            resp = requests.get(f"http://{host}:{port}/health", timeout=2)
            if resp.status_code == 200:
                return resp.json().get("model", "") or ""
        except Exception:
            pass
        return ""

    def _probe_external(self, host: str, port: int) -> bool:
        """探测端口上是否已有本服务（health.service==cosyvoice）"""
        import requests
        try:
            resp = requests.get(f"http://{host}:{port}/health", timeout=1.5)
            if resp.status_code == 200:
                return resp.json().get("service") == "cosyvoice"
        except Exception:
            pass
        return False


_tts_server_manager = None
_tts_mgr_lock = threading.Lock()


def get_tts_server_manager() -> TtsServerManager:
    """模块级单例"""
    global _tts_server_manager
    with _tts_mgr_lock:
        if _tts_server_manager is None:
            _tts_server_manager = TtsServerManager()
        return _tts_server_manager
