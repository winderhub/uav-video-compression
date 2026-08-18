# 桌面应用构建说明

PyInstaller 不是交叉编译器。Windows 安装包必须在 Windows 上构建，macOS 应用必须在 macOS 上构建。官方文档：<https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems>

## 目标产物

| 目标 | 构建环境 | Python | 命令 |
|---|---|---:|---|
| Windows 10/11 x64 | Windows 10/11 x64 | 3.11+ | `powershell -File packaging/windows/build.ps1 -Target modern` |
| Windows 7 SP1 x64 | Windows 7 SP1 x64 VM | 3.8 | `powershell -File packaging/windows/build.ps1 -Target win7` |
| macOS Intel | Intel Mac 或 x86_64 runner | 当前受支持版本 | `packaging/macos/build.sh x86_64` |
| macOS Apple Silicon | Apple Silicon Mac | 当前受支持版本 | `packaging/macos/build.sh arm64` |

PyInstaller 当前说明 Windows 7 可以尝试运行，但正式支持从 Windows 8 开始。因此 Win7 产物必须单独构建和验收，不能用 Win10 构建成功代替。官方项目说明：<https://github.com/pyinstaller/pyinstaller#requirements-and-tested-platforms>

## Windows 安装程序

现代 Windows 目录构建完成后，用 Inno Setup 编译：

~~~powershell
ISCC.exe packaging\windows\installer.iss
~~~

Win7 旧版建议先分发 `dist/windows-win7/AerialVideoCompressor/` 的 ZIP 进行兼容测试，确认可运行后再准备兼容 Win7 的安装器配置。

## macOS 签名

未签名 `.app` 会触发 Gatekeeper 警告。正式给采集人员分发前，需要在两种架构上完成代码签名、公证和启动测试。签名证书不存入仓库。
