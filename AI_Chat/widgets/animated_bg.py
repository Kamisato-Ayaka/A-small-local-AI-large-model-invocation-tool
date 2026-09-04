"""
动态背景组件 - 支持 GIF 动画、MP4 视频和静态图片背景
"""
import os
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, QUrl, QSize, pyqtSignal
from PyQt5.QtGui import QMovie, QPixmap, QPainter, QColor, QBrush, QImage, QPainterPath, QPen, QCursor, QImageReader
from PyQt5.QtMultimedia import (
    QMediaPlayer, QMediaContent, QVideoFrame, QAbstractVideoSurface,
    QAbstractVideoBuffer,
)

# 视频扩展名（Wallpaper Engine 的 video 类型壁纸是 mp4）
VIDEO_EXTS = (".mp4", ".avi", ".mkv", ".mov", ".webm")


class _VideoSurface(QAbstractVideoSurface):
    """把 QMediaPlayer 的视频帧取出为 QImage，交给背景组件绘制"""

    def __init__(self, on_frame):
        super().__init__()
        self._on_frame = on_frame

    def supportedPixelFormats(self, handleType):
        if handleType == QAbstractVideoBuffer.NoHandle:
            return [
                QVideoFrame.Format_ARGB32, QVideoFrame.Format_ARGB32_Premultiplied,
                QVideoFrame.Format_RGB32, QVideoFrame.Format_RGB24,
                QVideoFrame.Format_RGB565, QVideoFrame.Format_YUV420P,
                QVideoFrame.Format_YV12, QVideoFrame.Format_NV12,
                QVideoFrame.Format_BGRA32, QVideoFrame.Format_BGR32,
            ]
        return []

    def present(self, frame):
        if not frame.isValid():
            return False
        f = QVideoFrame(frame)
        if f.map(QAbstractVideoBuffer.ReadOnly):
            fmt = QVideoFrame.imageFormatFromPixelFormat(f.pixelFormat())
            if fmt != QImage.Format_Invalid:
                img = QImage(f.bits(), f.width(), f.height(), f.bytesPerLine(), fmt).copy()
                f.unmap()
                self._on_frame(img)
        return True


class AnimatedBackground(QWidget):
    """支持 GIF 动画 / MP4 视频的背景组件"""

    aspectRatioChanged = pyqtSignal(float)  # 媒体宽高比 w/h（用于窗口适配）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._movie = None
        self._pixmap = None
        self._bg_color = "#1e1e1e"
        self._opacity = 1.0
        self._timer = None
        self._frame_index = 0
        # 视频相关
        self._player = None
        self._surface = None
        self._video_image = None
        self._video_source = ""
        # 双层互动视频（鼠标透视：圆圈内显示第二层视频）
        self._player2 = None
        self._surface2 = None
        self._video_image2 = None
        self._video_source2 = ""
        self._reveal_pos = None       # 鼠标位置（本组件坐标），None=不在窗口内不画透视圈
        self.reveal_radius = 60      # 透视圈半径（px）
        self._sync_timer = None
        self._mouse_timer = None      # 轮询全局鼠标位置（Qt 不给未开 tracking 的控件发 MouseMove）
        self._aspect_emitted = False  # 当前媒体是否已报告宽高比
        self._skip_fill = False
        self.setAttribute(Qt.WA_StyledBackground, False)

    # ---------- 公共接口 ----------

    def set_background(self, image_path: str = "", bg_color: str = "#1e1e1e", opacity: float = 1.0):
        """设置背景

        Args:
            image_path: 路径，支持 .gif/.png/.jpg/.bmp/.webp 及 .mp4 等视频
            bg_color: 背景色（无图片时使用）
            opacity: 透明度 0.0-1.0
        """
        self._bg_color = bg_color
        self._opacity = max(0.1, min(1.0, opacity))
        self._skip_fill = False
        self._aspect_emitted = False

        # 停止之前的动画
        self._stop_movie()
        self._pixmap = None

        if not image_path or not os.path.exists(image_path):
            self._stop_video()
            self.update()
            return

        ext = os.path.splitext(image_path)[1].lower()

        if ext == ".gif":
            # GIF 动画
            self._stop_video()
            self._movie = QMovie(image_path)
            self._movie.start()
            # 用定时器刷新
            if self._timer is None:
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._on_frame_changed)
            frame_count = self._movie.frameCount()
            self._timer.start(80 if frame_count > 0 else 100)
            self._emit_aspect(image_path)
        elif ext in VIDEO_EXTS:
            # 视频背景（静音循环播放），宽高比在首帧回调时报告
            self._start_video(image_path)
        else:
            # 静态图片
            self._stop_video()
            self._pixmap = QPixmap(image_path)
            self._emit_aspect(image_path)

        self.update()

    def _emit_aspect(self, path: str):
        """用 QImageReader 读取媒体尺寸并广播宽高比（图片/GIF 即时可得）"""
        try:
            size = QImageReader(path).size()
            if size.isValid() and size.width() > 0 and size.height() > 0:
                self._aspect_emitted = True
                self.aspectRatioChanged.emit(size.width() / size.height())
        except Exception:
            pass

    def clear(self):
        """清除背景（仍绘制底色）"""
        self._stop_movie()
        self._stop_video()
        self._pixmap = None
        self._skip_fill = False
        self.update()

    def clear_to_transparent(self):
        """清除内容且不再绘制底色（让下层壁纸透出）"""
        self._stop_movie()
        self._stop_video()
        self._pixmap = None
        self._video_image = None
        self._skip_fill = True
        self.update()

    # ---------- GIF ----------

    def _stop_movie(self):
        if self._movie:
            if self._timer:
                self._timer.stop()
                self._timer = None
            self._movie = None

    def _on_frame_changed(self):
        """GIF 帧更新"""
        if self._movie:
            self.update()

    # ---------- 视频 ----------

    def _start_video(self, path: str):
        self._video_image = None
        if self._player is None:
            try:
                self._surface = _VideoSurface(self._on_video_frame)
                self._player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
                self._player.setVideoOutput(self._surface)
                self._player.setMuted(True)
                self._player.mediaStatusChanged.connect(self._on_media_status)
            except Exception:
                self._player = None
                self._surface = None
                return
        if self._player is None:
            return
        self._video_source = path
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self._player.play()
        # 同文件夹存在第二个视频 → 开启鼠标透视互动
        self._setup_reveal_layer(path)

    def _stop_video(self):
        for player in (self._player, self._player2):
            if player:
                try:
                    player.stop()
                    player.setMedia(QMediaContent())
                except Exception:
                    pass
        self._video_image = None
        self._video_source = ""
        self._video_image2 = None
        self._video_source2 = ""
        self._reveal_pos = None
        if self._sync_timer:
            self._sync_timer.stop()
        if self._mouse_timer:
            self._mouse_timer.stop()

    def set_reveal_position(self, pos):
        """主窗口转发鼠标位置（本组件坐标）；None 表示鼠标不在窗口内"""
        if pos != self._reveal_pos:
            self._reveal_pos = pos
            self.update()

    # ---------- 双层互动视频 ----------

    def _find_reveal_video(self, path: str) -> str:
        """在同文件夹（含 extracted/）里找另一个视频作为透视层，返回路径或空"""
        folder = os.path.dirname(path)
        cands = []
        for d in (folder, os.path.join(folder, "extracted")):
            try:
                for n in os.listdir(d):
                    p = os.path.join(d, n)
                    if (os.path.isfile(p) and n.lower().endswith(VIDEO_EXTS)
                            and os.path.abspath(p) != os.path.abspath(path)):
                        cands.append(p)
            except OSError:
                continue
        if not cands:
            return ""
        return max(cands, key=os.path.getsize)

    def _setup_reveal_layer(self, base_path: str):
        """若存在第二个视频，启动透视层播放并开启周期同步"""
        reveal = self._find_reveal_video(base_path)
        if not reveal:
            self._stop_reveal_player()
            return
        try:
            if self._player2 is None:
                self._surface2 = _VideoSurface(self._on_video_frame2)
                self._player2 = QMediaPlayer(None, QMediaPlayer.VideoSurface)
                self._player2.setVideoOutput(self._surface2)
                self._player2.setMuted(True)
                self._player2.mediaStatusChanged.connect(self._on_media_status2)
        except Exception:
            self._player2 = None
            self._surface2 = None
            return
        self._video_source2 = reveal
        self._player2.setMedia(QMediaContent(QUrl.fromLocalFile(reveal)))
        self._player2.play()
        # 与主视频周期同步，避免两个循环时长漂移
        if self._sync_timer is None:
            self._sync_timer = QTimer(self)
            self._sync_timer.timeout.connect(self._sync_videos)
        self._sync_timer.start(5000)
        # 轮询鼠标位置驱动透视圈
        if self._mouse_timer is None:
            self._mouse_timer = QTimer(self)
            self._mouse_timer.timeout.connect(self._poll_mouse)
        self._mouse_timer.start(30)

    def _stop_reveal_player(self):
        if self._player2:
            try:
                self._player2.stop()
                self._player2.setMedia(QMediaContent())
            except Exception:
                pass
        self._video_image2 = None
        self._video_source2 = ""
        if self._sync_timer:
            self._sync_timer.stop()
        if self._mouse_timer:
            self._mouse_timer.stop()

    def _poll_mouse(self):
        """轮询全局光标位置驱动透视圈（不依赖控件 mouseTracking）"""
        if not self.isVisible():
            return
        pos = self.mapFromGlobal(QCursor.pos())
        self.set_reveal_position(pos if self.rect().contains(pos) else None)

    def _on_video_frame2(self, img: QImage):
        self._video_image2 = img
        self.update()

    def _on_media_status2(self, status):
        if status == QMediaPlayer.EndOfMedia and self._player2 and self._video_source2:
            self._player2.setPosition(0)
            self._player2.play()

    def _sync_videos(self):
        """把透视层位置对齐主视频（差 0.8 秒以上才校准）"""
        try:
            if (self._player and self._player2
                    and self._player.state() == QMediaPlayer.PlayingState
                    and self._player2.state() == QMediaPlayer.PlayingState
                    and abs(self._player.position() - self._player2.position()) > 800):
                self._player2.setPosition(self._player.position())
        except Exception:
            pass

    def _on_video_frame(self, img: QImage):
        self._video_image = img
        # 首帧到达时报告视频宽高比（视频元数据异步，帧尺寸最可靠）
        if not self._aspect_emitted and not img.isNull() and img.width() > 0:
            self._aspect_emitted = True
            self.aspectRatioChanged.emit(img.width() / img.height())
        self.update()

    def _on_media_status(self, status):
        # 播放结束 → 循环重播
        if status == QMediaPlayer.EndOfMedia and self._player and self._video_source:
            self._player.setPosition(0)
            self._player.play()

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rect = self.rect()

        # 先画背景色（透明模式跳过）
        if not self._skip_fill:
            color = QColor(self._bg_color)
            color.setAlphaF(self._opacity)
            painter.fillRect(rect, color)

        # 再画内容
        if self._movie and self._movie.state() == QMovie.Running:
            pixmap = self._movie.currentPixmap()
            if not pixmap.isNull():
                self._draw_cover(painter, pixmap, rect)
        elif self._video_image is not None and not self._video_image.isNull():
            self._draw_cover(painter, QPixmap.fromImage(self._video_image), rect)
        elif self._pixmap and not self._pixmap.isNull():
            self._draw_cover(painter, self._pixmap, rect)

        # 鼠标透视圈：圆内绘制第二层视频（互动壁纸）
        if (self._video_image2 is not None and not self._video_image2.isNull()
                and self._reveal_pos is not None and self.reveal_radius > 0):
            painter.save()
            circle = QPainterPath()
            circle.addEllipse(self._reveal_pos, float(self.reveal_radius), float(self.reveal_radius))
            painter.setClipPath(circle)
            self._draw_cover(painter, QPixmap.fromImage(self._video_image2), rect)
            painter.restore()
            # 圈边缘微光
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QPen(QColor(255, 255, 255, 90), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(self._reveal_pos, self.reveal_radius, self.reveal_radius)

        painter.end()

    def _draw_cover(self, painter: QPainter, pixmap: QPixmap, rect):
        """居中缩放绘制（保持比例 cover 模式）"""
        if pixmap.isNull():
            return

        pw = pixmap.width()
        ph = pixmap.height()
        rw = rect.width()
        rh = rect.height()

        if pw == 0 or ph == 0 or rw == 0 or rh == 0:
            return

        # 按 cover 模式缩放
        scale = max(rw / pw, rh / ph)
        new_w = int(pw * scale)
        new_h = int(ph * scale)
        x = (rw - new_w) // 2
        y = (rh - new_h) // 2

        # 应用透明度
        painter.setOpacity(self._opacity)
        painter.drawPixmap(x, y, new_w, new_h, pixmap)
        painter.setOpacity(1.0)
