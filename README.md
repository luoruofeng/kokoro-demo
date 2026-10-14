# Kokoro-82M 多语言语音合成 Demo

用 [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)（82M 参数的开源 TTS 模型）做的**多语言朗读效果演示**：
一个网页就能切换 9 种语言、54 个音色、实时调语速，生成后直接在浏览器里播放，并带有波形、实时频谱、音素（IPA）回显和一键九语对比。

克隆下来只需要一条命令：**`.\run.ps1`**。缺虚拟环境会自动建、缺依赖会自动装、缺模型会自动下载（约 330 MB），下载完自动启动服务。
模型权重与音色全部落在项目内 `models/`（**不会提交到 GitHub**），推理完全离线，不联网也能跑。

---

## 1. 实测效果

在普通 CPU（无 GPU）上跑出来的数据：

| 语言 | 音色 | 示例音频时长 | 合成耗时 | 实时率 RTF |
| --- | --- | --- | --- | --- |
| 美式英语 | af_heart | 8.80 s | 1.54 s | 0.18 |
| 英式英语 | bf_emma | 6.80 s | 1.27 s | 0.19 |
| 西班牙语 | ef_dora | 7.05 s | 1.27 s | 0.18 |
| 法语 | ff_siwis | 7.67 s | 1.39 s | 0.18 |
| 印地语 | hf_alpha | 7.72 s | 1.33 s | 0.17 |
| 意大利语 | if_sara | 6.50 s | 1.14 s | 0.18 |
| 巴西葡语 | pf_dora | 6.88 s | 1.24 s | 0.18 |
| 日语 | jf_alpha | 8.30 s | 1.52 s | 0.18 |
| 中文 | zf_xiaoxiao | 8.72 s | 1.91 s | 0.22 |

> RTF = 合成耗时 / 音频时长，**越小越快**。0.18 表示比实时快 5 倍多，一句话基本 1~2 秒出音。
> 模型加载（含 9 个语言前端初始化）约 **7 秒**，之后常驻内存。

首次运行还要额外下载模型（约 330 MB）：本机实测 ModelScope 约 0.5~2 MB/s，**总耗时 3~10 分钟**；
下载支持断点续传，中途 Ctrl+C 或断网后重跑即可继续。

---

## 2. 快速开始

### 2.1 一键运行（推荐）

```powershell
git clone <你的仓库地址> kokoro-demo
cd kokoro-demo
.\run.ps1
```

`run.ps1` 会**自动按顺序**完成（每一步都会打印进度，已完成则跳过）：

1. 没有 `.venv` 就创建虚拟环境；
2. 缺依赖就安装：PyTorch（CPU 版）→ `requirements.txt` → spacy 英文模型 `en_core_web_sm`；
3. 检查 `models/Kokoro-82M`：缺 `config.json` / `kokoro-v1_0.pth` / `voices/*.pt` 就自动下载（ModelScope 优先，失败回退 HuggingFace，断点续传）；
4. 模型就绪后启动 Web 服务并打开 <http://127.0.0.1:8000>。

浏览器打开后，页面顶部会显示加载/下载进度；模型加载完成即可开始合成。

常用开关：

```powershell
.\run.ps1 -Port 8080        # 换端口
.\run.ps1 -Source hf        # 换下载源（auto / modelscope / hf）
.\run.ps1 -SkipDeps         # 依赖已装好时跳过检查
.\run.ps1 -SkipDownload     # 跳过模型下载（离线或已有模型）
.\run.ps1 -NoBrowser        # 不自动打开浏览器
.\run.ps1 -CheckOnly        # 只准备环境与模型（自检），不启动服务
```

> 如果 PowerShell 提示“禁止运行脚本”，用
> `powershell -ExecutionPolicy Bypass -File .\run.ps1` 运行，
> 或先执行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

### 2.2 手动步骤（等价于 run.ps1 做的事）

```powershell
# 1) 虚拟环境
python -m venv .venv

# 2) PyTorch（CPU 版；有 NVIDIA 显卡可换成 CUDA 版）
.\.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu

# 3) 其余依赖（kokoro / misaki 从 GitHub 装最新版）
.\.venv\Scripts\python -m pip install -r requirements.txt

# 4) 英文 G2P 需要的 spacy 模型
.\.venv\Scripts\python -m spacy download en_core_web_sm

# 5) 下载 Kokoro-82M 权重与音色到 models/（约 330 MB，可断点续传）
.\.venv\Scripts\python scripts\download_model.py

# 6) 启动 Web Demo
.\run.ps1
```

---

## 3. 模型自动下载与离线使用

模型文件不随仓库分发（见 `.gitignore`），由程序自己保证“缺什么补什么”。
`server.py`、`cli.py`、`run.ps1` 共用同一套逻辑（`model_assets.py`）：

| 场景 | 行为 |
| --- | --- |
| 文件齐全 | 直接加载，不联网（`[模型] 已就绪：59 个文件，339.0MB`） |
| 缺少任意文件 | 自动补齐：先读远端清单，只下缺失的文件，逐个校验大小 |
| 文件被截断 | 大小与远端不一致时自动重下（`.part` 临时文件避免半个文件被误用） |
| 下载源失败 | 自动回退：ModelScope → HuggingFace；也可 `--source` 指定 |
| 全部源失败 | 报错并给出排查建议，服务以“模型加载失败”状态启动，页面会提示可执行的手动命令 |
| 离线 / 已有模型 | 加 `--no-download`（server.py、cli.py）或 `-SkipDownload`（run.ps1），只检查不下载 |

相关命令：

```powershell
# 只检查模型是否齐全（齐全返回 0，缺文件返回 3）
.\.venv\Scripts\python scripts\download_model.py --check

# 补齐全部资源（权重 + 54 个音色 + 说明文档）
.\.venv\Scripts\python scripts\download_model.py

# 只下 config + 权重；强制走 HuggingFace
.\.venv\Scripts\python scripts\download_model.py --only-core --source hf

# 查看本地模型统计（也可以直接跑模块自检）
.\.venv\Scripts\python model_assets.py

# 禁止自动下载（离线启动）
.\.venv\Scripts\python server.py --no-download
```

自定义模型目录：设置环境变量 `KOKORO_MODEL_DIR`（默认 `models/Kokoro-82M`），
适合把模型放在共享盘或多项目复用，例如：

```powershell
$env:KOKORO_MODEL_DIR = "D:\models\Kokoro-82M"
.\run.ps1
```

---

## 4. Web 界面能做什么

- **左侧语言栏**：9 种语言一键切换，切换后自动填入该语言的示例文案。
- **音色网格**：显示官方质量等级（A/A-/B-/C/D…）、男女声，点一下立即用当前文本试听。
- **语速滑杆**：0.6× ~ 1.6× 实时调整。
- **文本区**：示例文案一键填充，`Ctrl + Enter` 快速生成，空行分段，长文本自动切块。
- **播放器**：
  - 波形图（生成后绘制，播放进度实时染色，点击波形任意位置可跳转）
  - 实时频谱图（正在播放时跳动）
  - 指标：音频时长、合成耗时、RTF、切块数、采样率
  - **音素序列**（折叠面板）：显示模型真正吃进去的 IPA 音素，方便对比不同语言的 G2P 差异
- **一键对比全部语言**：9 种语言各用自己的示例文案合成，"依次播放"可连续听完全部。
- **历史记录**：所有生成的 wav 都保存在 `outputs/`，可回放、可回填文本。
- **启动遮罩层**：首次运行时显示自动下载进度（已完成文件数、写入量、速度、总进度）。

---

## 5. 命令行用法

```powershell
.\.venv\Scripts\python cli.py --list                      # 查看语言与音色
.\.venv\Scripts\python cli.py --lang z --text "你好世界"    # 合成中文
.\.venv\Scripts\python cli.py --lang a --text "Hello" --play   # 合成后播放（Windows）
.\.venv\Scripts\python cli.py --demo --no-play             # 9 种语言各生成一条示例
.\.venv\Scripts\python cli.py --demo                       # 生成并依次播放
.\.venv\Scripts\python cli.py --lang z --text "你好" --no-download   # 离线模式（不自动下载）
```

CLI 在执行前也会自动检查模型、缺什么补什么，补完继续执行。

Python 里直接调用：

```python
from kokoro_tts import get_engine

tts = get_engine().load()                       # 加载权重 + 预热
speech = tts.synthesize("你好，世界", "z", voice="zf_xiaoxiao", speed=1.0)
print(speech.seconds, speech.rtf)               # 音频时长 / 实时率
speech.save("hello.wav")                        # 24 kHz 单声道 wav
```

---

## 6. 目录结构

```
kokoro-demo/
├─ run.ps1                # 一键启动：建环境 → 装依赖 → 拉模型 → 起服务
├─ server.py              # FastAPI 服务 + REST 接口（启动时自动检查/下载模型）
├─ model_assets.py        # 模型清单 + 自动检查 / 自动下载（含进度回调）
├─ kokoro_tts.py          # 推理引擎（KModel + 每语言一个 KPipeline）
├─ languages.py           # 9 种语言 / 54 个音色 / 示例文案
├─ cli.py                 # 命令行 Demo
├─ static/
│  ├─ index.html          # 单页界面
│  ├─ style.css           # 深色玻璃拟态样式
│  └─ app.js              # Web Audio 播放器（波形 + 频谱 + 跳转 + 下载进度条）
├─ scripts/
│  ├─ check_env.py        # 环境自检（依赖是否齐全 / spacy 模型，供 run.ps1 调用）
│  ├─ download_model.py   # 模型下载 CLI（--check / --only-core / --source）
│  ├─ smoke_test.py       # 后端端到端测试（逐语言合成 + 校验音频能量）
│  └─ ui_check.mjs        # 前端全流程测试（jsdom 打桩后跑真实接口）
├─ models/
│  ├─ .gitkeep            # 占位说明（该目录内容不进 Git）
│  └─ Kokoro-82M/         # config.json + kokoro-v1_0.pth + voices/*.pt（自动下载）
└─ outputs/               # 生成的 wav（运行时产物）
```

### REST 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/status` | 加载/下载状态、当前阶段、下载进度、模型文件统计 |
| GET | `/api/catalog` | 语言、音色、示例文案、引擎信息 |
| POST | `/api/tts` | `{text, lang, voice, speed, save}` → wav(base64) + 时长/RTF/音素 |
| POST | `/api/compare` | 一次合成多种语言，用于横向对比 |
| GET/DELETE | `/api/history` | 历史记录列表 / 清空 |

`/api/status` 关键字段：

```json
{
  "state": "downloading",
  "message": "缺少 59 个模型文件，开始自动下载（下载源：ModelScope、HuggingFace）",
  "download": {
    "stage": "download", "file": "kokoro-v1_0.pth",
    "files_done": 2, "files_total": 59,
    "percent": 64.0, "overall_percent": 64.0,
    "bytes_done": 209715200, "bytes_total": 327212226,
    "bytes_written": 222298112, "speed": 589824.0
  },
  "assets": { "files_present": 2, "files_expected": 59, "voices_present": 0, "voices_expected": 54,
              "human_size": "313.9MB", "missing": 57 },
  "auto_download": true
}
```

---

## 7. 支持的语言与音色

| 代码 | 语言 | G2P 方案 | 音色数 | 推荐音色 |
| --- | --- | --- | --- | --- |
| `a` | 美式英语 | misaki[en] + espeak-ng 兜底 | 20 | `af_heart` (A)、`af_bella` (A-) |
| `b` | 英式英语 | misaki[en]（英式） | 8 | `bf_emma` (B-) |
| `e` | 西班牙语 | espeak-ng | 3 | `ef_dora` |
| `f` | 法语 | espeak-ng | 1 | `ff_siwis` (B-) |
| `h` | 印地语 | espeak-ng | 4 | `hf_alpha` |
| `i` | 意大利语 | espeak-ng | 2 | `if_sara` |
| `p` | 巴西葡语 | espeak-ng | 3 | `pf_dora` |
| `j` | 日语 | misaki[ja]（cutlet + unidic-lite） | 5 | `jf_alpha` (C+) |
| `z` | 中文 | misaki[zh]（jieba + pypinyin + 数字归一化） | 8 | `zf_xiaoxiao` |

> 等级为官方 VOICES.md 标注的 Overall Grade，表示音色训练数据质量与时长。
> 非英语语言的训练数据普遍偏少，**中文/日语/法语**音色等级较低，听起来会比英语"机械"一些，这是模型本身的限制，不是配置问题。

---

## 8. 验证

```powershell
# 环境自检：依赖是否齐全 / spacy 英文模型是否可用（run.ps1 内部调用同一脚本）
.\.venv\Scripts\python scripts\check_env.py
.\.venv\Scripts\python scripts\check_env.py --spacy

# 环境 + 模型一起自检（不启动服务）
.\run.ps1 -CheckOnly

# 模型自检：文件是否齐全（不联网）
.\.venv\Scripts\python scripts\download_model.py --check

# 后端：等待就绪 → 逐语言合成 → 校验音频时长/峰值/音素 → 检查对比与历史接口
.\.venv\Scripts\python scripts\smoke_test.py

# 前端：jsdom 加载真实页面与脚本，打桩 Web Audio/Canvas，走完
#       选语言 → 生成 → 播放 → 九语对比 → 历史回填 全流程
npm install --no-save jsdom
node scripts/ui_check.mjs
```

想验证“首次运行自动下载”，可以先备份再清空模型目录：

```powershell
Move-Item models\Kokoro-82M models\_bak
.\run.ps1                 # 会重新下载全部 59 个文件并自动启动
# 确认无误后删除备份
Remove-Item -Recurse -Force models\_bak
```

---

## 9. 常见问题

**HuggingFace 连不上怎么办？**
`model_assets.py`（以及 `scripts/download_model.py`）默认走 ModelScope（国内可直连），失败才回退 HuggingFace；也可以 `--source hf` / `--source modelscope` 强制指定、`--only-core` 只下权重。脚本支持断点续传，中断后重跑即可。

**下载很慢或中途失败？**
日志里会打印每个文件的百分比与速度。可以：
① 换源重试 `.\.venv\Scripts\python scripts\download_model.py --source hf`；
② 直接重跑命令（已下好的文件按大小校验后跳过，不会重复下载）；
③ 手动下载 `hexgrad/Kokoro-82M` 的 `config.json`、`kokoro-v1_0.pth`、`voices/` 放进 `models/Kokoro-82M/` 即可（也可以放在别处，用 `KOKORO_MODEL_DIR` 指向）。

**想完全离线运行？**
准备好模型目录后，用 `server.py --no-download`（或 `cli.py --no-download`、`run.ps1 -SkipDownload`）启动；
或者预置 `KOKORO_MODEL_DIR` 指向已有模型，程序检测到文件齐全时根本不会发起网络请求。

**`pip install` 解析依赖时卡在编译 spacy / blis？**
先单独装 `spacy>=3.7,<4`（有 Python 3.13 的 wheel），再装其余依赖。**不要**安装 `spacy-curated-transformers>=2`——它会拖入 `spacy 4.0.0.dev3` 并触发源码编译。本项目不使用它（英文标注走 `trf=False`）。

**`transformers` 报 `huggingface-hub<1.0 is required`？**
`huggingface_hub` 被别的包升级到 2.x 了，执行
`.\.venv\Scripts\python -m pip install "huggingface_hub<1.0"` 即可。

**页面一直停在“加载失败”？**
遮罩层会直接显示后端给出的错误与建议命令。最常见的原因是模型文件缺失且下载失败（网络受限），按提示重试或换源即可；状态详情也可以直接看 `GET /api/status`。

**中文想更好听？**
v1.0 的中文音色官方评级为 D。官方另有 `Kokoro-82M-v1.1-zh`（100 个中文音色，质量明显更好），
可把该仓库同样下到 `models/Kokoro-82M-v1.1-zh/`，再用
`KModel(repo_id='hexgrad/Kokoro-82M-v1.1-zh', config=..., model=...)` 配合 `KPipeline(lang_code='z', repo_id='hexgrad/Kokoro-82M-v1.1-zh')` 使用——`repo_id` 不以 `/Kokoro-82M` 结尾时，misaki 会自动改用 v1.1 词表。

**想用 GPU？**
`.\.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cu124`，
引擎会自动检测（`KokoroTTS` 里 `device=None` 时选 cuda）。82M 模型在 CPU 上已经够快，GPU 收益有限。

**Windows PowerShell 拒绝执行 `run.ps1`？**
`powershell -ExecutionPolicy Bypass -File .\run.ps1`，或先 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。
`run.ps1` 已带 UTF-8 BOM，中文提示在 PowerShell 5.1 下也能正常显示。

---

## 10. 提交到 GitHub 前

- `.gitignore` 已忽略 **模型权重与大文件**：整个 `models/`（仅保留 `models/.gitkeep` 说明文件），
  以及 `*.pth/*.pt/*.onnx/*.safetensors/*.bin/*.zip/...`、下载临时文件 `*.part`、`outputs/`、`.venv/`、日志等。
- 因此仓库里只有代码与前端资源（几 MB），克隆后靠 `run.ps1`（或 `server.py` / `cli.py` 自身）自动补全模型。
- 提交前可以自查一下有没有漏网的大文件：

```powershell
git status --porcelain
git ls-files | Where-Object { $_ -like "models/*" }   # 正常应该只有 models/.gitkeep
```

---

## 11. 致谢与许可

- 模型：[hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)，Apache-2.0
- 推理与 G2P：[hexgrad/kokoro](https://github.com/hexgrad/kokoro)、[hexgrad/misaki](https://github.com/hexgrad/misaki)
- 音素化后端：[espeak-ng](https://github.com/espeak-ng/espeak-ng)
