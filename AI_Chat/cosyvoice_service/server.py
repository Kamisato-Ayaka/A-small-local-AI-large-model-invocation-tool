"""
CosyVoice TTS 独立服务（由 conda 环境的 python 运行，不要在程序主进程 import 本文件）

用法：
    <env_python> server.py --host 127.0.0.1 --port 8901 --repo <CosyVoice目录> --model-dir <模型目录> [--ref-dir <音色库目录>]

接口：
    GET  /health  → {"status","service","model_loaded","loading","device","sample_rate","voices"}
    GET  /voices  → {"voices":[...]}
    POST /tts     {"text","voice","speed"} → audio/wav

音色说明（Fun-CosyVoice3 为 zero-shot 基座，无内置音色）：
    - 默认音色 = CosyVoice 仓库自带的 asset/cross_lingual_prompt.wav
    - 自定义音色：往 --ref-dir（默认 <模型上级>/ref_audio）放 5-10 秒清晰人声 wav/mp3/flac，
      文件名（去扩展名）即音色名；同名 .txt（音频的文字内容）可提升克隆准确度（zero_shot 模式）
"""
import argparse
import io
import os
import sys
import threading
import wave

# 命令行参数先解析（argparse 自带 --help）
parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8901)
parser.add_argument("--repo", required=True, help="CosyVoice 仓库目录")
parser.add_argument("--model-dir", required=True, help="预训练模型目录")
parser.add_argument("--ref-dir", default="", help="音色库目录（wav/mp3/flac，文件名=音色名）")
args, _unknown = parser.parse_known_args()

# CosyVoice 仓库 + Matcha-TTS 子模块必须加入 sys.path
sys.path.insert(0, args.repo)
_matcha = None
_matcha_dir = os.path.join(args.repo, "third_party", "Matcha-TTS")
if os.path.isdir(_matcha_dir):
    _matcha = _matcha_dir
    sys.path.insert(0, _matcha)

import torch  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
import uvicorn  # noqa: E402

if not args.ref_dir:
    args.ref_dir = os.path.join(os.path.dirname(os.path.abspath(args.model_dir)), "ref_audio")
os.makedirs(args.ref_dir, exist_ok=True)
_AUDIO_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
_DEFAULT_REF = os.path.join(args.repo, "asset", "cross_lingual_prompt.wav")
_EOP_PREFIX = "You are a helpful assistant.<|endofprompt|>"  # CosyVoice3 必需标记（官方示例格式）

_state = {
    "model": None,
    "model_type": "",
    "loaded": False,
    "loading": True,
    "error": "",
    "sample_rate": 24000,
    "device": "cuda" if torch.cuda.is_available() else "cpu",
}
_lock = threading.Lock()  # 合成串行化

app = FastAPI(title="CosyVoice TTS Service")


def load_model():
    """后台线程加载模型"""
    try:
        print(f"[cosyvoice-service] loading model from {args.model_dir} "
              f"(device={_state['device']})", flush=True)
        try:
            from cosyvoice.cli.cosyvoice import AutoModel
            model = AutoModel(model_dir=args.model_dir)
        except ImportError:
            # 旧版仓库回退
            from cosyvoice.cli.cosyvoice import CosyVoice2  # type: ignore
            model = CosyVoice2(model_dir=args.model_dir)

        _state["model"] = model
        _state["model_type"] = type(model).__name__  # CosyVoice3 需要 <|endofprompt|>，CosyVoice/2 不需要
        try:
            _state["sample_rate"] = int(model.sample_rate)
        except Exception:
            pass
        _state["loaded"] = True
        _state["loading"] = False
        print(f"[cosyvoice-service] model loaded OK (type={_state['model_type']})", flush=True)
    except Exception as e:
        _state["loading"] = False
        _state["error"] = str(e)
        print(f"[cosyvoice-service] model load FAILED: {e}", flush=True)


def _norm_output(item):
    """兼容新版 dict（j['tts_speech']）与旧版 tuple（(speech, sr)）"""
    if isinstance(item, dict):
        return item.get("tts_speech")
    if isinstance(item, (tuple, list)):
        return item[0]
    return item


def _list_voices():
    try:
        return list(_state["model"].list_available_spks())
    except Exception:
        return []


def _find_ref_file(voice: str) -> str:
    """按音色名在音色库找参考音频文件；找不到返回 ''（用默认）"""
    for ext in _AUDIO_EXTS:
        p = os.path.join(args.ref_dir, voice + ext)
        if os.path.isfile(p):
            return p
    return ""


def _list_voices():
    try:
        names = []
        for fn in os.listdir(args.ref_dir):
            base, ext = os.path.splitext(fn)
            if ext.lower() in _AUDIO_EXTS and base not in names:
                names.append(base)
        return names
    except Exception:
        return []


def _load_ref_wav(path: str):
    """（已废弃）本版本 CosyVoice inference_* 直接接收文件路径"""
    return path


def _is_v3() -> bool:
    """CosyVoice3 系模型要求文本含 <|endofprompt|>；CosyVoice/2 不要加"""
    return "CosyVoice3" in (_state.get("model_type") or "")


def _clone_gen(text: str, ref: str, speed: float):
    """参考音频克隆合成：ref 为音频文件路径，旁挂同名 .txt 时走 zero_shot"""
    model = _state["model"]
    txt_path = os.path.splitext(ref)[0] + ".txt"
    if os.path.isfile(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            prompt_text = f.read().strip()
        if prompt_text:
            return model.inference_zero_shot(text, (_EOP_PREFIX + prompt_text) if _is_v3() else prompt_text,
                                             ref, stream=False, speed=speed)
    return model.inference_cross_lingual((_EOP_PREFIX + text) if _is_v3() else text,
                                         ref, stream=False, speed=speed)


def synth_to_wav(text: str, voice: str, speed: float, ref_path: str = "") -> bytes:
    """合成 → wav bytes（串行锁内调用）

    参考音频优先级：ref_path（客户端直传克隆音频）> voice 音色库 > voice 内置音色 > 默认参考音频。
    注意：
    1. inference_* 内部用 load_wav(path) 自行加载音频，必须传文件路径而不是张量。
    2. CosyVoice3 要求文本含 <|endofprompt|> 标记（官方示例格式 "You are a helpful assistant.<|endofprompt|>"）。
    """
    model = _state["model"]

    # ① 客户端直传的克隆音频（角色绑定/全局默认）
    if ref_path:
        if not os.path.isfile(ref_path):
            raise ValueError(f"克隆音频不存在: {ref_path}")
        ext = os.path.splitext(ref_path)[1].lower()
        if ext not in _AUDIO_EXTS:
            raise ValueError(f"不支持的音频格式 {ext}（支持 wav/mp3/flac/ogg/m4a）")
        gen = _clone_gen(text, ref_path, speed)

    else:
        ref_file = _find_ref_file(voice) if voice else ""
        if voice and not ref_file:
            builtin = _list_voices()
            # ② 内置音色（如 CosyVoice2 自带 中文女/中文男 等）
            if voice in builtin:
                gen = model.inference_sft(text, voice, stream=False, speed=speed)
            else:
                others = builtin or _list_voices()
                print(f"[cosyvoice-service] 音色 '{voice}' 不存在，使用默认音色"
                      + (f"（可用: {others}）" if others else ""), flush=True)
                # ③ 默认参考音频
                if not os.path.isfile(_DEFAULT_REF):
                    raise ValueError("无可用参考音频：默认音色文件缺失且音色库为空")
                gen = _clone_gen(text, _DEFAULT_REF, speed)
        elif ref_file:
            # ②' 音色库中同名参考音频
            gen = _clone_gen(text, ref_file, speed)
        else:
            # ③ 默认参考音频
            if not os.path.isfile(_DEFAULT_REF):
                raise ValueError("无可用参考音频：默认音色文件缺失且音色库为空")
            gen = _clone_gen(text, _DEFAULT_REF, speed)

    chunks = []
    for item in gen:
        t = _norm_output(item)
        if t is None:
            continue
        if isinstance(t, torch.Tensor) and t.dim() > 1:
            t = t.squeeze()
        chunks.append(t)
    if not chunks:
        raise RuntimeError("合成结果为空")

    speech = torch.cat(chunks) if len(chunks) > 1 else chunks[0]
    sr = _state["sample_rate"]

    buf = io.BytesIO()
    wav_bytes(buf, speech, sr)
    return buf.getvalue()


def wav_bytes(buf: io.BytesIO, speech, sr: int):
    """speech float32 (-1~1) → 16bit PCM WAV 写入 buf（纯标准库，避免 torchaudio.save 兼容问题）"""
    tensor = speech if torch.is_tensor(speech) else torch.tensor(speech)
    tensor = tensor.detach().cpu().float().reshape(-1)
    pcm = (tensor.clamp(-1.0, 1.0) * 32767.0).to(torch.int16).numpy().tobytes()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm)


@app.get("/health")
def health():
    if _state["error"]:
        return JSONResponse({
            "status": "error", "service": "cosyvoice",
            "model_loaded": False, "loading": False,
            "error": _state["error"],
        })
    return JSONResponse({
        "status": "ok",
        "service": "cosyvoice",
        "model_loaded": _state["loaded"],
        "loading": _state["loading"],
        "model": os.path.basename(args.model_dir),
        "model_type": _state["model_type"],
        "device": _state["device"],
        "sample_rate": _state["sample_rate"],
        "voices": _list_voices(),
    })


@app.get("/voices")
def voices():
    if not _state["loaded"]:
        raise HTTPException(503, "模型未加载完成")
    return JSONResponse({"voices": _list_voices()})


@app.post("/tts")
def tts(payload: dict):
    if not _state["loaded"]:
        raise HTTPException(503, "模型未加载完成" if _state["loading"] else f"模型加载失败: {_state['error']}")
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    voice = payload.get("voice", "")
    speed = float(payload.get("speed", 1.0))
    ref_path = (payload.get("ref_path") or "").strip()
    try:
        with _lock:
            wav = synth_to_wav(text, voice, speed, ref_path=ref_path)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e))
    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    # 输出重定向到日志文件：父进程（主程序）退出后管道会破裂，
    # tqdm/print 写日志会报 [Errno 22] 甚至卡死，写文件则完全不受影响
    try:
        _log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.log")
        _log_fd = open(_log_path, "w", encoding="utf-8", buffering=1)
        sys.stdout = _log_fd
        sys.stderr = _log_fd
        os.dup2(_log_fd.fileno(), 1)
        os.dup2(_log_fd.fileno(), 2)
    except Exception:
        pass

    if _matcha is None:
        print("[cosyvoice-service] 警告: 未找到 third_party/Matcha-TTS，模型加载可能失败", flush=True)
    threading.Thread(target=load_model, daemon=True).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
