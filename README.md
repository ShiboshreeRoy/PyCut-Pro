# PyCut Pro - Professional Video Editor

PyCut Pro is a powerful, open-source video editor built with Python and PyQt6 that provides professional-grade video editing capabilities. This application offers a comprehensive suite of tools for creating and editing videos with an intuitive interface.

## Features

- **Timeline-based editing** with multiple video and audio tracks
- **Media library** for organizing video, audio, and image assets
- **Video effects** including fade in/out, scaling, rotation, opacity adjustment
- **Chroma key (green screen)** functionality
- **Text overlays** with customizable fonts, colors, and animations
- **Sticker support** with positioning, scaling, and rotation
- **Speed adjustment** for clips
- **Export functionality** to MP4 format
- **Project saving/loading** in custom format
- **Undo/Redo** functionality

## Technical Highlights

- Built with Python 3 and PyQt6 for the GUI
- Uses OpenCV for video processing and preview
- Leverages FFmpeg for video encoding/decoding
- Implements PIL (Pillow) for image/text manipulation
- JSON-based project file format
- Custom timeline widget with drag-and-drop support
- Video player with playback controls

## Installation

### Prerequisites
- Python 3.7+
- FFmpeg installed and added to PATH

### Dependencies
Install required packages:
```bash
pip install opencv-python numpy pillow pyqt6
```

### Running the Application
```bash
python pycut_pro.py
```

## Usage

1. **Create a new project** or open an existing one
2. **Import media** (videos, images, audio) through the media library
3. **Drag media to the timeline** on appropriate tracks
4. **Apply effects** using the effects panel
5. **Preview your project** in the video player
6. **Export your final video** when ready

## Known Limitations

- Limited to MP4 export format
- Basic transitions only (fade)
- No keyframe animation support
- Limited audio mixing capabilities
- Performance may degrade with large projects

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Screenshot

![PyCut Pro Interface](screenshot.png)

---

**Note**: This is a simplified video editor for educational purposes. For professional video editing, consider using dedicated software like DaVinci Resolve or Adobe Premiere Pro.