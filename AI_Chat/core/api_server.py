"""
对外 AI 服务 - 把本程序正在使用的本地模型（llama-server）以
OpenAI Chat Completions 兼容接口提供给外部程序使用。

外部程序（如 TRAE 的「自定义模型」）只需填：
  - 自定义请求地址:  http://<本机IP>:<端口>/v1
  - 模型 ID:         本程序当前加载的模型（由 /v1/models 提供）
  - API 密钥:        本对话框生成的密钥（可关闭校验）

端点：
  GET  /v1/models              → OpenAI 模型列表
  POST /v1/chat/completions    → 对话补全（支持流式 SSE 透传）
"""
import hmac
import json
import socket
import threading
import time
from typing import Optional

import requests

try:
    from fastapi import FastAPI, Request, Body
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


def get_local_ip() -> str:
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _openai_error(message: str, code: str = "invalid_request_error", status: int = 400):
    """构造 OpenAI 风格的错误响应"""
    return JSONResponse(
        {"error": {"message": message, "type": code, "code": code}},
        status_code=status,
    )


class AIApiServer:
    """OpenAI 兼容对外服务（单例，通过 get_api_server 获取）"""

    def __init__(self):
        self.port = 8900
        self.api_key = ""          # 为空表示不校验
        self.require_key = True
        self.llm_base_url = "http://127.0.0.1:8080"  # 本地 llama-server
        self.is_running = False
        self._app = None
        self._server = None        # uvicorn.Server
        self._thread = None
        self._last_error = ""
        if FASTAPI_AVAILABLE:
            self._init_app()

    # ---------------- FastAPI 应用 ----------------

    def _init_app(self):
        self._app = FastAPI(title="AI Chat OpenAI-Compatible API", docs_url=None, redoc_url=None)
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @self._app.get("/")
        def root():
            return JSONResponse({
                "service": "AI Chat Video - OpenAI Compatible API",
                "endpoints": ["/v1/models", "/v1/chat/completions"],
                "status": "running" if self.is_running else "stopped",
            })

        @self._app.get("/v1/models")
        def list_models(request: Request):
            err = self._check_auth(request)
            if err is not None:
                return err
            data = []
            # 优先取 llama-server 已加载的模型 ID
            try:
                r = requests.get(f"{self.llm_base_url.rstrip('/')}/v1/models", timeout=3)
                if r.status_code == 200:
                    for m in r.json().get("data", []):
                        data.append({
                            "id": m.get("id", "local-model"),
                            "object": "model",
                            "owned_by": "ai-chat-video",
                            "permission": [],
                        })
            except Exception:
                pass
            if not data:
                # 兜底：用配置里的当前模型名
                try:
                    from core.config import get_config_manager
                    cfg = get_config_manager()
                    cur = cfg.get_current_model() or {}
                    name = cur.get("name") or cur.get("id") or "local-model"
                except Exception:
                    name = "local-model"
                data.append({
                    "id": name,
                    "object": "model",
                    "owned_by": "ai-chat-video",
                    "permission": [],
                })
            return JSONResponse({"object": "list", "data": data})

        @self._app.post("/v1/chat/completions")
        def chat_completions(request: Request, payload: dict = Body(...)):
            err = self._check_auth(request)
            if err is not None:
                return err
            body = payload
            messages = body.get("messages")
            if not messages or not isinstance(messages, list):
                return _openai_error("缺少 messages 参数")

            upstream = f"{self.llm_base_url.rstrip('/')}/v1/chat/completions"
            stream = bool(body.get("stream", False))
            try:
                r = requests.post(
                    upstream,
                    json=body,
                    stream=stream,
                    timeout=(10, 600),
                )
            except Exception as e:
                return _openai_error(
                    f"无法连接本地模型服务 {self.llm_base_url}：{e}。请先在本程序中启动模型。",
                    code="upstream_unavailable", status=502,
                )

            if r.status_code != 200:
                try:
                    detail = r.json().get("error", {}).get("message", r.text[:200])
                except Exception:
                    detail = r.text[:200]
                return _openai_error(f"本地模型返回 {r.status_code}: {detail}",
                                     code="upstream_error", status=502)

            if stream:
                # 流式：把 llama-server 的 SSE 字节流原样透传（已是 OpenAI 格式）
                def gen():
                    try:
                        for chunk in r.iter_content(chunk_size=None):
                            if chunk:
                                yield chunk
                    finally:
                        r.close()
                return StreamingResponse(
                    gen(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                )
            # 非流式：llama-server 的响应本身就是 OpenAI 格式，原样返回
            try:
                return JSONResponse(json.loads(r.content))
            except Exception:
                return _openai_error(
                    f"本地模型返回了非 JSON 响应：{r.text[:200]}",
                    code="upstream_error", status=502,
                )

    def _check_auth(self, request: Request) -> Optional["JSONResponse"]:
        """校验 Bearer 密钥；未启用或未设置密钥时放行"""
        if not self.require_key or not self.api_key:
            return None
        auth = request.headers.get("authorization", "")
        expect = f"Bearer {self.api_key}"
        if not auth or not hmac.compare_digest(auth, expect):
            return _openai_error("无效的 API 密钥", code="invalid_api_key", status=401)
        return None

    # ---------------- 生命周期 ----------------

    def start(self, port: int, api_key: str, require_key: bool,
              llm_base_url: str) -> tuple:
        """启动服务。返回 (ok, 错误信息)"""
        if not FASTAPI_AVAILABLE:
            return False, "FastAPI/uvicorn 未安装：pip install fastapi uvicorn"
        if self.is_running:
            if port == self.port:
                # 仅更新鉴权/上游参数（请求时即时读取），无需重启
                self.api_key = (api_key or "").strip()
                self.require_key = bool(require_key)
                self.llm_base_url = llm_base_url.rstrip("/")
                return True, ""
            self.stop()

        self.port = int(port)
        self.api_key = (api_key or "").strip()
        self.require_key = bool(require_key)
        self.llm_base_url = llm_base_url.rstrip("/")
        self._last_error = ""

        config = uvicorn.Config(self._app, host="0.0.0.0", port=self.port,
                                log_level="warning")
        server = uvicorn.Server(config)
        self._server = server
        self._thread = threading.Thread(target=server.run, daemon=True,
                                        name="AIApiServer")
        self._thread.start()

        # 等待启动完成（或失败）
        for _ in range(50):
            if server.started:
                self.is_running = True
                return True, ""
            if not self._thread.is_alive() or getattr(server, "exit_code", None) not in (None,):
                break
            time.sleep(0.1)
        if server.started:
            self.is_running = True
            return True, ""
        self.is_running = False
        return False, f"启动失败（端口 {self.port} 可能被占用）"

    def stop(self):
        """停止服务"""
        if self._server is not None:
            try:
                self._server.should_exit = True
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._server = None
        self._thread = None
        self.is_running = False

    def get_base_url(self, lan: bool = True) -> str:
        """对外展示的服务地址（/v1 结尾，外部程序会在末尾补 /chat/completions）"""
        ip = get_local_ip() if lan else "127.0.0.1"
        return f"http://{ip}:{self.port}/v1"


# ---------------- 单例 ----------------

_api_server: Optional[AIApiServer] = None
_api_server_lock = threading.Lock()


def get_api_server() -> AIApiServer:
    global _api_server
    with _api_server_lock:
        if _api_server is None:
            _api_server = AIApiServer()
        return _api_server
