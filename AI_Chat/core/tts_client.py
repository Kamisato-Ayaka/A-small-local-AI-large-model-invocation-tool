"""
TTS HTTP 客户端 - 调用 CosyVoice 独立服务（无 Qt 依赖，可在工作线程使用）
"""
import os
import re
import tempfile
import time
from typing import List, Optional

import requests

from core.config import get_config_manager


def get_tts_base_url() -> str:
    """http://host:port（读 config）"""
    cfg = get_config_manager().get_tts_config()
    return f"http://{cfg.get('host', '127.0.0.1')}:{int(cfg.get('port', 8901))}"


def clean_text_for_tts(text: str, max_chars: int = 0) -> str:
    """清洗文本供朗读：去掉思考块/代码块/markdown 符号/动作描述，超长截断"""
    if not text:
        return ""
    if not max_chars:
        max_chars = int(get_config_manager().get_tts_config().get("max_read_chars", 1000))

    t = text
    t = re.sub(r"<think(?:ing|_cont)?>[\s\S]*?</think(?:ing|_cont)?>", "", t, flags=re.I)
    t = re.sub(r"```[\s\S]*?```", "（代码略）", t)
    t = re.sub(r"`[^`]+`", "", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)   # 链接/图片
    t = re.sub(r"[*_~#>|]+", "", t)                      # markdown 符号
    t = re.sub(r"（[^）]*）", "", t)                      # （动作）
    t = re.sub(r"\([^)]*\)", "", t)                      # (动作)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_chars:
        t = t[:max_chars]
    return t


class TTSClient:
    """CosyVoice 服务 HTTP 客户端"""

    def __init__(self, base_url: str = ""):
        self.base_url = base_url or get_tts_base_url()

    def is_alive(self) -> bool:
        """服务是否存活（且非 error）"""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=1.5)
            if resp.status_code == 200:
                return resp.json().get("status") == "ok"
        except Exception:
            pass
        return False

    def is_ready(self) -> bool:
        """模型已加载可合成"""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=1.5)
            if resp.status_code == 200:
                return bool(resp.json().get("model_loaded"))
        except Exception:
            pass
        return False

    def get_voices(self) -> List[str]:
        try:
            resp = requests.get(f"{self.base_url}/voices", timeout=3)
            if resp.status_code == 200:
                return resp.json().get("voices", [])
        except Exception:
            pass
        return []

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0,
                   out_path: str = "", timeout: int = 1800,
                   ref_path: str = "") -> str:
        """合成 → 写 wav 文件，返回路径（阻塞，供工作线程调用）

        ref_path: 克隆参考音频文件路径（优先于 voice 音色名）
        timeout: 合成超时上限，默认 30 分钟（长文本合成耗时可达数分钟）
        """
        payload = {"text": text, "voice": voice, "speed": speed}
        if ref_path:
            payload["ref_path"] = ref_path
        resp = requests.post(f"{self.base_url}/tts", json=payload, timeout=timeout)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RuntimeError(f"TTS 合成失败: {detail}")
        if not out_path:
            fd, out_path = tempfile.mkstemp(prefix="tts_", suffix=".wav")
            os.close(fd)
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path


def ensure_tts_service(wait_ready: bool = True, max_wait: int = 30) -> bool:
    """确保 TTS 服务可用：已 running → True；否则拉起服务并等待就绪"""
    from core.tts_server_manager import get_tts_server_manager

    mgr = get_tts_server_manager()
    client = TTSClient()

    if client.is_alive():
        if mgr.status != "running":
            mgr._external_alive = True
            mgr._set_status("running")
        return client.is_ready()

    if not client.is_alive():
        # 状态残留（如上次会话的孤儿服务已死/被清理）→ 复位后重新拉起
        if mgr.status != "stopped":
            mgr.stop_service()
        if not mgr.start_service():
            return False

    if not wait_ready:
        return True

    deadline = time.time() + max_wait
    while time.time() < deadline:
        if mgr.status == "error":
            return False
        if client.is_ready():
            return True
        time.sleep(1)
    return False
