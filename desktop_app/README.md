# 桌面应用源码

这里保存 Python/Tkinter 桌面应用。普通用户无需运行源码，请从项目 [Releases](https://github.com/winderhub/uav-video-compression/releases/latest) 下载安装包，并阅读[桌面应用使用指南](../docs/desktop-user-guide.md)。

源码运行要求 Python 3.8+、Tkinter、FFmpeg 和 FFprobe：

```bash
python desktop_app/main.py
```

无界面诊断：

```bash
python desktop_app/main.py --diagnose
```

可用环境变量覆盖 FFmpeg 路径：

```text
VIDEO_COMPRESSOR_FFMPEG
VIDEO_COMPRESSOR_FFPROBE
```

构建发布产物请阅读[安装包构建与发布](../docs/building-installers.md)。
