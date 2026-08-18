# 安装包生成与分发

## 最简单的方式：在 GitHub 网页点一次

仓库已经提供 `Build installers` 工作流，不需要在本地安装 Python、FFmpeg 或
打包工具。

1. 打开仓库的 **Actions** 页面。
2. 左侧选择 **Build installers**。
3. 点击 **Run workflow**。
4. 版本号填写 `v0.1.0`；下次发布依次使用 `v0.1.1`、`v0.2.0` 等新版本号。
5. 再点击绿色的 **Run workflow**，等待三个平台任务全部变绿。
6. 打开仓库的 **Releases** 页面，下载生成的安装包。

一次运行会自动执行测试，并发布三个文件：

| 文件 | 给谁使用 |
|---|---|
| `AerialVideoCompressor-<版本>-Windows-x64-Setup.exe` | Windows 10/11 64 位 |
| `AerialVideoCompressor-<版本>-macOS-x86_64.dmg` | Intel 芯片 Mac |
| `AerialVideoCompressor-<版本>-macOS-arm64.dmg` | M1/M2/M3/M4 等 Apple Silicon Mac |

工作流使用 GitHub 自动提供的临时 `GITHUB_TOKEN` 创建 Release。仓库中没有、
也不需要保存个人 Token、API Key、密码、签名证书或私钥。

## 把安装包发给采集人员

Windows 用户只需要双击 `Setup.exe`，按安装向导完成安装，然后从桌面或开始
菜单启动。当前安装包没有购买商业代码签名证书，Windows 可能显示
SmartScreen 提示；内部试用时需要点击“更多信息”再选择“仍要运行”。

Mac 用户按芯片类型下载对应 DMG，双击打开后，把应用拖到 `Applications`
文件夹。当前应用只有 ad-hoc 签名，没有 Apple Developer ID 公证；首次启动
可能需要在 Finder 中右键应用选择“打开”，或在“系统设置 → 隐私与安全性”
中允许打开。

这两个警告不是程序错误。若要让普通用户完全无警告地双击运行，需要分别
购买 Windows 代码签名证书和 Apple Developer Program，并把证书作为 GitHub
Actions Secrets 配置，不能把证书或密码提交到公开仓库。

## Windows 7 兼容包

Windows 7 不能由 GitHub 托管构建机可靠代替。PyInstaller 官方建议为了兼容
旧 Windows，直接在 Windows 7 上构建；因此 Win7 包必须在 Win7 SP1 x64
实机或虚拟机中生成并验收。

准备 Python 3.8 后，在 Win7 PowerShell 中运行：

~~~powershell
python packaging\fetch_ffmpeg.py windows-win7
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -Target win7 -PythonExe python -SkipFetch
~~~

产物位于：

~~~text
dist/windows-win7/AerialVideoCompressor/
~~~

先把整个目录压缩成 ZIP，在真实 Win7 机器上检查启动、扫描、1 个短视频压缩、
中断恢复和原文件替换。验收通过后，可在装有 Inno Setup 的 Windows 电脑上
生成 Win7 安装程序：

~~~powershell
ISCC.exe /DWin7Build /DMyAppVersion=0.1.0 packaging\windows\installer.iss
~~~

Win7 的关键风险不是安装器，而是 Python、Universal CRT、FFmpeg 和系统补丁
的组合。没有真实机器验收时，不能把“构建成功”当成“Win7 已支持”。

## 本地构建（自动下载 FFmpeg）

PyInstaller 不是交叉编译器。Windows 包必须在 Windows 构建，Mac 包必须在
Mac 构建。构建脚本会自动下载固定的 FFmpeg 6.1.1/FFprobe，核对 SHA-256，
并把上游许可证和构建说明放进应用资源目录。

Windows 10/11：

~~~powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -Target modern
ISCC.exe /DMyAppVersion=0.1.0 packaging\windows\installer.iss
~~~

Intel Mac：

~~~bash
packaging/macos/build.sh x86_64
~~~

Apple Silicon Mac：

~~~bash
packaging/macos/build.sh arm64
~~~

FFmpeg 下载自固定的公开 Release，并核验仓库中记录的 SHA-256。FFmpeg 官方
只发布源码，其下载页列出的 Windows/macOS 二进制也来自第三方构建者：
<https://ffmpeg.org/download.html>。

PyInstaller 多平台说明：
<https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems>。

PyInstaller 的 Windows 支持说明：
<https://github.com/pyinstaller/pyinstaller#requirements-and-tested-platforms>。

## 发布前最低验收

自动工作流只做一段 1 秒合成视频的编码与探测测试。正式给采集人员前，每个
平台至少人工检查：

1. 软件能启动并识别内置 FFmpeg。
2. 能扫描真实 DJI MP4。
3. 完成一个视频后，分辨率、帧率和画面符合预期。
4. 中途关闭再启动可以继续。
5. SD 卡空间不足时能选择电脑磁盘作为备用临时目录。
6. 替换完成后原视频文件名不变，且没有残留临时视频。

## 签名与正式发布

当前自动产物适合内部试用，不是完全无警告的正式商业分发包。正式发布还需：

- Windows：使用可信代码签名证书签名安装器。
- macOS：使用 Developer ID Application 签名，并提交 Apple 公证。
- 把证书、证书密码等只放进 GitHub Actions Secrets，不提交到仓库。
- 每个安装包计算 SHA-256，并在 Release 页面公布。
