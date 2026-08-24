# 航拍视频压缩工具

面向航拍视频的批量压缩工具。普通用户可以安装 Windows/macOS 桌面应用，服务器管理员可以继续使用 Linux Bash 脚本处理大批量视频。

## 下载桌面应用

[前往 Releases 下载最新版本](https://github.com/winderhub/uav-video-compression/releases/latest)

| 系统 | 下载文件 |
|---|---|
| Windows 10/11 64 位 | `AerialVideoCompressor-<版本>-Windows-x64-Setup.exe` |
| Intel Mac | `AerialVideoCompressor-<版本>-macOS-x86_64.dmg` |
| Apple Silicon Mac | `AerialVideoCompressor-<版本>-macOS-arm64.dmg` |

下载后不需要另行安装 FFmpeg。当前安装包没有商业代码签名，Windows SmartScreen 或 macOS Gatekeeper 可能显示安全提醒。内部试用方法见[桌面应用使用指南](docs/desktop-user-guide.md)。

## 选择适合你的入口

### 桌面用户

从 Releases 下载对应安装包，选择视频目录后即可扫描和压缩。应用支持中断续跑、空间检查、压缩后校验和安全替换。

[查看桌面应用使用指南](docs/desktop-user-guide.md)

### Linux 服务器管理员

服务器脚本支持输出到独立目录、原位替换、压缩报告、运行指标和夜间调度。

[查看 Linux 服务器使用指南](docs/server-guide.md)

## 重要的数据安全说明

- 压缩方式为高质量有损压缩，不是无损压缩。
- 只保留第一路视频流，不保留音频、DJI 私有数据流和其他附加视频流。
- 第一次处理真实数据时，优先输出到独立目录并抽样检查。
- 使用原位替换前，确认数据已有备份或可以重新获取。
- 不要对同一个源目录同时启动多个压缩任务。

固定编码参数为 `libx264`、`preset fast`、`CRF 18`、`yuv420p` 和 `+faststart`，不主动改变分辨率或帧率。

## 仓库导航

| 目录 | 内容 |
|---|---|
| [`desktop_app/`](desktop_app/) | 桌面应用源码 |
| [`compression/`](compression/) | Linux 批量压缩脚本 |
| [`scheduling/`](scheduling/) | Linux 夜间调度脚本 |
| [`tools/`](tools/) | Linux 运行指标工具 |
| [`packaging/`](packaging/) | Windows/macOS 打包脚本 |
| [`tests/`](tests/) | 自动化测试 |
| [`docs/`](docs/) | 用户、服务器、构建与项目结构文档 |

完整说明见[仓库结构与开发入口](docs/repository-layout.md)。本地生成的 `build/`、`dist/` 和 FFmpeg vendor 文件不会提交到 Git。

## 开发与发布

- [安装包构建与发布](docs/building-installers.md)
- [桌面应用源码入口](desktop_app/README.md)
- [文档索引](docs/README.md)

运行源码测试：

```bash
python -m unittest discover -s tests -v
```

## 许可证状态

仓库当前尚未声明项目许可证。在添加明确许可证前，请不要默认拥有复制、修改或分发源码的授权。FFmpeg 等第三方组件的许可证见 [`packaging/THIRD_PARTY_NOTICES.txt`](packaging/THIRD_PARTY_NOTICES.txt)。
