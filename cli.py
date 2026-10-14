"""命令行版的 Kokoro-82M 多语言 TTS Demo。

常用命令：
    python cli.py --list                          # 查看支持的语言与音色
    python cli.py --lang z --text "你好世界"       # 合成中文
    python cli.py --lang a --text "Hello" --play  # 合成后立刻播放（Windows）
    python cli.py --demo                          # 每种语言各合成一条示例并依次播放
    python cli.py --demo --no-play                # 只生成文件，不播放

模型文件缺失时会自动下载（可加 --no-download 关闭）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK，这里强制 UTF-8，避免中文/表情报错
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent

from kokoro_tts import get_engine
from languages import DEFAULT_VOICE, LANG_BY_CODE
from model_assets import ConsoleReporter, ensure_assets

OUTPUT_DIR = ROOT / "outputs"


def ensure_model(allow_download: bool = True) -> None:
    """检查本地模型，缺文件就自动下载，下载完再继续执行。"""
    reporter = ConsoleReporter()
    try:
        report = ensure_assets(allow_download=allow_download, on_progress=reporter)
    finally:
        reporter.finish()
    if report.needed_download:
        print(f"[模型] {report.summary()}")
    if not report.verified:
        raise SystemExit(f"[模型] {report.error or '模型文件不完整'}")


def play_wav(path: Path) -> None:
    """用系统播放器播放 wav；Windows 下用 winsound 同步播放。"""
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
    else:
        print(f"    （请手动播放：{path}）")


def print_catalog() -> None:
    print("Kokoro-82M 支持的语言与音色：\n")
    for code, meta in LANG_BY_CODE.items():
        voices = "、".join(f"{name}[{grade}]" for _, name, _, grade, _ in meta["voices"])
        print(f"  {code}  {meta['flag']} {meta['name']}（{meta['english']}）")
        print(f"      G2P：{meta['g2p']}")
        print(f"      默认音色：{DEFAULT_VOICE.get(code)}")
        print(f"      音色：{voices}\n")


def synthesize(text: str, lang: str, voice: str | None, speed: float, out: Path | None) -> Path:
    engine = get_engine()
    if not engine.loaded:
        print("首次运行，正在加载模型（约 3~8 秒）...")
    started = time.perf_counter()
    speech = engine.synthesize(text, lang, voice=voice, speed=speed)
    waited = time.perf_counter() - started

    if out is None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = OUTPUT_DIR / f"cli_{stamp}_{lang}_{speech.voice}.wav"
    speech.save(out)
    print(
        f"  {LANG_BY_CODE[lang]['flag']} {LANG_BY_CODE[lang]['name']:<8} "
        f"{speech.voice:<14} 音频 {speech.seconds:5.2f}s | 用时 {waited:5.2f}s | "
        f"RTF {speech.rtf:4.2f} | 切块 {speech.chunks} | {out.name}"
    )
    return out


def run_demo(no_play: bool, speed: float) -> int:
    engine = get_engine()
    print("== 加载模型 ==")
    engine.load()
    engine.warm_up()
    print(f"模型加载完成，用时 {engine.load_seconds:.2f}s，设备 {engine.device}\n")

    print("== 逐语言合成示例 ==")
    files: list[Path] = []
    for code in LANG_BY_CODE:
        sample = LANG_BY_CODE[code]["samples"][0]
        try:
            files.append(synthesize(sample, code, None, speed, None))
        except Exception as exc:  # noqa: BLE001
            print(f"  {code} 合成失败：{exc}")

    print(f"\n共生成 {len(files)} 个音频文件，目录：{OUTPUT_DIR}")
    if not no_play:
        print("\n== 依次播放（Ctrl+C 可中断）==")
        for path in files:
            print(f"  播放 {path.name}")
            play_wav(path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Kokoro-82M 多语言 TTS Demo（命令行）")
    parser.add_argument("--list", action="store_true", help="列出支持的语言与音色")
    parser.add_argument("--lang", default="z", help="语言代码：a/b/e/f/h/i/p/j/z")
    parser.add_argument("--text", default="", help="要朗读的文本")
    parser.add_argument("--voice", default=None, help="音色 id，如 zf_xiaoxiao / af_heart")
    parser.add_argument("--speed", type=float, default=1.0, help="语速，0.6~1.6")
    parser.add_argument("--out", type=Path, default=None, help="输出 wav 路径")
    parser.add_argument("--play", action="store_true", help="合成后立即播放")
    parser.add_argument("--demo", action="store_true", help="每种语言各合成一条示例")
    parser.add_argument("--no-play", action="store_true", help="配合 --demo 使用时只生成不播放")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="缺少模型文件时不自动下载（离线使用或已有本地模型）",
    )
    args = parser.parse_args()

    if args.list:
        print_catalog()
        return 0

    # 执行前先确保模型可用：缺什么补什么，下完继续跑
    ensure_model(allow_download=not args.no_download)

    if args.demo:
        return run_demo(args.no_play, args.speed)

    if not args.text:
        parser.error("请用 --text 指定要朗读的文本，或使用 --demo / --list")

    if args.lang not in LANG_BY_CODE:
        parser.error(f"不支持的语言代码 {args.lang}，可选：{'/'.join(LANG_BY_CODE)}")

    path = synthesize(args.text, args.lang, args.voice, args.speed, args.out)
    if args.play:
        play_wav(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
