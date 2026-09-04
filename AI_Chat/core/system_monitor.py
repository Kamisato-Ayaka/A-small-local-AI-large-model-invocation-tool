"""
系统监控 - CPU、内存、GPU 使用率
"""
import os
import threading
import time
from typing import Dict, Optional
from PyQt5.QtCore import QObject, pyqtSignal, QTimer


class SystemMonitor(QObject):
    """系统监控器"""

    stats_updated = pyqtSignal(dict)  # {cpu, memory, gpu, gpu_memory}

    def __init__(self, interval_ms: int = 2000, parent=None):
        super().__init__(parent)
        self.interval_ms = interval_ms
        self._timer = None
        self._psutil_available = False
        self._nvidia_available = False

        # 尝试导入 psutil
        try:
            import psutil
            self._psutil_available = True
        except ImportError:
            self._psutil_available = False

        # 检查 nvidia-smi
        self._nvidia_available = self._check_nvidia()

        self._last_stats = {
            "cpu": 0,
            "memory": 0,
            "memory_total_gb": 0,
            "memory_used_gb": 0,
            "gpu": 0,
            "gpu_memory": 0,
            "gpu_memory_total_gb": 0,
            "gpu_memory_used_gb": 0,
        }

    def _check_nvidia(self) -> bool:
        """检查是否有 NVIDIA GPU"""
        try:
            result = os.popen("nvidia-smi --query-gpu=name --format=csv,noheader 2>nul").read()
            return bool(result.strip())
        except Exception:
            return False

    def start(self):
        """开始监控"""
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._update_stats)
            self._timer.start(self.interval_ms)
            # 立即更新一次
            QTimer.singleShot(0, self._update_stats)

    def stop(self):
        """停止监控"""
        if self._timer:
            self._timer.stop()
            self._timer = None

    @property
    def is_running(self) -> bool:
        return self._timer is not None

    @property
    def last_stats(self) -> dict:
        return self._last_stats.copy()

    def _update_stats(self):
        """更新系统状态"""
        stats = self._last_stats.copy()

        # CPU 和内存（用 psutil）
        if self._psutil_available:
            try:
                import psutil
                stats["cpu"] = psutil.cpu_percent(interval=0)
                mem = psutil.virtual_memory()
                stats["memory"] = mem.percent
                stats["memory_total_gb"] = round(mem.total / (1024**3), 1)
                stats["memory_used_gb"] = round(mem.used / (1024**3), 1)
            except Exception:
                pass
        else:
            # 没有 psutil，用简单方式
            try:
                import psutil
            except ImportError:
                # 用 wmic 做粗略估计（Windows）
                if os.name == "nt":
                    try:
                        # CPU 使用率（通过 wmic）
                        cpu_out = os.popen("wmic cpu get loadpercentage 2>nul").read()
                        for line in cpu_out.strip().split("\n"):
                            line = line.strip()
                            if line.isdigit():
                                stats["cpu"] = int(line)
                                break
                    except Exception:
                        pass

        # GPU（用 nvidia-smi）
        if self._nvidia_available:
            try:
                cmd = "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits"
                result = os.popen(cmd).read().strip()
                if result:
                    parts = [p.strip() for p in result.split(",")]
                    if len(parts) >= 3:
                        stats["gpu"] = float(parts[0])
                        mem_used = float(parts[1])
                        mem_total = float(parts[2])
                        stats["gpu_memory_used_gb"] = round(mem_used / 1024, 1)
                        stats["gpu_memory_total_gb"] = round(mem_total / 1024, 1)
                        if mem_total > 0:
                            stats["gpu_memory"] = round(mem_used / mem_total * 100, 1)
            except Exception:
                pass

        self._last_stats = stats
        self.stats_updated.emit(stats)

    def get_cpu_text(self) -> str:
        return f"CPU {self._last_stats['cpu']:.0f}%"

    def get_memory_text(self) -> str:
        s = self._last_stats
        if s["memory_total_gb"] > 0:
            return f"内存 {s['memory']:.0f}% ({s['memory_used_gb']:.1f}/{s['memory_total_gb']:.1f}GB)"
        return f"内存 {s['memory']:.0f}%"

    def get_gpu_text(self) -> str:
        s = self._last_stats
        if self._nvidia_available and s["gpu_memory_total_gb"] > 0:
            return f"GPU {s['gpu']:.0f}% ({s['gpu_memory_used_gb']:.1f}/{s['gpu_memory_total_gb']:.1f}GB)"
        elif self._nvidia_available:
            return f"GPU {s['gpu']:.0f}%"
        return "GPU N/A"

    @property
    def has_gpu(self) -> bool:
        return self._nvidia_available

    @property
    def has_psutil(self) -> bool:
        return self._psutil_available
