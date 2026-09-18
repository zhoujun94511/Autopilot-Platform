# AutoPilot Platform 新设备一键安装（Windows）。
# 默认安装全部：Platform Web、Runner 宿主工具、JDK/Node/Appium/Python。
# 本仓库 resources/ 已有的二进制一律跳过。

<#
.SYNOPSIS
    为新电脑安装 AutoPilot Platform 与 Runner 所需全部宿主依赖。
.PARAMETER SkipPython
    不创建 .venv、不 pip install。
.PARAMETER SkipAppium
    不安装 Appium。
.PARAMETER SkipFrontend
    不执行 frontend npm install。
.PARAMETER SkipInit
    不调用 tools/init_platform.py init。
.PARAMETER WithPlaywright
    额外安装 Playwright Chromium。
.PARAMETER WithRemote
    额外安装 runner_remote（远控 WebRTC）。
.PARAMETER WithAllPython
    额外安装 s3/pg/secure/web_playwright/runner_remote。
.PARAMETER CheckOnly
    只体检，不安装。
#>

[CmdletBinding()]
param(
    [switch]$SkipPython = $false,
    [switch]$SkipAppium = $false,
    [switch]$SkipFrontend = $false,
    [switch]$SkipInit = $false,
    [switch]$WithPlaywright = $false,
    [switch]$WithRemote = $false,
    [switch]$WithAllPython = $false,
    [switch]$CheckOnly = $false
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

try {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
} catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir
Set-Location $RootDir

$LocalRes = Join-Path $RootDir "resources"

$NodeVer = "v22.23.2"
$MinNodeMajor = 18
$MinJavaMajor = 17

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   AutoPilot Platform 新设备一键安装（Windows）" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "   仓库: $RootDir"
Write-Host "   resources: $LocalRes" -ForegroundColor DarkGray

function Test-CommandExists {
    param([string]$Command)
    return $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Update-EnvironmentPath {
    $standardDirs = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
        "$env:LOCALAPPDATA\Programs\node",
        "$env:USERPROFILE\.local\share\node",
        "$env:LOCALAPPDATA\Programs\platform-tools",
        "$env:USERPROFILE\.local\share\platform-tools",
        "$env:USERPROFILE\.local\bin",
        "$env:USERPROFILE\scoop\shims",
        "C:\ProgramData\chocolatey\bin",
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools",
        "$env:LOCALAPPDATA\Android\android-sdk\platform-tools",
        "$env:ProgramFiles\Android\platform-tools",
        "${env:ProgramFiles(x86)}\Android\android-sdk\platform-tools",
        "$env:ProgramFiles\nodejs",
        "${env:ProgramFiles(x86)}\nodejs",
        "$env:APPDATA\npm"
    )
    if ($env:ANDROID_HOME) { $standardDirs += "$env:ANDROID_HOME\platform-tools" }
    if ($env:ANDROID_SDK_ROOT) { $standardDirs += "$env:ANDROID_SDK_ROOT\platform-tools" }
    if ($env:JAVA_HOME) { $standardDirs += "$env:JAVA_HOME\bin" }
    if ($env:NVM_SYMLINK) { $standardDirs = @($env:NVM_SYMLINK) + $standardDirs }

    $regPath = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $currentPaths = ($env:PATH -split ";") + ($regPath -split ";") + $standardDirs |
        Where-Object { $_ -and (Test-Path $_) } |
        Select-Object -Unique
    $env:PATH = $currentPaths -join ";"

    foreach ($portable in @(
        "$env:LOCALAPPDATA\Programs\node",
        "$env:LOCALAPPDATA\Programs\platform-tools"
    )) {
        if (Test-Path $portable) {
            $env:PATH = "$portable;$env:PATH"
        }
    }
}

function Add-UserPath {
    param([Parameter(Mandatory=$true)][string]$Dir)
    if (-not (Test-Path $Dir)) { return }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    $parts = @($userPath -split ";" | Where-Object { $_ })
    if ($parts -contains $Dir) { return }
    [Environment]::SetEnvironmentVariable("Path", ($Dir + ";" + $userPath).Trim(";"), "User")
    $env:PATH = "$Dir;$env:PATH"
    Write-Host "   [OK] 已写入用户 PATH: $Dir" -ForegroundColor Green
}

function Test-LocalResource {
    param([Parameter(Mandatory=$true)][string]$RelativePath)
    return Test-Path (Join-Path $LocalRes $RelativePath)
}

function Invoke-DownloadFile {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [Parameter(Mandatory=$true)][string]$OutFile,
        [int]$TimeoutSec = 90
    )
    if (Test-Path $OutFile) {
        Remove-Item -Path $OutFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-CommandExists "curl.exe") {
        try {
            & curl.exe -f -sSL --connect-timeout 8 --max-time $TimeoutSec "$Uri" -o "$OutFile" 2>$null
            if ($LASTEXITCODE -eq 0 -and (Test-Path $OutFile) -and ((Get-Item $OutFile).Length -gt 0)) {
                return $true
            }
        } catch {}
        if (Test-Path $OutFile) { Remove-Item -Path $OutFile -Force -ErrorAction SilentlyContinue }
    }
    try {
        $prevProgress = $ProgressPreference
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $Uri -OutFile $OutFile -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
        $ProgressPreference = $prevProgress
        if ((Test-Path $OutFile) -and ((Get-Item $OutFile).Length -gt 0)) {
            return $true
        }
    } catch {
        $ProgressPreference = $prevProgress
    }
    if (Test-Path $OutFile) { Remove-Item -Path $OutFile -Force -ErrorAction SilentlyContinue }
    return $false
}

function Get-NodeMajor {
    if (-not (Test-CommandExists "node")) { return 0 }
    try {
        $ver = (& node -v 2>$null).ToString().Trim().TrimStart("v")
        return [int]($ver.Split(".")[0])
    } catch {
        return 0
    }
}

function Test-NodeReady {
    $hasNpm = (Test-CommandExists "npm") -or (Test-CommandExists "npm.cmd")
    return ((Get-NodeMajor) -ge $MinNodeMajor) -and $hasNpm
}

function Get-JavaMajor {
    if (-not (Test-CommandExists "java")) { return 0 }
    try {
        $raw = & java -version 2>&1 | Out-String
        if ($raw -match 'version "1\.(\d+)') { return [int]$Matches[1] }
        if ($raw -match 'version "(\d+)') { return [int]$Matches[1] }
    } catch {}
    return 0
}

function Get-NpmExe {
    if (Test-CommandExists "npm.cmd") { return "npm.cmd" }
    if (Test-CommandExists "npm") { return "npm" }
    return $null
}

function Install-PortablePlatformTools {
    $ptDir = "$env:LOCALAPPDATA\Programs\platform-tools"
    if (Test-Path "$ptDir\adb.exe") {
        Add-UserPath $ptDir
        return $true
    }
    Write-Host "   [INFO] 内置 re_adb 不在仓库中，安装用户态 Android platform-tools..." -ForegroundColor Cyan
    $zipPath = "$env:TEMP\platform-tools-windows.zip"
    if (Invoke-DownloadFile -Uri "https://dl.google.com/android/repository/platform-tools-latest-windows.zip" -OutFile $zipPath -TimeoutSec 90) {
        New-Item -ItemType Directory -Path "$env:LOCALAPPDATA\Programs" -Force | Out-Null
        Expand-Archive -Path $zipPath -DestinationPath "$env:LOCALAPPDATA\Programs" -Force
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        if (Test-Path "$ptDir\adb.exe") {
            Add-UserPath $ptDir
            Write-Host "   [OK] adb 已装到用户目录（未写入 resources/）。" -ForegroundColor Green
            return $true
        }
    }
    Write-Host "   [WARN] 便携 adb 安装失败，且仓库 resources/re_adb 不可用。" -ForegroundColor DarkYellow
    return $false
}

function Install-PortableNode {
    $nodeDir = "$env:LOCALAPPDATA\Programs\node"
    if ((Test-Path "$nodeDir\node.exe") -and (Test-NodeReady)) {
        Add-UserPath $nodeDir
        return $true
    }
    Write-Host "   [INFO] 安装便携 Node.js $NodeVer 到用户目录..." -ForegroundColor Cyan
    $arch = if ($env:PROCESSOR_ARCHITECTURE -match "ARM64") { "arm64" } else { "x64" }
    $zipPath = "$env:TEMP\node-$NodeVer-win-$arch.zip"
    $uri = "https://nodejs.org/dist/$NodeVer/node-$NodeVer-win-$arch.zip"
    if (Invoke-DownloadFile -Uri $uri -OutFile $zipPath -TimeoutSec 90) {
        $extractDir = "$env:TEMP\node_extract"
        if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
        $extractedFolder = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
        if ($extractedFolder) {
            if (-not (Test-Path $nodeDir)) {
                New-Item -ItemType Directory -Path $nodeDir -Force | Out-Null
            }
            Copy-Item -Path "$($extractedFolder.FullName)\*" -Destination $nodeDir -Recurse -Force
        }
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path "$nodeDir\node.exe") {
            Add-UserPath $nodeDir
            Write-Host "   [OK] 便携 Node.js $NodeVer 已就绪。" -ForegroundColor Green
            return $true
        }
    }
    Write-Host "   [WARN] 便携 Node.js 安装失败。" -ForegroundColor DarkYellow
    return $false
}

function Install-NodeIfMissing {
    if (Test-NodeReady) { return $true }
    if (Test-CommandExists "nvm") {
        Write-Host "   [INFO] 通过 nvm 安装 Node 22..." -ForegroundColor Cyan
        & nvm install 22.23.2 | Out-Null
        & nvm use 22.23.2 | Out-Null
        Update-EnvironmentPath
    }
    if (-not (Test-NodeReady) -and (Test-CommandExists "winget")) {
        Write-Host "   [INFO] 通过 WinGet 安装 Node.js LTS..." -ForegroundColor Cyan
        winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements --silent 2>$null | Out-Null
        Update-EnvironmentPath
    }
    if (-not (Test-NodeReady)) {
        Install-PortableNode | Out-Null
        Update-EnvironmentPath
    }
    return (Test-NodeReady)
}

function Install-JdkIfNeeded {
    if ((Get-JavaMajor) -ge $MinJavaMajor) { return $true }
    if (-not (Test-CommandExists "winget")) {
        Write-Host "   [WARN] 未找到 JDK 17+。Runner 跑 Android 需要 JDK 17+ 并设 JAVA_HOME。" -ForegroundColor DarkYellow
        return $false
    }
    Write-Host "   [INFO] 通过 WinGet 安装 Microsoft OpenJDK 17..." -ForegroundColor Cyan
    winget install --id Microsoft.OpenJDK.17 -e --accept-source-agreements --accept-package-agreements --silent 2>$null | Out-Null
    Update-EnvironmentPath
    return ((Get-JavaMajor) -ge $MinJavaMajor)
}

function Install-AppiumStack {
    if (-not (Install-NodeIfMissing)) {
        Write-Host "   [FAIL] Node.js >= $MinNodeMajor 未就绪，跳过 Appium。" -ForegroundColor Red
        return $false
    }
    $npm = Get-NpmExe
    if (-not $npm) { return $false }
    if (-not (Test-CommandExists "appium")) {
        Write-Host "   [INFO] npm install -g appium ..." -ForegroundColor Cyan
        & $npm install -g appium --no-fund --no-audit
        Update-EnvironmentPath
        Add-UserPath "$env:APPDATA\npm"
    }
    if (-not (Test-CommandExists "appium")) {
        Write-Host "   [FAIL] Appium CLI 安装失败。" -ForegroundColor Red
        return $false
    }
    Write-Host "   [OK] Appium $(appium --version 2>$null)" -ForegroundColor Green
    Write-Host "   [INFO] appium driver install uiautomator2 ..." -ForegroundColor Cyan
    & appium driver install uiautomator2
    return $true
}

function Install-Frontend {
    if (-not (Install-NodeIfMissing)) {
        Write-Host "   [FAIL] Node.js 未就绪，无法 npm install 前端。" -ForegroundColor Red
        return $false
    }
    $frontend = Join-Path $RootDir "autopilot_platform\frontend"
    if (-not (Test-Path (Join-Path $frontend "package.json"))) {
        Write-Host "   [WARN] 未找到 frontend/package.json" -ForegroundColor DarkYellow
        return $false
    }
    $npm = Get-NpmExe
    Write-Host "   [INFO] npm install (autopilot_platform/frontend) ..." -ForegroundColor Cyan
    Push-Location $frontend
    try {
        & $npm install --no-fund --no-audit
    } finally {
        Pop-Location
    }
    return ($LASTEXITCODE -eq 0)
}

function Get-PythonSpec {
    $parts = @("dev", "runner")
    if ($WithRemote -or $WithAllPython) { $parts += "runner_remote" }
    if ($WithPlaywright -or $WithAllPython) { $parts += "web_playwright" }
    if ($WithAllPython) { $parts += @("s3", "pg", "secure") }
    $parts = $parts | Select-Object -Unique
    return ".[$($parts -join ',')]"
}

function Install-PythonEnv {
    $py = $null
    foreach ($cand in @("py", "python", "python3")) {
        if (Test-CommandExists $cand) { $py = $cand; break }
    }
    if (-not $py) {
        Write-Host "   [FAIL] 未找到 Python。请先安装 Python 3.10+ 并勾选 Add to PATH。" -ForegroundColor Red
        return $false
    }
    $venvPy = Join-Path $RootDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Host "   [INFO] 创建 .venv ..." -ForegroundColor Cyan
        if ($py -eq "py") {
            & py -3 -m venv (Join-Path $RootDir ".venv")
        } else {
            & $py -m venv (Join-Path $RootDir ".venv")
        }
    }
    if (-not (Test-Path $venvPy)) {
        Write-Host "   [FAIL] 创建虚拟环境失败。" -ForegroundColor Red
        return $false
    }
    $spec = Get-PythonSpec
    Write-Host "   [INFO] pip install -e $spec ..." -ForegroundColor Cyan
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -e $spec
    if ($LASTEXITCODE -ne 0) { return $false }
    if ($WithPlaywright -or $WithAllPython) {
        Write-Host "   [INFO] playwright install chromium ..." -ForegroundColor Cyan
        & $venvPy -m playwright install chromium
    }
    return $true
}

function Initialize-DotEnv {
    $envFile = Join-Path $RootDir ".env"
    $example = Join-Path $RootDir ".env.example"
    if (Test-Path $envFile) {
        Write-Host "   [OK] .env 已存在" -ForegroundColor Green
        return
    }
    if (Test-Path $example) {
        Copy-Item $example $envFile
        Write-Host "   [OK] 已从 .env.example 生成 .env" -ForegroundColor Green
    }
}

function Initialize-PlatformData {
    $db = Join-Path $RootDir "data\autopilot_platform.db"
    if (Test-Path $db) {
        Write-Host "   [OK] 已有 data/ 主库，跳过 init" -ForegroundColor Green
        return
    }
    $venvPy = Join-Path $RootDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Host "   [WARN] 无 .venv，跳过 init_platform.py" -ForegroundColor DarkYellow
        return
    }
    Write-Host "   [INFO] tools/init_platform.py init ..." -ForegroundColor Cyan
    & $venvPy (Join-Path $RootDir "tools\init_platform.py") init
}

function Show-ResourceSkipReport {
    Write-Host "`n1. 内置设备资源（本仓库 resources/ 已有则跳过）..." -ForegroundColor Yellow
    $items = @(
        @{ Name = "re_adb (platform-tools zip)"; Rel = "re_adb\platform-tools-latest-windows.zip" },
        @{ Name = "re_aapt"; Rel = "re_aapt\aapt-windows.zip" },
        @{ Name = "re_scrcpy/scrcpy-server.jar"; Rel = "re_scrcpy\scrcpy-server.jar" },
        @{ Name = "re_uiautomator 设备侧 apk"; Rel = "re_uiautomator\app-uiautomator.apk" },
        @{ Name = "re_go_ios/executable"; Rel = "re_go_ios\executable\win\ios.exe" },
        @{ Name = "re_go_ios/devimages"; Rel = "re_go_ios\devimages" }
    )
    foreach ($it in $items) {
        if (Test-LocalResource $it.Rel) {
            Write-Host "   [SKIP] $($it.Name) 已在 resources/，不重复下载" -ForegroundColor Green
        } else {
            Write-Host "   [MISS] $($it.Name) 未找到（运行期对应能力可能不可用）" -ForegroundColor DarkYellow
        }
    }
}

function Show-Summary {
    Write-Host "`n就绪摘要:" -ForegroundColor Yellow
    foreach ($t in @("adb", "java", "node", "npm", "appium")) {
        $lookup = $t
        if ($t -eq "npm" -and -not (Test-CommandExists "npm") -and (Test-CommandExists "npm.cmd")) {
            $lookup = "npm.cmd"
        }
        if (Test-CommandExists $lookup) {
            Write-Host "   [OK] $t -> $((Get-Command $lookup).Source)" -ForegroundColor Green
        } else {
            Write-Host "   [--] $t 不在 PATH" -ForegroundColor DarkYellow
        }
    }
    $venvPy = Join-Path $RootDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        Write-Host "   [OK] Python venv -> $venvPy" -ForegroundColor Green
    } else {
        Write-Host "   [--] .venv 未创建" -ForegroundColor DarkYellow
    }
    $nm = Join-Path $RootDir "autopilot_platform\frontend\node_modules"
    if (Test-Path $nm) {
        Write-Host "   [OK] frontend node_modules 已安装" -ForegroundColor Green
    } else {
        Write-Host "   [--] frontend 尚未 npm install" -ForegroundColor DarkYellow
    }
}

# ---- 执行 ----
Update-EnvironmentPath
Show-ResourceSkipReport

if ($CheckOnly) {
    Write-Host "`n[CheckOnly] 仅体检，不安装。" -ForegroundColor Cyan
    Show-Summary
    exit 0
}

Write-Host "`n2. Android 设备层 adb ..." -ForegroundColor Yellow
if (Test-LocalResource "re_adb\platform-tools-latest-windows.zip") {
    Write-Host "   [SKIP] 使用仓库 resources/re_adb，不安装系统 adb。" -ForegroundColor Green
} elseif (Test-CommandExists "adb") {
    Write-Host "   [OK] PATH 上已有 adb" -ForegroundColor Green
} else {
    Install-PortablePlatformTools | Out-Null
}

Write-Host "`n3. JDK 17+（Appium Android）..." -ForegroundColor Yellow
Install-JdkIfNeeded | Out-Null

Write-Host "`n4. Node.js ..." -ForegroundColor Yellow
Install-NodeIfMissing | Out-Null

if ($SkipAppium) {
    Write-Host "   [SKIP] 按参数跳过 Appium" -ForegroundColor DarkYellow
} else {
    Write-Host "   Appium + uiautomator2 ..." -ForegroundColor Yellow
    Install-AppiumStack | Out-Null
}

Write-Host "`n5. 环境文件 .env ..." -ForegroundColor Yellow
Initialize-DotEnv

if ($SkipPython) {
    Write-Host "`n6. [SKIP] 按参数跳过 Python 依赖" -ForegroundColor DarkYellow
} else {
    Write-Host "`n6. Python 虚拟环境与项目依赖 ..." -ForegroundColor Yellow
    Install-PythonEnv | Out-Null
}

if ($SkipFrontend) {
    Write-Host "`n7. [SKIP] 按参数跳过前端 npm install" -ForegroundColor DarkYellow
} else {
    Write-Host "`n7. 前端 npm install ..." -ForegroundColor Yellow
    Install-Frontend | Out-Null
}

if ($SkipInit) {
    Write-Host "`n8. [SKIP] 按参数跳过 init_platform" -ForegroundColor DarkYellow
} else {
    Write-Host "`n8. 初始化 data/ ..." -ForegroundColor Yellow
    Initialize-PlatformData
}

if (Test-CommandExists "adb") {
    try {
        $orig = $env:ADB_SERVER_SOCKET
        Remove-Item Env:\ADB_SERVER_SOCKET -ErrorAction SilentlyContinue
        & adb start-server 2>$null | Out-Null
        if ($orig) { $env:ADB_SERVER_SOCKET = $orig }
    } catch {}
}

Show-Summary

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   安装流程结束。建议再跑预检：" -ForegroundColor Green
Write-Host "     .venv\Scripts\python.exe tools\preflight.py" -ForegroundColor Cyan
Write-Host "   启动 Platform+Web：  .venv\Scripts\python.exe start_dev.py" -ForegroundColor Cyan
Write-Host "   启动 Runner：  python -m autopilot_platform.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
