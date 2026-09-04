"""
ComfyUI API 客户端 - 用于视频生成
"""
import json
import time
import requests
from typing import Dict, List, Optional, Callable


class ComfyUIClient:
    """ComfyUI API 客户端"""

    def __init__(self, server_address: str = "127.0.0.1:8188"):
        self.server_address = server_address
        self.client_id = "codemate_video_client"
        self._session = requests.Session()

    def _url(self, path: str) -> str:
        return f"http://{self.server_address}{path}"

    def check_connection(self) -> bool:
        """检查 ComfyUI 是否可连接"""
        try:
            resp = self._session.get(self._url("/system_stats"), timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def get_system_stats(self) -> dict:
        """获取系统状态"""
        try:
            resp = self._session.get(self._url("/system_stats"), timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def get_queue(self) -> dict:
        """获取队列状态"""
        try:
            resp = self._session.get(self._url("/queue"), timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {"queue_running": [], "queue_pending": []}

    def upload_image(self, filepath: str) -> dict:
        """
        上传图片到 ComfyUI 的 input 目录，返回 {"name", "subfolder", "type"}
        供 LoadImage 节点引用
        """
        import os
        import uuid
        if not os.path.isfile(filepath):
            raise RuntimeError(f"图片不存在: {filepath}")

        # 唯一化文件名，避免与 input 目录已有文件冲突
        ext = os.path.splitext(filepath)[1].lower() or ".png"
        upload_name = f"i2v_{uuid.uuid4().hex[:8]}{ext}"

        with open(filepath, "rb") as f:
            files = {"image": (upload_name, f, "application/octet-stream")}
            data = {"overwrite": "true", "type": "input"}
            resp = self._session.post(
                self._url("/upload/image"), files=files, data=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        return {
            "name": result.get("name", upload_name),
            "subfolder": result.get("subfolder", ""),
            "type": result.get("type", "input"),
        }

    def inject_load_image(self, prompt_workflow: dict, image_ref: dict, node_id=None) -> int:
        """
        将上传后的图片引用注入工作流的 LoadImage 节点
        node_id 为 None 时注入所有 LoadImage 节点，否则只注入指定节点
        返回注入的节点数量
        """
        value = image_ref.get("name", "")
        if not value:
            return 0
        count = 0
        for nid, node in prompt_workflow.items():
            if node_id is not None and str(nid) != str(node_id):
                continue
            ctype = str(node.get("class_type", "")).lower()
            if ctype in ("loadimage", "load_image"):
                inputs = node.setdefault("inputs", {})
                inputs["image"] = value
                wv = node.get("_widgets_values")
                if isinstance(wv, list) and wv:
                    wv[0] = value
                count += 1
        return count

    def submit_prompt(self, prompt_workflow: dict) -> str:
        """提交工作流到队列，返回 prompt_id"""
        payload = {
            "prompt": prompt_workflow,
            "client_id": self.client_id,
        }
        resp = self._session.post(self._url("/prompt"), json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("prompt_id", "")

    def get_history(self, prompt_id: str) -> Optional[dict]:
        """获取历史记录（生成结果）"""
        try:
            resp = self._session.get(self._url(f"/history/{prompt_id}"), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get(prompt_id)
        except Exception:
            pass
        return None

    def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> Optional[bytes]:
        """获取生成的图片/视频文件"""
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        try:
            resp = self._session.get(self._url("/view"), params=params, timeout=30)
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
        return None

    def get_progress(self) -> dict:
        """获取当前进度"""
        try:
            resp = self._session.get(self._url("/progress"), timeout=3)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {"value": 0, "max": 0, "progress": 0}

    def interrupt(self) -> bool:
        """中断当前生成"""
        try:
            resp = self._session.post(self._url("/interrupt"), timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def generate_and_wait(
        self,
        prompt_workflow: dict,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        poll_interval: float = 1.0,
    ) -> dict:
        """
        提交生成并等待完成，返回结果信息
        
        Args:
            prompt_workflow: ComfyUI API 格式的工作流字典
            progress_cb: 进度回调 (progress_0to1, status_text)
            poll_interval: 轮询间隔（秒）
            
        Returns:
            {"outputs": {...}, "images": [...], "videos": [...]}
        """
        # 1. 提交任务
        prompt_id = self.submit_prompt(prompt_workflow)
        if not prompt_id:
            raise RuntimeError("提交任务失败")

        if progress_cb:
            progress_cb(0.0, "已提交，等待执行...")

        # 2. 等待完成 + 轮询进度
        last_node = 0
        max_nodes = 0
        
        while True:
            # 检查是否完成
            history = self.get_history(prompt_id)
            if history:
                if progress_cb:
                    progress_cb(1.0, "生成完成")
                return self._extract_outputs(history)

            # 获取进度
            prog = self.get_progress()
            if prog.get("max", 0) > 0:
                current = prog.get("value", 0)
                max_val = prog.get("max", 1)
                pct = min(current / max_val, 0.99)
                
                # 获取队列状态看当前在哪个节点
                queue = self.get_queue()
                running = queue.get("queue_running", [])
                status_text = "生成中..."
                if running:
                    status_text = f"生成中... (步骤 {current}/{max_val})"
                
                if progress_cb:
                    progress_cb(pct, status_text)

            time.sleep(poll_interval)

    def _extract_outputs(self, history: dict) -> dict:
        """从历史记录中提取输出"""
        result = {"outputs": {}, "images": [], "videos": [], "files": []}
        
        outputs = history.get("outputs", {})
        for node_id, node_output in outputs.items():
            result["outputs"][node_id] = node_output
            
            images = node_output.get("images", [])
            for img in images:
                img_info = {
                    "filename": img.get("filename", ""),
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                }
                fname = img_info["filename"].lower()
                if fname.endswith(('.mp4', '.webm', '.avi', '.mov', '.mkv')):
                    result["videos"].append(img_info)
                elif fname.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    result["images"].append(img_info)
                else:
                    result["files"].append(img_info)
        
        return result


def inject_prompt_text(prompt_workflow: dict, node_id, text: str) -> int:
    """
    把提示词注入指定节点（API 格式工作流）。
    兼容三种情况：
    1. 节点本身有字符串输入（PrimitiveStringMultiline 的 value / CLIPTextEncode 的 text）
    2. 节点的 text/prompt/value 输入是链接（如 TextGenerateLTX2Prompt 的 prompt
       指向 PrimitiveStringMultiline）→ 顺着链接找到源头字符串节点注入
    3. 找不到可注入点 → 返回 0，由调用方报错提示
    """
    node = prompt_workflow.get(str(node_id))
    if not node:
        return 0

    def _set_string_value(n) -> bool:
        inputs = n.setdefault("inputs", {})
        for key in ("value", "text", "prompt"):
            if isinstance(inputs.get(key), str):
                inputs[key] = text
                return True
        return False

    # 情况 1：节点自身有字符串输入
    if _set_string_value(node):
        return 1

    # 情况 2：顺着链接找源头（Switch 节点再多跳一层 on_true/on_false）
    def _follow(link) -> int:
        if not isinstance(link, (list, tuple)) or len(link) < 1:
            return 0
        src = prompt_workflow.get(str(link[0]))
        if not src:
            return 0
        if _set_string_value(src):
            return 1
        if "switch" in str(src.get("class_type", "")).lower():
            s_inputs = src.get("inputs", {})
            for s_key in ("on_true", "on_false"):
                if _follow(s_inputs.get(s_key)) == 1:
                    return 1
        return 0

    inputs = node.get("inputs", {})
    for key in ("text", "prompt", "value"):
        if _follow(inputs.get(key)) == 1:
            return 1
    return 0


def inject_video_params(prompt_workflow: dict, width=None, height=None,
                        duration=None, fps=None) -> int:
    """
    把面板视频参数注入 LTX 模板工作流的 PrimitiveInt 参数节点。
    通过 _meta.title 匹配：Duration / Frame Rate / Width / Height。
    返回成功注入的参数个数。步数与 CFG 在此模板中由固定 Sigmas 决定，不注入。
    """
    targets = {}  # title_lower -> value
    if duration is not None:
        targets["duration"] = int(duration)
    if fps is not None:
        for t in ("frame rate", "fps"):
            targets[t] = int(fps)
    if width is not None:
        targets["width"] = int(width)
    if height is not None:
        targets["height"] = int(height)
    if not targets:
        return 0

    count = 0
    for node in prompt_workflow.values():
        if str(node.get("class_type", "")) != "PrimitiveInt":
            continue
        title = str(node.get("_meta", {}).get("title", "")).strip().lower()
        if title in targets:
            node.setdefault("inputs", {})["value"] = targets[title]
            count += 1
    return count


def load_workflow_json(filepath: str) -> dict:
    """加载 ComfyUI 工作流 JSON 文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def convert_ui_to_api(ui_workflow: dict) -> dict:
    """
    将 ComfyUI UI 格式的工作流转换为 API 格式
    UI 格式有 nodes/links 结构，API 格式是 {node_id: {class_type, inputs}}
    
    这是一个简化的转换，对于复杂模板节点可能不完整。
    """
    api_workflow = {}
    
    for node in ui_workflow.get("nodes", []):
        node_id = str(node["id"])
        class_type = node.get("type", "")
        widgets_values = node.get("widgets_values", [])
        
        # 构建 inputs
        inputs = {}
        
        # widget 值作为输入（按顺序映射需要知道节点定义，这里简化处理）
        # 对于简单的文本节点，widgets_values[0] 就是文本
        if widgets_values:
            # 尝试猜测哪些 widget 是输入
            # 对于 CLIPTextEncode 等节点，text 通常是第一个 widget
            pass
        
        # 连接输入
        for inp in node.get("inputs", []):
            in_name = inp.get("name", "")
            link_id = inp.get("link")
            if link_id is not None:
                # 找到对应的输出节点
                for link in ui_workflow.get("links", []):
                    if link[0] == link_id:
                        src_node_id = str(link[1])
                        src_slot = link[2]
                        inputs[in_name] = [src_node_id, src_slot]
                        break
        
        api_node = {
            "class_type": class_type,
            "inputs": inputs,
        }
        
        # 添加 widget 值
        if widgets_values:
            api_node["_widgets_values"] = widgets_values
        
        api_workflow[node_id] = api_node
    
    return api_workflow


def find_text_nodes(api_workflow: dict) -> List[str]:
    """查找工作流中的文本输入节点（可能是提示词）"""
    text_nodes = []
    
    for node_id, node in api_workflow.items():
        class_type = node.get("class_type", "").lower()
        
        # 常见的文本输入节点类型
        text_keywords = [
            "cliptextencode", "textencode", "textinput",
            "prompt", "text", "positive", "negative",
            "clipprompt", "conditioning"
        ]
        
        if any(kw in class_type for kw in text_keywords):
            text_nodes.append(node_id)
        
        # 也检查 widget 值中是否包含文本
        wv = node.get("_widgets_values", [])
        if wv and isinstance(wv[0], str) and len(wv[0]) > 10:
            if node_id not in text_nodes:
                text_nodes.append(node_id)
    
    return text_nodes
