"""
GPT-SoVITS 语音服务管理器 - 独立服务进程生命周期（单例）

复刻 CosyVoice TtsServerManager 骨架：状态信号 + 子进程监控线程 + 健康检查线程。
GPT-SoVITS 自带 runtime Python 3.9 环境，启动命令：
  runtime\\python.exe api.py -s <SoVITS权重> -g <GPT权重> -dr <参考音频> -dt <参考文本> -dl zh -d cuda -a host -p port
"""
import atexit
import os
import subprocess
import threading
import time
from typing import Optional, Tuple

from PyQt5.QtCore import QObject, pyqtSignal

from core.config import get_config_manager

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _runtime_python(repo_dir: str) -> str:
    """返回 GPT-SoVITS runtime 里的 python.exe 路径"""
    p = os.path.join(repo_dir, "runtime", "python.exe")
    return p if os.path.exists(p) else ""


class GptSovitsServerManager(QObject):
    """GPT-SoVITS 语音服务管理器"""

    status_changed = pyqtSignal(str)  # stopped, starting, running, error
    log_received = pyqtSignal(str)

    MAX_START_WAIT_SEC = 120  # 模型加载约 30-90s

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config_manager()
        self._process: Optional[subprocess.Popen] = None
        self._status = "stopped"
        self._monitor_thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        self._start_time = 0.0
        self._health_retry_count = 0
        self._external_alive = False
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
        """→ (repo_dir, sovits_path, gpt_path, host, port)；缺失返回空"""
        cfg = self.config.load()
        sovits_cfg = cfg.get("gpt_sovits", {})
        host = sovits_cfg.get("host", "127.0.0.1")
        port = int(sovits_cfg.get("port", 9880))

        repo_dir = sovits_cfg.get("repo_dir", "")
        if not repo_dir or not os.path.isdir(repo_dir):
            # 自动探测：models/GPT-SoVITS*
            models_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "models")
            for entry in os.listdir(models_root) if os.path.isdir(models_root) else []:
                if entry.startswith("GPT-SoVITS") and os.path.isdir(os.path.join(models_root, entry)):
                    repo_dir = os.path.join(models_root, entry)
                    break
        if not repo_dir or not os.path.isdir(repo_dir):
            self.log_received.emit("[错误] 找不到 GPT-SoVITS 整合包目录")
            return "", "", "", host, port

        sovits_path = sovits_cfg.get("sovits_model", "")
        gpt_path = sovits_cfg.get("gpt_model", "")
        if not sovits_path or not os.path.exists(sovits_path):
            self.log_received.emit("[错误] 请先选择 SoVITS 权重文件（.pth）")
            return repo_dir, "", "", host, port
        if not gpt_path or not os.path.exists(gpt_path):
            self.log_received.emit("[错误] 请先选择 GPT 权重文件（.ckpt）")
            return repo_dir, sovits_path, "", host, port

        return repo_dir, sovits_path, gpt_path, host, port

    # ---------- 启动 / 停止 ----------

    def start_service(self) -> bool:
        """启动 GPT-SoVITS API 服务"""
        repo_dir, sovits_path, gpt_path, host, port = self.resolve_runtime()
        if not repo_dir or not sovits_path or not gpt_path:
            self._set_status("error")
            return False

        runtime_py = _runtime_python(repo_dir)
        if not runtime_py:
            self.log_received.emit(f"[错误] 找不到 runtime\\python.exe: {repo_dir}")
            self._set_status("error")
            return False

        # 已在运行：同模型 → 复用；不同模型 → 用 /set_model 热切换
        if self._status in ("starting", "running"):
            want_sovits = os.path.basename(sovits_path)
            cur_sovits = self._running_model_name(host, port)
            if cur_sovits == want_sovits:
                return True
            self.log_received.emit(f"[切换] 运行时切换音色 {cur_sovits} → {want_sovits}")
            self._hot_switch_model(gpt_path, sovits_path, host, port)
            return True

        # 端口复用探测
        if self._probe_external(host, port):
            self.log_received.emit(f"[启动] 端口 {port} 已有 GPT-SoVITS 服务在运行，直接复用")
            self._external_alive = True
            self._set_status("running")
            return True

        # 构建启动参数
        device = self.config.get("gpt_sovits.device", "cuda")
        refer_wav = self.config.get("gpt_sovits.default_refer_wav", "")
        refer_text = self.config.get("gpt_sovits.default_refer_text", "")
        refer_lang = self.config.get("gpt_sovits.default_refer_lang", "zh")

        cmd = [
            runtime_py, "-I", "api.py",
            "-s", sovits_path,
            "-g", gpt_path,
            "-dl", refer_lang,
            "-d", device,
            "-a", host,
            "-p", str(port),
        ]
        if refer_wav and os.path.exists(refer_wav):
            cmd += ["-dr", refer_wav, "-dt", refer_text or "参考音频"]

        self._start_time = time.time()
        self._health_retry_count = 0
        self._external_alive = False
        self._set_status("starting")
        self.log_received.emit("[启动] 正在启动 GPT-SoVITS 语音服务...")
        self.log_received.emit(f"  SoVITS: {os.path.basename(sovits_path)}")
        self.log_received.emit(f"  GPT: {os.path.basename(gpt_path)}")
        self.log_received.emit(f"  设备: {device}  地址: http://{host}:{port}")
        self.log_received.emit("  加载模型中（首次约 30-90 秒）...")

        try:
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"

            self._process = subprocess.Popen(
                cmd,
                cwd=repo_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=_CREATE_NO_WINDOW,
            )

            self._monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
            self._monitor_thread.start()
            self._health_thread = threading.Thread(target=self._health_check_loop, args=(host, port), daemon=True)
            self._health_thread.start()
            return True
        except Exception as e:
            self.log_received.emit(f"[错误] 启动失败: {e}")
            self._set_status("error")
            self._process = None
            return False

    def stop_service(self):
        if self._external_alive:
            self._external_alive = False
            self._set_status("stopped")
            return

        proc = self._process
        if proc and proc.poll() is None:
            try:
                self.log_received.emit("[停止] 正在停止 GPT-SoVITS 语音服务...")
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

    # ---------- 热切换模型 ----------

    def _hot_switch_model(self, gpt_path: str, sovits_path: str, host: str, port: int):
        """用 /set_model 端点运行时切换音色（不重启服务）"""
        import requests
        try:
            resp = requests.post(
                f"http://{host}:{port}/set_model",
                json={"gpt_model_path": gpt_path, "sovits_model_path": sovits_path},
                timeout=30,
            )
            if resp.status_code == 200:
                self.log_received.emit("[就绪] 音色已切换")
            else:
                self.log_received.emit(f"[警告] 音色切换返回 {resp.status_code}，可能需要重启")
        except Exception as e:
            self.log_received.emit(f"[警告] 热切换失败: {e}，将在下次启动时生效")

    # ---------- 监控 / 健康检查 ----------

    def _monitor_process(self):
        proc = self._process
        if not proc:
            return
        try:
            for raw in iter(proc.stdout.readline, b""):
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                except Exception:
                    line = raw.decode("gbk", errors="replace").rstrip("\r\n")
                if line:
                    self.log_received.emit(line)
        except Exception:
            pass

        proc.wait()
        if self._status in ("starting", "running") and not self._external_alive:
            self.log_received.emit(f"[停止] GPT-SoVITS 服务已退出 (code: {proc.returncode})")
            self._set_status("stopped")
        self._process = None

    def _health_check_loop(self, host: str, port: int):
        """每 3s GET /control 探测服务存活（api.py 的 /set_model GET 需参数，会返回 400；/control GET 无参数返回 200）"""
        time.sleep(2)
        import requests

        url = f"http://{host}:{port}/control"

        while self._status == "starting":
            proc = self._process
            if proc is not None and proc.poll() is not None:
                self.log_received.emit(
                    f"[错误] GPT-SoVITS 进程异常退出 (exit={proc.returncode})")
                self._set_status("error")
                return

            elapsed = time.time() - self._start_time
            if elapsed > self.MAX_START_WAIT_SEC:
                self.log_received.emit(
                    f"[错误] GPT-SoVITS 启动超时（{int(elapsed)}s），请查看日志")
                self._set_status("error")
                return

            try:
                resp = requests.get(url, timeout=2)
                if resp.status_code == 200:
                    self.log_received.emit(
                        f"[就绪] GPT-SoVITS 服务已就绪（{int(elapsed)}s）")
                    self._set_status("running")
                    return
            except Exception:
                pass

            self._health_retry_count += 1
            if self._health_retry_count % 10 == 0:
                self.log_received.emit(f"  ...模型仍在加载（已等待 {int(elapsed)}s）…")
            time.sleep(3)

    def _running_model_name(self, host: str, port: int) -> str:
        """探测运行中服务是否响应（GET /control 返回 200 = 活着）"""
        import requests
        try:
            resp = requests.get(f"http://{host}:{port}/control", timeout=2)
            if resp.status_code == 200:
                # /control 返回 null，没法拿到模型名，但知道服务活着就行
                return "running"
        except Exception:
            pass
        return ""

    def _probe_external(self, host: str, port: int) -> bool:
        """探测端口上是否已有本服务（GET /control 返回 200）"""
        import requests
        try:
            resp = requests.get(f"http://{host}:{port}/control", timeout=1.5)
            return resp.status_code == 200
        except Exception:
            pass
        return False


_gpt_sovits_mgr = None
_gpt_sovits_lock = threading.Lock()


def get_gpt_sovits_server_manager() -> GptSovitsServerManager:
    """模块级单例"""
    global _gpt_sovits_mgr
    with _gpt_sovits_lock:
        if _gpt_sovits_mgr is None:
            _gpt_sovits_mgr = GptSovitsServerManager()
        return _gpt_sovits_mgr
