"""
配置管理 - 保存和加载用户设置
"""
import os
import json
import copy
import glob
from typing import Optional, List, Dict


PROGRAM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _all_search_roots() -> List[str]:
    """返回所有候选搜索根目录列表"""
    parent_dir = os.path.dirname(PROGRAM_ROOT)
    grandparent_dir = os.path.dirname(parent_dir)
    return [PROGRAM_ROOT, parent_dir, grandparent_dir]


def _find_all_models_dirs() -> List[str]:
    """
    收集所有可能存放 .gguf 的 models/ 目录（多源合并）。
    搜索顺序：
      1. 搜索根（CodeMate-AI / P / P 的上一级）下直接的 models/
      2. 搜索根下任何 llama* 或 codemate* 子目录里的 models/
         （含 llama.cpp-master、llama-b*-bin-*、CodeMate-AI 自身）
    返回去重后的绝对路径列表。
    """
    roots = _all_search_roots()
    results: List[str] = []
    seen = set()

    def _add_dir(p: str):
        if not p or not os.path.isdir(p):
            return
        ap = os.path.abspath(p)
        key = ap.lower()
        if key in seen:
            return
        seen.add(key)
        results.append(ap)

    # 1. 搜索根下直接的 models/（含 P\models、CodeMate-AI\models 等）
    for r in roots:
        if os.path.isdir(r):
            _add_dir(os.path.join(r, "models"))

    # 2. 搜索根下 llama* / codemate* 子目录里的 models/
    for r in roots:
        if not os.path.isdir(r):
            continue
        try:
            for entry in os.listdir(r):
                entry_path = os.path.join(r, entry)
                if not os.path.isdir(entry_path):
                    continue
                el = entry.lower()
                if el.startswith("llama") or "codemate" in el:
                    _add_dir(os.path.join(entry_path, "models"))
        except OSError:
            pass

    return results


def _find_models_dir() -> Optional[str]:
    """返回第一个存在的 models/ 目录（兼容旧接口）。真正扫描用 _find_all_models_dirs。"""
    dirs = _find_all_models_dirs()
    return dirs[0] if dirs else None


def _find_llama_server_exe() -> Optional[str]:
    """
    独立搜索 llama-server 可执行文件。
    在各搜索根下直接查 + 扫描 llama-b*-bin-* 子目录 + 任何子目录。
    """
    exe_name = "llama-server.exe" if os.name == "nt" else "llama-server"
    roots = _all_search_roots()

    for root in roots:
        if not os.path.isdir(root):
            continue
        # 直接放在根下
        direct = os.path.join(root, exe_name)
        if os.path.exists(direct):
            return direct
        # 遍历根下一级的子文件夹
        try:
            for entry in os.listdir(root):
                entry_path = os.path.join(root, entry)
                if not os.path.isdir(entry_path):
                    continue
                candidate = os.path.join(entry_path, exe_name)
                if os.path.exists(candidate):
                    return candidate
        except OSError:
            pass

    return None


def _scan_models_gguf() -> Dict[str, str]:
    """
    扫描【所有】models/ 目录（P\models + llama.cpp-master\models + ...）里的 gguf。
    返回结构：
      {"models": {文件名小写: 完整路径},
       "mmprojs": {文件名小写: 完整路径},
       "all_files": {绝对路径: size(int)},
       "dirs_used": [扫描过的目录列表]}
    注意：ggml-vocab-* 等 < 10MB 的词典/模板文件不会被当作真正的推理模型
          （避免把它们误填到 Gemma 3 1B 等预置模型上）。
    """
    result: Dict = {"models": {}, "mmprojs": {}, "all_files": {}, "dirs_used": []}
    dirs = _find_all_models_dirs()
    if not dirs:
        return result

    VOCAB_THRESHOLD = 50 * 1024 * 1024  # 50MB 以下视为词典/模板，不当成真正的推理模型

    for md in dirs:
        result["dirs_used"].append(md)
        try:
            for f in os.listdir(md):
                if not f.lower().endswith(".gguf"):
                    continue
                full = os.path.join(md, f)
                try:
                    sz = os.path.getsize(full)
                except OSError:
                    continue
                fl = f.lower()
                result["all_files"][full] = sz

                # 词典/模板太小 (<50MB) + 名字暗示是 vocab → 只登记，不当推理/导入
                skip_as_model = False
                for tok in ("ggml-vocab-", "mmproj", "clip"):
                    if tok in fl:
                        if sz < VOCAB_THRESHOLD:
                            skip_as_model = True
                        break

                if skip_as_model:
                    # mmproj/clip 还是要登记（但单独桶）；vocab 不进任何匹配桶
                    if "mmproj" in fl or "clip" in fl:
                        prev = result["mmprojs"].get(fl)
                        if prev is None or sz > os.path.getsize(prev):
                            result["mmprojs"][fl] = full
                    continue

                if "mmproj" in fl or "clip" in fl:
                    prev = result["mmprojs"].get(fl)
                    if prev is None or sz > os.path.getsize(prev):
                        result["mmprojs"][fl] = full
                else:
                    prev = result["models"].get(fl)
                    if prev is None or sz > os.path.getsize(prev):
                        result["models"][fl] = full
        except OSError:
            continue

    return result


def _match_model_path(keywords: List[str], scanned: Dict[str, str]) -> str:
    """根据关键词在扫描结果中匹配模型路径"""
    for fl, full in scanned.items():
        if all(kw in fl for kw in keywords):
            return full
    return ""


def _match_mmproj_path(keywords: List[str], scanned: Dict[str, str]) -> str:
    """根据关键词在 mmproj 扫描结果中匹配"""
    for fl, full in scanned["mmprojs"].items():
        if all(kw in fl for kw in keywords):
            return full
    return ""


DEFAULT_CONFIG = {
    "models": [
        {
            "id": "gemma3-1b",
            "name": "Gemma 3 1B",
            "description": "小模型日常对话",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.7,
            "match_keywords": ["gemma", "3", "1b"],
        },
        {
            "id": "gemma-4-e4b-uncensored",
            "name": "Gemma 4 E4B Uncensored",
            "description": "越狱版",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.7,
            "match_keywords": ["gemma", "4", "uncensored"],
        },
        {
            "id": "qwen35-35b-uncensored",
            "name": "Qwen3.6-35B Uncensored",
            "description": "越狱版",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.7,
            "match_keywords": ["qwen", "35b", "uncensored"],
        },
        {
            "id": "qwen-vl",
            "name": "Qwen VL 多模态",
            "description": "需 mmproj 文件",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.7,
            "match_keywords": ["qwen", "35b", "uncensored"],
            "mmproj_match_keywords": ["qwen", "mmproj"],
        },
        {
            "id": "deepseek-v3",
            "name": "DeepSeek-V3",
            "description": "越狱版（占位）",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.7,
            "match_keywords": ["deepseek", "v3"],
        },
        {
            "id": "llama3-8b-darkidol",
            "name": "Llama3-8b-DarkIdol",
            "description": "暗黑角色扮演，越狱版",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.85,
            "match_keywords": ["llama", "darkidol"],
        },
        {
            "id": "gemma-4-31b-jang-crack",
            "name": "Gemma-4-31b-jang-crack",
            "description": "越狱版",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.7,
            "match_keywords": ["gemma", "31b", "jang"],
        },
        {
            "id": "hermes-3",
            "name": "Hermes-3",
            "description": "越狱版",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.7,
            "match_keywords": ["hermes", "3"],
        },
        {
            "id": "custom-local",
            "name": "用户自定义本地模型",
            "description": "手动指定路径",
            "type": "local",
            "model_path": "",
            "mmproj_path": "",
            "n_gpu_layers": 999,
            "ctx_size": 8192,
            "n_predict": 4096,
            "temperature": 0.7,
            "match_keywords": [],
        },
        {
            "id": "sdk-model",
            "name": "SDK 模型 (OpenAI 兼容)",
            "description": "API 调用，占位",
            "type": "sdk",
            "base_url": "",
            "api_key": "",
            "model_name": "",
            "temperature": 0.7,
        },
        {
            "id": "cosyvoice-tts",
            "name": "CosyVoice 本地语音",
            "description": "本地 TTS 语音合成（独立服务进程）",
            "type": "tts",
            "engine": "cosyvoice",
            "model_key": "CosyVoice2-0.5B",
            "voice": "中文女",
            "speed": 1.0,
            "auto_start": False,
            "repo_dir": "",
            "model_dir": "",
        },
    ],
    "current_model_id": "gemma-4-e4b-uncensored",
    "llm": {
        "host": "127.0.0.1",
        "port": 8080,
    },
    "tts": {
        "host": "127.0.0.1",
        "port": 8901,
        "conda_path": "",
        "env_name": "cosyvoice",
        "models_root": "",
        "pip_mirror": "https://mirrors.aliyun.com/pypi/simple/",
        "max_read_chars": 1000,
    },
    "server": {
        "auto_start": False,
        "llama_server_path": "",
    },
    "app": {
        "theme": "dark",
        "font_size": 13,
        "show_welcome": True,
    },
    "theme": {
        "editor_bg_image": "",
        "chat_bg_image": "",
        "editor_bg_color": "#1e1e1e",
        "chat_bg_color": "#252526",
        "accent_color": "#007acc",
        "text_color": "#cccccc",
        "chat_text_color": "#cccccc",
        "bg_opacity": 100,
        "text_opacity": 100,
        "ui_transparency": 50,
    },
    "system_monitor": {
        "enabled": True,
        "interval_ms": 2000,
    },
    "chat": {
        "memory_rounds": 10,
    },
    "comfyui": {
        "server_address": "127.0.0.1:8188",
        "exe_path": "",
        "download_folder": "",
        "model_source": "Sulphur 2",
        "workflows": [],
        "last_workflow": "",
        "setup_completed": False,
        "default_width": 768,
        "default_height": 432,
        "default_duration": 5,
        "default_fps": 24,
        "default_steps": 20,
        "default_cfg": 6,
    },
    "gpt_sovits": {
        "host": "127.0.0.1",
        "port": 9880,
        "repo_dir": "",
        "device": "cuda",
        "sovits_model": "",
        "gpt_model": "",
        "default_refer_wav": "",
        "default_refer_text": "",
        "default_refer_lang": "zh",
        "default_text_language": "zh",
        "top_k": 5,
        "top_p": 1.0,
        "temperature": 1.0,
        "speed": 1.0,
        "cut_punc": "",
        "auto_start": False,
    },
    "tts_engine": "gpt_sovits",  # cosyvoice | gpt_sovits
}


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = os.path.join(os.path.expanduser("~"), ".codemate")
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, "config.json")
        self._config = None

        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)

    def load(self) -> dict:
        """加载配置"""
        if self._config is not None:
            return self._config

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                self._config = self._deep_merge(DEFAULT_CONFIG, loaded)
                self._migrate_old_config()
                self.auto_detect_models_dir()
            except Exception:
                self._config = copy.deepcopy(DEFAULT_CONFIG)
                self.auto_detect_models_dir()
        else:
            self._config = copy.deepcopy(DEFAULT_CONFIG)
            self.auto_detect_models_dir()

        return self._config

    def auto_detect_models_dir(self):
        """
        自动扫描 models/ 目录：
        1) 将实际存在的 gguf 文件路径填入预置模型的 model_path / mmproj_path
        2) 扫描到但预置模型没用到的 .gguf，自动追加为「自动导入」模型条目
        """
        scanned = _scan_models_gguf()

        # 1. 给预置模型填路径
        used_paths = set()

        for model in self._config.get("models", []):
            if model.get("type") != "local":
                continue
            matched = False
            if model.get("match_keywords"):
                path = _match_model_path(model["match_keywords"], scanned["models"])
                if path:
                    model["model_path"] = path
                    used_paths.add(os.path.abspath(path).lower())
                    matched = True
            if model.get("mmproj_match_keywords"):
                mmproj = _match_mmproj_path(model["mmproj_match_keywords"], scanned)
                if mmproj:
                    model["mmproj_path"] = mmproj
                    used_paths.add(os.path.abspath(mmproj).lower())
                    matched = True
            elif model.get("mmproj_path") == "" and "vl" in model.get("id", "").lower():
                if scanned["mmprojs"]:
                    first_mmproj = list(scanned["mmprojs"].values())[0]
                    if not model.get("mmproj_path"):
                        model["mmproj_path"] = first_mmproj
                        used_paths.add(os.path.abspath(first_mmproj).lower())
                        matched = True
            # 同时记录已有 model_path（用户之前手填的或已匹配成功的），避免重复导入
            mp = model.get("model_path", "")
            if mp:
                try:
                    used_paths.add(os.path.abspath(mp).lower())
                except OSError:
                    pass
            pp = model.get("mmproj_path", "")
            if pp:
                try:
                    used_paths.add(os.path.abspath(pp).lower())
                except OSError:
                    pass

        # 2. 找到未占用的推理模型/MMproj，自动追加条目
        cfg_models = self._config.setdefault("models", [])
        existing_ids = {m.get("id") for m in cfg_models}

        def _friendly_name(filepath: str) -> str:
            base = os.path.splitext(os.path.basename(filepath))[0]
            # 去掉常见后缀，让名字更短
            for suf in ("-Q4_K_M", "-IQ2_M", "-Q5_K_M", "-Q8_0", "-F16", "-f16", "-Q2_K", "-Q3_K_M", "-Q6_K"):
                if base.lower().endswith(suf.lower()):
                    base = base[: -len(suf)]
            # 压缩多个连字符
            return base.replace("--", "-").strip("-_ ")[:40] or os.path.basename(filepath)

        import time

        # --- 追加未使用的普通模型 ---
        for fl, full in scanned["models"].items():
            try:
                key = os.path.abspath(full).lower()
            except OSError:
                continue
            if key in used_paths:
                continue
            used_paths.add(key)
            auto_id = "auto-" + str(int(time.time() * 1000)) + "-" + fl.replace(".gguf", "").replace(" ", "_")[-20:]
            # 避免重复 ID（极端情况多个 gguf 同名）
            suffix_id = 0
            final_id = auto_id
            while final_id in existing_ids:
                suffix_id += 1
                final_id = f"{auto_id}-{suffix_id}"
            existing_ids.add(final_id)
            sz = scanned["all_files"].get(full, 0)
            size_desc = ""
            if sz:
                if sz >= 1024**3:
                    size_desc = f"  ({sz/1024**3:.2f} GB)"
                elif sz >= 1024**2:
                    size_desc = f"  ({sz/1024**2:.0f} MB)"
            cfg_models.append({
                "id": final_id,
                "name": _friendly_name(full) + size_desc,
                "description": f"自动导入：{full}",
                "type": "local",
                "model_path": full,
                "mmproj_path": "",
                "n_gpu_layers": 999,
                "ctx_size": 8192,
                "n_predict": 4096,
                "temperature": 0.7,
                "match_keywords": [],  # 空关键词=永不重匹配，保留用户手动填的路径
                "_auto_imported": True,
            })

        # --- 追加未使用的 mmproj 到「自定义多模态」占位（无需单独条目，留作匹配）---
        #  mmprojs 通常是附在主模型上的，这里不单独生成条目，只做路径已标记 used_paths

        # 3. 兜底：写入 llama-server 路径
        if not self._config.get("server", {}).get("llama_server_path", ""):
            server_exe = _find_llama_server_exe()
            if server_exe:
                self._config.setdefault("server", {})
                self._config["server"]["llama_server_path"] = server_exe

    def _migrate_old_config(self):
        """迁移旧版配置到新的多模型结构"""
        cfg = self._config

        # ---- 补种 CosyVoice TTS 占位条目（旧配置的 models[] 会整体覆盖默认值，需在此补）----
        models_0 = cfg.get("models", []) or []
        if not any(m.get("id") == "cosyvoice-tts" for m in models_0):
            tts_default = None
            for m in DEFAULT_CONFIG.get("models", []):
                if m.get("id") == "cosyvoice-tts":
                    tts_default = copy.deepcopy(m)
                    break
            if tts_default is not None:
                cfg.setdefault("models", []).append(tts_default)

        if not cfg.get("models") and cfg.get("llm", {}).get("model_path"):
            old = cfg["llm"]
            model = {
                "id": f"local-{int(os.times()[4])}",
                "name": os.path.splitext(os.path.basename(old.get("model_path", "")))[0][:30] or "本地模型",
                "type": "local",
                "model_path": old.get("model_path", ""),
                "mmproj_path": old.get("mmproj_path", ""),
                "n_gpu_layers": old.get("n_gpu_layers", 999),
                "ctx_size": old.get("ctx_size", 8192),
                "n_predict": old.get("n_predict", 4096),
                "temperature": old.get("temperature", 0.7),
            }
            cfg["models"] = [model]
            cfg["current_model_id"] = model["id"]
            self.save()
        # ---- 去重：清理 models 中重复 id（历史脏数据）----
        models_ = cfg.get("models", []) or []
        seen_ = set()
        uniq_ = []
        for m_ in models_:
            mid_ = m_.get("id")
            if mid_ in seen_:
                continue
            seen_.add(mid_)
            uniq_.append(m_)
        cfg["models"] = uniq_
        # 清理同名下的空壳副本（多个 custom-local 同 name 但 id 不同且路径空）
        entry_ids = {"custom-local", "sdk-model"}
        for key_id in list(entry_ids):
            kept = None
            keep_idx = None
            for i2_, m2_ in enumerate(uniq_):
                if m2_.get("id") == key_id:
                    kept = m2_; keep_idx = i2_; break
            if kept is None:
                continue
            # 如果 kept 自己已填好路径，那其它同 name 未就绪的视为重复空壳，删除
            name_ = kept.get("name")
            type_ = kept.get("type")
            filtered_ = []
            for i2_, m2_ in enumerate(uniq_):
                if i2_ == keep_idx:
                    filtered_.append(m2_); continue
                same = (m2_.get("name") == name_ and m2_.get("type") == type_
                        and not m2_.get("_auto_imported")
                        and not (m2_.get("match_keywords") or []) and m2_.get("id") not in entry_ids)
                if same:
                    # 判空：未就绪则删
                    if type_ == "sdk":
                        empty_ = not bool(m2_.get("base_url"))
                    else:
                        mp_ = m2_.get("model_path", "")
                        empty_ = not (mp_ and os.path.exists(mp_))
                    if empty_:
                        continue
                filtered_.append(m2_)
            cfg["models"] = filtered_
            uniq_ = filtered_

    def save(self, config: dict = None):
        """保存配置"""
        if config is not None:
            self._config = config
        if self._config is None:
            self._config = copy.deepcopy(DEFAULT_CONFIG)

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def get(self, key: str, default=None):
        """获取配置项，支持点分隔路径"""
        config = self.load()
        keys = key.split('.')
        val = config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key: str, value):
        """设置配置项"""
        config = self.load()
        keys = key.split('.')
        d = config
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
        self.save()

    # ========== 模型管理 ==========

    def get_models(self) -> List[Dict]:
        """获取所有模型列表"""
        models_ = self.load().get("models", [])
        # 按 id 去重（保留首次出现），清理历史配置中的重复条目（如重复 custom-local）
        seen_ = set()
        out_ = []
        for m_ in models_:
            mid_ = m_.get("id")
            if mid_ in seen_:
                continue
            seen_.add(mid_)
            out_.append(m_)
        return out_

    def get_current_model(self) -> Optional[Dict]:
        """获取当前选中的模型"""
        cfg = self.load()
        model_id = cfg.get("current_model_id", "")
        for m in cfg.get("models", []):
            if m.get("id") == model_id:
                return m
        return None

    # ========== TTS（CosyVoice）管理 ==========

    def get_tts_models(self) -> List[Dict]:
        """获取所有 TTS 模型条目"""
        return [m for m in self.get_models() if m.get("type") == "tts"]

    def get_tts_config(self) -> Dict:
        """获取 tts 全局配置节"""
        return self.load().get("tts", copy.deepcopy(DEFAULT_CONFIG.get("tts", {})))

    def get_tts_ready_model(self) -> Optional[Dict]:
        """获取第一个已就绪（model_dir 存在）的 TTS 模型条目"""
        for m in self.get_tts_models():
            md = m.get("model_dir", "")
            if md and os.path.isdir(md):
                return m
        return None

    def add_model(self, model: Dict) -> str:
        """添加模型，返回模型 ID"""
        cfg = self.load()
        if "id" not in model or not model["id"]:
            import time
            model["id"] = f"{model.get('type', 'local')}-{int(time.time()*1000)}"
        cfg["models"].append(model)

        if len(cfg["models"]) == 1:
            cfg["current_model_id"] = model["id"]

        self.save()
        return model["id"]

    def update_model(self, model_id: str, updates: Dict):
        """更新模型配置"""
        cfg = self.load()
        for m in cfg.get("models", []):
            if m.get("id") == model_id:
                m.update(updates)
                self.save()
                return True
        return False

    def delete_model(self, model_id: str):
        """删除模型"""
        cfg = self.load()
        cfg["models"] = [m for m in cfg.get("models", []) if m.get("id") != model_id]

        if cfg.get("current_model_id") == model_id:
            if cfg["models"]:
                cfg["current_model_id"] = cfg["models"][0]["id"]
            else:
                cfg["current_model_id"] = ""

        self.save()

    def set_current_model(self, model_id: str):
        """设置当前模型"""
        cfg = self.load()
        for m in cfg.get("models", []):
            if m.get("id") == model_id:
                cfg["current_model_id"] = model_id
                self.save()
                return True
        return False

    def refresh_auto_detect(self):
        """手动触发一次自动检测（并保存）"""
        self.load()
        self.auto_detect_models_dir()
        self.save()

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """深度合并两个字典"""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


_config_manager = None


def get_config_manager(config_dir: str = None) -> ConfigManager:
    """获取全局配置管理器"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_dir)
    return _config_manager
