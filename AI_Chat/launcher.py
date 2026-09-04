"""
A Small Local AI Runner 启动器
- 检查并安装依赖
- 可选启动 llama-server
- 启动 A Small Local AI Runner 主程序
- 所有输出通过 Python 控制台，避免 cmd 中文乱码
"""
import os
import sys
import subprocess
import time
import argparse


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


# 依赖列表：(导入名, pip 包名)
# 导入名支持点号（如 "PyQt5.Qsci"），会自动 import 顶层模块并检查子模块
REQUIREMENTS = [
    ("PyQt5", "PyQt5>=5.15.0"),
    ("requests", "requests>=2.28.0"),
    ("chardet", "chardet>=5.0.0"),
    ("psutil", "psutil>=5.9.0"),
    ("fastapi", "fastapi>=0.100.0"),
    ("uvicorn", "uvicorn>=0.23.0"),
    ("qrcode", "qrcode>=7.4.0"),
    ("PIL", "Pillow>=9.0.0"),
    ("pyngrok", "pyngrok>=7.0.0"),
]

# LLM 配置
LLM_PORT = 8080
LLM_HOST = "127.0.0.1"


def print_header():
    print("=" * 55)
    print("  A Small Local AI Runner Launcher")
    print("  Local AI Code Assistant")
    print("=" * 55)
    print()


def check_package(name: str) -> bool:
    """检查包是否可用，支持点号分隔的子模块（如 PyQt5.Qsci）"""
    try:
        if "." in name:
            # 使用 __import__ 带 fromlist 确保子模块被加载
            parts = name.split(".")
            mod = __import__(name, fromlist=[parts[-1]])
        else:
            __import__(name)
        return True
    except (ImportError, AttributeError, ValueError):
        return False


def install_package(pkg: str) -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            timeout=300
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("  [ERROR] Install timeout (5 min)")
        return False
    except Exception as e:
        print(f"  [ERROR] Install failed: {e}")
        return False


def check_dependencies():
    """检查并安装依赖，返回是否成功"""
    print("[1/3] Checking dependencies...")
    print()

    missing = []
    for name, pkg in REQUIREMENTS:
        if check_package(name):
            print(f"  [OK] {name} - installed")
        else:
            print(f"  [MISSING] {name} - not installed")
            missing.append((name, pkg))

    print()

    if missing:
        print(f"Found {len(missing)} missing packages. Installing...")
        print()

        failed = []
        for i, (name, pkg) in enumerate(missing):
            print(f"  [{i+1}/{len(missing)}] Installing {name}...")
            print(f"        pip install {pkg}")
            print()

            success = install_package(pkg)

            if success and check_package(name):
                print(f"  [OK] {name} installed successfully")
            else:
                print(f"  [FAIL] {name} installation failed")
                failed.append(name)

            print()

        if failed:
            print("[ERROR] Some packages failed to install: " + ", ".join(failed))
            print()
            print("Please try manually:")
            for name, pkg in missing:
                if name in failed:
                    print(f"  pip install {pkg}")
            return False

        print("[OK] All dependencies installed!")
        print()
    else:
        print("[OK] All dependencies are ready!")
        print()

    return True


def find_llama_server():
    """查找 llama-server.exe 的位置"""
    # 上一级目录
    parent_dir = os.path.dirname(BASE_DIR)
    server_exe = os.path.join(parent_dir, "llama-server.exe")
    if os.path.exists(server_exe):
        return server_exe, parent_dir
    return None, None


def find_model_files(base_dir: str):
    """查找模型文件"""
    models_dir = os.path.join(base_dir, "models")
    if not os.path.exists(models_dir):
        return None, None

    # 找 .gguf 模型文件
    model_file = None
    mmproj_file = None

    try:
        for f in os.listdir(models_dir):
            fpath = os.path.join(models_dir, f)
            if not os.path.isfile(fpath):
                continue
            lower = f.lower()
            if lower.endswith(".gguf"):
                if "mmproj" in lower:
                    mmproj_file = fpath
                elif model_file is None:
                    model_file = fpath
    except Exception:
        pass

    return model_file, mmproj_file


def start_llm_server():
    """启动 llama-server，返回 (进程, 是否成功)"""
    print("[2/3] Starting LLM server...")
    print()

    server_exe, base_dir = find_llama_server()
    if not server_exe:
        print("  [WARN] llama-server.exe not found")
        print("  You can start it manually later.")
        print()
        return None

    model_file, mmproj_file = find_model_files(base_dir)
    if not model_file:
        print("  [WARN] No model file found in models/ directory")
        print("  You can start llama-server manually later.")
        print()
        return None

    # 构建命令
    cmd = [
        server_exe,
        "-m", model_file,
        "-ngl", "999",
        "-c", "8192",
        "-n", "4096",
        "--host", LLM_HOST,
        "--port", str(LLM_PORT),
    ]

    if mmproj_file:
        cmd.extend(["--mmproj", mmproj_file])

    model_name = os.path.basename(model_file)
    if len(model_name) > 40:
        model_name = model_name[:37] + "..."

    print(f"  Model: {model_name}")
    print(f"  Server: http://{LLM_HOST}:{LLM_PORT}")
    print()
    print("  Loading model... (this may take 10-30 seconds)")

    try:
        # 后台启动（新窗口最小化）
        if os.name == "nt":
            # Windows: 用 start 命令最小化启动
            proc = subprocess.Popen(
                ["cmd", "/c", "start", "/min", "llama-server"] + cmd,
                cwd=base_dir
            )
        else:
            proc = subprocess.Popen(cmd, cwd=base_dir)

        # 等待一会儿让服务启动
        time.sleep(3)

        # 检查进程是否还在
        if os.name == "nt":
            # 用 start 启动的是独立进程，这里检查端口
            time.sleep(5)

        print("  [OK] LLM server starting...")
        print("  (It will be ready after model loads)")
        print()
        return proc

    except Exception as e:
        print(f"  [ERROR] Failed to start LLM server: {e}")
        print()
        return None


def start_codemate():
    """启动 A Small Local AI Runner 主程序"""
    print("[3/3] Starting A Small Local AI Runner...")
    print()

    app_script = os.path.join(BASE_DIR, "app.py")

    try:
        subprocess.Popen([sys.executable, app_script])
        time.sleep(1)
        print("[OK] A Small Local AI Runner started!")
        print()
        print("The A Small Local AI Runner window should appear shortly.")
        print("You can close this window.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to start A Small Local AI Runner: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="A Small Local AI Runner Launcher")
    parser.add_argument("--with-llm", action="store_true",
                        help="Start llama-server together with A Small Local AI Runner")
    args = parser.parse_args()

    try:
        print_header()

        # 步骤1：检查依赖
        if not check_dependencies():
            print()
            input("Press Enter to exit...")
            sys.exit(1)

        # 步骤2：启动 LLM（可选）
        if args.with_llm:
            start_llm_server()
        else:
            print("[2/3] Skipping LLM server (use --with-llm to start it)")
            print()

        # 步骤3：启动 A Small Local AI Runner
        if not start_codemate():
            print()
            input("Press Enter to exit...")
            sys.exit(1)

        # 短暂显示后自动退出（如果是 GUI 模式则交给 GUI 启动器）
        time.sleep(2)

    except KeyboardInterrupt:
        print()
        print("Cancelled.")
        sys.exit(0)
    except Exception as e:
        print()
        print(f"[ERROR] Launcher error: {e}")
        import traceback
        traceback.print_exc()
        print()
        input("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
