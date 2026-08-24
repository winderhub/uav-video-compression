# 安装包构建与发布

## 概览

项目使用 PyInstaller 生成桌面应用目录，再使用 Inno Setup 生成 Windows 安装器，使用 `hdiutil` 生成 macOS DMG。

PyInstaller 不是交叉编译器。Windows 产物必须在 Windows 上构建，macOS 产物必须在对应架构的 macOS 上构建。最省事且最可重复的方式是使用仓库自带的 GitHub Actions 工作流。

## 通过 GitHub Actions 发布

工作流文件是 `.github/workflows/build-installers.yml`，支持两种触发方式。

### 从 GitHub 网页手动发布

1. 打开仓库的 **Actions** 页面。
2. 选择 **Build installers**。
3. 点击 **Run workflow**。
4. 输入版本标签，例如 `v0.1.0`。
5. 再次确认运行，等待 Windows 和两个 macOS 任务完成。
6. 打开 **Releases** 页面检查安装包和 `SHA256SUMS.txt`。

### 推送版本标签自动发布

先确认主分支处于可发布状态，再创建符合语义化版本格式的标签：

```bash
git tag v0.1.0
git push origin v0.1.0
```

推送 `v*` 标签会自动执行测试、构建三个平台并创建或更新同名 GitHub Release。不要重复使用已经对外发布的版本号；下一次发布使用 `v0.1.1`、`v0.2.0` 等新标签。

## Release 文件

一次完整运行发布：

| 文件 | 目标用户 |
|---|---|
| `AerialVideoCompressor-<版本>-Windows-x64-Setup.exe` | Windows 10/11 64 位 |
| `AerialVideoCompressor-<版本>-macOS-x86_64.dmg` | Intel Mac |
| `AerialVideoCompressor-<版本>-macOS-arm64.dmg` | Apple Silicon Mac |
| `SHA256SUMS.txt` | 下载完整性校验 |

工作流使用 GitHub 临时提供的 `GITHUB_TOKEN` 创建 Release，不需要在仓库保存个人 Token、API Key、密码、签名证书或私钥。

## 固定构建依赖

`packaging/fetch_ffmpeg.py` 从固定上游 Release 下载 FFmpeg 6.1.1 和 FFprobe，并验证仓库中记录的 SHA-256。许可证和上游构建说明会一同放入应用资源目录。

PyInstaller 版本固定在 `packaging/requirements-build.txt`。

## Windows 10/11 本地构建

要求：

- Windows 10/11 64 位
- Python 3.8+
- PowerShell
- Inno Setup 6
- 可访问 GitHub 和 Python 包索引

生成应用目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -Target modern -PythonExe python
```

输出：

```text
dist/windows-modern/AerialVideoCompressor/
```

生成版本为 `0.1.0` 的安装器：

```powershell
ISCC.exe /DMyAppVersion=0.1.0 packaging\windows\installer.iss
```

输出：

```text
dist/installer/AerialVideoCompressor-0.1.0-Windows-x64-Setup.exe
```

如果 FFmpeg 已经下载并校验，可以使用 `-SkipFetch` 跳过再次下载：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -Target modern -PythonExe python -SkipFetch
```

## Windows 7 兼容包

Windows 7 包必须在 Windows 7 SP1 x64 实机或虚拟机中使用 Python 3.8 构建和验收。现代 Windows 或 GitHub 托管构建机不能替代真实兼容性验证。

```powershell
python packaging\fetch_ffmpeg.py windows-win7
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -Target win7 -PythonExe python -SkipFetch
```

输出：

```text
dist/windows-win7/AerialVideoCompressor/
```

先压缩整个目录并在真实 Windows 7 上验收。通过后，在装有 Inno Setup 的 Windows 电脑上生成安装器：

```powershell
ISCC.exe /DWin7Build /DMyAppVersion=0.1.0 packaging\windows\installer.iss
```

Windows 7 的主要风险来自 Python、Universal CRT、FFmpeg 和系统补丁的组合。没有真实机器验收时，不能把“构建成功”表述为“已支持 Windows 7”。

## macOS 本地构建

### Intel Mac

```bash
packaging/macos/build.sh x86_64
```

### Apple Silicon Mac

```bash
packaging/macos/build.sh arm64
```

本地脚本生成 `.app`。创建 DMG 前需要进行 ad-hoc 签名和基本诊断；完整步骤可以参考 GitHub Actions 工作流中的 macOS job。

## 构建前测试

普通单元测试：

```bash
python -m unittest discover -s tests -v
```

使用已下载的 Windows FFmpeg 运行真实编码冒烟测试：

```powershell
$vendor = (Resolve-Path "packaging/vendor/windows-x64-modern").Path
$env:VIDEO_COMPRESSOR_FFMPEG = Join-Path $vendor "ffmpeg.exe"
$env:VIDEO_COMPRESSOR_FFPROBE = Join-Path $vendor "ffprobe.exe"
$env:RUN_FFMPEG_INTEGRATION = "1"
python -m unittest discover -s tests -v
```

构建后的应用应执行无界面诊断：

```powershell
dist\windows-modern\AerialVideoCompressor\AerialVideoCompressor.exe --diagnose
```

## 发布前最低验收

自动工作流只使用一段 1 秒合成视频进行编码和探测。正式交付前，每个平台至少人工检查：

1. 应用能启动并识别内置 FFmpeg。
2. 能扫描真实 DJI MP4。
3. 完成一个视频后，分辨率、帧率和画面符合预期。
4. 中途关闭再启动可以继续。
5. 源位置空间不足时能选择另一个存储卷作为备用临时目录。
6. 替换后原视频文件名不变，没有残留临时视频。

## 签名与正式分发

当前自动产物适合内部试用，尚未达到完全无警告的商业分发状态。

- Windows：使用可信代码签名证书签名应用和安装器。
- macOS：使用 Developer ID Application 签名并提交 Apple 公证。
- 证书和密码只能保存在 GitHub Actions Secrets 等安全位置。
- 不要把证书、密码或私钥提交到仓库。
- Release 中应保留 `SHA256SUMS.txt`，供下载者验证文件完整性。

FFmpeg 官方下载说明：<https://ffmpeg.org/download.html>

PyInstaller 多平台说明：<https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems>
