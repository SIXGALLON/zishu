#!/usr/bin/env python3
"""自书 · 环境自检：这台电脑能做哪些事、缺了什么会怎样降级。

  python3 doctor.py            # 只检查
  python3 doctor.py --smoke    # 再用示例照片真跑一本（约 1 分钟），确认装好了
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import platform_kit as kit  # noqa: E402


def main():
    kit.utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="用 examples/ 里的示例照片和示例感受真跑一本")
    ap.add_argument("--out", help="冒烟测试的输出目录（默认临时目录）")
    a = ap.parse_args()

    print(f"自书 · 环境自检（{kit.SYSTEM}）\n")
    rows = kit.doctor()
    for name, st, info in rows:
        print(f"  {st} {name}：{info}")
    hard = [r for r in rows if r[1] == "✗"]
    print()
    if hard:
        print("✗ 有必需项缺失，先装好再出书：" + "、".join(r[0] for r in hard))
    else:
        print("✓ 可以出书。△ 的项目缺了也能跑，只是少一部分效果。")

    if a.smoke:
        if hard:
            sys.exit(1)
        ex = kit.SKILL / "examples"
        out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="zishu-smoke-"))
        print(f"\n冒烟测试 → {out}")
        r = subprocess.run([sys.executable, str(HERE / "zishu.py"), "--images", str(ex / "sample-input" / "images"),
                            "--feeling", str(ex / "feelings" / "示例-傍晚散步.json"), "--out", str(out)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(r.stdout[-2500:])
        if r.returncode:
            print(r.stderr[-2500:])
            sys.exit(r.returncode)
        need = ["zine.html", "plan.json"] + (["总览.jpg", "按页顺序.pdf", "骑马钉拼版.pdf"] if kit.browser().mode else [])
        miss = [n for n in need if not (out / n).exists()]
        checks = json.loads((out / "plan.json").read_text(encoding="utf-8"))["checks"]
        bad = [c[0] for c in checks if not c[1]]
        print(("✓ 冒烟测试通过" if not miss and not bad else "✗ 冒烟测试有问题") +
              (f"；缺文件：{miss}" if miss else "") + (f"；自检未过：{bad}" if bad else ""))
        sys.exit(1 if miss or bad else 0)


if __name__ == "__main__":
    main()
