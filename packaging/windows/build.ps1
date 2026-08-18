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
        throw "Windows 7 builds require Python 3.8; current version is $PythonVersion."
    }
}

if (-not $SkipFetch) {
    & $PythonExe (Join-Path $ProjectRoot "packaging\fetch_ffmpeg.py") "windows-$Target"
    if ($LASTEXITCODE -ne 0) {
        throw "Downloading or verifying the FFmpeg components failed."
    }
}

foreach ($Name in @("ffmpeg.exe", "ffprobe.exe")) {
    if (-not (Test-Path (Join-Path $VendorDir $Name))) {
        throw "Missing $VendorDir\$Name. Provide FFmpeg binaries compatible with the target Windows version."
    }
}

& $PythonExe -m venv $VenvDir
if ($LASTEXITCODE -ne 0) {
    throw "Creating the Python virtual environment failed."
}
$BuildPython = Join-Path $VenvDir "Scripts\python.exe"
& $BuildPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Upgrading pip failed."
}
& $BuildPython -m pip install -r (Join-Path $ProjectRoot "packaging\requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Installing the packaging dependencies failed."
}

$env:VIDEO_COMPRESSOR_PLATFORM_BIN_DIR = $VendorDir
Push-Location $ProjectRoot
try {
    & $BuildPython -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $ProjectRoot "dist\windows-$Target") `
        --workpath (Join-Path $ProjectRoot "build\pyinstaller-windows-$Target") `
        (Join-Path $ProjectRoot "packaging\aerial_video_compressor.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "The PyInstaller build failed."
    }
} finally {
    Pop-Location
}

Write-Host "Build completed: dist\windows-$Target\AerialVideoCompressor"
