"""
Web 服务器 - 提供 WiFi 网页访问 AI 对话和角色扮演功能
"""
import os
import json
import queue
import socket
import threading
import time
import asyncio
from typing import List, Dict, Optional

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

from core.llm_client import LLMClient, ThinkStreamFilter, sanitize_history_text, estimate_tokens
from core.character_manager import CharacterManager, Character


def _cfg_web():
    """获取配置管理器（延迟导入避免循环依赖）"""
    from core.config import get_config_manager
    return get_config_manager()


class WebServer:
    """Web 服务器管理"""

    def __init__(self, charter_dir: str = None, llm_base_url: str = None,
                 server_manager=None, system_monitor=None):
        self.charter_dir = charter_dir
        self.llm_base_url = llm_base_url or "http://127.0.0.1:8080"
        self.app = None
        self.server_thread = None
        self.is_running = False
        self.port = 8765
        self.host = "0.0.0.0"
        self.config = None
        self.server_manager = server_manager
        self.system_monitor = system_monitor

        # 会话管理（内存中，简单实现）
        self.sessions = {}  # session_id -> {messages, character, mode, ...}
        self._session_counter = 0

        # ngrok 隧道
        self.ngrok_tunnel = None

        self._init_app()

    def _init_app(self):
        """初始化 FastAPI 应用"""
        if not FASTAPI_AVAILABLE:
            return

        self.app = FastAPI(title="A Small Local AI Runner Web")

        # 静态文件
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        if os.path.exists(static_dir):
            self.app.mount("/static", StaticFiles(directory=static_dir), name="static")

        # 路由
        @self.app.get("/")
        async def index():
            return FileResponse(os.path.join(static_dir, "index.html"))

        @self.app.get("/api/status")
        async def api_status():
            """获取服务状态"""
            character_manager = self._get_char_manager()
            characters = []
            if character_manager:
                for c in character_manager.get_characters():
                    characters.append({
                        "name": c.name,
                        "icon": f"/api/character/icon/{c.name}" if c.has_icon else None
                    })
            return JSONResponse({
                "status": "ok",
                "llm_url": self.llm_base_url,
                "characters": characters,
                "model_status": self._get_model_status(),
                "system_stats": self._get_system_stats()
            })

        @self.app.get("/api/character/list")
        async def character_list():
            """获取角色列表"""
            character_manager = self._get_char_manager()
            characters = []
            if character_manager:
                for c in character_manager.get_characters():
                    characters.append({
                        "name": c.name,
                        "has_icon": c.has_icon
                    })
            return JSONResponse({"characters": characters})

        @self.app.get("/api/system/stats")
        async def system_stats():
            """获取系统状态（CPU、内存、GPU）"""
            return JSONResponse(self._get_system_stats())

        @self.app.get("/api/model/status")
        async def model_status():
            """获取模型状态"""
            return JSONResponse(self._get_model_status())

        @self.app.post("/api/model/start")
        async def model_start():
            """启动模型"""
            if not self.server_manager:
                return JSONResponse({"ok": False, "error": "Server manager not available"})
            try:
                self.server_manager.start_server()
                return JSONResponse({"ok": True, "status": self.server_manager.status})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        @self.app.post("/api/model/stop")
        async def model_stop():
            """停止模型"""
            if not self.server_manager:
                return JSONResponse({"ok": False, "error": "Server manager not available"})
            try:
                self.server_manager.stop_server()
                return JSONResponse({"ok": True, "status": self.server_manager.status})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        @self.app.get("/api/models")
        async def models_list():
            """获取可选模型列表（含就绪状态与当前选中项）"""
            try:
                from core.config import get_config_manager
                cfg = get_config_manager()
                models = []
                for m in cfg.get_models():
                    mtype = m.get("type", "local")
                    path = m.get("model_path", "")
                    if mtype == "local":
                        ready = bool(path) and os.path.exists(path)
                    else:
                        # 自定义 / SDK 模型无需本地 .gguf 文件
                        ready = True
                    models.append({
                        "id": m.get("id", ""),
                        "name": m.get("name", m.get("id", "")),
                        "type": mtype,
                        "ready": ready,
                        "current": m.get("id") == cfg.get("current_model_id", ""),
                    })
                return JSONResponse({
                    "models": models,
                    "model_status": self._get_model_status(),
                })
            except Exception as e:
                return JSONResponse({"models": [], "error": str(e)})

        @self.app.post("/api/model/select")
        async def model_select(data: dict):
            """选择使用的模型；若服务正在运行则后台自动重启以加载新模型"""
            model_id = data.get("model_id", "")
            try:
                from core.config import get_config_manager
                cfg = get_config_manager()
                ok = cfg.set_current_model(model_id)
                if not ok:
                    return JSONResponse({"ok": False, "error": "模型不存在"})
                restarted = False
                if self.server_manager and self.server_manager.status in ("running", "starting"):
                    # 后台线程重启（健康检查已线程化，Web 线程可安全启停）
                    threading.Thread(target=self.server_manager.restart_server, daemon=True).start()
                    restarted = True
                return JSONResponse({
                    "ok": True,
                    "restarted": restarted,
                    "model_status": self._get_model_status(),
                })
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        @self.app.post("/api/model/capabilities")
        async def model_capabilities():
            """询问当前已加载的 AI 模型具备哪些能力（按模型缓存结果）"""
            try:
                if not self.server_manager or self.server_manager.status != "running":
                    return JSONResponse({"ok": False, "error": "模型服务未运行，请先启动模型"})
                current = self.server_manager.config.get_current_model() or {}
                model_id = current.get("id", "")
                if not hasattr(self, "_cap_cache"):
                    self._cap_cache = {}
                if model_id and model_id in self._cap_cache:
                    return JSONResponse({"ok": True, "capabilities": self._cap_cache[model_id], "cached": True})

                prompt = (
                    "请用一行、不超过40个字，简要列出你具备的能力，"
                    "格式示例：中文对话 / 代码生成 / 逻辑推理 / 长文本 / 视觉理解 / 工具调用。"
                    "只输出这一行，不要解释。"
                )

                def _ask():
                    llm = LLMClient(base_url=self.llm_base_url)
                    resp = llm.chat(
                        [{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=120,
                    )
                    try:
                        return resp["choices"][0]["message"]["content"] or ""
                    except Exception:
                        return str(resp)[:200]

                # 阻塞请求放入线程池，避免卡死事件循环
                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(None, _ask)
                text = sanitize_history_text(text)[0].strip() or "（模型未返回有效信息）"
                if model_id:
                    self._cap_cache[model_id] = text
                return JSONResponse({"ok": True, "capabilities": text})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        @self.app.get("/api/character/icon/{name}")
        async def character_icon(name: str):
            """获取角色图标"""
            character_manager = self._get_char_manager()
            if not character_manager:
                raise HTTPException(status_code=404, detail="Character manager not available")
            char = character_manager.get_character(name)
            if not char or not char.has_icon:
                raise HTTPException(status_code=404, detail="Icon not found")
            return FileResponse(char.icon_file)

        @self.app.post("/api/session/new")
        async def new_session(data: dict):
            """创建新会话（内存态）

            角色扮演模式：网页端不创建任何会话文件夹/文件，
            只绑定电脑客户端已创建的游戏会话（含 对话历史.txt），读取并原地写入。
            """
            self._session_counter += 1
            session_id = f"session_{self._session_counter}_{int(time.time())}"
            mode = data.get("mode", "chat")  # chat | roleplay
            character_name = data.get("character")
            session_name = data.get("session_name", "")

            character = None
            character_attrs = ""
            game_data = None
            session_path = ""
            if mode == "roleplay" and character_name:
                char_manager = self._get_char_manager()
                if not char_manager:
                    raise HTTPException(status_code=400, detail="角色管理器不可用")
                character = char_manager.get_character(character_name)
                if not character:
                    raise HTTPException(status_code=400, detail=f"角色不存在：{character_name}")
                # 只能使用客户端已创建的游戏会话（对话历史.txt）
                session_path = self._find_game_session(character, session_name)
                if not session_path:
                    raise HTTPException(
                        status_code=400,
                        detail="该角色还没有游戏会话，请先在电脑客户端创建游戏会话（游戏世界）",
                    )
                template = character.get_template()
                player_tpl = character.get_player_template()
                background = character.get_game_background(session_path)
                if not (template.strip() and player_tpl.strip() and background.strip()):
                    raise HTTPException(
                        status_code=400,
                        detail="该游戏会话缺少 角色基础模板/玩家模板/游戏背景，请先在电脑客户端完善",
                    )
                character_attrs = template
                game_data = {
                    "template": template,
                    "player_template": player_tpl,
                    "background": background,
                    "attrs": character.get_game_attrs(session_path),
                }

            self.sessions[session_id] = {
                "id": session_id,
                "mode": mode,
                "character": character_name,
                "character_attrs": character_attrs,
                "game_data": game_data,
                "session_path": session_path,
                "messages": [],
                "created_at": time.time()
            }
            # 游戏会话：载入已有 对话历史.txt（新格式），与电脑客户端打开会话的行为一致
            if session_path and character:
                try:
                    self.sessions[session_id]["messages"] = character.get_session_history(session_path)
                except Exception:
                    pass
            return JSONResponse({
                "session_id": session_id,
                "is_game": bool(game_data),
                "messages": self.sessions[session_id]["messages"],
            })

        @self.app.post("/api/session/delete")
        async def delete_session(data: dict):
            """删除会话"""
            session_id = data.get("session_id")
            if session_id in self.sessions:
                del self.sessions[session_id]
            return JSONResponse({"ok": True})

        @self.app.get("/api/character/sessions")
        async def character_sessions(character: str):
            """获取角色的会话列表"""
            char_manager = self._get_char_manager()
            if not char_manager:
                return JSONResponse({"sessions": []})
            char = char_manager.get_character(character)
            if not char:
                return JSONResponse({"sessions": []})
            sessions = char.get_sessions()
            return JSONResponse({"sessions": sessions})

        @self.app.get("/api/session/history")
        async def session_history(session_id: str = None, character: str = None, session_name: str = None):
            """获取会话历史"""
            # 优先从内存会话获取
            if session_id and session_id in self.sessions:
                return JSONResponse({"messages": self.sessions[session_id]["messages"]})

            # 从文件读取
            if character and session_name:
                char_manager = self._get_char_manager()
                if char_manager:
                    char = char_manager.get_character(character)
                    if char:
                        session_path = os.path.join(char.sessions_dir, session_name)
                        history = char.get_session_history(session_path)
                        # 同时更新内存
                        if session_id and session_id in self.sessions:
                            self.sessions[session_id]["messages"] = history
                        return JSONResponse({"messages": history})

            return JSONResponse({"messages": []})

        @self.app.get("/api/settings/memory_rounds")
        async def get_memory_rounds():
            """获取记忆轮数设置"""
            try:
                if self.config:
                    rounds = self.config.get("chat.memory_rounds", 10)
                else:
                    from core.config import get_config_manager
                    cfg = get_config_manager()
                    rounds = cfg.get("chat.memory_rounds", 10)
                return JSONResponse({"memory_rounds": int(rounds)})
            except Exception:
                return JSONResponse({"memory_rounds": 10})

        @self.app.post("/api/settings/memory_rounds")
        async def set_memory_rounds(data: dict):
            """设置记忆轮数"""
            try:
                rounds = int(data.get("rounds", 10))
                rounds = max(1, min(100, rounds))
                from core.config import get_config_manager
                cfg = get_config_manager()
                cfg.set("chat.memory_rounds", rounds)
                return JSONResponse({"ok": True, "memory_rounds": rounds})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        @self.app.websocket("/ws/chat")
        async def websocket_chat(websocket: WebSocket):
            """WebSocket 流式聊天"""
            await websocket.accept()
            try:
                while True:
                    data = await websocket.receive_json()
                    session_id = data.get("session_id")
                    message = data.get("message", "")
                    mode = data.get("mode", "chat")
                    character = data.get("character")

                    if not message:
                        continue

                    # 获取或创建会话
                    session = self.sessions.get(session_id)
                    if not session:
                        self._session_counter += 1
                        session_id = f"session_{self._session_counter}_{int(time.time())}"
                        session = {
                            "id": session_id,
                            "mode": mode,
                            "character": character,
                            "character_attrs": "",
                            "game_data": None,   # 游戏式角色扮演数据（模板/玩家模板/游戏背景）
                            "session_path": "",  # 绑定的客户端游戏会话文件夹
                            "messages": [],
                            "created_at": time.time()
                        }
                        if mode == "roleplay" and character:
                            char_manager = self._get_char_manager()
                            char_obj = char_manager.get_character(character) if char_manager else None
                            if not char_obj:
                                await websocket.send_json({
                                    "type": "error",
                                    "message": f"角色不存在：{character}"
                                })
                                continue
                            # 只能使用客户端已创建的游戏会话（对话历史.txt），不新建任何文件夹
                            spath = self._find_game_session(char_obj)
                            if not spath:
                                await websocket.send_json({
                                    "type": "error",
                                    "message": "该角色还没有游戏会话，请先在电脑客户端创建游戏会话（游戏世界）"
                                })
                                continue
                            template = char_obj.get_template()
                            player_tpl = char_obj.get_player_template()
                            background = char_obj.get_game_background(spath)
                            if not (template.strip() and player_tpl.strip() and background.strip()):
                                await websocket.send_json({
                                    "type": "error",
                                    "message": "该游戏会话缺少 角色基础模板/玩家模板/游戏背景，请先在电脑客户端完善"
                                })
                                continue
                            session["character_attrs"] = template
                            session["session_path"] = spath
                            session["game_data"] = {
                                "template": template,
                                "player_template": player_tpl,
                                "background": background,
                                "attrs": char_obj.get_game_attrs(spath),
                            }
                            # 载入已有 对话历史.txt（新格式），与电脑客户端打开会话的行为一致
                            try:
                                session["messages"] = char_obj.get_session_history(spath)
                            except Exception:
                                pass
                        self.sessions[session_id] = session

                    # 构建消息
                    msgs = []
                    is_game = bool(mode == "roleplay" and session.get("game_data"))

                    if is_game:
                        # 游戏式角色扮演：角色定义+玩家定义+游戏背景+前面N次AI输出+玩家输入
                        # 历史轮数统一读 chat.memory_rounds（玩家在设置里的"对话记忆轮数"）
                        # 实际发送多少轮还会被 build_game_round_prompt 的 token 预算保护进一步截断
                        from core.character_manager import build_game_round_prompt
                        gd = session["game_data"]
                        try:
                            rounds_n = int(_cfg_web().get("chat.memory_rounds", 1))
                            if not rounds_n:
                                rounds_n = int(_cfg_web().get("roleplay.memory_rounds", 1))
                        except Exception:
                            rounds_n = 1
                        rounds_n = max(0, min(50, rounds_n))
                        ai_outputs = [m["content"] for m in session["messages"] if m.get("role") == "assistant"]
                        prev_outputs = ai_outputs[-rounds_n:] if rounds_n > 0 else []
                        # 与本地客户端一致：max_tokens 按模型上下文分级，prompt 设总预算
                        _game_mt, _game_budget = self._game_ctx_and_budget()
                        msgs = build_game_round_prompt(
                            char_name=character,
                            template=gd["template"],
                            player_template=gd["player_template"],
                            background=gd["background"],
                            prev_ai_outputs=prev_outputs,
                            current_attrs=gd.get("attrs", ""),
                            user_input=message,
                            total_token_budget=_game_budget,
                        )
                    else:
                        if mode == "roleplay" and session["character_attrs"]:
                            # 旧式角色扮演
                            ctx = (
                                f"【角色扮演】\n"
                                f"你是{character}。\n"
                                f"设定：{session['character_attrs']}\n\n"
                                f"规则：始终以{character}的身份和口吻回复。"
                                f"如果角色状态变化，回复末尾用[属性更新]...[/属性更新]记录变化。"
                            )
                            msgs.append({"role": "user", "content": ctx})
                            msgs.append({"role": "assistant", "content": f"好的，我是{character}。"})

                        # 获取记忆轮数
                        try:
                            memory_rounds = int(_cfg_web().get("chat.memory_rounds", 10))
                            memory_rounds = max(1, min(100, memory_rounds))
                        except Exception:
                            memory_rounds = 10

                        # 添加历史消息（按配置的记忆轮数）
                        history = session["messages"][-memory_rounds:] if len(session["messages"]) > memory_rounds else session["messages"]
                        msgs.extend(history)
                        msgs.append({"role": "user", "content": message})

                    # 保存用户消息
                    session["messages"].append({"role": "user", "content": message})

                    # 发送 session_id 给前端
                    await websocket.send_json({
                        "type": "session_id",
                        "session_id": session_id
                    })

                    # 流式调用 LLM
                    # 关键：chat_stream 是阻塞式 HTTP 流，绝不能直接在 async 事件循环里迭代，
                    # 否则会卡死 uvicorn 事件循环 → WebSocket 心跳超时 → 手机端迟迟收不到任何
                    # 内容甚至断连。改为：生产者线程读取流 → 队列 → 事件循环异步消费。
                    llm = LLMClient()
                    llm.base_url = self.llm_base_url

                    _q: queue.Queue = queue.Queue()

                    def _produce():
                        try:
                            # 游戏式输出很长，max_tokens 按模型上下文分级（与本地客户端一致）
                            _mt = _game_mt if is_game else 4096
                            for _chunk in llm.chat_stream(msgs, max_tokens=_mt):
                                _q.put(("chunk", _chunk))
                            _q.put(("end", None))
                        except Exception as _e:
                            _q.put(("error", _e))

                    threading.Thread(target=_produce, daemon=True).start()
                    _loop = asyncio.get_running_loop()

                    full_response = ""
                    think_filter = ThinkStreamFilter()
                    stream_error = None
                    try:
                        while True:
                            kind, payload = await _loop.run_in_executor(None, _q.get)
                            if kind == "end":
                                break
                            if kind == "error":
                                stream_error = payload
                                break
                            full_response += payload
                            visible = think_filter.feed(payload)
                            if visible:
                                await websocket.send_json({
                                    "type": "chunk",
                                    "content": visible
                                })
                        # 流结束：取回过滤器中扣住的残余（如结尾恰好是标签前缀）
                        rest = think_filter.flush()
                        if rest:
                            await websocket.send_json({
                                "type": "chunk",
                                "content": rest
                            })

                        if stream_error is not None:
                            raise stream_error

                        # 入史前深度清洗（剥离思考块/幻觉续写/特殊 token）
                        cleaned, _cut = sanitize_history_text(full_response)

                        # 属性更新（用清洗后的文本，避免匹配思考内容）
                        if is_game:
                            # 游戏式：提取 '角色属性:11 22 33' 纯数字 → 更新会话最新属性
                            from core.character_manager import extract_attr_numbers
                            nums = extract_attr_numbers(cleaned)
                            if nums:
                                session["game_data"]["attrs"] = nums
                                await websocket.send_json({
                                    "type": "attr_update",
                                    "attrs": nums
                                })
                        elif mode == "roleplay" and "[属性更新]" in cleaned and "[/属性更新]" in cleaned:
                            import re
                            match = re.search(r'\[属性更新\](.*?)\[/属性更新\]', cleaned, re.DOTALL)
                            if match:
                                new_attrs = match.group(1).strip()
                                if session["character_attrs"]:
                                    session["character_attrs"] += "\n\n" + new_attrs
                                else:
                                    session["character_attrs"] = new_attrs
                                await websocket.send_json({
                                    "type": "attr_update",
                                    "attrs": session["character_attrs"]
                                })

                        # 保存 AI 回复（清洗后的文本）
                        session["messages"].append({"role": "assistant", "content": cleaned})

                        # 角色扮演模式：把历史写回绑定的客户端游戏会话文件夹
                        # （绝不新建会话文件夹；save_session_history 对游戏会话
                        #   会以与本地客户端完全一致的 第N轮:>玩家输入=.../ >AI=输出... 格式整写 对话历史.txt）
                        if mode == "roleplay" and character and session.get("session_path"):
                            try:
                                char_manager = self._get_char_manager()
                                if char_manager:
                                    char_obj = char_manager.get_character(character)
                                    if char_obj:
                                        char_obj.save_session_history(
                                            session["session_path"], session["messages"]
                                        )
                                        # 游戏式：保存最新角色属性（→ 角色属性.txt，与本地一致）
                                        if is_game and session.get("game_data", {}).get("attrs"):
                                            char_obj.update_session_attrs(
                                                session["session_path"],
                                                session["game_data"]["attrs"]
                                            )
                            except Exception:
                                pass

                        # Token 用量：输入 = 发给 AI 的全部信息（角色设定+属性+历史+玩家输入），
                        # 输出 = AI 回复。优先用服务端精确 usage，缺失时本地估算
                        try:
                            usage = getattr(llm, "last_usage", None) or {}
                            input_tokens = usage.get("prompt_tokens") or 0
                            output_tokens = usage.get("completion_tokens") or 0
                            if not input_tokens:
                                input_tokens = sum(
                                    estimate_tokens(m.get("content", "")) for m in msgs
                                )
                            if not output_tokens:
                                output_tokens = estimate_tokens(cleaned)
                            await websocket.send_json({
                                "type": "usage",
                                "input_tokens": int(input_tokens),
                                "output_tokens": int(output_tokens),
                            })
                        except Exception:
                            pass

                        await websocket.send_json({
                            "type": "done"
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "error",
                            "message": str(e)
                        })

            except WebSocketDisconnect:
                pass
            except Exception as e:
                print(f"WebSocket error: {e}")

    def _get_char_manager(self) -> Optional[CharacterManager]:
        """获取角色管理器"""
        if self.charter_dir and os.path.exists(self.charter_dir):
            return CharacterManager(self.charter_dir)
        return None

    @staticmethod
    def _find_game_session(char, session_name: str = "") -> str:
        """查找角色已有的游戏会话文件夹（含 对话历史.txt 的会话）

        网页端不创建会话，只复用电脑客户端创建的游戏会话：
        - 指定 session_name 且该会话是游戏会话 → 用它
        - 否则取最新的游戏会话（get_sessions 已按创建时间倒序）
        找不到返回 ""
        """
        try:
            if session_name:
                path = os.path.join(char.sessions_dir, session_name)
                if char.is_game_session(path):
                    return path
            for s in char.get_sessions():
                if s.get("is_game"):
                    return s["path"]
        except Exception:
            pass
        return ""

    def _game_ctx_and_budget(self) -> tuple:
        """游戏模式的 max_tokens 与 prompt 总预算（与本地客户端同一策略）：
        llama-server 的 ctx 是 prompt+output 共享，需给 prompt 留出空间"""
        ctx_size = 8192
        try:
            cur = _cfg_web().get_current_model() or {}
            ctx_size = max(2048, int(cur.get("ctx_size") or 8192))
        except Exception:
            pass
        if ctx_size >= 32768:
            max_tokens = 6144
        elif ctx_size >= 16384:
            max_tokens = 4096
        else:
            max_tokens = 2048
        total_budget = max(1024, ctx_size - max_tokens - 384)
        return max_tokens, total_budget

    def _get_system_stats(self) -> dict:
        """获取系统状态"""
        if self.system_monitor:
            stats = self.system_monitor.last_stats
            return {
                "cpu": stats.get("cpu", 0),
                "memory": stats.get("memory", 0),
                "memory_total_gb": stats.get("memory_total_gb", 0),
                "memory_used_gb": stats.get("memory_used_gb", 0),
                "gpu": stats.get("gpu", 0),
                "gpu_memory": stats.get("gpu_memory", 0),
                "gpu_memory_total_gb": stats.get("gpu_memory_total_gb", 0),
                "gpu_memory_used_gb": stats.get("gpu_memory_used_gb", 0),
                "has_gpu": self.system_monitor.has_gpu,
            }
        # 没有监控器时，用 psutil 临时获取
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            return {
                "cpu": cpu,
                "memory": mem.percent,
                "memory_total_gb": round(mem.total / (1024**3), 1),
                "memory_used_gb": round(mem.used / (1024**3), 1),
                "gpu": 0,
                "gpu_memory": 0,
                "gpu_memory_total_gb": 0,
                "gpu_memory_used_gb": 0,
                "has_gpu": False,
            }
        except Exception:
            return {
                "cpu": 0, "memory": 0, "memory_total_gb": 0, "memory_used_gb": 0,
                "gpu": 0, "gpu_memory": 0, "gpu_memory_total_gb": 0, "gpu_memory_used_gb": 0,
                "has_gpu": False,
            }

    def _get_model_status(self) -> dict:
        """获取模型状态"""
        if not self.server_manager:
            return {
                "status": "unknown",
                "status_text": "不可用",
                "port": 0,
                "model_name": "",
            }
        status = self.server_manager.status
        status_map = {
            "stopped": "已停止",
            "starting": "启动中",
            "running": "运行中",
            "stopping": "停止中",
            "error": "错误",
        }
        return {
            "status": status,
            "status_text": status_map.get(status, status),
            "port": getattr(self.server_manager, "port", 8080),
            "model_name": getattr(self.server_manager, "model_name", ""),
        }

    def get_local_ip(self) -> str:
        """获取本机局域网 IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def get_url(self) -> str:
        """获取访问 URL"""
        ip = self.get_local_ip()
        return f"http://{ip}:{self.port}"

    def generate_qr_code(self, save_path: str = None) -> Optional[str]:
        """生成二维码图片"""
        if not QRCODE_AVAILABLE:
            return None

        url = self.get_url()
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        if save_path:
            img.save(save_path)
            return save_path

        # 保存到临时位置
        tmp_path = os.path.join(os.path.dirname(__file__), "static", "qr_temp.png")
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        img.save(tmp_path)
        return tmp_path

    def start(self, port: int = None):
        """启动 Web 服务器"""
        if self.is_running:
            return

        if port:
            self.port = port

        if not FASTAPI_AVAILABLE:
            raise Exception("FastAPI 未安装，请先安装 fastapi 和 uvicorn")

        self.is_running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        time.sleep(1)  # 等待服务启动

    def _run_server(self):
        """运行服务器（在线程中）"""
        try:
            config = uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="warning"
            )
            server = uvicorn.Server(config)
            server.run()
        except Exception as e:
            print(f"Web server error: {e}")
        finally:
            self.is_running = False

    def stop(self):
        """停止 Web 服务器"""
        self.is_running = False
        # uvicorn 没有简单的停止方法，这里只是标记
        # 实际应用退出时线程会自动结束

    def start_ngrok_tunnel(self, auth_token: str = None) -> str:
        """启动 ngrok 隧道，返回公网 URL"""
        try:
            from pyngrok import ngrok
        except ImportError:
            raise Exception("pyngrok 未安装，请先安装: pip install pyngrok")

        if auth_token:
            ngrok.set_auth_token(auth_token)

        # 关闭已有的隧道
        if self.ngrok_tunnel:
            try:
                ngrok.disconnect(self.ngrok_tunnel.public_url)
            except Exception:
                pass
            self.ngrok_tunnel = None

        # 启动新隧道
        self.ngrok_tunnel = ngrok.connect(self.port, "http")
        public_url = self.ngrok_tunnel.public_url

        # 确保是 https
        if public_url.startswith("http://"):
            public_url = "https://" + public_url[7:]

        return public_url

    def stop_ngrok_tunnel(self):
        """停止 ngrok 隧道"""
        if self.ngrok_tunnel:
            try:
                from pyngrok import ngrok
                ngrok.disconnect(self.ngrok_tunnel.public_url)
            except Exception:
                pass
            self.ngrok_tunnel = None

    def get_ngrok_url(self) -> Optional[str]:
        """获取 ngrok 公网 URL"""
        if self.ngrok_tunnel:
            url = self.ngrok_tunnel.public_url
            if url.startswith("http://"):
                url = "https://" + url[7:]
            return url
        return None

    def generate_ngrok_qr_code(self, save_path: str = None) -> Optional[str]:
        """生成 ngrok 公网地址二维码"""
        url = self.get_ngrok_url()
        if not url:
            return None

        if not QRCODE_AVAILABLE:
            return None

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        if save_path:
            img.save(save_path)
            return save_path

        tmp_path = os.path.join(os.path.dirname(__file__), "static", "qr_ngrok_temp.png")
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        img.save(tmp_path)
        return tmp_path

    def check_dependencies(self) -> Dict[str, bool]:
        """检查依赖是否安装"""
        try:
            import pyngrok
            pyngrok_ok = True
        except ImportError:
            pyngrok_ok = False

        return {
            "fastapi": FASTAPI_AVAILABLE,
            "qrcode": QRCODE_AVAILABLE,
            "pyngrok": pyngrok_ok,
        }
