#!/usr/bin/env python3
"""自书 · 一键安装：把这个 skill 装进你电脑上的各个 AI 终端，并准备好依赖和开源字体。

  python3 install.py                 # 装进检测到的所有终端（Claude Code / Codex / Gemini CLI / WorkBuddy）
  python3 install.py --only claude,codex
  python3 install.py --project .     # 装进某个项目（.agents/skills 与 .claude/skills），团队共享
  python3 install.py --copy          # 复制而不是建链接（Windows 没有开发者模式时自动改用复制）
  python3 install.py --no-fonts --no-deps
  python3 install.py --uninstall     # 只删除本脚本建的链接 / 复制品，不碰源文件夹

各终端读 skill 的位置（官方文档）：
  Claude Code  ~/.claude/skills/<name>/SKILL.md
  Codex        ~/.agents/skills/<name>/SKILL.md（项目内为 .agents/skills）
  Gemini CLI   ~/.gemini/skills/<name>/SKILL.md
  WorkBuddy    ~/.workbuddy/skills/<name>/SKILL.md
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
NAME = "zishu"
MARK = ".zishu-installed-copy"       # 复制安装时留的记号：卸载只删带记号的目录
HOME = Path.home()
TARGETS = {
    "claude":    ("Claude Code", HOME / ".claude" / "skills", HOME / ".claude"),
    "codex":     ("Codex", HOME / ".agents" / "skills", HOME / ".codex"),
    "gemini":    ("Gemini CLI", HOME / ".gemini" / "skills", HOME / ".gemini"),
    "workbuddy": ("WorkBuddy", HOME / ".workbuddy" / "skills", HOME / ".workbuddy"),
}


def say(*a):
    print(*a, flush=True)


def same(p):
    try:
        return p.resolve() == SRC
    except Exception:
        return False


def place(dst_root, copy):
    dst = dst_root / NAME
    if same(dst):
        return "已就绪（就是源文件夹或已链接）"
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink():
            dst.unlink()                       # 旧链接，直接换
        elif (dst / MARK).exists():
            shutil.rmtree(dst)                 # 本脚本以前复制的，换新
        else:
            return f"跳过：{dst} 已存在且不是本脚本装的，没动它"
    dst_root.mkdir(parents=True, exist_ok=True)
    if not copy:
        try:
            os.symlink(SRC, dst, target_is_directory=True)
            return f"已链接 → {dst}"
        except OSError:
            pass                               # Windows 无权限建链接
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dst / MARK).write_text(str(SRC), encoding="utf-8")
    return f"已复制 → {dst}（以后更新要重新运行 install.py）"


def remove(dst_root):
    dst = dst_root / NAME
    if dst.is_symlink() and same(dst):
        dst.unlink()
        return f"已删除链接 {dst}"
    if dst.exists() and (dst / MARK).exists():
        shutil.rmtree(dst)
        return f"已删除复制品 {dst}"
    return None


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="安装「自书」skill")
    ap.add_argument("--only", help="逗号分隔：" + ",".join(TARGETS))
    ap.add_argument("--all", action="store_true", help="没检测到的终端也装（先建好目录）")
    ap.add_argument("--project", help="装进某个项目目录（.agents/skills 与 .claude/skills）")
    ap.add_argument("--copy", action="store_true")
    ap.add_argument("--no-deps", action="store_true", help="不装 Python 依赖")
    ap.add_argument("--no-fonts", action="store_true", help="不下载开源字体（约 95 MB）")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()

    if a.project:
        p = Path(a.project).resolve()
        roots = [("项目 · Codex / 通用", p / ".agents" / "skills"), ("项目 · Claude Code", p / ".claude" / "skills")]
    else:
        keys = [k.strip() for k in a.only.split(",")] if a.only else list(TARGETS)
        roots = []
        for k in keys:
            if k not in TARGETS:
                sys.exit(f"不认识的终端：{k}（可选 {', '.join(TARGETS)}）")
            label, root, probe = TARGETS[k]
            if a.only or a.all or probe.exists():
                roots.append((label, root))
            else:
                say(f"  · {label}：没检测到（{probe} 不存在），跳过；要装请加 --all 或 --only {k}")

    say(f"\n自书 skill 源文件夹：{SRC}\n")
    for label, root in roots:
        r = remove(root) if a.uninstall else place(root, a.copy)
        say(f"  {label:<14} {r or '没有本脚本装的东西'}")
    if a.uninstall:
        return

    if not a.no_deps:
        say("\n安装 Python 依赖（Pillow 必需；fonttools、brotli 用来把字体打包进成品）…")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(SRC / "requirements.txt")])
        say("  ✓ 完成" if r.returncode == 0 else "  ! pip 安装失败：请手动运行 pip install -r requirements.txt")

    sys.path.insert(0, str(SRC / "scripts"))
    import platform_kit as kit
    if not a.no_fonts:
        say(f"\n下载开源字体到 {kit.shared_font_dir()}（只需一次）…")
        res = kit.fetch_fonts()
        bad = [k for k, v in res.items() if not v]
        say("  ✓ 字体就绪" if not bad else f"  ! 这些没下成：{bad}（会退到系统字体；可稍后重跑 install.py）")

    say("\n环境自检：")
    for name, st, info in kit.doctor():
        say(f"  {st} {name}：{info}")
    say("\n装好了。在任意终端里对 AI 说「把这些照片做成一本小册子」即可；"
        "也可以显式调用：Claude Code 用 /zishu，Codex 用 $zishu。\n"
        f"想确认能跑：python3 {SRC / 'scripts' / 'doctor.py'} --smoke")


if __name__ == "__main__":
    main()
