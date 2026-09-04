"""
ComfyUI 模型文件管理 - 检测、复制、验证模型文件
"""
import os
import shutil
from typing import List, Dict, Tuple, Callable


# 需要检查的模型文件列表
# (源文件名, 目标子文件夹, 显示名称)
REQUIRED_MODELS = [
    (
        "gemma-3-12b-it-ablit-norms-biproj-fp8mixed.safetensors",
        "text_encoders",
        "文本编码器 (Gemma 3 12B)"
    ),
    (
        "10Eros_v1.4_DMD_int8_convrot.safetensors",
        "checkpoints",
        "扩散主模型 (10Eros v1.4 INT8)"
    ),
    (
        "ltx-2.3-22b-distilled-lora-384.safetensors",
        "loras",
        "LoRA 模型 (LTX 2.3 Distilled)"
    ),
    (
        "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
        "latent_upscale_models",
        "潜空间超分模型 (Spatial Upscaler x2)"
    ),
]


def get_app_root() -> str:
    """获取程序根目录（codemate-desktop 的上一级）"""
    import os
    core_dir = os.path.dirname(os.path.abspath(__file__))
    desktop_dir = os.path.dirname(core_dir)
    return os.path.dirname(desktop_dir)


def get_source_folder(model_source: str = "Sulphur 2") -> str:
    """获取模型源文件夹路径"""
    return os.path.join(get_app_root(), "models", model_source)


def check_models(download_folder: str, model_source: str = "Sulphur 2") -> List[Dict]:
    """
    检查下载文件夹中的模型文件状态

    返回列表，每项包含：
    - name: 显示名称
    - filename: 文件名
    - target_folder: 目标子文件夹
    - target_path: 完整目标路径
    - exists: 是否已存在
    - source_path: 源文件路径
    - source_exists: 源文件是否存在
    """
    results = []
    source_folder = get_source_folder(model_source)

    for filename, subfolder, display_name in REQUIRED_MODELS:
        target_path = os.path.join(download_folder, subfolder, filename)
        source_path = os.path.join(source_folder, filename)
        results.append({
            "name": display_name,
            "filename": filename,
            "target_folder": subfolder,
            "target_path": target_path,
            "exists": os.path.exists(target_path),
            "source_path": source_path,
            "source_exists": os.path.exists(source_path),
        })

    return results


def copy_models(
    download_folder: str,
    model_source: str = "Sulphur 2",
    progress_callback: Callable[[str, int, int], None] = None,
) -> Tuple[bool, str, List[Dict]]:
    """
    复制缺失的模型文件到下载文件夹

    Args:
        download_folder: ComfyUI 下载文件夹（实例目录）
        model_source: 模型源文件夹名
        progress_callback: 进度回调 (当前文件名, 当前索引, 总数)

    Returns:
        (是否成功, 消息, 检查结果列表)
    """
    if not download_folder or not os.path.isdir(download_folder):
        return False, f"下载文件夹不存在: {download_folder}", []

    source_folder = get_source_folder(model_source)
    if not os.path.isdir(source_folder):
        return False, f"模型源文件夹不存在: {source_folder}", []

    models = check_models(download_folder, model_source)
    missing = [m for m in models if not m["exists"]]

    if not missing:
        return True, "所有模型文件已就绪", models

    total = len(missing)
    for idx, model in enumerate(missing):
        if not model["source_exists"]:
            return False, f"源文件缺失: {model['filename']}", models

        # 确保目标目录存在
        target_dir = os.path.join(download_folder, model["target_folder"])
        os.makedirs(target_dir, exist_ok=True)

        # 进度回调
        if progress_callback:
            progress_callback(model["name"], idx, total)

        # 复制文件
        try:
            shutil.copy2(model["source_path"], model["target_path"])
        except Exception as e:
            return False, f"复制 {model['name']} 失败: {str(e)}", models

    # 重新检查
    models = check_models(download_folder, model_source)
    all_ok = all(m["exists"] for m in models)

    if all_ok:
        return True, f"已复制 {len(missing)} 个模型文件", models
    else:
        return False, "部分文件复制失败", models


def verify_comfyui_exe(exe_path: str) -> Tuple[bool, str]:
    """
    验证 ComfyUI 可执行文件是否有效

    Returns:
        (是否有效, 描述)
    """
    if not exe_path:
        return False, "未指定 ComfyUI 路径"

    if not os.path.exists(exe_path):
        return False, "文件不存在"

    if not os.path.isfile(exe_path):
        return False, "不是文件"

    ext = os.path.splitext(exe_path)[1].lower()
    if ext not in ('.exe', '.bat', '.cmd', '.ps1'):
        # 也可能是 python 脚本启动
        basename = os.path.basename(exe_path).lower()
        if 'comfy' not in basename and 'main' not in basename:
            return False, "可能不是 ComfyUI 启动文件"

    return True, "ComfyUI 路径有效"


def verify_download_folder(folder: str) -> Tuple[bool, str]:
    """
    验证下载文件夹是否是有效的 ComfyUI 实例目录

    检查标准：目录存在，且名称中包含"下载"或"download"，
    或者里面有 text_encoders / checkpoints 等子目录
    """
    if not folder:
        return False, "未指定下载文件夹"

    if not os.path.exists(folder):
        return False, "文件夹不存在"

    if not os.path.isdir(folder):
        return False, "不是文件夹"

    # 检查是否有模型子目录
    subdirs = {'text_encoders', 'checkpoints', 'loras', 'vae', 'embeddings'}
    existing = set()
    try:
        for name in os.listdir(folder):
            if os.path.isdir(os.path.join(folder, name)):
                existing.add(name.lower())
    except Exception:
        pass

    has_model_dirs = bool(subdirs & existing)

    if has_model_dirs:
        return True, "文件夹包含模型目录，看起来是正确的"
    else:
        # 即使没有模型目录，也可能是新的实例文件夹
        return True, "文件夹存在（暂无模型目录）"
