"""
CosyVoice TTS 安装器 - 分步安装流水线（克隆仓库 / conda 环境 / 下载模型）

全链路 subprocess.Popen(shell=False) 绝对路径直调，
不依赖任何 shell（本机 PowerShell 执行策略会拦截脚本）。
"""
import os
import re
import shutil
import subprocess
import threading
from typing import Optional, Dict, List

from PyQt5.QtCore import QObject, pyqtSignal

from core.config import get_config_manager


COSYVOICE_REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"

# model_key → ModelScope 模型 ID
MODELSCOPE_IDS = {
    "CosyVoice2-0.5B": "iic/CosyVoice2-0.5B",
    "Fun-CosyVoice3-0.5B-2512": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
}

STEP_NAMES = {0: "克隆仓库", 1: "安装 conda 环境与依赖", 2: "下载预训练模型"}

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _decode_output(data: bytes) -> str:
    """子进程输出解码：utf-8 优先，gbk 兜底"""
    if not data:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc, errors="replace")
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


class TTSInstaller(QObject):
    """CosyVoice 分步安装器"""

    step_started = pyqtSignal(int)                # step
    log_received = pyqtSignal(str)                # 日志行
    step_finished = pyqtSignal(int, bool, str)    # step, ok, message
    install_state_changed = pyqtSignal()          # 任一步完成后刷新就绪状态

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config_manager()
        self._cancel_flag = threading.Event()
        self._current_proc: Optional[subprocess.Popen] = None
        self._running = False

    # ---------- 路径与环境探测 ----------

    def models_root(self) -> str:
        """models/CosyVoice 根目录（懒填回 config）"""
        cfg = self.config.get_tts_config()
        root = cfg.get("models_root", "")
        if root and os.path.isdir(root):
            return root
        # 默认 <程序根>/../models/CosyVoice（与 .gguf 共用上级 models 目录）
        program_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        parent_dir = os.path.dirname(program_root)
        candidate = os.path.join(parent_dir, "models", "CosyVoice")
        if not os.path.isdir(os.path.dirname(candidate)):
            candidate = os.path.join(program_root, "models", "CosyVoice")
        self.config.set("tts.models_root", os.path.dirname(candidate))
        return candidate

    def repo_dir(self) -> str:
        return os.path.join(self.models_root(), "CosyVoice")

    def model_dir(self, model_key: str = "") -> str:
        if not model_key:
            model_key = self._current_model_key()
        return os.path.join(self.repo_dir(), "pretrained_models", model_key)

    def _current_model_key(self) -> str:
        m = self._tts_model()
        return m.get("model_key", "CosyVoice2-0.5B") if m else "CosyVoice2-0.5B"

    def _tts_model(self) -> Optional[Dict]:
        models = self.config.get_tts_models()
        return models[0] if models else None

    def find_git(self) -> Optional[str]:
        return shutil.which("git")

    def find_conda(self) -> Optional[str]:
        cfg = self.config.get_tts_config()
        custom = cfg.get("conda_path", "")
        if custom and os.path.exists(custom):
            return custom

        exe = shutil.which("conda")
        if exe:
            return exe

        # 常见安装路径探测
        user = os.path.expanduser("~")
        candidates = [
            os.path.join(user, "miniconda3", "Scripts", "conda.exe"),
            os.path.join(user, "anaconda3", "Scripts", "conda.exe"),
            os.path.join(user, "Miniconda3", "Scripts", "conda.exe"),
            os.path.join(user, "Anaconda3", "Scripts", "conda.exe"),
            os.path.join("C:\\ProgramData", "miniconda3", "Scripts", "conda.exe"),
            os.path.join("C:\\ProgramData", "anaconda3", "Scripts", "conda.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "miniconda3", "Scripts", "conda.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "anaconda3", "Scripts", "conda.exe"),
            os.path.join(user, "miniforge3", "Scripts", "conda.exe"),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return None

    def conda_root(self, conda_exe: str = "") -> str:
        """conda.exe → conda 根目录（Scripts 的上一级）"""
        if not conda_exe:
            conda_exe = self.find_conda() or ""
        if not conda_exe:
            return ""
        return os.path.dirname(os.path.dirname(os.path.abspath(conda_exe)))

    def env_python(self, env_name: str = "") -> Optional[str]:
        """conda 环境 python.exe 路径"""
        if not env_name:
            env_name = self.config.get_tts_config().get("env_name", "cosyvoice")
        root = self.conda_root()
        if not root:
            return None
        py = os.path.join(root, "envs", env_name, "python.exe")
        return py if os.path.exists(py) else None

    def check_environment(self) -> Dict:
        """环境状态检测（UI 就绪徽标用）"""
        git = self.find_git()
        conda = self.find_conda()
        repo = self.repo_dir()
        cloned = os.path.isdir(os.path.join(repo, ".git"))
        env_py = self.env_python()
        model_key = self._current_model_key()
        mdir = self.model_dir(model_key)
        model_ready = os.path.isdir(mdir) and (
            os.path.exists(os.path.join(mdir, "llm.pt"))
            or os.path.exists(os.path.join(mdir, "config.yaml"))
        )
        requirements_ok = False
        if env_py and cloned:
            requirements_ok = self._import_check(env_py)
        return {
            "git": git,
            "conda": conda,
            "env_exists": bool(env_py),
            "env_python": env_py,
            "cloned": cloned,
            "repo_dir": repo,
            "model_key": model_key,
            "model_dir": mdir,
            "model_ready": model_ready,
            "requirements_ok": requirements_ok,
        }

    def _import_check(self, env_python: str) -> bool:
        """校验核心依赖可导入"""
        try:
            r = subprocess.run(
                [env_python, "-c", "import torch, torchaudio"],
                capture_output=True, timeout=120,
                creationflags=_CREATE_NO_WINDOW,
            )
            return r.returncode == 0
        except Exception:
            return False

    # ---------- 子进程执行辅助 ----------

    def _run_cmd(self, cmd: List[str], cwd: str = "", log_prefix: str = "",
                 env_extra: dict = None) -> tuple:
        """阻塞执行命令，逐行转发日志。返回 (exit_code, 输出全文)"""
        if cwd and not os.path.isdir(cwd):
            os.makedirs(cwd, exist_ok=True)
        self._cancel_flag.clear()
        env = None
        if env_extra:
            env = os.environ.copy()
            env.update(env_extra)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_CREATE_NO_WINDOW,
                env=env,
            )
        except OSError as e:
            self.log_received.emit(f"[错误] 无法启动 {cmd[0]}: {e}")
            return -1, str(e)

        self._current_proc = proc
        full_lines: List[str] = []

        def _reader():
            for raw in iter(proc.stdout.readline, b""):
                line = _decode_output(raw).rstrip("\r\n")
                full_lines.append(line)
                self.log_received.emit(f"{log_prefix}{line}" if log_prefix else line)
            proc.stdout.close()

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        code = proc.wait()
        t.join(timeout=5)
        self._current_proc = None
        return code, "\n".join(full_lines)

    def cancel(self):
        """取消当前步骤"""
        self._cancel_flag.set()
        proc = self._current_proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def is_running(self) -> bool:
        return self._running

    # ---------- 三步骤 ----------

    def run_step(self, step: int):
        """异步执行单步（内部线程）"""
        if self._running:
            self.log_received.emit("[提示] 已有安装步骤在执行中")
            return
        threading.Thread(target=self._run_step_sync, args=(step,), daemon=True).start()

    def run_all(self):
        """顺序执行全部步骤"""
        if self._running:
            self.log_received.emit("[提示] 已有安装步骤在执行中")
            return

        def _all():
            for step in (0, 1, 2):
                ok = self._run_step_sync(step)
                if not ok or self._cancel_flag.is_set():
                    break
        threading.Thread(target=_all, daemon=True).start()

    def _run_step_sync(self, step: int) -> bool:
        """同步执行单步，返回是否成功"""
        self._running = True
        self.step_started.emit(step)
        ok, msg = False, ""
        try:
            if step == 0:
                ok, msg = self._step_clone()
            elif step == 1:
                ok, msg = self._step_env()
            elif step == 2:
                ok, msg = self._step_download()
            else:
                ok, msg = False, f"未知步骤 {step}"
        except Exception as e:
            ok, msg = False, f"异常: {e}"
        finally:
            self._running = False
            self.step_finished.emit(step, ok, msg)
            if ok:
                self.install_state_changed.emit()
        return ok

    # --- 步骤 0：克隆仓库 ---

    def _step_clone(self) -> tuple:
        git = self.find_git()
        if not git:
            return False, "未找到 git，请先安装：https://git-scm.com/download/win"

        repo = self.repo_dir()
        os.makedirs(self.models_root(), exist_ok=True)

        if os.path.isdir(os.path.join(repo, ".git")):
            self.log_received.emit("[步骤0] 仓库已存在，补齐子模块...")
            code, out = self._run_cmd(
                [git, "-C", repo, "submodule", "update", "--init", "--recursive"],
                log_prefix="[git] ",
            )
        else:
            self.log_received.emit("[步骤0] 开始克隆 CosyVoice 仓库（含子模块，数百 MB）...")
            code, out = self._run_cmd(
                [git, "clone", "--recursive", "--depth", "1", "--shallow-submodules",
                 COSYVOICE_REPO_URL, repo],
                cwd=self.models_root(),
                log_prefix="[git] ",
            )
            if code != 0:
                self.log_received.emit("[步骤0] 浅克隆失败，回退完整克隆...")
                code, out = self._run_cmd(
                    [git, "clone", "--recursive", COSYVOICE_REPO_URL, repo],
                    cwd=self.models_root(),
                    log_prefix="[git] ",
                )

        if self._cancel_flag.is_set():
            return False, "已取消"

        matcha = os.path.join(repo, "third_party", "Matcha-TTS")
        if code == 0 and os.path.isdir(matcha):
            m = self._tts_model()
            if m:
                self.config.update_model(m["id"], {"repo_dir": repo})
            return True, "仓库克隆完成"
        if code == 0 and not os.path.isdir(matcha):
            return False, "克隆完成但缺少 third_party/Matcha-TTS 子模块，请重跑本步骤"
        return False, "git 克隆失败，请查看日志"

    # --- 步骤 1：conda 环境与依赖 ---

    def _step_env(self) -> tuple:
        conda = self.find_conda()
        if not conda:
            return False, "未找到 conda，请先安装 Miniconda：https://docs.conda.io/en/latest/miniconda.html"
        repo = self.repo_dir()
        if not os.path.isdir(repo):
            return False, "请先完成步骤 0（克隆仓库）"

        self.config.set("tts.conda_path", conda)
        env_name = self.config.get_tts_config().get("env_name", "cosyvoice")
        mirror = self.config.get_tts_config().get(
            "pip_mirror", "https://mirrors.aliyun.com/pypi/simple/")
        env_py = self.env_python(env_name)

        # 1a 创建环境
        if not env_py:
            self.log_received.emit(f"[步骤1] 创建 conda 环境 {env_name} (python 3.10)...")
            code, _ = self._run_cmd(
                [conda, "create", "-n", env_name, "-y", "python=3.10"],
                log_prefix="[conda] ",
            )
            if code != 0:
                return False, "conda 环境创建失败，请查看日志"
            env_py = self.env_python(env_name)
            if not env_py:
                return False, f"环境已创建但找不到 python.exe（{os.path.join(self.conda_root(), 'envs', env_name)}）"
        else:
            self.log_received.emit(f"[步骤1] conda 环境已存在: {env_py}")

        req = os.path.join(repo, "requirements.txt")
        if not os.path.exists(req):
            return False, f"找不到 {req}"

        # 1b 安装依赖（镜像回退链：阿里 → 清华 → 官方 PyPI，某镜像缺包时自动切换）
        self.log_received.emit("[步骤1] 安装依赖（torch 体积大，需 10-30 分钟，请耐心等待）...")

        # Windows 特殊包预处理：
        # - openai-whisper 源码构建需 pkg_resources，但新版 setuptools(81+) 已移除，
        #   且隔离构建环境不受主环境控制 → 剔除后预装 setuptools<81 再 --no-build-isolation 安装
        # - pynini/WeTextProcessing Windows 构建地狱 → 剔除后装 wetext（新版前端默认即 wetext）
        special_re = re.compile(r"pynini|WeTextProcessing|openai-whisper", re.I)
        try:
            with open(req, "r", encoding="utf-8") as f:
                req_lines = f.read().splitlines()
        except OSError:
            req_lines = []
        specials = [ln.strip() for ln in req_lines if special_re.search(ln)]
        filtered = [ln for ln in req_lines if not special_re.search(ln)]
        tmp_req = os.path.join(self.models_root(), "_requirements_filtered.txt")
        os.makedirs(self.models_root(), exist_ok=True)
        with open(tmp_req, "w", encoding="utf-8") as f:
            f.write("\n".join(filtered))

        mirrors = [
            (mirror, "mirrors.aliyun.com"),
            ("https://pypi.tuna.tsinghua.edu.cn/simple", "pypi.tuna.tsinghua.edu.cn"),
            ("https://pypi.org/simple", "pypi.org"),
        ]
        code, out = -1, ""
        used_mir, used_host = mirrors[0]
        for mi, (mir, host) in enumerate(mirrors):
            used_mir, used_host = mir, host  # 记录实际使用的镜像（后续单独安装也用它）
            if mi > 0:
                self.log_received.emit(f"[步骤1] 当前镜像缺包/失败，切换镜像重试: {mir}")
            code, out = self._run_cmd(
                [env_py, "-m", "pip", "install", "-r", tmp_req,
                 "-i", mir, "--trusted-host", host],
                log_prefix="[pip] ",
            )
            if self._cancel_flag.is_set():
                return False, "已取消"
            if code == 0:
                break

        if code != 0:
            return False, "依赖安装失败，请查看日志"

        # 特殊包逐个补装
        if any("openai-whisper" in s.lower() for s in specials):
            self.log_received.emit("[步骤1] 安装 openai-whisper（预装旧版 setuptools 以提供 pkg_resources）...")
            self._run_cmd(
                [env_py, "-m", "pip", "install", "setuptools<81", "wheel",
                 "-i", used_mir, "--trusted-host", used_host],
                log_prefix="[pip] ",
            )
            if self._cancel_flag.is_set():
                return False, "已取消"
            whisper_args = [p for p in next(
                s for s in specials if "openai-whisper" in s.lower()).split(";")[0].split()]
            code, _ = self._run_cmd(
                [env_py, "-m", "pip", "install", *whisper_args,
                 "--no-build-isolation", "-i", used_mir, "--trusted-host", used_host],
                log_prefix="[pip] ",
            )
            if code != 0:
                self.log_received.emit("[警告] openai-whisper 安装失败（仅影响转写功能，TTS 合成不受影响）")

        if any(re.search(r"pynini|WeTextProcessing", s, re.I) for s in specials):
            self.log_received.emit("[步骤1] 安装 wetext 替代 pynini（文本正则化前端）...")
            self._run_cmd(
                [env_py, "-m", "pip", "install", "wetext",
                 "-i", used_mir, "--trusted-host", used_host],
                log_prefix="[pip] ",
            )

        # 1c 补装服务依赖
        self.log_received.emit("[步骤1] 补装服务依赖 fastapi/uvicorn/modelscope...")
        self._run_cmd(
            [env_py, "-m", "pip", "install", "fastapi", "uvicorn", "modelscope", "requests",
             "-i", used_mir, "--trusted-host", used_host],
            log_prefix="[pip] ",
        )

        # 校验
        self.log_received.emit("[步骤1] 校验核心依赖...")
        if self._import_check(env_py):
            return True, "环境安装完成"
        return False, "依赖安装后校验失败（import torch 失败），请查看日志"

    # --- 步骤 2：下载预训练模型 ---

    def _step_download(self) -> tuple:
        env_py = self.env_python()
        if not env_py:
            return False, "请先完成步骤 1（安装 conda 环境）"

        model_key = self._current_model_key()
        model_id = MODELSCOPE_IDS.get(model_key)
        if not model_id:
            return False, f"未知的模型 {model_key}"

        mdir = self.model_dir(model_key)
        if os.path.isdir(mdir) and (
            os.path.exists(os.path.join(mdir, "llm.pt"))
            or os.path.exists(os.path.join(mdir, "config.yaml"))
        ):
            self.log_received.emit(f"[步骤2] 模型已存在: {mdir}")
            self._save_model_dir(mdir)
            return True, "模型已下载"

        # 生成下载脚本（由 env python 执行，不在程序进程 import modelscope）
        script = os.path.join(self.models_root(), "_download_model.py")
        os.makedirs(self.models_root(), exist_ok=True)
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import sys, time\n"
                "from modelscope import snapshot_download\n"
                "ok = False\n"
                "for attempt in range(3):\n"
                "    try:\n"
                "        snapshot_download(sys.argv[1], local_dir=sys.argv[2])\n"
                "        ok = True\n"
                "        break\n"
                "    except Exception as e:\n"
                "        print(f'DOWNLOAD_RETRY {attempt + 1}: {e}', flush=True)\n"
                "        time.sleep(3)\n"
                "print('DOWNLOAD_DONE' if ok else 'DOWNLOAD_FAILED')\n"
                "sys.exit(0 if ok else 1)\n"
            )

        self.log_received.emit(
            f"[步骤2] 从 ModelScope 下载 {model_id}（约 5-10 GB，耗时取决于网速）...")
        # ModelScope 是国内 CDN，走系统代理（Clash 等）反而容易断连 → 绕过代理直连
        download_env = {
            "NO_PROXY": "modelscope.cn,.modelscope.cn,aliyun.com,.aliyun.com",
            "no_proxy": "modelscope.cn,.modelscope.cn,aliyun.com,.aliyun.com",
        }
        code, out = self._run_cmd(
            [env_py, script, model_id, mdir],
            log_prefix="[download] ",
            env_extra=download_env,
        )
        if self._cancel_flag.is_set():
            return False, "已取消"

        if code == 0 and os.path.isdir(mdir) and (
            os.path.exists(os.path.join(mdir, "llm.pt"))
            or os.path.exists(os.path.join(mdir, "config.yaml"))
        ):
            self._save_model_dir(mdir)
            return True, "模型下载完成"
        return False, "模型下载失败，请查看日志（必要时重跑本步骤续传）"

    def _save_model_dir(self, mdir: str):
        m = self._tts_model()
        if m:
            self.config.update_model(m["id"], {"model_dir": mdir})
