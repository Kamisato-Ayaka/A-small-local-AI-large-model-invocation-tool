"""
音频播放 - winsound 播放 wav（Windows 标准库，零依赖，异步不阻塞 UI）
"""
import winsound

from PyQt5.QtCore import QObject, pyqtSignal


class AudioPlayer(QObject):
    """wav 播放器（单例）"""

    playing_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playing = False
        self._current_path = ""

    @property
    def is_busy(self) -> bool:
        return self._playing

    def play(self, wav_path: str):
        """异步播放 wav；新播放会打断旧播放"""
        if not wav_path:
            return
        self._current_path = wav_path
        if not self._playing:
            self._playing = True
            self.playing_changed.emit(True)
        try:
            winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            self._playing = False
            self.playing_changed.emit(False)

    def stop(self):
        """停止播放"""
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        if self._playing:
            self._playing = False
            self.playing_changed.emit(False)
        self._current_path = ""


_audio_player = None


def get_audio_player() -> AudioPlayer:
    global _audio_player
    if _audio_player is None:
        _audio_player = AudioPlayer()
    return _audio_player
