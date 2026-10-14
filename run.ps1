<#
一键启动 Kokoro-82M 多语言 TTS Demo（Web 界面）。

从 GitHub 克隆后直接运行本脚本即可，全流程自动完成：
  1) 没有虚拟环境就创建 .venv
  2) 缺依赖就安装（PyTorch CPU 版 + requirements.txt + spacy 英文模型）
  3) 检查 models/Kokoro-82M，缺权重/音色就自动下载（约 330 MB，可断点续传）
  4) 启动 Web 服务并打开浏览器

用法：
  .\run.ps1                      # 全自动：准备环境 + 下载模型 + 启动
  .\run.ps1 -Port 8080           # 指定端口
  .\run.ps1 -Source hf           # 指定模型下载源（auto/modelscope/hf）
  .\run.ps1 -SkipDeps            # 跳过依赖检查（已装好时更快）
  .\run.ps1 -SkipDownload        # 跳过模型下载（离线或已有模型）
  .\run.ps1 -NoBrowser           # 不自动打开浏览器
  .\run.ps1 -CheckOnly           # 只准备环境与模型，不启动服务
#>
param(
  [int]$Port = 8000,
  [ValidateSet("auto", "modelscope", "hf")][string]$Source = "auto",
  [switch]$SkipDeps,
  [switch]$SkipDownload,
  [switch]$NoBrowser,
  [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Note($text) { Write-Host "    $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host $text -ForegroundColor Red; exit 1 }

# --------------------------------------------------------------- 1) 虚拟环境
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  Step "未找到虚拟环境，正在创建 .venv ..."
  if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m venv .venv
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m venv .venv
  } else {
    Fail "未检测到 Python，请先安装 Python 3.10+ 并勾选“Add to PATH”，然后重新运行。"
  }
  if (-not (Test-Path $python)) { Fail "创建虚拟环境失败。" }
  Ok "虚拟环境创建完成：.venv"
} else {
  Ok "已找到虚拟环境：.venv"
}

# 统一用 venv 里的 python + UTF-8 输出
function Invoke-Py { & $python -X utf8 @args }

# --------------------------------------------------------------- 2) 依赖
$checkEnv = Join-Path $root "scripts\check_env.py"
if (-not $SkipDeps) {
  Step "检查 Python 依赖 ..."
  Invoke-Py $checkEnv --quiet
  if ($LASTEXITCODE -ne 0) {
    Note "开始安装依赖（首次约 3~8 分钟，需要联网）..."
    Invoke-Py -m pip install --upgrade pip
    Step "安装 PyTorch（CPU 版；有 NVIDIA 显卡可换成 CUDA 版）..."
    Invoke-Py -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) {
      Note "官方 CPU 源不可用，改用默认源安装 PyTorch ..."
      Invoke-Py -m pip install torch
      if ($LASTEXITCODE -ne 0) { Fail "PyTorch 安装失败，请检查网络后重试。" }
    }
    Step "安装其余依赖（requirements.txt；kokoro/misaki 从 GitHub 拉取）..."
    Invoke-Py -m pip install -r (Join-Path $root "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
      Note "依赖安装失败（GitHub 偶发抽风时可重试，已装好的包不会重复下载）"
      Fail "请检查网络后重新运行 .\run.ps1，或手动执行：.\.venv\Scripts\python -m pip install -r requirements.txt"
    }
    Ok "依赖安装完成"
  } else {
    Ok "依赖完整"
  }

  Step "检查英文 G2P 需要的 spacy 模型 en_core_web_sm ..."
  $ErrorActionPreference = "Continue"
  Invoke-Py $checkEnv --spacy --quiet 2>$null
  $spacyReady = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = "Stop"
  if (-not $spacyReady) {
    Note "正在安装 en_core_web_sm ..."
    Invoke-Py -m spacy download en_core_web_sm
    if ($LASTEXITCODE -ne 0) { Note "en_core_web_sm 安装失败（不影响中文等非英语合成）" }
  } else {
    Ok "en_core_web_sm 已安装"
  }
} else {
  Ok "已跳过依赖检查（-SkipDeps）"
}

# --------------------------------------------------------------- 3) 模型文件
if (-not $SkipDownload) {
  Step "检查模型文件（config.json + 权重 + 54 个音色）..."
  Invoke-Py (Join-Path $root "scripts\download_model.py") --check --quiet
  if ($LASTEXITCODE -ne 0) {
    Note "模型不完整，开始自动下载（约 330 MB，支持断点续传，中断后重跑即可）..."
    Invoke-Py (Join-Path $root "scripts\download_model.py") --source $Source
    if ($LASTEXITCODE -ne 0) {
      Fail "模型下载失败。可换源重试 .\run.ps1 -Source hf，或手动执行：.\.venv\Scripts\python scripts\download_model.py"
    }
  } else {
    Ok "模型文件已就绪"
  }
} else {
  Ok "已跳过模型下载（-SkipDownload），服务启动时会自行检查"
}

# --------------------------------------------------------------- 4) 启动服务
if ($CheckOnly) {
  Step "环境与模型检查完毕（-CheckOnly），不启动服务。"
  Write-Host "    直接运行 .\run.ps1 即可启动：http://127.0.0.1:$Port" -ForegroundColor DarkGray
  exit 0
}

$serverArgs = @((Join-Path $root "server.py"), "--port", "$Port", "--source", $Source)
if (-not $NoBrowser) { $serverArgs += "--open" }

Step "启动 Kokoro-82M Demo：http://127.0.0.1:$Port"
Write-Host "    模型在后台加载，页面顶部会显示进度；按 Ctrl+C 结束服务" -ForegroundColor DarkGray
Invoke-Py @serverArgs
