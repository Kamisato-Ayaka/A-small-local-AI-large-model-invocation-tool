# 🎮 AI Chat — A Small Local AI Runner

PyQt5 本地桌面 AI 应用，集成 **AI 对话 / 角色扮演 / 文生视频 / 图生视频 / 语音合成** 五大功能模块，无浏览器依赖，支持动态壁纸桌面美化。

![主界面](docs/screenshots/main%E7%95%8C%E9%9D%A2.png)

## ✨ 功能特性

| 模块              | 说明                                                 |
| --------------- | -------------------------------------------------- |
| 💬 **AI 对话**    | 本地 LLM（llama-server）流式对话，支持思考过程可视化                 |
| 🎭 **角色扮演对话**   | 角色卡模板 + 世界书 + 游戏式 prompt 组装                        |
| 🎬 **文生视频**     | ComfyUI + LTX-Video + Sulphur 2                    |
| 🖼 **图生视频**     | 同上，额外上传首帧并注入 LoadImage 节点                          |
| 🎤 **语音系统**     | CosyVoice（中文零样本克隆）/ GPT-SoVITS-v2pro（多语种 v2Pro 克隆） |
| 🖼 **壁纸与外观**    | Wallpaper Engine pkg 导入 + 互动透视壁纸 + 文字透明度补偿         |
| 📱 **手机 Web 版** | FastAPI + WebSocket，支持 ngrok 隧道 + 二维码扫码            |

## 🚀 快速开始

### 1. 安装依赖 & 启动（推荐）

```bash
python install_and_launch.py
```

点击「📦 安装依赖」→ 点击「🚀 启动 AI Chat」

### 2. 手动启动

```bash
pip install -r AI_Chat/requirements.txt
cd AI_Chat
python app.py
```

### 3. 首次启动后配置

1. 打开 **🎤 语音系统** → 选择引擎（GPT-SoVITS-v2pro / CosyVoice）→ 配置权重路径 → 启动服务
2. 打开 **💬 对话** → 顶栏选择本地 LLM 模型 → 🎤 启动语音服务 → 开始对话

***

## 📁 完整文件结构

```
AI_Chat/                              ← 项目根目录（仓库根）
│
├── .gitignore
├── README.md                         ← 你正在读的文件
├── install_and_launch.py             ← ⭐ 一键安装依赖 + 启动
├── requirements.txt                   ← Python 依赖列表
├── start.bat                         ← Windows 启动脚本
│
├── docs/                             ← 文档和截图
│   └── screenshots/
│       └── main界面.png              ← 程序运行截图
│
├── AI_Chat/                          ← ⭐ 源代码（全部 Python）
│   ├── app.py                        ← 入口（全局异常钩子 + QApplication）
│   ├── launcher.py                   ← 依赖检查 + llama-server 定位
│   ├── main.py                       ← MainWindow（顶栏两行 + 6 选项卡 + 窗口级壁纸）
│   ├── ComfyUI_ITX2.3_Sulphur 2_TexttoVideo.json   ← 文生视频 Workflow
│   ├── ComfyUI_ITX2.3_Sulphur 2_PicturetoVideo.json ← 图生视频 Workflow
│   ├── core/                         ← ⭐ 核心逻辑层
│   │   ├── config.py                 ← ConfigManager 单例（点路径 get/set）
│   │   ├── server_manager.py         ← llama-server 进程管理
│   │   ├── llm_client.py             ← OpenAI 兼容流式客户端
│   │   ├── character_manager.py      ← 角色卡 + 世界书 + 游戏 prompt
│   │   ├── tts_installer.py          ← CosyVoice 安装器
│   │   ├── tts_server_manager.py     ← CosyVoice 服务管理
│   │   ├── tts_client.py             ← CosyVoice HTTP 客户端
│   │   ├── gpt_sovits_server_manager.py  ← GPT-SoVITS 服务管理
│   │   ├── gpt_sovits_client.py      ← GPT-SoVITS HTTP 客户端
│   │   ├── comfyui_client.py         ← ComfyUI API 客户端
│   │   ├── system_monitor.py         ← psutil 监控
│   │   ├── we_pkg_extract.py         ← Wallpaper Engine pkg 解包
│   │   ├── theme_manager.py          ← 主题管理
│   │   ├── text_opacity.py           ← 文字透明度补偿
│   │   └── api_server.py             ← 内嵌 API
│   ├── widgets/                      ← ⭐ UI 层
│   │   ├── ai_panel.py               ← 💬 对话 + 🎭 角色扮演 面板
│   │   ├── video_panel_v2.py         ← 🎬 文生视频 + 🖼 图生视频 面板（当前生效版）
│   │   ├── video_setup_wizard.py     ← ComfyUI workflow 向导
│   │   ├── tts_panel.py               ← 🎤 语音系统 面板
│   │   ├── wallpaper_panel.py         ← 🖼 壁纸与外观 面板
│   │   ├── animated_bg.py            ← 窗口级壁纸（图片/视频 + 互动透视层）
│   │   ├── wallpaper_import_dialog.py ← 壁纸导入对话框
│   │   ├── character_dialog.py        ← 新建/管理角色
│   │   ├── settings_dialog.py        ← 设置对话框
│   │   ├── web_server_dialog.py      ← 手机版服务对话框
│   │   └── ...
│   ├── web/                          ← 手机版 FastAPI 服务
│   │   └── web_server.py
│   └── cosyvoice_service/            ← CosyVoice FastAPI 服务（独立 conda 进程）
│       └── server.py
│
└── models/                           ← ⚠️ 模型目录（需自行下载，见下方指南）
    ├── .gitkeep                      ← git 占位（模型文件不入库）
    ├── (LLM gguf 文件直接放这里)
    ├── Sulphur 2/                    ← 视频模型（README 里有下载链接）
    ├── GPT-SoVITS-v2pro/             ← 语音模型整合包
    └── CosyVoice/                    ← CosyVoice 语音模型
```

***

## 🧠 模型下载 & 放置指南

> ⚠️ 所有模型文件不随 GitHub 仓库分发（单文件超 100MB / 总计超 90GB），请按下方链接自行下载后放入对应目录。

### 一、LLM 对话模型（llama.cpp / GGUF 格式）

**程序里设置位置**：顶栏第二行 → 💬 对话 / 🎭 角色扮演 下拉框

| 模型                                      | 大小       | 下载链接                                                                            | 放入目录      |
| --------------------------------------- | -------- | ------------------------------------------------------------------------------- | --------- |
| **Gemma 4 E4B Uncensored (Q4\_K\_M)**   | \~5 GB   | [ModelScope](https://www.modelscope.cn) / [HuggingFace](https://huggingface.co) | `models/` |
| **Qwen3.6-35B A3B Uncensored (IQ2\_M)** | \~11 GB  | [ModelScope](https://www.modelscope.cn) / [HuggingFace](https://huggingface.co) | `models/` |
| **mmproj-Qwen3.6**（多模态投影）               | \~858 MB | 随 Qwen3.6 一起下载                                                                  | `models/` |

放置后启动程序会**自动扫描** `models/` 下所有 `.gguf` 文件填入下拉框。

***

### 二、llama-server.exe（LLM 推理引擎）

**程序里设置位置**：自动定位（`launcher.py` 扫描常见路径），或手动指定

| 资源                                  | 下载链接                                              | 放入目录                                       |
| ----------------------------------- | ------------------------------------------------- | ------------------------------------------ |
| **llama.cpp Windows CUDA 13.3 预编译** | <https://github.com/ggerganov/llama.cpp/releases> | 项目根目录 `llama-b9381-bin-win-cuda-13.3-x64/` |

需要 `llama-server.exe` + 配套的 CUDA DLL（`cublasLt64_13.dll` 等）。

***

### 三、GPT-SoVITS-v2pro（多语种语音克隆）⭐ 推荐

**程序里设置位置**：🎤 语音系统 → 顶栏选 GPT-SoVITS-v2pro → 配置整合包路径 + 权重 + 参考音频

| 资源                            | 下载链接                                                                       | 放入目录                         |
| ----------------------------- | -------------------------------------------------------------------------- | ---------------------------- |
| **完整整合包（含 runtime + api.py）** | <https://www.modelscope.cn/models/AI-ModelScope/GPT-SoVITS-v2pro-20250604> | `models/GPT-SoVITS-v2pro/`   |
| **官方仓库（从源码编译）**               | <https://github.com/RVC-Boss/GPT-SoVITS>                                   | 同上                           |
| **🎭 角色 GPT-SoVITS 模型库（热门）**  | **<https://www.ai-hobbyist.com/>**                                         | 下载 `.ckpt` + `.pth` 放入对应权重目录 |

整合包解压后目录结构：

```
models/GPT-SoVITS-v2pro/
├── api.py / api_v2.py / webui.py
├── runtime/                          ← 自带 Python 3.9 + PyTorch CUDA（无需自己装）
├── GPT_SoVITS/pretrained_models/     ← 基础预训练模型（整合包已带）
├── GPT_weights_v2Pro/               ← 📥 你的角色 GPT 权重（.ckpt）
│   └── 你的角色-e10.ckpt
├── SoVITS_weights_v2Pro/             ← 📥 你的角色 SoVITS 权重（.pth）
│   └── 你的角色_e10_s940.pth
└── tools/uvr5/uvr5_weights/         ← 人声分离模型（可选）
```

**程序里还需要配置**：

| 配置项              | 说明                | 示例                                       |
| ---------------- | ----------------- | ---------------------------------------- |
| 整合包路径            | 含 api.py 的目录      | `models/GPT-SoVITS-v2pro`                |
| SoVITS 权重 (.pth) | v2Pro 格式          | `SoVITS_weights_v2Pro/你的角色_e10_s940.pth` |
| GPT 权重 (.ckpt)   | v2Pro 格式          | `GPT_weights_v2Pro/你的角色-e10.ckpt`        |
| 默认参考音频           | 3-5 秒干净 wav       | 角色的一段录音                                  |
| 默认参考文本           | 音频里说的话（精确匹配）      | `"可恶，怎么又是盗宝团！"`                          |
| 默认参考语种           | zh / en / ja / ko | `zh`                                     |

**⚠️ 重要**：参考音频建议 3-5 秒、单句、无背景噪音。每次合成都**不传**参考参数（让服务用启动时 `-dr/-dt/-dl` 设置的 default\_refer），否则每次会重新 zero-shot 克隆，长参考音频的尾部内容会被当作"固定前缀"注入输出。

***

### 四、CosyVoice2 / CosyVoice3（中文零样本语音克隆）

**程序里设置位置**：🎤 语音系统 → 顶栏选 CosyVoice → 配置 repo 路径 + 模型目录

| 资源                               | 下载链接                                                            | 放入目录                                                           |
| -------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------- |
| **CosyVoice 官方仓库**               | <https://github.com/FunAudioLLM/CosyVoice>                      | `models/CosyVoice/`                                            |
| **Fun-CosyVoice3-0.5B-2512（推荐）** | <https://www.modelscope.cn/models/iic/Fun-CosyVoice3-0.5B-2512> | `models/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B-2512/` |
| **CosyVoice2-0.5B**              | 同上                                                              | `models/CosyVoice/pretrained_models/CosyVoice2-0.5B/`          |

程序内置 CosyVoice 安装器（设置页 → 语音模型 → 步骤 1-2），自动 clone 仓库 + 创建 conda 环境 + 安装依赖 + 下载模型。

***

### 五、视频生成模型（ComfyUI + LTX-Video + Sulphur 2）

**程序里设置位置**：🎬 文生视频 / 🖼 图生视频 → 启动向导 → 加载 workflow → 填入模型路径

需要先装 **ComfyUI 桌面版**：<https://github.com/comfyanonymous/ComfyUI>

Sulphur 2 模型文件（需手动下载后放入 ComfyUI 的 `ComfyUI/models/checkpoints/`）：

| 模型文件                                                       | 大小       | 下载链接                                                                            |
| ---------------------------------------------------------- | -------- | ------------------------------------------------------------------------------- |
| **10Eros\_v1.4\_DMD\_int8\_convrot.safetensors**           | \~27 GB  | [ModelScope](https://www.modelscope.cn) / [HuggingFace](https://huggingface.co) |
| **gemma-3-12b-it-ablit-norms-biproj-fp8mixed.safetensors** | \~12 GB  | 同上                                                                              |
| **ltx-2.3-22b-distilled-lora-384.safetensors**             | \~7.3 GB | 同上                                                                              |
| **ltx-2.3-spatial-upscaler-x2-1.1.safetensors**            | \~950 MB | 同上                                                                              |

Workflow 模板：程序已内置两份 JSON（仓库根目录 `AI_Chat/` 下），也可在 ComfyUI 里导出 API 格式。

***

## 🖼 壁纸系统说明（重要！）

> ⚠️ **本程序的壁纸功能是通过读取 Wallpaper Engine 订阅时下载的文件夹来工作的**。
>
> 也就是说，本程序本身**不提供**壁纸资源。你需要：
>
> 1. 先在 **Wallpaper Engine**（Steam 版）里订阅喜欢的壁纸作者的作品
> 2. 程序的「📁 导入 Wallpaper Engine 壁纸文件夹」按钮会自动扫描你电脑上 Wallpaper Engine 的下载目录
> 3. **使用壁纸前，请务必在 Wallpaper Engine 中关注/订阅该作者**，尊重原创劳动成果

程序支持的壁纸类型：

* 📸 **静态图片壁纸**（Wallpaper Engine pkg 格式，程序会自动提取预览图）

* 🎬 **动态视频壁纸**（直接支持 mp4/avi 等格式）

* 🖱 **互动透视壁纸**（移动鼠标时有光晕跟随效果）

***

## 🛠 依赖清单

| 包          | 版本       | 用途           |
| ---------- | -------- | ------------ |
| PyQt5      | ≥5.15.0  | GUI 框架       |
| QScintilla | ≥2.13.0  | 代码编辑器        |
| requests   | ≥2.28.0  | HTTP 客户端     |
| chardet    | ≥5.0.0   | 字符编码检测       |
| psutil     | ≥5.9.0   | 系统监控         |
| fastapi    | ≥0.100.0 | Web 服务器（手机版） |
| uvicorn    | ≥0.23.0  | ASGI 服务器     |

## ⌨️ 快捷键

| 快捷键    | 功能        |
| ------ | --------- |
| Ctrl+0 | 🖼 壁纸与外观  |
| Ctrl+1 | 💬 对话     |
| Ctrl+2 | 🎭 角色扮演对话 |
| Ctrl+3 | 🎬 文生视频   |
| Ctrl+4 | 🖼 图生视频   |
| Ctrl+5 | 🎤 语音系统   |

***

## 📄 License

GPL-3.0
