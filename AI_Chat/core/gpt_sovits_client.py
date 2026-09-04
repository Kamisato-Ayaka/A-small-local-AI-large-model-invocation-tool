"""
GPT-SoVITS HTTP 客户端 - 调用 GPT-SoVITS 独立服务（无 Qt 依赖，可在工作线程使用）
"""
import os
import tempfile
import time
from typing import Optional

import requests

from core.config import get_config_manager


def get_gpt_sovits_base_url() -> str:
    """http://host:port（读 config）"""
    cfg = get_config_manager().get("gpt_sovits", {})
    return f"http://{cfg.get('host', '127.0.0.1')}:{int(cfg.get('port', 9880))}"


class GptSovitsClient:
    """GPT-SoVITS 服务 HTTP 客户端"""

    def __init__(self, base_url: str = ""):
        self.base_url = base_url or get_gpt_sovits_base_url()

    def is_alive(self) -> bool:
        """服务是否存活（GET /control 返回 200，无参数即可探活）"""
        try:
            resp = requests.get(f"{self.base_url}/control", timeout=1.5)
            return resp.status_code == 200
        except Exception:
            pass
        return False

    def synthesize(self, text: str,
                   text_language: str = "zh",
                   refer_wav_path: str = "",
                   prompt_text: str = "",
                   prompt_language: str = "",
                   top_k: int = 5,
                   top_p: float = 1.0,
                   temperature: float = 1.0,
                   speed: float = 1.0,
                   cut_punc: str = "",
                   inp_refs: Optional[list] = None,
                   out_path: str = "",
                   timeout: int = 600) -> str:
        """合成 → 写 wav 文件，返回路径（阻塞，供工作线程调用）

        refer_wav_path + prompt_text + prompt_language: 零样本克隆参考音频
        三者都为空时使用服务端启动时指定的默认参考音频
        """
        payload = {
            "text": text,
            "text_language": text_language,
            "top_k": top_k,
            "top_p": top_p,
            "temperature": temperature,
            "speed": speed,
        }
        if refer_wav_path:
            payload["refer_wav_path"] = refer_wav_path
            payload["prompt_text"] = prompt_text
            payload["prompt_language"] = prompt_language or text_language
        if cut_punc:
            payload["cut_punc"] = cut_punc
        if inp_refs:
            payload["inp_refs"] = inp_refs

        resp = requests.post(f"{self.base_url}/", json=payload, timeout=timeout)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RuntimeError(f"GPT-SoVITS 合成失败: {detail}")

        if not out_path:
            fd, out_path = tempfile.mkstemp(prefix="sovits_", suffix=".wav")
            os.close(fd)
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path

    def change_refer(self, refer_wav_path: str, prompt_text: str,
                     prompt_language: str = "zh") -> bool:
        """更换服务端默认参考音频"""
        payload = {
            "refer_wav_path": refer_wav_path,
            "prompt_text": prompt_text,
            "prompt_language": prompt_language,
        }
        try:
            resp = requests.post(f"{self.base_url}/change_refer", json=payload, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def control(self, command: str) -> bool:
        """重启或退出服务: command='restart'|'exit'"""
        try:
            resp = requests.post(f"{self.base_url}/control",
                                 json={"command": command}, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def set_model(self, gpt_path: str, sovits_path: str) -> bool:
        """运行时切换音色（不重启服务）"""
        try:
            resp = requests.post(f"{self.base_url}/set_model",
                                 json={"gpt_model_path": gpt_path, "sovits_model_path": sovits_path},
                                 timeout=30)
            return resp.status_code == 200
        except Exception:
            return False


def ensure_gpt_sovits_service(wait_ready: bool = True, max_wait: int = 60) -> bool:
    """确保 GPT-SoVITS 服务可用"""
    from core.gpt_sovits_server_manager import get_gpt_sovits_server_manager

    mgr = get_gpt_sovits_server_manager()
    client = GptSovitsClient()

    if client.is_alive():
        if mgr.status != "running":
            mgr._external_alive = True
            mgr._set_status("running")
        return True

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
        if client.is_alive():
            return True
        time.sleep(1)
    return False
