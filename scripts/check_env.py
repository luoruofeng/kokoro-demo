"""检查运行环境是否就绪（供 run.ps1 调用，也可以单独运行）。

用法：
    python scripts/check_env.py          # 检查 Python 依赖是否齐全（齐全返回 0）
    python scripts/check_env.py --spacy  # 只检查英文 G2P 需要的 en_core_web_sm
    python scripts/check_env.py --json   # 以 JSON 输出检查结果
    python scripts/check_env.py --quiet  # 只返回退出码，不打印（供 run.ps1 使用）

之所以单独做成脚本，是为了让 run.ps1 不必把 Python 代码塞进命令行参数里
（PowerShell 5.1 传参时会吞掉内嵌引号，容易踩坑）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys

# 跑通本项目（Web + CLI + 9 种语言）所需的模块
REQUIRED = [
    "torch",
    "numpy",
    "soundfile",
    "requests",
    "fastapi",
    "uvicorn",
    "kokoro",
    "misaki",
    "spacy",
    "phonemizer",
    "espeakng_loader",
    "jieba",
    "pypinyin",
    "pyopenjtalk",
]

SPACY_MODEL = "en_core_web_sm"


def missing_modules() -> list[str]:
    return [name for name in REQUIRED if importlib.util.find_spec(name) is None]


def spacy_model_ready() -> tuple[bool, str]:
    try:
        import spacy
    except Exception as exc:  # noqa: BLE001
        return False, f"spacy 未安装（{exc}）"
    try:
        spacy.load(SPACY_MODEL)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Kokoro Demo 运行环境")
    parser.add_argument("--spacy", action="store_true", help="只检查 en_core_web_sm")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--quiet", action="store_true", help="不打印，只用退出码表示结果")
    args = parser.parse_args()

    if args.spacy:
        ok, reason = spacy_model_ready()
        if args.quiet:
            pass
        elif args.json:
            print(json.dumps({"ok": ok, "reason": reason}, ensure_ascii=False))
        elif ok:
            print(f"{SPACY_MODEL} 已安装")
        else:
            print(f"{SPACY_MODEL} 不可用：{reason}")
        return 0 if ok else 1

    missing = missing_modules()
    ok = not missing
    if args.quiet:
        pass
    elif args.json:
        print(json.dumps({"ok": ok, "missing": missing}, ensure_ascii=False))
    elif ok:
        print("依赖完整")
    else:
        print("缺少依赖：" + "、".join(missing))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
