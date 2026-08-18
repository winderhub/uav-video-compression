# FFmpeg 打包组件

仓库不直接提交 FFmpeg 二进制文件。构建前按目标平台放置：

~~~text
packaging/vendor/
├── windows-x64-modern/
│   ├── ffmpeg.exe
│   └── ffprobe.exe
├── windows-x64-win7/
│   ├── ffmpeg.exe
│   └── ffprobe.exe
├── macos-x86_64/
│   ├── ffmpeg
│   └── ffprobe
└── macos-arm64/
    ├── ffmpeg
    └── ffprobe
~~~

要求：

- 必须包含 `libx264` 编码器。
- Windows 7 目录中的二进制必须在 Windows 7 SP1 x64 实机或虚拟机验证。
- macOS 二进制架构必须与目录名一致。
- 发布安装包时必须同时提供 FFmpeg/libx264 对应的许可证文本和源代码获取方式，履行 GPL 要求。
- 不要从来源不明的网站下载二进制文件。
