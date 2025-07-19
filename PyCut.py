import sys
import os
import cv2
import numpy as np
import json
import tempfile
import subprocess
import shutil
import random
from datetime import timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QMessageBox,
    QLabel, QSlider, QPushButton, QFileDialog, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsPixmapItem, QToolBar, QStatusBar, QComboBox,
    QListWidget, QListWidgetItem, QSizePolicy, QFrame, QStyleFactory, QDockWidget,
    QMenu, QMenuBar, QProgressBar, QDialog, QGridLayout, QLineEdit, QSpinBox,
    QDoubleSpinBox, QColorDialog, QCheckBox, QGroupBox, QScrollArea, QRadioButton,
    QButtonGroup, QTabWidget, QTextEdit, QGraphicsItem, QGraphicsPathItem, QGraphicsTextItem
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRectF, QSize, pyqtSignal, QObject, QThread, QPointF
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QColor, QIcon, QAction, 
    QBrush, QPalette, QCursor, QKeySequence, QFont, QPainterPath, QTransform,
    QFontMetrics, QLinearGradient, QRadialGradient, QConicalGradient
)
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Constants
DEFAULT_PROJECT_NAME = "Untitled Project"
DEFAULT_FPS = 30
DEFAULT_RESOLUTION = (1920, 1080)
SUPPORTED_VIDEO_FORMATS = ["mp4", "mov", "avi", "mkv", "flv"]
SUPPORTED_AUDIO_FORMATS = ["mp3", "wav", "aac", "ogg"]
SUPPORTED_IMAGE_FORMATS = ["png", "jpg", "jpeg", "bmp", "tiff", "webp"]
TRACK_HEIGHT = 60
TIMELINE_SCALE = 10  # pixels per second
MAX_TRACKS = 10

class VideoExportWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, clips, project_settings, output_path):
        super().__init__()
        self.clips = clips
        self.project_settings = project_settings
        self.output_path = output_path
        self.canceled = False

    def export(self):
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp()
            intermediate_files = []
            total_clips = len(self.clips)
            
            # Process each clip
            for i, clip in enumerate(self.clips):
                if self.canceled:
                    break
                    
                self.progress.emit(int((i / total_clips) * 80))
                output_path = os.path.join(temp_dir, f"clip_{i}.mp4")
                
                if clip['type'] == "video":
                    self.process_video_clip(clip, output_path)
                elif clip['type'] == "image":
                    self.process_image_clip(clip, output_path)
                elif clip['type'] == "text":
                    self.process_text_clip(clip, output_path)
                elif clip['type'] == "transition":
                    self.process_transition_clip(clip, output_path)
                elif clip['type'] == "audio":
                    # Audio will be processed separately
                    continue
                elif clip['type'] == "sticker":
                    self.process_sticker_clip(clip, output_path)
                    
                if clip['type'] != "audio":
                    intermediate_files.append(output_path)
            
            # Process audio tracks
            audio_files = []
            for i, clip in enumerate(self.clips):
                if clip['type'] == "audio":
                    audio_path = os.path.join(temp_dir, f"audio_{i}.wav")
                    self.process_audio_clip(clip, audio_path)
                    audio_files.append(audio_path)
            
            # Create file list for concatenation
            video_list_file = os.path.join(temp_dir, "video_list.txt")
            with open(video_list_file, "w") as f:
                for file in intermediate_files:
                    f.write(f"file '{file}'\n")
            
            # Concatenate video clips
            concat_path = os.path.join(temp_dir, "concat.mp4")
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
                "-i", video_list_file, "-c", "copy", concat_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Add audio tracks
            final_output = self.output_path
            if audio_files:
                # Mix audio tracks
                audio_inputs = []
                filter_complex = ""
                for j, audio_file in enumerate(audio_files):
                    audio_inputs.extend(["-i", audio_file])
                    filter_complex += f"[{j+1}:a]"
                
                filter_complex += f"amix=inputs={len(audio_files)}:duration=longest[a]"
                mixed_audio = os.path.join(temp_dir, "mixed_audio.wav")
                
                mix_cmd = [
                    "ffmpeg", "-y", 
                    *audio_inputs,
                    "-filter_complex", filter_complex,
                    "-map", "[a]", mixed_audio
                ]
                subprocess.run(mix_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # Combine video and audio
                combine_cmd = [
                    "ffmpeg", "-y", "-i", concat_path, "-i", mixed_audio,
                    "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-shortest", final_output
                ]
                subprocess.run(combine_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # Just copy the concatenated video
                shutil.copy(concat_path, final_output)
            
            # Cleanup
            shutil.rmtree(temp_dir)
            
            if not self.canceled:
                self.finished.emit(final_output)
            
        except Exception as e:
            self.error.emit(str(e))
            # Cleanup temp directory if it exists
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def process_video_clip(self, clip, output_path):
        start_time = clip.get('start_trim', 0)
        duration = clip.get('duration', 10)
        end_time = start_time + duration
        filters = []
        
        # Apply effects
        if clip.get('fade_in', 0) > 0:
            filters.append(f"fade=t=in:st={start_time}:d={clip['fade_in']}")
        if clip.get('fade_out', 0) > 0:
            fade_out_start = end_time - clip['fade_out']
            filters.append(f"fade=t=out:st={fade_out_start}:d={clip['fade_out']}")
        if clip.get('scale', 1) != 1:
            filters.append(f"scale=iw*{clip['scale']}:-1")
        if clip.get('rotation', 0) != 0:
            filters.append(f"rotate={clip['rotation']}*PI/180")
        if clip.get('opacity', 1) < 1:
            filters.append(f"colorchannelmixer=aa={clip['opacity']}")
        if clip.get('bw', False):
            filters.append("hue=s=0")
        if clip.get('blur', 0) > 0:
            filters.append(f"boxblur={clip['blur']}")
        if clip.get('chroma_key', False):
            color = clip.get('chroma_color', '#00FF00')
            similarity = clip.get('chroma_similarity', 0.1)
            blend = clip.get('chroma_blend', 0.1)
            r, g, b = self.hex_to_rgb(color)
            filters.append(f"chromakey=color={r}:{g}:{b}:similarity={similarity}:blend={blend}")
        if clip.get('lut', ''):
            lut_path = clip['lut']
            filters.append(f"lut3d=file='{lut_path}'")
        if clip.get('speed', 1) != 1:
            filters.append(f"setpts={1/clip['speed']}*PTS")
            duration = duration / clip['speed']
            
        filter_str = ",".join(filters) if filters else None
        
        # Handle speed adjustment
        if clip.get('speed', 1) != 1:
            cmd = [
                "ffmpeg", "-y", "-ss", str(start_time), "-i", clip['path'],
                "-t", str(duration), "-vf", filter_str, 
                "-filter:a", f"atempo={clip['speed']}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23", output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-ss", str(start_time), "-i", clip['path'],
                "-t", str(duration), "-vf", filter_str, "-c:v", "libx264", 
                "-preset", "fast", "-crf", "23", output_path
            ]
            
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def process_image_clip(self, clip, output_path):
        duration = clip.get('duration', 5)
        filters = []
        
        # Apply effects
        if clip.get('fade_in', 0) > 0:
            filters.append(f"fade=t=in:st=0:d={clip['fade_in']}")
        if clip.get('fade_out', 0) > 0:
            fade_out_start = duration - clip['fade_out']
            filters.append(f"fade=t=out:st={fade_out_start}:d={clip['fade_out']}")
        if clip.get('scale', 1) != 1:
            filters.append(f"scale=iw*{clip['scale']}:-1")
        if clip.get('rotation', 0) != 0:
            filters.append(f"rotate={clip['rotation']}*PI/180")
        if clip.get('opacity', 1) < 1:
            filters.append(f"colorchannelmixer=aa={clip['opacity']}")
        if clip.get('bw', False):
            filters.append("hue=s=0")
        if clip.get('blur', 0) > 0:
            filters.append(f"boxblur={clip['blur']}")
        if clip.get('chroma_key', False):
            color = clip.get('chroma_color', '#00FF00')
            similarity = clip.get('chroma_similarity', 0.1)
            blend = clip.get('chroma_blend', 0.1)
            r, g, b = self.hex_to_rgb(color)
            filters.append(f"chromakey=color={r}:{g}:{b}:similarity={similarity}:blend={blend}")
        if clip.get('lut', ''):
            lut_path = clip['lut']
            filters.append(f"lut3d:file='{lut_path}'")
            
        filter_str = ",".join(filters) if filters else None
        
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", clip['path'],
            "-t", str(duration), "-vf", filter_str, "-c:v", "libx264", 
            "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23", output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def process_text_clip(self, clip, output_path):
        text = clip.get('text', "Sample Text")
        duration = clip.get('duration', 5)
        font_size = clip.get('font_size', 48)
        font_color = clip.get('font_color', "#FFFFFF")
        bg_color = clip.get('bg_color', "#00000000")  # Transparent by default
        position = clip.get('position', "center")
        font_file = clip.get('font_file', "")
        shadow = clip.get('shadow', False)
        shadow_color = clip.get('shadow_color', "#000000")
        shadow_offset = clip.get('shadow_offset', 2)
        outline = clip.get('outline', False)
        outline_color = clip.get('outline_color', "#000000")
        outline_width = clip.get('outline_width', 1)
        animation = clip.get('animation', "none")
        
        # Map position to FFmpeg coordinates
        position_map = {
            "top-left": "x=10:y=10",
            "top-center": "x=(w-text_w)/2:y=10",
            "top-right": "x=w-text_w-10:y=10",
            "center": "x=(w-text_w)/2:y=(h-text_h)/2",
            "bottom-left": "x=10:y=h-text_h-10",
            "bottom-center": "x=(w-text_w)/2:y=h-text_h-10",
            "bottom-right": "x=w-text_w-10:y=h-text_h-10"
        }
        pos_str = position_map.get(position, "x=(w-text_w)/2:y=(h-text_h)/2")
        
        width, height = self.project_settings['resolution']
        fps = self.project_settings['fps']
        
        # Escape special characters
        text = text.replace(":", "\\:").replace("'", "\\\\'")
        
        # Base command
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", 
            "-i", f"color=size={width}x{height}:rate={fps}:color={bg_color}",
            "-t", str(duration), "-c:v", "libx264", 
            "-pix_fmt", "yuv420p", output_path
        ]
        
        # Generate text with effects using PIL
        temp_text_img = os.path.join(tempfile.gettempdir(), "text_overlay.png")
        self.create_text_image(text, font_size, font_color, bg_color, 
                             shadow, shadow_color, shadow_offset,
                             outline, outline_color, outline_width,
                             font_file, width, height, temp_text_img)
        
        # Overlay text image
        overlay_cmd = [
            "ffmpeg", "-y", "-i", output_path, "-i", temp_text_img,
            "-filter_complex", "[0:v][1:v]overlay=0:0",
            "-c:a", "copy", output_path
        ]
        
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(overlay_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Cleanup
        os.remove(temp_text_img)

    def create_text_image(self, text, font_size, font_color, bg_color, 
                         shadow, shadow_color, shadow_offset,
                         outline, outline_color, outline_width,
                         font_file, width, height, output_path):
        # Create image
        img = Image.new('RGBA', (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        
        # Load font
        try:
            if font_file and os.path.exists(font_file):
                font = ImageFont.truetype(font_file, font_size)
            else:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()
        
        # Calculate text size and position
        text_width, text_height = draw.textsize(text, font=font)
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        # Draw shadow
        if shadow:
            draw.text((x + shadow_offset, y + shadow_offset), text, 
                     fill=shadow_color, font=font)
        
        # Draw outline
        if outline and outline_width > 0:
            # Draw multiple times in all directions
            for dx in [-outline_width, 0, outline_width]:
                for dy in [-outline_width, 0, outline_width]:
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), text, 
                                 fill=outline_color, font=font)
        
        # Draw main text
        draw.text((x, y), text, fill=font_color, font=font)
        
        # Save image
        img.save(output_path)
        
    def process_sticker_clip(self, clip, output_path):
        duration = clip.get('duration', 5)
        width, height = self.project_settings['resolution']
        fps = self.project_settings['fps']
        
        # Create background
        bg_cmd = [
            "ffmpeg", "-y", "-f", "lavfi", 
            "-i", f"color=size={width}x{height}:rate={fps}:color=#00000000",
            "-t", str(duration), "-c:v", "libx264", 
            "-pix_fmt", "yuv420p", output_path
        ]
        subprocess.run(bg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Overlay sticker with transformations
        sticker_path = clip['path']
        x = clip.get('x', width // 2)
        y = clip.get('y', height // 2)
        scale = clip.get('scale', 1.0)
        rotation = clip.get('rotation', 0)
        opacity = clip.get('opacity', 1.0)
        
        # Apply transformations using FFmpeg
        overlay_cmd = [
            "ffmpeg", "-y", "-i", output_path, "-i", sticker_path,
            "-filter_complex", 
            f"[1]scale=iw*{scale}:-1,rotate={rotation}*PI/180:ow='rotw(iw,ih,{rotation})':oh='roth(iw,ih,{rotation})',colorchannelmixer=aa={opacity}[sticker];"
            f"[0][sticker]overlay={x}:{y}",
            "-c:a", "copy", output_path
        ]
        subprocess.run(overlay_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def process_transition_clip(self, clip, output_path):
        duration = clip.get('duration', 2)
        width, height = self.project_settings['resolution']
        fps = self.project_settings['fps']
        
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", 
            "-i", f"color=size={width}x{height}:rate={fps}:color=black",
            "-t", str(duration), "-c:v", "libx264", 
            "-pix_fmt", "yuv420p", output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def process_audio_clip(self, clip, output_path):
        start_time = clip.get('start_trim', 0)
        duration = clip.get('duration', 10)
        end_time = start_time + duration
        volume = clip.get('volume', 1.0)
        
        cmd = [
            "ffmpeg", "-y", "-ss", str(start_time), "-i", clip['path'],
            "-t", str(duration), "-af", f"volume={volume}",
            output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    def hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def cancel(self):
        self.canceled = True

class ExportProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exporting Video")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedSize(400, 150)
        
        layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.status_label = QLabel("Preparing export...")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_export)
        
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.cancel_button)
        self.setLayout(layout)
        
        self.worker = None
        self.thread = None
        
    def start_export(self, clips, project_settings, output_path):
        self.thread = QThread()
        self.worker = VideoExportWorker(clips, project_settings, output_path)
        self.worker.moveToThread(self.thread)
        
        self.thread.started.connect(self.worker.export)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.export_finished)
        self.worker.error.connect(self.export_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.thread.start()
        
    def update_progress(self, value):
        self.progress_bar.setValue(value)
        if value < 30:
            self.status_label.setText("Processing clips...")
        elif value < 70:
            self.status_label.setText("Applying effects...")
        else:
            self.status_label.setText("Finalizing export...")
    
    def export_finished(self, output_path):
        self.accept()
        QMessageBox.information(self, "Export Complete", 
                               f"Video successfully exported to:\n{output_path}")
    
    def export_error(self, error_msg):
        self.reject()
        QMessageBox.critical(self, "Export Error", 
                            f"An error occurred during export:\n{error_msg}")
    
    def cancel_export(self):
        if self.worker:
            self.worker.cancel()
        self.reject()

class TimelineClip(QGraphicsRectItem):
    def __init__(self, start, length, track, color=Qt.GlobalColor.blue, clip_type="video"):
        super().__init__(0, track * TRACK_HEIGHT, length * TIMELINE_SCALE, TRACK_HEIGHT - 5)
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.GlobalColor.black))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        
        self.start_time = start
        self.duration = length
        self.track = track
        self.clip_type = clip_type
        self.name = "Clip"
        self.clip_id = -1

        # Create label
        self.text_bg = QGraphicsRectItem(0, 0, length * TIMELINE_SCALE, 20, self)
        self.text_bg.setBrush(QColor(0, 0, 0, 180))
        self.text_bg.setPen(QPen(Qt.PenStyle.NoPen))
        
        self.label = QGraphicsPixmapItem(self.text_bg)
        self.update_label()
        
        # Create handles for resizing
        self.left_handle = QGraphicsRectItem(0, 0, 8, TRACK_HEIGHT - 5, self)
        self.left_handle.setBrush(QBrush(QColor(200, 200, 200, 200)))
        self.left_handle.setPen(QPen(Qt.PenStyle.NoPen))
        self.left_handle.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        
        self.right_handle = QGraphicsRectItem(length * TIMELINE_SCALE - 8, 0, 8, TRACK_HEIGHT - 5, self)
        self.right_handle.setBrush(QBrush(QColor(200, 200, 200, 200)))
        self.right_handle.setPen(QPen(Qt.PenStyle.NoPen))
        self.right_handle.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        
        # Hide handles by default
        self.left_handle.hide()
        self.right_handle.hide()
        
    def update_label(self):
        img = Image.new('RGBA', (200, 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((5, 0), self.name, fill=(255, 255, 255))
        qimg = QImage(img.tobytes(), img.width, img.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        self.label.setPixmap(pixmap)
        
    def show_handles(self, show=True):
        self.left_handle.setVisible(show)
        self.right_handle.setVisible(show)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicked on handle
            if self.left_handle.isVisible() and self.left_handle.contains(event.pos()):
                self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
                self.resizing = "left"
            elif self.right_handle.isVisible() and self.right_handle.contains(event.pos()):
                self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
                self.resizing = "right"
            else:
                self.resizing = None
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                super().mousePressEvent(event)
                
    def mouseMoveEvent(self, event):
        if self.resizing == "left":
            # Calculate new position and duration
            new_x = event.pos().x()
            new_duration = self.duration - (new_x / TIMELINE_SCALE)
            if new_duration > 0.1:  # Minimum duration
                self.duration = new_duration
                self.setRect(new_x, self.rect().y(), 
                            self.duration * TIMELINE_SCALE, self.rect().height())
                self.right_handle.setRect(self.duration * TIMELINE_SCALE - 8, 0, 8, TRACK_HEIGHT - 5)
                self.update_label()
        elif self.resizing == "right":
            new_width = event.pos().x()
            new_duration = new_width / TIMELINE_SCALE
            if new_duration > 0.1:  # Minimum duration
                self.duration = new_duration
                self.setRect(0, self.rect().y(), 
                            self.duration * TIMELINE_SCALE, self.rect().height())
                self.right_handle.setRect(self.duration * TIMELINE_SCALE - 8, 0, 8, TRACK_HEIGHT - 5)
                self.update_label()
        else:
            super().mouseMoveEvent(event)
            
    def mouseReleaseEvent(self, event):
        self.resizing = None
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)
        
    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionChange:
            # Snap to timeline grid
            new_pos = value
            new_pos.setX(round(new_pos.x() / (TIMELINE_SCALE / 5)) * (TIMELINE_SCALE / 5))
            new_pos.setY(self.track * TRACK_HEIGHT)
            return new_pos
            
        return super().itemChange(change, value)

class TimelineWidget(QGraphicsView):
    clip_selected = pyqtSignal(int)
    clip_moved = pyqtSignal(int, float, int)
    clip_resized = pyqtSignal(int, float)
    playhead_moved = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setMinimumHeight(300)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        
        self.clips = []
        self.current_time = 0
        self.time_indicator = None
        self.max_time = 60  # 60 seconds by default
        
        self.draw_timeline()
        
        # Context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
    def draw_timeline(self):
        self.scene.clear()
        self.clips = []
        
        # Draw timeline background
        self.scene.addRect(0, 0, self.max_time * TIMELINE_SCALE, MAX_TRACKS * TRACK_HEIGHT, 
                          brush=QBrush(QColor(40, 40, 40)))
        
        # Draw time markers
        for i in range(0, self.max_time + 1):
            x = i * TIMELINE_SCALE
            self.scene.addLine(x, 0, x, MAX_TRACKS * TRACK_HEIGHT, QPen(QColor(80, 80, 80)))
            if i % 5 == 0:
                time_text = self.scene.addText(str(i))
                time_text.setDefaultTextColor(QColor(200, 200, 200))
                time_text.setPos(x - 5, -20)
        
        # Draw track separators
        for i in range(1, MAX_TRACKS):
            self.scene.addLine(0, i * TRACK_HEIGHT, 
                              self.max_time * TIMELINE_SCALE, i * TRACK_HEIGHT, 
                              QPen(QColor(60, 60, 60)))
        
        # Add track labels
        track_names = [f"Video {i+1}" for i in range(5)] + [f"Audio {i+1}" for i in range(5)]
        for i, name in enumerate(track_names):
            label = self.scene.addText(name)
            label.setDefaultTextColor(QColor(200, 200, 200))
            label.setPos(-80, i * TRACK_HEIGHT + 15)
        
        # Add playhead
        self.time_indicator = self.scene.addLine(0, 0, 0, MAX_TRACKS * TRACK_HEIGHT, 
                                               QPen(QColor(255, 50, 50), 2))
        
    def add_clip(self, clip_id, start, duration, track=0, name="Clip", 
                clip_type="video", color=Qt.GlobalColor.blue):
        clip = TimelineClip(start, duration, track, color, clip_type)
        clip.clip_id = clip_id
        clip.name = name
        clip.update_label()
        self.scene.addItem(clip)
        self.clips.append(clip)
        return clip
    
    def remove_clip(self, clip_id):
        for clip in self.clips[:]:
            if clip.clip_id == clip_id:
                self.scene.removeItem(clip)
                self.clips.remove(clip)
                return True
        return False
    
    def get_clip(self, clip_id):
        for clip in self.clips:
            if clip.clip_id == clip_id:
                return clip
        return None
    
    def set_current_time(self, time):
        self.current_time = time
        if self.time_indicator:
            self.time_indicator.setLine(time * TIMELINE_SCALE, 0, 
                                      time * TIMELINE_SCALE, MAX_TRACKS * TRACK_HEIGHT)
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicked on timeline background
            pos = self.mapToScene(event.pos())
            if 0 <= pos.y() <= MAX_TRACKS * TRACK_HEIGHT:
                # Move playhead to clicked position
                time = max(0, min(pos.x() / TIMELINE_SCALE, self.max_time))
                self.set_current_time(time)
                self.playhead_moved.emit(time)
                
        super().mousePressEvent(event)
        
    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if item and isinstance(item, TimelineClip):
            self.clip_selected.emit(item.clip_id)
        super().mouseDoubleClickEvent(event)
        
    def show_context_menu(self, pos):
        scene_pos = self.mapToScene(pos)
        track = int(scene_pos.y() // TRACK_HEIGHT)
        
        menu = QMenu(self)
        
        # Add actions based on track
        if track < 5:  # Video tracks
            import_action = menu.addAction("Import Video")
            import_action.triggered.connect(lambda: self.parent().import_media(track))
            
            image_action = menu.addAction("Add Image")
            image_action.triggered.connect(lambda: self.parent().import_image(track))
            
            text_action = menu.addAction("Add Text")
            text_action.triggered.connect(lambda: self.parent().add_text(track))
            
            transition_action = menu.addAction("Add Transition")
            transition_action.triggered.connect(lambda: self.parent().add_transition(track))
            
            sticker_action = menu.addAction("Add Sticker")
            sticker_action.triggered.connect(lambda: self.parent().add_sticker(track))
            
            # Add split action only if a clip is selected
            selected_clip = None
            for item in self.scene.selectedItems():
                if isinstance(item, TimelineClip):
                    selected_clip = item
                    break
                    
            if selected_clip:
                split_action = menu.addAction("Split Clip")
                split_action.triggered.connect(lambda: self.parent().split_clip(selected_clip))
                
        else:  # Audio tracks
            audio_action = menu.addAction("Import Audio")
            audio_action.triggered.connect(lambda: self.parent().import_audio(track))
            
        menu.exec(self.mapToGlobal(pos))

class VideoPlayerWidget(QWidget):
    frame_changed = pyqtSignal(float)  # Signal to emit current time

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 450)
        self.setStyleSheet("background-color: #1e1e1e;")
        
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setStyleSheet("border: none;")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setLayout(layout)

        # Control bar
        control_frame = QFrame()
        control_frame.setStyleSheet("background-color: #2d2d30; padding: 5px;")
        control_layout = QHBoxLayout(control_frame)
        
        self.play_btn = QPushButton("Play")
        self.play_btn.setFixedSize(80, 32)
        self.play_btn.setStyleSheet("""
            QPushButton {
                border-radius: 4px; 
                background-color: #007acc;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0088e0;
            }
            QPushButton:pressed {
                background-color: #0066b3;
            }
        """)
        self.play_btn.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.play_btn)
        
        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(0, 100)
        self.time_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 6px;
                background: #333333;
                margin: 2px 0;
            }
            QSlider::handle:horizontal {
                background: #007acc;
                border: 1px solid #5c5c5c;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #007acc;
            }
        """)
        self.time_slider.sliderMoved.connect(self.seek_video)
        control_layout.addWidget(self.time_slider, 1)
        
        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.time_label.setStyleSheet("color: #cccccc;")
        control_layout.addWidget(self.time_label)
        
        layout.addWidget(control_frame)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.is_playing = False
        self.video_cap = None
        self.current_frame_num = 0
        self.total_frames = 0
        self.fps = 30
        self.video_loaded = False

    def load_video(self, file_path):
        if self.video_cap:
            self.video_cap.release()
            self.video_loaded = False

        self.video_cap = cv2.VideoCapture(file_path)
        if not self.video_cap.isOpened():
            return False

        self.total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.video_cap.get(cv2.CAP_PROP_FPS)
        if self.fps <= 0:
            self.fps = 30
            
        self.time_slider.setRange(0, self.total_frames)
        duration = self.total_frames / self.fps
        self.time_label.setText(f"00:00:00 / {self.format_time(duration)}")
        self.show_frame(0)
        self.video_loaded = True
        return True

    def show_frame(self, frame_num):
        if not self.video_cap or not self.video_loaded:
            return

        # Convert to integer frame number
        frame_num = int(frame_num)

        # Ensure frame number is within valid range
        if frame_num < 0:
            frame_num = 0
        elif frame_num >= self.total_frames:
            frame_num = self.total_frames - 1
            
        self.current_frame_num = frame_num
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = self.video_cap.read()
        if ret:
            # Convert to RGB for display
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)

            self.scene.clear()
            self.scene.addPixmap(pixmap)
            self.time_slider.setValue(frame_num)  # Now frame_num is integer
            current_time = frame_num / self.fps
            duration = self.total_frames / self.fps
            self.time_label.setText(f"{self.format_time(current_time)} / {self.format_time(duration)}")
            self.frame_changed.emit(current_time)

    def update_frame(self):
        if not self.video_cap or not self.video_loaded or not self.is_playing:
            return

        next_frame = self.current_frame_num + 1
        if next_frame >= self.total_frames:
            self.is_playing = False
            self.play_btn.setText("Play")
            self.timer.stop()
            return

        self.show_frame(next_frame)

    def toggle_play(self):
        if not self.video_cap or not self.video_loaded:
            return

        self.is_playing = not self.is_playing
        if self.is_playing:
            self.play_btn.setText("Pause")
            # Calculate interval in milliseconds as integer
            interval = max(1, int(1000 / self.fps))
            self.timer.start(interval)
        else:
            self.play_btn.setText("Play")
            self.timer.stop()

    def seek_video(self, position):
        # Position is integer from slider
        self.show_frame(position)

    def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

class TextClipDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Text Clip")
        self.setFixedSize(500, 500)
        
        tabs = QTabWidget()
        basic_tab = QWidget()
        style_tab = QWidget()
        animation_tab = QWidget()
        
        tabs.addTab(basic_tab, "Basic")
        tabs.addTab(style_tab, "Style")
        tabs.addTab(animation_tab, "Animation")
        
        # Basic tab
        basic_layout = QGridLayout(basic_tab)
        
        # Text input
        basic_layout.addWidget(QLabel("Text:"), 0, 0)
        self.text_input = QTextEdit("Your Text Here")
        self.text_input.setMinimumHeight(100)
        basic_layout.addWidget(self.text_input, 0, 1, 1, 2)
        
        # Font size
        basic_layout.addWidget(QLabel("Font Size:"), 1, 0)
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 200)
        self.font_size.setValue(48)
        basic_layout.addWidget(self.font_size, 1, 1)
        
        # Font file
        basic_layout.addWidget(QLabel("Font File:"), 2, 0)
        self.font_file = QLineEdit()
        font_btn = QPushButton("Browse...")
        font_btn.clicked.connect(self.browse_font)
        basic_layout.addWidget(self.font_file, 2, 1)
        basic_layout.addWidget(font_btn, 2, 2)
        
        # Position
        basic_layout.addWidget(QLabel("Position:"), 3, 0)
        self.position = QComboBox()
        self.position.addItems([
            "top-left", "top-center", "top-right",
            "center", 
            "bottom-left", "bottom-center", "bottom-right"
        ])
        self.position.setCurrentText("center")
        basic_layout.addWidget(self.position, 3, 1, 1, 2)
        
        # Duration
        basic_layout.addWidget(QLabel("Duration (s):"), 4, 0)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.1, 60)
        self.duration.setValue(5)
        self.duration.setSingleStep(0.5)
        basic_layout.addWidget(self.duration, 4, 1, 1, 2)
        
        # Style tab
        style_layout = QGridLayout(style_tab)
        
        # Font color
        style_layout.addWidget(QLabel("Font Color:"), 0, 0)
        self.font_color = QPushButton("#FFFFFF")
        self.font_color.clicked.connect(self.choose_font_color)
        self.font_color.setStyleSheet("background-color: #FFFFFF; color: #000000;")
        style_layout.addWidget(self.font_color, 0, 1)
        
        # Background color
        style_layout.addWidget(QLabel("Background:"), 1, 0)
        self.bg_color = QPushButton("Transparent")
        self.bg_color.clicked.connect(self.choose_bg_color)
        self.bg_color.setStyleSheet("background-color: #00000000; color: #FFFFFF;")
        style_layout.addWidget(self.bg_color, 1, 1)
        
        # Shadow
        self.shadow = QCheckBox("Shadow")
        style_layout.addWidget(self.shadow, 2, 0)
        
        style_layout.addWidget(QLabel("Shadow Color:"), 3, 0)
        self.shadow_color = QPushButton("#000000")
        self.shadow_color.clicked.connect(self.choose_shadow_color)
        self.shadow_color.setStyleSheet("background-color: #000000; color: #FFFFFF;")
        style_layout.addWidget(self.shadow_color, 3, 1)
        
        style_layout.addWidget(QLabel("Shadow Offset:"), 4, 0)
        self.shadow_offset = QSpinBox()
        self.shadow_offset.setRange(1, 20)
        self.shadow_offset.setValue(2)
        style_layout.addWidget(self.shadow_offset, 4, 1)
        
        # Outline
        self.outline = QCheckBox("Outline")
        style_layout.addWidget(self.outline, 5, 0)
        
        style_layout.addWidget(QLabel("Outline Color:"), 6, 0)
        self.outline_color = QPushButton("#000000")
        self.outline_color.clicked.connect(self.choose_outline_color)
        self.outline_color.setStyleSheet("background-color: #000000; color: #FFFFFF;")
        style_layout.addWidget(self.outline_color, 6, 1)
        
        style_layout.addWidget(QLabel("Outline Width:"), 7, 0)
        self.outline_width = QSpinBox()
        self.outline_width.setRange(1, 10)
        self.outline_width.setValue(1)
        style_layout.addWidget(self.outline_width, 7, 1)
        
        # Animation tab
        anim_layout = QGridLayout(animation_tab)
        
        anim_group = QButtonGroup(self)
        self.no_anim = QRadioButton("No Animation")
        self.fade_in = QRadioButton("Fade In")
        self.slide_in = QRadioButton("Slide In")
        self.zoom_in = QRadioButton("Zoom In")
        self.no_anim.setChecked(True)
        
        anim_layout.addWidget(self.no_anim, 0, 0)
        anim_layout.addWidget(self.fade_in, 1, 0)
        anim_layout.addWidget(self.slide_in, 2, 0)
        anim_layout.addWidget(self.zoom_in, 3, 0)
        
        anim_group.addButton(self.no_anim)
        anim_group.addButton(self.fade_in)
        anim_group.addButton(self.slide_in)
        anim_group.addButton(self.zoom_in)
        
        anim_layout.addWidget(QLabel("Duration (s):"), 4, 0)
        self.anim_duration = QDoubleSpinBox()
        self.anim_duration.setRange(0.1, 5)
        self.anim_duration.setValue(1)
        anim_layout.addWidget(self.anim_duration, 4, 1)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout = QVBoxLayout()
        layout.addWidget(tabs)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def browse_font(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Font File", "", "Font Files (*.ttf *.otf)"
        )
        if file_path:
            self.font_file.setText(file_path)
            
    def choose_font_color(self):
        color = QColorDialog.getColor(QColor(self.font_color.text()))
        if color.isValid():
            self.font_color.setText(color.name())
            self.font_color.setStyleSheet(f"background-color: {color.name()}; color: {'#000000' if color.lightness() > 127 else '#FFFFFF'};")
            
    def choose_bg_color(self):
        color = QColorDialog.getColor(QColor(0, 0, 0, 0), self, "Choose Background Color", 
                                     QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            if color.alpha() == 0:
                self.bg_color.setText("Transparent")
                self.bg_color.setStyleSheet("background-color: #00000000; color: #FFFFFF;")
            else:
                self.bg_color.setText(color.name())
                self.bg_color.setStyleSheet(f"background-color: {color.name()}; color: {'#000000' if color.lightness() > 127 else '#FFFFFF'};")
                
    def choose_shadow_color(self):
        color = QColorDialog.getColor(QColor(self.shadow_color.text()))
        if color.isValid():
            self.shadow_color.setText(color.name())
            self.shadow_color.setStyleSheet(f"background-color: {color.name()}; color: {'#000000' if color.lightness() > 127 else '#FFFFFF'};")
            
    def choose_outline_color(self):
        color = QColorDialog.getColor(QColor(self.outline_color.text()))
        if color.isValid():
            self.outline_color.setText(color.name())
            self.outline_color.setStyleSheet(f"background-color: {color.name()}; color: {'#000000' if color.lightness() > 127 else '#FFFFFF'};")
                
    def get_values(self):
        # Determine animation
        animation = "none"
        if self.fade_in.isChecked():
            animation = "fade_in"
        elif self.slide_in.isChecked():
            animation = "slide_in"
        elif self.zoom_in.isChecked():
            animation = "zoom_in"
            
        return {
            "text": self.text_input.toPlainText(),
            "font_size": self.font_size.value(),
            "font_file": self.font_file.text(),
            "font_color": self.font_color.text(),
            "bg_color": self.bg_color.text() if self.bg_color.text() != "Transparent" else "#00000000",
            "position": self.position.currentText(),
            "duration": self.duration.value(),
            "shadow": self.shadow.isChecked(),
            "shadow_color": self.shadow_color.text(),
            "shadow_offset": self.shadow_offset.value(),
            "outline": self.outline.isChecked(),
            "outline_color": self.outline_color.text(),
            "outline_width": self.outline_width.value(),
            "animation": animation,
            "anim_duration": self.anim_duration.value()
        }

class ChromaKeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Chroma Key Settings")
        self.setFixedSize(300, 300)
        
        layout = QGridLayout()
        
        # Color selection
        layout.addWidget(QLabel("Key Color:"), 0, 0)
        self.key_color = QPushButton("#00FF00")
        self.key_color.clicked.connect(self.choose_key_color)
        self.key_color.setStyleSheet("background-color: #00FF00;")
        layout.addWidget(self.key_color, 0, 1)
        
        # Similarity
        layout.addWidget(QLabel("Similarity:"), 1, 0)
        self.similarity = QDoubleSpinBox()
        self.similarity.setRange(0.01, 1.0)
        self.similarity.setValue(0.1)
        self.similarity.setSingleStep(0.01)
        layout.addWidget(self.similarity, 1, 1)
        
        # Blend
        layout.addWidget(QLabel("Blend:"), 2, 0)
        self.blend = QDoubleSpinBox()
        self.blend.setRange(0.0, 1.0)
        self.blend.setValue(0.1)
        self.blend.setSingleStep(0.05)
        layout.addWidget(self.blend, 2, 1)
        
        # Preview
        self.preview_btn = QPushButton("Preview Effect")
        layout.addWidget(self.preview_btn, 3, 0, 1, 2)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout, 4, 0, 1, 2)
        self.setLayout(layout)
        
    def choose_key_color(self):
        color = QColorDialog.getColor(QColor(self.key_color.text()))
        if color.isValid():
            self.key_color.setText(color.name())
            self.key_color.setStyleSheet(f"background-color: {color.name()};")
            
    def get_values(self):
        return {
            "chroma_color": self.key_color.text(),
            "chroma_similarity": self.similarity.value(),
            "chroma_blend": self.blend.value()
        }

class SpeedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Speed Adjustment")
        self.setFixedSize(300, 200)
        
        layout = QGridLayout()
        
        # Speed selection
        layout.addWidget(QLabel("Speed:"), 0, 0)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.1, 10.0)
        self.speed.setValue(1.0)
        self.speed.setSingleStep(0.1)
        layout.addWidget(self.speed, 0, 1)
        
        # Preview
        self.preview_btn = QPushButton("Preview Speed")
        layout.addWidget(self.preview_btn, 1, 0, 1, 2)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout, 2, 0, 1, 2)
        self.setLayout(layout)
        
    def get_values(self):
        return {
            "speed": self.speed.value()
        }

class StickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Sticker")
        self.setFixedSize(400, 400)
        
        layout = QGridLayout()
        
        # Sticker selection
        layout.addWidget(QLabel("Sticker:"), 0, 0)
        self.sticker_path = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_sticker)
        layout.addWidget(self.sticker_path, 0, 1)
        layout.addWidget(browse_btn, 0, 2)
        
        # Position
        layout.addWidget(QLabel("X Position:"), 1, 0)
        self.x_pos = QSpinBox()
        self.x_pos.setRange(0, 1920)
        self.x_pos.setValue(960)
        layout.addWidget(self.x_pos, 1, 1)
        
        layout.addWidget(QLabel("Y Position:"), 2, 0)
        self.y_pos = QSpinBox()
        self.y_pos.setRange(0, 1080)
        self.y_pos.setValue(540)
        layout.addWidget(self.y_pos, 2, 1)
        
        # Scale
        layout.addWidget(QLabel("Scale:"), 3, 0)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.1, 5.0)
        self.scale.setValue(1.0)
        self.scale.setSingleStep(0.1)
        layout.addWidget(self.scale, 3, 1)
        
        # Rotation
        layout.addWidget(QLabel("Rotation:"), 4, 0)
        self.rotation = QSpinBox()
        self.rotation.setRange(0, 360)
        self.rotation.setValue(0)
        layout.addWidget(self.rotation, 4, 1)
        
        # Opacity
        layout.addWidget(QLabel("Opacity:"), 5, 0)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.0, 1.0)
        self.opacity.setValue(1.0)
        self.opacity.setSingleStep(0.1)
        layout.addWidget(self.opacity, 5, 1)
        
        # Duration
        layout.addWidget(QLabel("Duration (s):"), 6, 0)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.1, 60)
        self.duration.setValue(5)
        self.duration.setSingleStep(0.5)
        layout.addWidget(self.duration, 6, 1)
        
        # Preview
        self.preview_btn = QPushButton("Preview Sticker")
        layout.addWidget(self.preview_btn, 7, 0, 1, 3)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout, 8, 0, 1, 3)
        self.setLayout(layout)
        
    def browse_sticker(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Sticker", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)"
        )
        if file_path:
            self.sticker_path.setText(file_path)
            
    def get_values(self):
        return {
            "path": self.sticker_path.text(),
            "x": self.x_pos.value(),
            "y": self.y_pos.value(),
            "scale": self.scale.value(),
            "rotation": self.rotation.value(),
            "opacity": self.opacity.value(),
            "duration": self.duration.value()
        }

class VideoEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{DEFAULT_PROJECT_NAME} - PyCut Pro")
        self.setGeometry(100, 50, 1400, 900)
        
        # Project state
        self.project_name = DEFAULT_PROJECT_NAME
        self.project_path = None
        self.project_settings = {
            "fps": DEFAULT_FPS,
            "resolution": DEFAULT_RESOLUTION,
            "background": "#000000"
        }
        self.clips = []  # List of clip dictionaries
        self.next_clip_id = 1
        self.undo_stack = []
        self.redo_stack = []
        self.selected_clip_id = -1
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create splitter for main content
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Video player
        self.video_player = VideoPlayerWidget()
        
        # Timeline
        self.timeline = TimelineWidget()
        self.timeline.clip_selected.connect(self.select_clip)
        self.timeline.playhead_moved.connect(self.video_player.seek_video)
        self.video_player.frame_changed.connect(self.timeline.set_current_time)
        
        main_splitter.addWidget(self.video_player)
        main_splitter.addWidget(self.timeline)
        main_splitter.setSizes([600, 300])
        
        main_layout.addWidget(main_splitter)
        
        # Create UI elements
        self.create_menubar()
        self.create_toolbar()
        self.create_effects_panel()
        self.create_media_library()
        
        # Status bar
        self.statusBar().showMessage("Ready")
        self.statusBar().addPermanentWidget(QLabel(f"FPS: {self.project_settings['fps']} | Resolution: {self.project_settings['resolution'][0]}x{self.project_settings['resolution'][1]}"))
        
        # Styling
        self.apply_styles()
        
    def create_menubar(self):
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_action = QAction("&New Project", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.new_project)
        file_menu.addAction(new_action)
        
        open_action = QAction("&Open Project", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_project)
        file_menu.addAction(open_action)
        
        save_action = QAction("&Save Project", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_project)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("Save Project &As...", self)
        save_as_action.triggered.connect(self.save_project_as)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        export_action = QAction("&Export Video", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_project)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        
        undo_action = QAction("&Undo", self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self.undo)
        edit_menu.addAction(undo_action)
        
        redo_action = QAction("&Redo", self)
        redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        redo_action.triggered.connect(self.redo)
        edit_menu.addAction(redo_action)
        
        edit_menu.addSeparator()
        
        split_action = QAction("&Split Clip", self)
        split_action.setShortcut("Ctrl+K")
        split_action.triggered.connect(self.split_selected_clip)
        edit_menu.addAction(split_action)
        
        edit_menu.addSeparator()
        
        cut_action = QAction("Cu&t", self)
        cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        edit_menu.addAction(cut_action)
        
        copy_action = QAction("&Copy", self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        edit_menu.addAction(copy_action)
        
        paste_action = QAction("&Paste", self)
        paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        edit_menu.addAction(paste_action)
        
        delete_action = QAction("&Delete", self)
        delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        delete_action.triggered.connect(self.delete_selected)
        edit_menu.addAction(delete_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        fullscreen_action = QAction("&Full Screen", self)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)
        
        # Project menu
        project_menu = menubar.addMenu("&Project")
        
        settings_action = QAction("Project &Settings", self)
        settings_action.triggered.connect(self.show_project_settings)
        project_menu.addAction(settings_action)
        
        # Effects menu
        effects_menu = menubar.addMenu("&Effects")
        
        chroma_key_action = QAction("Chroma Key", self)
        chroma_key_action.triggered.connect(self.apply_chroma_key)
        effects_menu.addAction(chroma_key_action)
        
        lut_action = QAction("Apply LUT", self)
        lut_action.triggered.connect(self.apply_lut)
        effects_menu.addAction(lut_action)
        
        speed_action = QAction("Speed Adjustment", self)
        speed_action.triggered.connect(self.adjust_speed)
        effects_menu.addAction(speed_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About PyCut Pro", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # New project
        new_action = QAction("New Project", self)
        new_action.triggered.connect(self.new_project)
        toolbar.addAction(new_action)
        
        # Open project
        open_action = QAction("Open Project", self)
        open_action.triggered.connect(self.open_project)
        toolbar.addAction(open_action)
        
        # Save project
        save_action = QAction("Save Project", self)
        save_action.triggered.connect(self.save_project)
        toolbar.addAction(save_action)
        
        toolbar.addSeparator()
        
        # Import media
        import_action = QAction("Import Media", self)
        import_action.triggered.connect(self.import_media)
        toolbar.addAction(import_action)
        
        # Import audio
        audio_action = QAction("Import Audio", self)
        audio_action.triggered.connect(self.import_audio)
        toolbar.addAction(audio_action)
        
        # Add text
        text_action = QAction("Add Text", self)
        text_action.triggered.connect(self.add_text)
        toolbar.addAction(text_action)
        
        # Add sticker
        sticker_action = QAction("Add Sticker", self)
        sticker_action.triggered.connect(self.add_sticker)
        toolbar.addAction(sticker_action)
        
        toolbar.addSeparator()
        
        # Split
        split_action = QAction("Split Clip", self)
        split_action.triggered.connect(self.split_selected_clip)
        toolbar.addAction(split_action)
        
        # Delete
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self.delete_selected)
        toolbar.addAction(delete_action)
        
        toolbar.addSeparator()
        
        # Undo
        undo_action = QAction("Undo", self)
        undo_action.triggered.connect(self.undo)
        toolbar.addAction(undo_action)
        
        # Redo
        redo_action = QAction("Redo", self)
        redo_action.triggered.connect(self.redo)
        toolbar.addAction(redo_action)
        
        toolbar.addSeparator()
        
        # Play/pause
        self.play_action = QAction("Play", self)
        self.play_action.triggered.connect(self.video_player.toggle_play)
        toolbar.addAction(self.play_action)
        
        # Export
        export_action = QAction("Export Video", self)
        export_action.triggered.connect(self.export_project)
        toolbar.addAction(export_action)
    
    def create_effects_panel(self):
        effect_dock = QDockWidget("Effects", self)
        effect_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | 
                               QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        effect_widget = QWidget()
        effect_layout = QVBoxLayout(effect_widget)
        
        # Effects group
        effects_group = QGroupBox("Video Effects")
        effects_layout = QGridLayout()
        
        # Fade in
        effects_layout.addWidget(QLabel("Fade In:"), 0, 0)
        self.fade_in = QDoubleSpinBox()
        self.fade_in.setRange(0, 10)
        self.fade_in.setValue(0)
        self.fade_in.setSingleStep(0.1)
        effects_layout.addWidget(self.fade_in, 0, 1)
        
        # Fade out
        effects_layout.addWidget(QLabel("Fade Out:"), 1, 0)
        self.fade_out = QDoubleSpinBox()
        self.fade_out.setRange(0, 10)
        self.fade_out.setValue(0)
        self.fade_out.setSingleStep(0.1)
        effects_layout.addWidget(self.fade_out, 1, 1)
        
        # Scale
        effects_layout.addWidget(QLabel("Scale:"), 2, 0)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.1, 3)
        self.scale.setValue(1)
        self.scale.setSingleStep(0.1)
        effects_layout.addWidget(self.scale, 2, 1)
        
        # Rotation
        effects_layout.addWidget(QLabel("Rotation:"), 3, 0)
        self.rotation = QSpinBox()
        self.rotation.setRange(-180, 180)
        self.rotation.setValue(0)
        self.rotation.setSingleStep(5)
        effects_layout.addWidget(self.rotation, 3, 1)
        
        # Opacity
        effects_layout.addWidget(QLabel("Opacity:"), 4, 0)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0, 1)
        self.opacity.setValue(1)
        self.opacity.setSingleStep(0.1)
        effects_layout.addWidget(self.opacity, 4, 1)
        
        # Black & white
        self.bw = QCheckBox("Black & White")
        effects_layout.addWidget(self.bw, 5, 0, 1, 2)
        
        # Blur
        effects_layout.addWidget(QLabel("Blur:"), 6, 0)
        self.blur = QSpinBox()
        self.blur.setRange(0, 10)
        self.blur.setValue(0)
        effects_layout.addWidget(self.blur, 6, 1)
        
        # Chroma key
        self.chroma_key = QCheckBox("Chroma Key")
        effects_layout.addWidget(self.chroma_key, 7, 0, 1, 2)
        
        # Apply button
        apply_btn = QPushButton("Apply to Selected")
        apply_btn.clicked.connect(self.apply_effects_to_selected)
        effects_layout.addWidget(apply_btn, 8, 0, 1, 2)
        
        effects_group.setLayout(effects_layout)
        effect_layout.addWidget(effects_group)
        
        # Keyframes group
        keyframe_group = QGroupBox("Keyframe Animation")
        keyframe_layout = QVBoxLayout()
        
        keyframe_layout.addWidget(QLabel("Position"))
        keyframe_layout.addWidget(QPushButton("Add Keyframe"))
        keyframe_layout.addWidget(QPushButton("Remove Keyframe"))
        
        keyframe_group.setLayout(keyframe_layout)
        effect_layout.addWidget(keyframe_group)
        
        effect_layout.addStretch()
        
        effect_dock.setWidget(effect_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, effect_dock)
    
    def create_media_library(self):
        media_dock = QDockWidget("Media Library", self)
        media_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | 
                              QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        media_widget = QWidget()
        media_layout = QVBoxLayout(media_widget)
        
        # Import buttons
        import_layout = QHBoxLayout()
        video_btn = QPushButton("Import Video")
        video_btn.clicked.connect(self.import_media)
        import_layout.addWidget(video_btn)
        
        audio_btn = QPushButton("Import Audio")
        audio_btn.clicked.connect(self.import_audio)
        import_layout.addWidget(audio_btn)
        
        image_btn = QPushButton("Import Image")
        image_btn.clicked.connect(self.import_image)
        import_layout.addWidget(image_btn)
        
        sticker_btn = QPushButton("Add Stickers")
        sticker_btn.clicked.connect(self.add_sticker)
        import_layout.addWidget(sticker_btn)
        
        media_layout.addLayout(import_layout)
        
        # Media list
        self.media_list = QListWidget()
        self.media_list.setIconSize(QSize(64, 36))
        self.media_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.media_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.media_list.setMovement(QListWidget.Movement.Static)
        
        media_layout.addWidget(self.media_list)
        
        media_dock.setWidget(media_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, media_dock)
    
    def apply_styles(self):
        # Set application style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2d2d30;
            }
            QWidget {
                background-color: #2d2d30;
                color: #d0d0d0;
                font-family: Segoe UI, Arial;
                font-size: 10pt;
            }
            QToolBar {
                background-color: #333337;
                border: none;
                padding: 3px;
            }
            QToolButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 3px;
            }
            QToolButton:hover {
                background-color: #3e3e40;
                border: 1px solid #3e3e40;
            }
            QToolButton:pressed {
                background-color: #007acc;
            }
            QDockWidget {
                titlebar-close-icon: url(close.png);
                titlebar-normal-icon: url(undock.png);
            }
            QDockWidget::title {
                background-color: #333337;
                padding: 4px;
                text-align: center;
            }
            QGroupBox {
                border: 1px solid #3f3f46;
                border-radius: 4px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
            }
            QListWidget {
                background-color: #252526;
                border: 1px solid #3f3f46;
                border-radius: 4px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #333337;
                border: 1px solid #3f3f46;
                border-radius: 3px;
                padding: 3px;
            }
            QPushButton {
                background-color: #333337;
                border: 1px solid #3f3f46;
                border-radius: 3px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #3e3e40;
                border: 1px solid #3e3e40;
            }
            QPushButton:pressed {
                background-color: #007acc;
            }
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 6px;
                background: #333333;
                margin: 2px 0;
            }
            QSlider::handle:horizontal {
                background: #007acc;
                border: 1px solid #5c5c5c;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #007acc;
            }
        """)
    
    def new_project(self):
        if self.check_unsaved_changes():
            self.project_name = DEFAULT_PROJECT_NAME
            self.project_path = None
            self.clips = []
            self.next_clip_id = 1
            self.timeline.draw_timeline()
            self.media_list.clear()
            self.setWindowTitle(f"{self.project_name} - PyCut Pro")
            self.statusBar().showMessage("New project created")
    
    def open_project(self):
        if self.check_unsaved_changes():
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Open Project", "", "PyCut Projects (*.pcp)"
            )
            if file_path:
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                    
                    self.project_name = data.get('name', DEFAULT_PROJECT_NAME)
                    self.project_path = file_path
                    self.project_settings = data.get('settings', {
                        "fps": DEFAULT_FPS,
                        "resolution": DEFAULT_RESOLUTION,
                        "background": "#000000"
                    })
                    self.clips = data.get('clips', [])
                    self.next_clip_id = data.get('next_clip_id', 1)
                    
                    # Rebuild timeline
                    self.timeline.draw_timeline()
                    for clip in self.clips:
                        color = self.get_clip_color(clip['type'])
                        timeline_clip = self.timeline.add_clip(
                            clip['id'], clip['start'], clip['duration'], 
                            clip['track'], clip.get('name', 'Clip'), 
                            clip['type'], color
                        )
                        timeline_clip.clip_id = clip['id']
                    
                    # Rebuild media library
                    self.media_list.clear()
                    media_paths = set()
                    for clip in self.clips:
                        if clip['type'] in ['video', 'image', 'audio', 'sticker']:
                            media_paths.add(clip['path'])
                    
                    for path in media_paths:
                        self.add_media_to_library(path)
                    
                    self.setWindowTitle(f"{self.project_name} - PyCut Pro")
                    self.statusBar().showMessage(f"Project loaded: {os.path.basename(file_path)}")
                    
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to open project:\n{str(e)}")
    
    def save_project(self):
        if self.project_path:
            self.do_save_project(self.project_path)
        else:
            self.save_project_as()
    
    def save_project_as(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", self.project_name, "PyCut Projects (*.pcp)"
        )
        if file_path:
            if not file_path.endswith(".pcp"):
                file_path += ".pcp"
            self.project_path = file_path
            self.project_name = os.path.basename(file_path).replace('.pcp', '')
            self.do_save_project(file_path)
    
    def do_save_project(self, file_path):
        try:
            data = {
                'name': self.project_name,
                'settings': self.project_settings,
                'clips': self.clips,
                'next_clip_id': self.next_clip_id
            }
            
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            self.setWindowTitle(f"{self.project_name} - PyCut Pro")
            self.statusBar().showMessage(f"Project saved: {os.path.basename(file_path)}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save project:\n{str(e)}")
            return False
    
    def check_unsaved_changes(self):
        # For simplicity, always return True
        return True
    
    def export_project(self):
        if not self.clips:
            QMessageBox.warning(self, "Export", "No clips to export")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Video", self.project_name, "MP4 Files (*.mp4)"
        )
        if file_path:
            dialog = ExportProgressDialog(self)
            dialog.start_export(self.clips, self.project_settings, file_path)
            dialog.exec()
    
    def import_media(self, track=0):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Media", "", 
            f"Media Files ({' '.join(['*.' + f for f in SUPPORTED_VIDEO_FORMATS])})"
        )
        if file_path:
            self.add_video_clip(file_path, track)
    
    def import_audio(self, track=5):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Audio", "", 
            f"Audio Files ({' '.join(['*.' + f for f in SUPPORTED_AUDIO_FORMATS])})"
        )
        if file_path:
            self.add_audio_clip(file_path, track)
    
    def import_image(self, track=0):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Image", "", 
            f"Image Files ({' '.join(['*.' + f for f in SUPPORTED_IMAGE_FORMATS])})"
        )
        if file_path:
            self.add_image_clip(file_path, track)
    
    def add_text(self, track=1):
        dialog = TextClipDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.get_values()
            clip_id = self.next_clip_id
            self.next_clip_id += 1
            
            clip_data = {
                'id': clip_id,
                'type': 'text',
                'track': track,
                'start': self.timeline.current_time,
                'duration': values['duration'],
                'name': "Text: " + values['text'][:20],
                'text': values['text'],
                'font_size': values['font_size'],
                'font_file': values['font_file'],
                'font_color': values['font_color'],
                'bg_color': values['bg_color'],
                'position': values['position'],
                'shadow': values['shadow'],
                'shadow_color': values['shadow_color'],
                'shadow_offset': values['shadow_offset'],
                'outline': values['outline'],
                'outline_color': values['outline_color'],
                'outline_width': values['outline_width'],
                'animation': values['animation'],
                'anim_duration': values['anim_duration']
            }
            
            self.clips.append(clip_data)
            timeline_clip = self.timeline.add_clip(
                clip_id, clip_data['start'], clip_data['duration'], 
                track, clip_data['name'], 'text', Qt.GlobalColor.green
            )
            timeline_clip.clip_id = clip_id
            
            self.add_media_to_library("Text: " + values['text'][:20], is_text=True)
    
    def add_sticker(self, track=0):
        dialog = StickerDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.get_values()
            clip_id = self.next_clip_id
            self.next_clip_id += 1
            
            sticker_name = os.path.basename(values['path'])
            clip_data = {
                'id': clip_id,
                'type': 'sticker',
                'track': track,
                'start': self.timeline.current_time,
                'duration': values['duration'],
                'name': f"Sticker: {sticker_name}",
                'path': values['path'],
                'x': values['x'],
                'y': values['y'],
                'scale': values['scale'],
                'rotation': values['rotation'],
                'opacity': values['opacity']
            }
            
            self.clips.append(clip_data)
            timeline_clip = self.timeline.add_clip(
                clip_id, clip_data['start'], clip_data['duration'], 
                track, clip_data['name'], 'sticker', Qt.GlobalColor.yellow
            )
            timeline_clip.clip_id = clip_id
            
            self.add_media_to_library(values['path'])
            self.statusBar().showMessage(f"Sticker added: {sticker_name}")
    
    def add_transition(self, track=0):
        clip_id = self.next_clip_id
        self.next_clip_id += 1
        
        clip_data = {
            'id': clip_id,
            'type': 'transition',
            'track': track,
            'start': self.timeline.current_time,
            'duration': 2,
            'name': "Fade Transition"
        }
        
        self.clips.append(clip_data)
        timeline_clip = self.timeline.add_clip(
            clip_id, clip_data['start'], clip_data['duration'], 
            track, clip_data['name'], 'transition', Qt.GlobalColor.cyan
        )
        timeline_clip.clip_id = clip_id
        self.statusBar().showMessage("Fade transition added")
    
    def add_video_clip(self, file_path, track=0):
        try:
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                self.statusBar().showMessage("Error loading video")
                return
                
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = frame_count / fps if fps > 0 else 0
            cap.release()
            
            clip_id = self.next_clip_id
            self.next_clip_id += 1
            
            clip_name = os.path.basename(file_path)
            clip_data = {
                'id': clip_id,
                'type': 'video',
                'track': track,
                'start': self.timeline.current_time,
                'duration': duration,
                'name': clip_name,
                'path': file_path,
                'start_trim': 0
            }
            
            self.clips.append(clip_data)
            timeline_clip = self.timeline.add_clip(
                clip_id, clip_data['start'], clip_data['duration'], 
                track, clip_name, 'video', Qt.GlobalColor.blue
            )
            timeline_clip.clip_id = clip_id
            
            self.add_media_to_library(file_path)
            self.statusBar().showMessage(f"Loaded: {clip_name}")
            
            # Load the video in the player
            if not self.video_player.load_video(file_path):
                self.statusBar().showMessage(f"Failed to load video: {clip_name}")
                
        except Exception as e:
            self.statusBar().showMessage(f"Error: {str(e)}")
    
    def add_audio_clip(self, file_path, track=5):
        try:
            # Use ffprobe to get audio duration
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", 
                "format=duration", "-of", 
                "default=noprint_wrappers=1:nokey=1", file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            duration = float(result.stdout.strip())
            
            clip_id = self.next_clip_id
            self.next_clip_id += 1
            
            clip_name = os.path.basename(file_path)
            clip_data = {
                'id': clip_id,
                'type': 'audio',
                'track': track,
                'start': self.timeline.current_time,
                'duration': duration,
                'name': clip_name,
                'path': file_path,
                'volume': 1.0
            }
            
            self.clips.append(clip_data)
            timeline_clip = self.timeline.add_clip(
                clip_id, clip_data['start'], clip_data['duration'], 
                track, clip_name, 'audio', Qt.GlobalColor.magenta
            )
            timeline_clip.clip_id = clip_id
            
            self.add_media_to_library(file_path)
            self.statusBar().showMessage(f"Loaded: {clip_name}")
                
        except Exception as e:
            self.statusBar().showMessage(f"Error: {str(e)}")
    
    def add_image_clip(self, file_path, track=0):
        clip_id = self.next_clip_id
        self.next_clip_id += 1
        
        clip_name = os.path.basename(file_path)
        clip_data = {
            'id': clip_id,
            'type': 'image',
            'track': track,
            'start': self.timeline.current_time,
            'duration': 5,  # Default duration for images
            'name': clip_name,
            'path': file_path
        }
        
        self.clips.append(clip_data)
        timeline_clip = self.timeline.add_clip(
            clip_id, clip_data['start'], clip_data['duration'], 
            track, clip_name, 'image', Qt.GlobalColor.cyan
        )
        timeline_clip.clip_id = clip_id
        
        self.add_media_to_library(file_path)
        self.statusBar().showMessage(f"Loaded: {clip_name}")
    
    def add_media_to_library(self, path, is_text=False):
        item = QListWidgetItem()
        
        if is_text:
            item.setText(path)
        else:
            # Determine media type
            ext = os.path.splitext(path)[1].lower()[1:]
            if ext in SUPPORTED_VIDEO_FORMATS:
                # Try to get thumbnail
                cap = cv2.VideoCapture(path)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                    if ret:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        height, width, _ = frame.shape
                        bytes_per_line = 3 * width
                        q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
                        pixmap = QPixmap.fromImage(q_img).scaled(64, 36, Qt.AspectRatioMode.KeepAspectRatio)
                        item.setIcon(QIcon(pixmap))
                    cap.release()
                item.setText(os.path.basename(path))
            elif ext in SUPPORTED_AUDIO_FORMATS:
                item.setText(os.path.basename(path))
            elif ext in SUPPORTED_IMAGE_FORMATS:
                # Load image thumbnail
                pixmap = QPixmap(path).scaled(64, 36, Qt.AspectRatioMode.KeepAspectRatio)
                item.setIcon(QIcon(pixmap))
                item.setText(os.path.basename(path))
        
        self.media_list.addItem(item)
    
    def select_clip(self, clip_id):
        self.selected_clip_id = clip_id
        for clip in self.clips:
            if clip['id'] == clip_id:
                # Update effects panel with clip properties
                self.fade_in.setValue(clip.get('fade_in', 0))
                self.fade_out.setValue(clip.get('fade_out', 0))
                self.scale.setValue(clip.get('scale', 1))
                self.rotation.setValue(clip.get('rotation', 0))
                self.opacity.setValue(clip.get('opacity', 1))
                self.bw.setChecked(clip.get('bw', False))
                self.blur.setValue(clip.get('blur', 0))
                self.chroma_key.setChecked(clip.get('chroma_key', False))
                break
    
    def apply_effects_to_selected(self):
        if self.selected_clip_id == -1:
            self.statusBar().showMessage("No clip selected")
            return
            
        for clip in self.clips:
            if clip['id'] == self.selected_clip_id:
                clip['fade_in'] = self.fade_in.value()
                clip['fade_out'] = self.fade_out.value()
                clip['scale'] = self.scale.value()
                clip['rotation'] = self.rotation.value()
                clip['opacity'] = self.opacity.value()
                clip['bw'] = self.bw.isChecked()
                clip['blur'] = self.blur.value()
                clip['chroma_key'] = self.chroma_key.isChecked()
                self.statusBar().showMessage("Effects applied to selected clip")
                break
    
    def apply_chroma_key(self):
        if self.selected_clip_id == -1:
            self.statusBar().showMessage("Select a video clip first")
            return
            
        dialog = ChromaKeyDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.get_values()
            for clip in self.clips:
                if clip['id'] == self.selected_clip_id:
                    clip['chroma_key'] = True
                    clip['chroma_color'] = values['chroma_color']
                    clip['chroma_similarity'] = values['chroma_similarity']
                    clip['chroma_blend'] = values['chroma_blend']
                    self.statusBar().showMessage("Chroma key effect applied")
                    break
    
    def apply_lut(self):
        if self.selected_clip_id == -1:
            self.statusBar().showMessage("Select a video clip first")
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select LUT File", "", "LUT Files (*.cube *.3dl)"
        )
        if file_path:
            for clip in self.clips:
                if clip['id'] == self.selected_clip_id:
                    clip['lut'] = file_path
                    self.statusBar().showMessage(f"LUT applied: {os.path.basename(file_path)}")
                    break
    
    def adjust_speed(self):
        if self.selected_clip_id == -1:
            self.statusBar().showMessage("Select a video clip first")
            return
            
        dialog = SpeedDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.get_values()
            for clip in self.clips:
                if clip['id'] == self.selected_clip_id:
                    clip['speed'] = values['speed']
                    self.statusBar().showMessage(f"Speed adjusted to {values['speed']}x")
                    break
    
    def delete_selected(self):
        if self.selected_clip_id == -1:
            self.statusBar().showMessage("No clip selected")
            return
                
        # Remove from timeline
        self.timeline.remove_clip(self.selected_clip_id)
                
        # Remove from clips list
        for i, clip in enumerate(self.clips):
            if clip['id'] == self.selected_clip_id:
                del self.clips[i]
                self.selected_clip_id = -1
                self.statusBar().showMessage("Clip deleted")
                break
    
    def split_selected_clip(self):
        if self.selected_clip_id == -1:
            self.statusBar().showMessage("Select a clip first")
            return
            
        for clip in self.clips:
            if clip['id'] == self.selected_clip_id:
                if clip['type'] not in ['video', 'audio']:
                    self.statusBar().showMessage("Only video and audio clips can be split")
                    return
                    
                current_time = self.timeline.current_time
                clip_time = current_time - clip['start']
                
                if clip_time <= 0 or clip_time >= clip['duration']:
                    self.statusBar().showMessage("Playhead must be within the clip")
                    return
                    
                # Create new clip for the second part
                new_clip_id = self.next_clip_id
                self.next_clip_id += 1
                
                new_clip = clip.copy()
                new_clip['id'] = new_clip_id
                new_clip['start'] = current_time
                new_clip['duration'] = clip['duration'] - clip_time
                new_clip['start_trim'] = clip.get('start_trim', 0) + clip_time
                
                # Update original clip
                clip['duration'] = clip_time
                
                # Update timeline
                timeline_clip = self.timeline.get_clip(clip['id'])
                if timeline_clip:
                    timeline_clip.duration = clip_time
                    timeline_clip.update_label()
                    
                # Add new clip to timeline
                color = self.get_clip_color(new_clip['type'])
                new_timeline_clip = self.timeline.add_clip(
                    new_clip_id, new_clip['start'], new_clip['duration'], 
                    new_clip['track'], new_clip['name'], new_clip['type'], color
                )
                new_timeline_clip.clip_id = new_clip_id
                
                # Add to clips list
                self.clips.append(new_clip)
                
                self.statusBar().showMessage("Clip split at playhead position")
                break
    
    def undo(self):
        if self.undo_stack:
            state = self.undo_stack.pop()
            self.redo_stack.append({
                'clips': self.clips,
                'next_clip_id': self.next_clip_id
            })
            self.clips = state['clips']
            self.next_clip_id = state['next_clip_id']
            self.rebuild_timeline()
            self.statusBar().showMessage("Undo")
    
    def redo(self):
        if self.redo_stack:
            state = self.redo_stack.pop()
            self.undo_stack.append({
                'clips': self.clips,
                'next_clip_id': self.next_clip_id
            })
            self.clips = state['clips']
            self.next_clip_id = state['next_clip_id']
            self.rebuild_timeline()
            self.statusBar().showMessage("Redo")
    
    def rebuild_timeline(self):
        self.timeline.draw_timeline()
        for clip in self.clips:
            color = self.get_clip_color(clip['type'])
            timeline_clip = self.timeline.add_clip(
                clip['id'], clip['start'], clip['duration'], 
                clip['track'], clip.get('name', 'Clip'), 
                clip['type'], color
            )
            timeline_clip.clip_id = clip['id']
    
    def get_clip_color(self, clip_type):
        colors = {
            'video': Qt.GlobalColor.blue,
            'image': Qt.GlobalColor.cyan,
            'text': Qt.GlobalColor.green,
            'transition': Qt.GlobalColor.cyan,
            'audio': Qt.GlobalColor.magenta,
            'sticker': Qt.GlobalColor.yellow
        }
        return colors.get(clip_type, Qt.GlobalColor.gray)
    
    def show_project_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Project Settings")
        dialog.setFixedSize(400, 300)
        
        layout = QGridLayout()
        
        # Project name
        layout.addWidget(QLabel("Project Name:"), 0, 0)
        name_edit = QLineEdit(self.project_name)
        layout.addWidget(name_edit, 0, 1)
        
        # FPS
        layout.addWidget(QLabel("Framerate (FPS):"), 1, 0)
        fps_spin = QSpinBox()
        fps_spin.setRange(1, 120)
        fps_spin.setValue(self.project_settings['fps'])
        layout.addWidget(fps_spin, 1, 1)
        
        # Resolution
        layout.addWidget(QLabel("Resolution:"), 2, 0)
        res_layout = QHBoxLayout()
        width_spin = QSpinBox()
        width_spin.setRange(320, 7680)
        width_spin.setValue(self.project_settings['resolution'][0])
        res_layout.addWidget(width_spin)
        res_layout.addWidget(QLabel("x"))
        height_spin = QSpinBox()
        height_spin.setRange(240, 4320)
        height_spin.setValue(self.project_settings['resolution'][1])
        res_layout.addWidget(height_spin)
        layout.addLayout(res_layout, 2, 1)
        
        # Background color
        layout.addWidget(QLabel("Background:"), 3, 0)
        bg_button = QPushButton(self.project_settings['background'])
        bg_button.setStyleSheet(f"background-color: {self.project_settings['background']};")
        bg_button.clicked.connect(lambda: self.choose_background_color(bg_button))
        layout.addWidget(bg_button, 3, 1)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(lambda: self.apply_project_settings(
            dialog, name_edit.text(), fps_spin.value(), 
            (width_spin.value(), height_spin.value()), bg_button.text()
        ))
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout, 4, 0, 1, 2)
        dialog.setLayout(layout)
        dialog.exec()
    
    def choose_background_color(self, button):
        color = QColorDialog.getColor(QColor(button.text()), self, "Choose Background Color", 
                                     QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            button.setText(color.name())
            button.setStyleSheet(f"background-color: {color.name()};")
    
    def apply_project_settings(self, dialog, name, fps, resolution, background):
        self.project_name = name
        self.project_settings = {
            'fps': fps,
            'resolution': resolution,
            'background': background
        }
        self.setWindowTitle(f"{self.project_name} - PyCut Pro")
        dialog.accept()
    
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
    
    def show_about(self):
        QMessageBox.about(self, "About PyCut Pro", 
                         "PyCut Pro - Professional Video Editor\n\n"
                         "Version 1.0\n"
                         "© 2023 PyCut Software\n\n"
                         "A powerful video editing solution built with Python and PyQt6")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    
    # Create dark palette
    dark_palette = app.palette()
    dark_palette.setColor(dark_palette.ColorRole.Window, QColor(45, 45, 48))
    dark_palette.setColor(dark_palette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(dark_palette.ColorRole.Base, QColor(30, 30, 30))
    dark_palette.setColor(dark_palette.ColorRole.AlternateBase, QColor(45, 45, 48))
    dark_palette.setColor(dark_palette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(dark_palette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(dark_palette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(dark_palette.ColorRole.Button, QColor(60, 60, 60))
    dark_palette.setColor(dark_palette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(dark_palette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(dark_palette.ColorRole.Highlight, QColor(0, 122, 204))
    dark_palette.setColor(dark_palette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    
    app.setPalette(dark_palette)
    
    # Set style
    app.setStyleSheet("""
        QMessageBox {
            background-color: #2d2d30;
        }
        QMessageBox QLabel {
            color: #d0d0d0;
        }
    """)
    
    # Create and show editor
    editor = VideoEditor()
    editor.show()
    
    # Check if FFmpeg is available
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except:
        QMessageBox.critical(None, "FFmpeg Not Found", 
                            "FFmpeg is required for video processing. Please install FFmpeg and add it to your PATH.")
        sys.exit(1)
    
    sys.exit(app.exec())