param(
    [string]$PythonExe = "python",
    [ValidateSet("modern", "win7")]
    [string]$Target = "modern",
    [switch]$SkipFetch
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$VendorDir = Join-Path $ProjectRoot "packaging\vendor\windows-x64-$Target"
$VenvDir = Join-Path $ProjectRoot "build\venv-windows-$Target"

if ($Target -eq "win7") {
    $PythonVersion = & $PythonExe -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($PythonVersion -ne "3.8") {
        throw "Windows 7 构建必须使用 Python 3.8，当前是 $PythonVersion。"
    }
}

if (-not $SkipFetch) {
    & $PythonExe (Join-Path $ProjectRoot "packaging\fetch_ffmpeg.py") "windows-$Target"
    if ($LASTEXITCODE -ne 0) {
        throw "FFmpeg 组件下载或校验失败。"
    }
}

foreach ($Name in @("ffmpeg.exe", "ffprobe.exe")) {
    if (-not (Test-Path (Join-Path $VendorDir $Name))) {
        throw "缺少 $VendorDir\$Name。请放入与目标 Windows 版本兼容的 FFmpeg。"
    }
}

& $PythonExe -m venv $VenvDir
if ($LASTEXITCODE -ne 0) {
    throw "创建 Python 虚拟环境失败。"
}
$BuildPython = Join-Path $VenvDir "Scripts\python.exe"
& $BuildPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "升级 pip 失败。"
}
& $BuildPython -m pip install -r (Join-Path $ProjectRoot "packaging\requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "安装打包依赖失败。"
}

$env:VIDEO_COMPRESSOR_PLATFORM_BIN_DIR = $VendorDir
Push-Location $ProjectRoot
try {
    & $BuildPython -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $ProjectRoot "dist\windows-$Target") `
        --workpath (Join-Path $ProjectRoot "build\pyinstaller-windows-$Target") `
        (Join-Path $ProjectRoot "packaging\aerial_video_compressor.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败。"
    }
} finally {
    Pop-Location
}

Write-Host "构建完成：dist\windows-$Target\AerialVideoCompressor"
