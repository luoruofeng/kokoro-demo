"""把 Kokoro-82M 模型（权重 + 54 个音色 + 说明文档）下载到项目内的 models/Kokoro-82M。

默认从 ModelScope（国内可直连）拉取，失败时回退到 HuggingFace。
已存在且大小与远端一致的文件会跳过，中断后重跑即可续传。
真正的实现在项目根目录的 model_assets.py，这里只是命令行外壳
（server.py / cli.py / run.ps1 都会自动调用同一套逻辑）。

用法：
    python scripts/download_model.py                # 下载/补齐全部资源
    python scripts/download_model.py --check        # 只检查，缺文件则返回码 3
    python scripts/download_model.py --only-core    # 只下 config + 权重
    python scripts/download_model.py --source hf    # 强制走 HuggingFace
    python scripts/download_model.py --quiet        # 只输出结果
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_assets import (  # noqa: E402
    ConsoleReporter,
    default_model_dir,
    disk_usage,
    ensure_assets,
    human,
    missing_assets,
)


def print_check(model_dir: Path) -> int:
    info = disk_usage(model_dir)
    print(f"模型目录：{info['model_dir']}")
    print(
        f"文件：{info['files_present']}/{info['files_expected']} 个"
        f"，音色 {info['voices_present']}/{info['voices_expected']} 个"
        f"，占用 {human(info['bytes'])}"
    )
    if info["ready"]:
        print("状态：完整 ✅（无需下载）")
        return 0
    print(f"状态：缺少 {len(info['missing'])} 个文件 ❌")
    for path in info["missing"][:10]:
        print(f"  - {path}")
    if len(info["missing"]) > 10:
        print(f"  ... 其余 {len(info['missing']) - 10} 个")
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(
        description="下载 Kokoro-82M 权重与音色（可断点续传）",
    )
    parser.add_argument("--out", type=Path, default=None, help="模型存放目录")
    parser.add_argument("--source", choices=("auto", "modelscope", "hf"), default="auto")
    parser.add_argument("--only-core", action="store_true", help="只下载 config 与权重")
    parser.add_argument("--check", action="store_true", help="只检查文件是否齐全")
    parser.add_argument("--quiet", action="store_true", help="不打印逐文件进度")
    args = parser.parse_args()

    model_dir = Path(args.out) if args.out else default_model_dir()

    if args.check:
        if args.quiet and not missing_assets(model_dir):
            return 0
        return print_check(model_dir)

    reporter = ConsoleReporter(enabled=not args.quiet)
    try:
        report = ensure_assets(
            model_dir=model_dir,
            source=args.source,
            only_core=args.only_core,
            on_progress=reporter,
        )
    finally:
        reporter.finish()

    if report.needed_download or not report.verified:
        print(report.summary())
    if report.verified:
        print(f"模型目录：{report.model_dir}")
        return 0
    print("下载失败，可换源或稍后重试：--source hf", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
