"""
模型服务管理器 - 管理 llama-server 进程
"""
import os
import subprocess
import threading
import time
from typing import Optional
from PyQt5.QtCore import QObject, pyqtSignal

from core.config import get_config_manager


class ServerManager(QObject):
    """模型服务管理器"""

    status_changed = pyqtSignal(str)  # stopped, starting, running, error
    log_received = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config_manager()
        self._process = None
        self._status = "stopped"  # stopped, starting, running, error
        self._monitor_thread = None
        self._health_thread = None
        self.model_name = ""            # 当前加载的模型名（Web 状态栏显示用）
        self._start_time = 0.0          # 启动时间戳（秒），用于 starting 超时判定
        self._health_retry_count = 0    # 健康检查次数（避免无限重试）

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

    def find_llama_server(self) -> Optional[str]:
        """查找 llama-server 可执行文件"""
        cfg = self.config.load()
        custom_path = cfg.get("server", {}).get("llama_server_path", "")

        # 1. 配置中自定义路径
        if custom_path and os.path.exists(custom_path):
            return custom_path

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        parent_dir = os.path.dirname(project_root)
        server_name = "llama-server.exe" if os.name == "nt" else "llama-server"

        # 2. CodeMate-AI 的上一级目录（P 目录）下直接放置
        direct = os.path.join(parent_dir, server_name)
        if os.path.exists(direct):
            return direct

        # 3. P 目录下的 llama-b9381-bin-win-cuda-13.3-x64 子目录
        named = os.path.join(parent_dir, "llama-b9381-bin-win-cuda-13.3-x64", server_name)
        if os.path.exists(named):
            return named

        # 4. P 目录下所有同级子文件夹中查找
        try:
            for entry in os.listdir(parent_dir):
                entry_path = os.path.join(parent_dir, entry)
                if os.path.isdir(entry_path):
                    candidate = os.path.join(entry_path, server_name)
                    if os.path.exists(candidate):
                        return candidate
        except OSError:
            pass

        # 5. 当前工作目录
        cwd = os.path.join(os.getcwd(), server_name)
        if os.path.exists(cwd):
            return cwd

        return None

    def start_server(self) -> bool:
        """启动模型服务"""
        if self._status in ("starting", "running"):
            return True

        cfg = self.config.load()
        server_exe = self.find_llama_server()

        if not server_exe:
            self.log_received.emit("[错误] 找不到 llama-server，请在设置中指定路径")
            self._set_status("error")
            return False

        # 从当前模型配置获取参数
        model = self.config.get_current_model()
        if not model:
            self.log_received.emit("[错误] 请先在设置中添加并选择一个模型")
            self._set_status("error")
            return False

        if model.get("type") != "local":
            self.log_received.emit("[错误] 只有本地模型需要启动服务")
            self._set_status("error")
            return False

        model_path = model.get("model_path", "")
        mmproj = model.get("mmproj_path", "")

        # 注意：model_path / mmproj_path 已经是 ConfigManager auto_detect 填好的绝对路径
        # （扫描 P\models 得到），不要和 server 所在目录混淆，否则会错到 llama.cpp-master\models\templates

        if model_path and not os.path.isabs(model_path):
            # 仅当用户在设置界面手动输入了相对路径时才做兜底解析
            # 优先解析到 project-level 的 P\models，其次才是 server 目录下
            program_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            parent_models = os.path.join(os.path.dirname(program_root), "models")
            server_models = os.path.join(os.path.dirname(server_exe), "models")
            for candidate_root in (parent_models, server_models):
                trial = os.path.join(candidate_root, model_path)
                if os.path.exists(trial):
                    model_path = trial
                    break

        if mmproj and not os.path.isabs(mmproj):
            program_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            parent_models = os.path.join(os.path.dirname(program_root), "models")
            server_models = os.path.join(os.path.dirname(server_exe), "models")
            for candidate_root in (parent_models, server_models):
                trial = os.path.join(candidate_root, mmproj)
                if os.path.exists(trial):
                    mmproj = trial
                    break

        if not model_path or not os.path.exists(model_path):
            self.log_received.emit("[错误] 模型文件不存在，请检查路径：" + str(model_path))
            self._set_status("error")
            return False

        host = cfg.get("llm", {}).get("host", "127.0.0.1")
        port = cfg.get("llm", {}).get("port", 8080)

        # ---- 启动前的内存健康检查（避免用户「内存 98%」还在硬上，导致 300 秒超时/气泡空） ----
        try:
            import psutil

            def _fmt_bytes(b: int) -> str:
                if b >= 1024**3:
                    return f"{b / 1024**3:.2f} GB"
                if b >= 1024**2:
                    return f"{b / 1024**2:.1f} MB"
                return f"{b} B"

            vm = psutil.virtual_memory()
            model_size = os.path.getsize(model_path)
            need = int(model_size * 1.05)
            avail = vm.available
            # 可用 < 需要量的 60% 且系统占用 > 92% → 警告
            if avail < need * 0.6 and vm.percent > 92:
                self.log_received.emit(
                    f"[警告] 系统可用内存偏小："
                    f"可用 {_fmt_bytes(avail)}  /  模型预计 {_fmt_bytes(need)}。"
                    f" 若长时间卡在『启动中』请关闭其他程序。"
                )
        except Exception:
            pass

        # 构建命令
        cmd = [
            server_exe,
            "-m", model_path,
            "-ngl", str(model.get("n_gpu_layers", 999)),
            "-c", str(model.get("ctx_size", 8192)),
            "-n", str(model.get("n_predict", 4096)),
            "--host", host,
            "--port", str(port),
        ]

        if mmproj and os.path.exists(mmproj):
            cmd.extend(["--mmproj", mmproj])

        model_name = model.get("name", os.path.basename(model_path))
        self.model_name = model_name

        self._start_time = time.time()
        self._health_retry_count = 0
        self._set_status("starting")
        self.log_received.emit(f"[启动] 正在启动模型服务...")
        self.log_received.emit(f"  模型: {model_name}")
        self.log_received.emit(f"  地址: {host}:{port}")
        self.log_received.emit(f"  加载模型中，请稍候...")

        try:
            # 启动进程
            cwd = os.path.dirname(server_exe)

            if os.name == "nt":
                CREATE_NO_WINDOW = 0x08000000
                DETACHED_PROCESS = 0x00000008
                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                env["LANG"] = "en_US.UTF-8"
                env["LC_ALL"] = "en_US.UTF-8"
                self._process = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,  # 禁用 stdin 管道（防止阻塞）
                    env=env,
                    creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS
                )
            else:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    # 使用默认缓冲区大小（二进制 PIPE 不支持 bufsize=1 行缓冲）
                )

            # 启动监控线程（必须立刻启动！PIPE 反压会卡死 llama-server）
            self._monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
            self._monitor_thread.start()

            # 健康检查用后台线程轮询（不能用 QTimer：从 Web 服务线程调用 start_server 时
            # Qt 定时器无法在非 Qt 线程触发，会导致状态永远卡在『启动中』）
            self._health_thread = threading.Thread(target=self._health_check_loop, daemon=True)
            self._health_thread.start()

            return True

        except Exception as e:
            self.log_received.emit(f"[错误] 启动失败: {e}")
            self._set_status("error")
            self._process = None
            return False

    def _monitor_process(self):
        """监控进程输出"""
        if not self._process:
            return

        # 尝试导入 chardet 用于编码检测
        try:
            import chardet
            _has_chardet = True
        except ImportError:
            _has_chardet = False

        _detected_encoding = None  # 缓存检测到的编码

        def decode_line(raw_bytes):
            """智能解码：先尝试已检测编码，再用 chardet，最后逐编码尝试"""
            nonlocal _detected_encoding

            if not raw_bytes:
                return ""

            # 1. 如果已经检测过编码，直接用
            if _detected_encoding:
                try:
                    text = raw_bytes.decode(_detected_encoding)
                    if _is_good_text(text):
                        return text
                except (UnicodeDecodeError, LookupError):
                    _detected_encoding = None  # 检测失败，重置

            # 2. 先用 chardet 检测（如果可用且内容足够长）
            if _has_chardet and len(raw_bytes) > 20:
                try:
                    result = chardet.detect(raw_bytes)
                    enc = result.get("encoding", "")
                    conf = result.get("confidence", 0)
                    if enc and conf > 0.7:
                        try:
                            text = raw_bytes.decode(enc)
                            if _is_good_text(text):
                                _detected_encoding = enc  # 缓存成功的编码
                                return text
                        except (UnicodeDecodeError, LookupError):
                            pass
                except Exception:
                    pass

            # 3. 按优先级逐编码尝试
            encodings = ["utf-8", "gbk", "gb18030", "cp936", "gb2312", "big5", "shift_jis", "latin-1"]
            best_text = None
            best_score = -1

            for enc in encodings:
                try:
                    text = raw_bytes.decode(enc)
                    score = _text_quality_score(text)
                    if score > best_score:
                        best_score = score
                        best_text = text
                        if score > 0.9:  # 质量足够高，直接用
                            _detected_encoding = enc
                            return text
                except (UnicodeDecodeError, LookupError):
                    continue

            if best_text is not None:
                return best_text

            # 4. 最后兜底
            return raw_bytes.decode("utf-8", errors="replace")

        def _is_good_text(text: str) -> bool:
            """判断文本质量是否良好"""
            if not text:
                return False
            # 计算替换字符比例
            bad = sum(1 for c in text if c == '\ufffd')
            if bad / max(len(text), 1) > 0.05:
                return False
            # 检查是否有太多不可打印字符（控制字符等）
            control = sum(1 for c in text if ord(c) < 32 and c not in '\n\r\t')
            if control / max(len(text), 1) > 0.1:
                return False
            return True

        def _text_quality_score(text: str) -> float:
            """文本质量评分 (0-1)"""
            if not text:
                return 0.0
            score = 1.0
            # 替换字符扣分
            bad = sum(1 for c in text if c == '\ufffd')
            score -= bad / max(len(text), 1) * 3
            # 不可打印字符扣分
            control = sum(1 for c in text if ord(c) < 32 and c not in '\n\r\t')
            score -= control / max(len(text), 1) * 2
            # 中文字符加分（说明是正确的中文编码）
            chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            if chinese > 0:
                score += 0.1
            # ASCII 可打印字符加分
            printable = sum(1 for c in text if 32 <= ord(c) <= 126)
            score += printable / max(len(text), 1) * 0.2
            return max(0.0, min(1.0, score))

        try:
            for line in self._process.stdout:
                try:
                    text = decode_line(line).strip()
                    if text:
                        self.log_received.emit(text)
                except Exception:
                    pass
        except Exception:
            pass

        # 进程结束
        process = self._process
        if process is not None:
            process.wait()
            exit_code = process.returncode

            if self._status == "starting" or self._status == "running":
                self.log_received.emit(f"[停止] 服务已退出 (code: {exit_code})")
                self._set_status("stopped")

        self._process = None

    MAX_START_WAIT_SEC = 600  # 单模型启动最长等待 10 分钟（足够 35B 慢速加载）

    def _health_check_loop(self):
        """线程版健康检查（后台线程每 3 秒探测一次，直到 running / error / 状态改变）
        策略：
        1) 先看 self._process 是否还活着；死了立刻切 error
        2) 用 GET /health（及 /v1/models、/ 回退）检查 llama-server
        3) 失败时每 3 秒重试，总时长 ≤ MAX_START_WAIT_SEC（10 分钟），到时仍失败 → error
        注：信号 emit 可在非 GUI 线程调用（Qt 自动排队到主线程）。
        """
        time.sleep(1.5)  # 先给进程 1.5s 启动时间再开始探测

        while self._status == "starting":
            # 1) 进程已死？
            proc = self._process
            if proc is None:
                self._set_status("error")
                return
            if proc.poll() is not None:
                exit_code = proc.returncode
                self.log_received.emit(
                    f"[错误] 进程异常退出 (exit={exit_code})，请检查模型大小/CUDA/dll 是否齐全"
                )
                self._set_status("error")
                return

            # 2) 总启动超时？
            elapsed = time.time() - self._start_time
            if elapsed > self.MAX_START_WAIT_SEC:
                self.log_received.emit(
                    f"[错误] 启动超时（{int(elapsed)}s）。模型可能太大或系统资源不足，"
                    f"请点击『停止』后换更小的模型（如 Gemma-4-E4B），或关闭占内存的程序。"
                )
                self._set_status("error")
                return

            # 3) 调健康接口 + 同时尝试回退接口（某些 llama-server 路径是 /v1/models）
            import requests
            cfg = self.config.load()
            host = cfg.get("llm", {}).get("host", "127.0.0.1")
            port = cfg.get("llm", {}).get("port", 8080)
            base = f"http://{host}:{port}"
            healthy = False
            last_err = ""
            for probe in ("/health", "/v1/models", "/"):
                try:
                    resp = requests.get(base + probe, timeout=1.5)
                    if resp.status_code == 200:
                        healthy = True
                        break
                except Exception as e:
                    last_err = f"{type(e).__name__}"
                    continue

            if healthy:
                self.log_received.emit(f"[就绪] 模型服务已就绪（{int(elapsed)}s）")
                self._set_status("running")
                return

            # 4) 还没好，给日志进度提示（每 8 次 ≈ 24s 提示一次）
            self._health_retry_count += 1
            if self._health_retry_count % 8 == 0:
                self.log_received.emit(
                    f"  ...仍在加载中（已等待 {int(elapsed)}s，上次检查：{last_err or '响应异常'}）…"
                )

            time.sleep(3)

    def stop_server(self):
        """停止模型服务"""
        if self._process and self._process.poll() is None:
            try:
                self.log_received.emit("[停止] 正在停止模型服务...")
                self._process.terminate()
                time.sleep(1)
                if self._process.poll() is None:
                    self._process.kill()
            except Exception:
                pass

        self._set_status("stopped")
        self._process = None

    def restart_server(self) -> bool:
        """重启服务"""
        self.stop_server()
        time.sleep(1)
        return self.start_server()

    def get_server_url(self) -> str:
        """获取服务地址"""
        cfg = self.config.load()
        host = cfg.get("llm", {}).get("host", "127.0.0.1")
        port = cfg.get("llm", {}).get("port", 8080)
        return f"http://{host}:{port}"
