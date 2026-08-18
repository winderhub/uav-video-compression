# FFmpeg 打包组件

仓库不直接提交 FFmpeg 二进制文件。打包脚本会调用
`packaging/fetch_ffmpeg.py` 自动下载固定版本并校验 SHA-256，也可以手工按
以下结构放置：

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
- 每个平台目录还会包含上游的 GPL 许可证和构建说明，并随应用一起分发。
- Windows 7 目录中的二进制必须在 Windows 7 SP1 x64 实机或虚拟机验证。
- macOS 二进制架构必须与目录名一致。
- 发布安装包时必须同时提供 FFmpeg/libx264 对应的许可证文本和源代码获取方式，履行 GPL 要求。
- 不要从来源不明的网站下载二进制文件。
