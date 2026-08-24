# 仓库结构与开发入口

## 设计原则

本仓库同时维护桌面应用和 Linux 服务器脚本。两套入口共享视频压缩目标，但运行方式、状态管理和适用人员不同，因此保持为独立组件。

```text
uav-video-compression/
├── README.md                 # 产品首页和下载入口
├── docs/                     # 面向不同角色的正式文档
├── desktop_app/              # Python/Tkinter 桌面应用
├── compression/              # Linux 批量压缩脚本
├── scheduling/               # Linux 夜间启停脚本
├── tools/                    # Linux 运行指标工具
├── packaging/                # PyInstaller、Inno Setup 和 DMG 构建
├── tests/                    # 桌面应用自动化测试
└── .github/workflows/        # 跨平台构建和 Release 发布
```

## 目录职责

### `desktop_app/`

桌面应用入口是 `desktop_app/main.py`，核心包位于 `desktop_app/video_compressor/`。桌面版使用 SQLite 保存续跑状态，并内置 FFmpeg/FFprobe 到发布产物。

### `compression/`

- `batch_compress_raw_videos.sh`：输出到独立目录，保留源文件。
- `batch_compress_in_place.sh`：验证成功后原位替换源文件。
- `reporting.sh`：生成 TSV 压缩报告。

### `scheduling/`

通过 tmux 启动和停止夜间任务。脚本不保存真实业务路径，运行前必须通过环境变量指定源目录。

### `tools/`

可选的 CPU、内存、GPU 和阶段耗时采样工具。普通压缩任务不依赖这些脚本。

### `packaging/`

保存跨平台构建脚本、PyInstaller spec、安装器定义和第三方许可证说明。下载的 FFmpeg 文件位于 `packaging/vendor/`，不进入 Git。

### `tests/`

使用 Python `unittest`，覆盖配置、扫描、SQLite、压缩状态机、替换恢复和真实 FFmpeg 冒烟测试。

## 本地生成目录

以下目录会让本地项目看起来较大，但它们不是源码结构的一部分：

| 路径 | 用途 | 能否删除 |
|---|---|---|
| `build/` | 虚拟环境、PyInstaller 中间文件、临时构建工具 | 可以，后续构建会重新生成 |
| `dist/` | 可执行应用和安装包 | 可以，但先保留需要交付的安装包 |
| `packaging/vendor/<平台>/` | 下载并校验的 FFmpeg/FFprobe | 可以，后续构建会重新下载 |
| `**/__pycache__/` | Python 字节码缓存 | 可以 |

这些路径均由 `.gitignore` 排除。

## 常用开发命令

运行测试：

```bash
python -m unittest discover -s tests -v
```

运行桌面应用源码：

```bash
python desktop_app/main.py
```

执行无界面诊断：

```bash
python desktop_app/main.py --diagnose
```

构建和发布流程见[安装包构建与发布](building-installers.md)。
