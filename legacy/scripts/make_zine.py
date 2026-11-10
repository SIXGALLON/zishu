#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zine-maker 主程序（2026-11-04 22:21 后：视觉 v1，交互层保留）

给一堆图片 + 文字（或一份 story.json）→ 自动排出一本可打印的 zine。
风格语言来自 references/zine-dna.md + layout-catalog.md（v1）：近白暖纸 / 1 个高饱和色 /
白边贴纸式小图 / 圆形椭圆裁切 / 波点 / tiny 标签 / 手绘线 / 大量留白 / 跨页成对。
v2 的淡色极简与组合系统已归档，不再是生成依据。

两个入口：
  · 自动模式  plan_zine()   —— 页数驱动，图片按互质步长轮转
  · story 模式 plan_story() —— 用户摆的分组/顺序/原话/封面封底驱动排版；
                               引擎只读，不代写任何感受、地名、日期、印量

只用 Python 自带功能即可运行；Pillow（压缩与噪点纸）与 Chrome（出 PDF）都是可选增强。
输出：plan.json、版式清单.txt、zine.html、imposed.html、zine.pdf、imposed.pdf、README.txt；
      story 模式另有「文字来源对照.txt」。
"""
import argparse
import base64
import html
import io
import json
import math
import os
import struct
import subprocess
import sys
from collections import deque
from pathlib import Path

RUNTIME = {"noise": "", "speckle": ""}

# ---------------------------------------------------------------------------
# 0. 小工具（零依赖）
# ---------------------------------------------------------------------------

def jpeg_size(data):
    i, n = 2, len(data)
    while i < n - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
        if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seglen
    return None


def image_size(path):
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:2] == b"\xff\xd8":
            return jpeg_size(head) or (1, 1)
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", head[6:10])
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP" and head[12:16] == b"VP8 ":
            return (struct.unpack("<H", head[26:28])[0] & 0x3FFF,
                    struct.unpack("<H", head[28:30])[0] & 0x3FFF)
    except Exception:
        pass
    return (1, 1)


def mime_of(path):
    return {".png": "image/png", ".webp": "image/webp",
            ".gif": "image/gif"}.get(Path(path).suffix.lower(), "image/jpeg")


def data_uri(path):
    with open(path, "rb") as f:
        raw = f.read()
    return "data:%s;base64,%s" % (mime_of(path), base64.b64encode(raw).decode("ascii"))


def make_tiles():
    """生成两张极小的纸纹 tile，避免打印时把 SVG 滤镜栅格化成几十 MB。
    没有 Pillow 就返回空串，CSS 会回退到纯色背景。"""
    try:
        from PIL import Image
        import random
        rng = random.Random(11)
        # ① 细灰噪点（A / B 型）
        n = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        px = n.load()
        for y in range(96):
            for x in range(96):
                if rng.random() < .30:
                    v = rng.randint(90, 160)
                    px[x, y] = (v, v, v, rng.randint(14, 42))
        # ② 彩色斑点再生纸（C 型）
        s = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        sp = s.load()
        flecks = [(198, 168, 96), (150, 170, 130), (190, 120, 110),
                  (120, 140, 175), (170, 150, 120)]
        for _ in range(340):
            x, y = rng.randrange(120), rng.randrange(120)
            c = flecks[rng.randrange(len(flecks))]
            sp[x, y] = (c[0], c[1], c[2], rng.randint(60, 150))
        out = []
        for im in (n, s):
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            out.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"))
        return out[0], out[1]
    except Exception:
        return "", ""


def compress_images(images, out_dir, max_px=1200, quality=76):
    try:
        from PIL import Image
    except ImportError:
        print("  （没装 Pillow，跳过图片压缩，不影响排版）")
        return images
    cache = Path(out_dir) / "_assets"
    cache.mkdir(parents=True, exist_ok=True)
    result = []
    for i, im in enumerate(images, 1):
        dst = cache / ("%02d.jpg" % i)
        try:
            with Image.open(im["path"]) as src:
                pic = src.convert("RGB")
                pic.thumbnail((max_px, max_px), Image.LANCZOS)
                pic.save(dst, "JPEG", quality=quality, optimize=True)
            result.append(dict(im, path=str(dst)))
        except Exception:
            result.append(im)
    before = sum(os.path.getsize(i["path"]) for i in images)
    after = sum(os.path.getsize(i["path"]) for i in result)
    print("✓ 图片压缩：%.1f MB → %.1f MB" % (before / 1048576, after / 1048576))
    return result


# ---------------------------------------------------------------------------
# 1. 页序
# ---------------------------------------------------------------------------

def saddle_order(n):
    assert n % 4 == 0 and n >= 4, "页数必须是 4 的倍数且不少于 4"
    seq = []
    for i in range(n // 4):
        seq += [n - 2 * i, 2 * i + 1, 2 * i + 2, n - 2 * i - 1]
    return seq


def self_test():
    golden = {8: [8, 1, 2, 7, 6, 3, 4, 5],
              16: [16, 1, 2, 15, 14, 3, 4, 13, 12, 5, 6, 11, 10, 7, 8, 9]}
    for n, expected in golden.items():
        got = saddle_order(n)
        assert got == expected, "页序算错：%s" % got
        assert sorted(got) == list(range(1, n + 1))
        assert all(got[k] + got[k + 1] == n + 1 for k in range(0, n, 2))
    return True


# ---------------------------------------------------------------------------
# 2. 外观：五套风格，全部写成可判定参数
# ---------------------------------------------------------------------------

STYLES = {
    "field": {
        "label": "采集 / 散步记录（默认，最贴近参考）",
        "paper": "#FAF8F2", "paper2": "#E9F55C", "ink": "#2A2A28", "soft": "#8A857C",
        "accent": "#E9F55C", "accent2": "#3B7BE0",
        "dots": ["#F5D400", "#3B7BE0", "#E8462E", "#2FA84F"],
        "photo": "saturate(.92) contrast(1.04) brightness(1.02)",
        "title_font": "'Songti SC','STSong',Georgia,serif",
        "body_font": "'PingFang SC','Helvetica Neue',sans-serif",
        "tiny_font": "'Helvetica Neue',Arial,sans-serif",
        "round": True, "sticker": True, "hand": True, "speckle": False,
        "note": "近白暖纸、荧光黄绿块、四色圆点、圆形裁切、贴纸小图、时间地点 tiny 页眉。",
    },
    "colorblock": {
        "label": "色块拼贴",
        "paper": "#FFFFFF", "paper2": "#F5D400", "ink": "#1B1B1B", "soft": "#6B6B6B",
        "accent": "#2E6BE6", "accent2": "#6B1FA0",
        "dots": ["#2E6BE6", "#F5D400", "#3FA535", "#E08A1E"],
        "photo": "saturate(1.06) contrast(1.06)",
        "title_font": "'Arial Black','PingFang SC',sans-serif",
        "body_font": "'PingFang SC','Helvetica Neue',sans-serif",
        "tiny_font": "'Helvetica Neue',Arial,sans-serif",
        "round": True, "sticker": False, "hand": False, "speckle": False,
        "palette": ["#2E6BE6", "#F5D400", "#3FA535", "#E08A1E", "#6B1FA0", "#E8462E"],
        "note": "高饱和纯色与照片各占一半，小照片贴在色块上，2×2 单元感。",
    },
    "artbook": {
        "label": "艺术家书 / 豆本",
        "paper": "#F6EEDC", "paper2": "#F3E2B8", "ink": "#3A352B", "soft": "#8C8370",
        "accent": "#C9B98C", "accent2": "#E9EED8",
        "dots": ["#C9B98C", "#A9B79A", "#D3B7A0", "#8C8370"],
        "photo": "grayscale(1) contrast(1.35) sepia(.22)",
        "title_font": "'Songti SC','STSong',Georgia,serif",
        "body_font": "'Songti SC','STSong',Georgia,serif",
        "tiny_font": "Georgia,serif",
        "round": True, "sticker": False, "hand": True, "speckle": True,
        "note": "斑点再生纸、米黄淡绿色块、单个小物件、硫酸纸、80% 以上留白。",
    },
    "xerox": {
        "label": "黑白复印机 / 朋克",
        "paper": "#F7F6F1", "paper2": "#111111", "ink": "#111111", "soft": "#555555",
        "accent": "#111111", "accent2": "#111111",
        "dots": ["#111111", "#111111", "#111111", "#111111"],
        "photo": "grayscale(1) contrast(2.1) brightness(1.03)",
        "title_font": "'Courier New',monospace", "body_font": "'Courier New',monospace",
        "tiny_font": "'Courier New',monospace",
        "round": False, "sticker": True, "hand": True, "speckle": False,
        "note": "纯黑墨粉、死白死黑、打字机字、脏边和噪点。",
    },
    "riso": {
        "label": "Riso 双色套印",
        "paper": "#F5EEDC", "paper2": "#FF48B0", "ink": "#1D2A44", "soft": "#5A6480",
        "accent": "#FF48B0", "accent2": "#0078BF",
        "dots": ["#FF48B0", "#0078BF", "#F5D400", "#1D2A44"],
        "photo": "grayscale(1) contrast(1.8) sepia(1) hue-rotate(285deg) saturate(3)",
        "title_font": "'Arial Black','PingFang SC',sans-serif",
        "body_font": "'PingFang SC',sans-serif", "tiny_font": "Arial,sans-serif",
        "round": True, "sticker": True, "hand": False, "speckle": True,
        "note": "荧光粉 + 蓝两个专色、套印错位 2px、粗大标题。",
    },
}


# ---------------------------------------------------------------------------
# 3. CSS：用 {{占位符}} 替换，避免 CSS 里的百分号被格式化误伤
# ---------------------------------------------------------------------------

CSS_BASE = """
@page { size: {{PAGESIZE}}; margin: 0; }
* { box-sizing: border-box; }
html, body { margin:0; padding:0; }
body { background:#6E6B65; }
.page {
  width:148mm; height:210mm; position:relative; overflow:hidden;
  background:{{PAPER}}; color:{{INK}}; font-family:{{BODY}};
  print-color-adjust:exact; -webkit-print-color-adjust:exact;
  page-break-after:always; break-after:page; break-inside:avoid;
}
.page:last-child { page-break-after:auto; break-after:auto; }
.page::after {
  content:""; position:absolute; inset:0; pointer-events:none; z-index:6;
  background-image:url("{{NOISE}}"); background-repeat:repeat;
  mix-blend-mode:multiply; opacity:.55;
}
.page.speckle::after { background-image:url("{{SPECKLE}}"); opacity:.85; }
img { display:block; width:100%; height:100%; object-fit:cover; object-position:center;
      filter:{{PHOTO}}; }
.slot { position:relative; overflow:hidden; }
.full { position:absolute; inset:0; }
.grid { display:grid; height:100%; gap:3mm; padding:7mm; }
.g-one { grid-template:1fr / 1fr; }
.g-pair { grid-template:1fr / 1fr 1fr; }
.g-stack { grid-template:1fr 1fr / 1fr; }
.g-four { grid-template:1fr 1fr / 1fr 1fr; }
.g-nine { grid-template:1fr 1fr 1fr / 1fr 1fr 1fr; }

/* tiny 页眉：全本一致性靠它，不靠页码 */
.tiny { position:absolute; z-index:7; font-family:{{TINY}}; font-size:6.8pt;
        letter-spacing:.14em; text-transform:uppercase; color:{{SOFT}}; }
.tiny.top { top:6mm; left:8mm; right:8mm; display:flex; justify-content:space-between; }
.tiny.bottom { bottom:5mm; left:8mm; right:8mm; display:flex; justify-content:space-between; }
.tiny.vert { writing-mode:vertical-rl; top:8mm; left:6mm; letter-spacing:.22em; }

/* 贴纸式小图 */
.sticker { position:absolute; z-index:5; background:{{PAPER}};
           padding:1.6mm; box-shadow:0 1mm 2.5mm rgba(0,0,0,.20); }
.sticker img { width:100%; height:100%; object-fit:cover; }
.sticker.r1 { transform:rotate(-3deg); } .sticker.r2 { transform:rotate(2.5deg); }
.sticker.r3 { transform:rotate(-1.5deg); } .sticker.r4 { transform:rotate(4deg); }
.circle img, .circle { border-radius:50%; }
.oval img, .oval { border-radius:50% / 38%; }
.roundrect img, .roundrect { border-radius:9mm; }

/* 色块 */
.block { position:absolute; z-index:1; background:{{PAPER2}}; }
.block .cap { position:absolute; bottom:3mm; left:3mm; right:3mm; z-index:3;
              font-family:{{TINY}}; font-size:6.8pt; letter-spacing:.1em; color:{{INK}}; }
.block.alt { background:{{ACCENT2}}; }
.block.pale { background:{{ACCENT2}}; opacity:.55; }

/* 四色圆点 */
.dot { position:absolute; z-index:6; width:5.5mm; height:5.5mm; border-radius:50%; }
.dot.sm { width:3mm; height:3mm; }
/* 编号徽章 */
.badge { position:absolute; z-index:7; font-family:{{TINY}}; font-size:7pt;
         letter-spacing:.06em; background:{{ACCENT}}; color:{{INK}};
         padding:1mm 1.8mm; min-width:6mm; text-align:center; }
.badge.tri { clip-path:polygon(50% 0,100% 100%,0 100%); padding-top:3mm;
             background:{{ACCENT2}}; color:#fff; }
/* 手绘波浪线 */
.squiggle { position:absolute; inset:0; z-index:4; pointer-events:none;
            width:100%; height:100%; opacity:.75; }
/* 硫酸纸 */
.vellum { position:absolute; inset:0; z-index:5;
          background:rgba(255,255,255,.42); backdrop-filter:blur(.4mm); }

/* 文字 */
.quote { position:absolute; inset:0; display:flex; align-items:center;
         justify-content:center; padding:24mm 16mm; z-index:3; }
.quote div { font-family:{{TITLE}}; font-size:23pt; line-height:1.62;
             font-weight:600; text-align:center; }
.quote small { display:block; font-family:{{TINY}}; font-size:7pt; font-weight:400;
               letter-spacing:.16em; color:{{SOFT}}; margin-top:14mm; }
.note { position:absolute; z-index:5; font-size:8.4pt; line-height:1.8; color:{{INK}};
        max-width:52mm; }
.note.hand { font-family:{{TITLE}}; font-style:italic; }
.list { position:absolute; z-index:5; font-size:7.4pt; line-height:1.95; color:{{INK}}; }
.list li { list-style:none; } .list li::before { content:"• "; color:{{ACCENT2}}; }
.caption { position:absolute; left:8mm; right:8mm; bottom:9mm; z-index:5;
           font-size:8.2pt; line-height:1.7; color:{{INK}}; }
.caption.onphoto { color:#fff; text-shadow:0 0 3mm rgba(0,0,0,.9); }
.bigcap { position:absolute; z-index:5; font-family:{{TITLE}}; font-size:16pt;
          line-height:1.25; font-weight:700; letter-spacing:.02em; }

/* 封面 / 封底 */
.cover-title { position:absolute; z-index:7; left:9mm; bottom:14mm;
               font-family:{{TITLE}}; font-size:34pt; line-height:1.08;
               font-weight:700; letter-spacing:-.01em; color:#fff;
               text-shadow:0 0 7mm rgba(0,0,0,.7); }
.cover-title span { display:block; font-family:{{TINY}}; font-size:8pt;
                    font-weight:400; letter-spacing:.12em; margin-top:4mm; }
.back { position:absolute; inset:0; padding:26mm 14mm; z-index:3; font-size:9pt; line-height:2; }
.back h3 { font-family:{{TITLE}}; font-size:20pt; margin:0 0 8mm; font-weight:700; }
.back .rule { width:16mm; height:1px; background:{{ACCENT2}}; margin:7mm 0; }
.back .meta { color:{{SOFT}}; font-size:8pt; }
.back .stamp { margin-top:18mm; display:inline-block; padding:2.6mm 4mm;
               border:1px solid {{SOFT}}; font-family:{{TINY}}; font-size:7.5pt;
               letter-spacing:.14em; color:{{SOFT}}; transform:rotate(-3deg); }
/* 标本栏（FIELD_MAIN 右栏） */
.specimen { position:absolute; top:12mm; right:7mm; bottom:14mm; width:46mm; z-index:5; }
.specimen .item { position:relative; margin-bottom:4mm; text-align:center; }
.specimen .item .circle { width:24mm; height:24mm; margin:0 auto; overflow:hidden; }
.specimen .item .lbl { font-family:{{TINY}}; font-size:6.2pt; letter-spacing:.1em;
                       color:{{SOFT}}; margin-top:1mm; }
.folio { position:absolute; bottom:5mm; left:50%; transform:translateX(-50%);
         z-index:7; font-family:{{TINY}}; font-size:6.5pt; letter-spacing:.16em;
         color:{{SOFT}}; }

@media screen {
  body { padding:12mm 0; }
  .page { margin:0 auto 10mm; box-shadow:0 3mm 14mm rgba(0,0,0,.45); }
}
@media print { body { background:{{PAPER}}; padding:0; } .page { box-shadow:none; } }
"""

SHEET_CSS = """
.sheet { width:297mm; height:210mm; display:flex; position:relative;
         page-break-after:always; break-after:page; break-inside:avoid; }
.sheet:last-child { page-break-after:auto; break-after:auto; }
.half { width:148.5mm; height:210mm; position:relative; overflow:hidden; }
.sheet .page { page-break-after:auto !important; break-after:auto !important;
               margin:0 !important; box-shadow:none !important; }
.fold { position:absolute; left:148.5mm; top:0; bottom:0; width:.2mm;
        background:rgba(0,0,0,.10); z-index:9; }
@media screen { .sheet { margin:0 auto 10mm; box-shadow:0 3mm 14mm rgba(0,0,0,.45); background:#fff; } }
@media print { .fold { display:none; } }
"""


def css(style, sheet_mode=False):
    s = STYLES[style]
    rep = {
        "PAGESIZE": "297mm 210mm" if sheet_mode else "148mm 210mm",
        "PAPER": s["paper"], "PAPER2": s["paper2"], "INK": s["ink"],
        "SOFT": s["soft"], "ACCENT": s["accent"], "ACCENT2": s["accent2"],
        "PHOTO": s["photo"], "TITLE": s["title_font"],
        "BODY": s["body_font"], "TINY": s["tiny_font"],
        "NOISE": RUNTIME["noise"], "SPECKLE": RUNTIME["speckle"],
    }
    out = CSS_BASE
    for k, v in rep.items():
        out = out.replace("{{%s}}" % k, v)
    if not RUNTIME["noise"]:
        out = out.replace('background-image:url("");', "background-image:none;")
    return out + (SHEET_CSS if sheet_mode else "")


# ---------------------------------------------------------------------------
# 4. 决策树：把素材变成「每页放什么」
# ---------------------------------------------------------------------------

SKELETONS = [
    "FIELD_MAIN", "STICKERS", "SPREAD_FULL", "GRID_SMALL",
    "BLOCK_TRIO", "COLORBLOCK", "OVAL", "QUOTE", "ARTBOOK",
]


def split_long(t):
    """长文一律切成短句，不排成双栏文章（参考里几乎不存在长文页）。"""
    import re
    parts = [x.strip() for x in re.split(r"[。！？；\n]+", t) if len(x.strip()) > 4]
    return parts or [t[:40]]


def tkind(t):
    n = len(t.strip())
    return "quote" if n <= 16 else ("caption" if n <= 80 else "article")


def kind(im):
    r = im["w"] / max(im["h"], 1)
    return "L" if r >= 1.2 else ("P" if r <= .83 else "S")


NEED = {"FIELD_MAIN": 4, "STICKERS": 4, "SPREAD_FULL": 1, "GRID_SMALL": 4,
        "BLOCK_TRIO": 3, "COLORBLOCK": 2, "OVAL": 3, "QUOTE": 0, "ARTBOOK": 1}

ORDER_BY_STYLE = {
    "field": ["FIELD_MAIN", "STICKERS", "SPREAD_FULL", "BLOCK_TRIO", "GRID_SMALL",
              "QUOTE", "OVAL", "COLORBLOCK", "ARTBOOK"],
    "colorblock": ["COLORBLOCK", "GRID_SMALL", "STICKERS", "SPREAD_FULL", "QUOTE",
                   "BLOCK_TRIO", "OVAL", "FIELD_MAIN", "ARTBOOK"],
    "artbook": ["ARTBOOK", "QUOTE", "STICKERS", "SPREAD_FULL", "ARTBOOK", "QUOTE",
                "GRID_SMALL", "OVAL", "FIELD_MAIN"],
    "xerox": ["STICKERS", "SPREAD_FULL", "GRID_SMALL", "QUOTE", "FIELD_MAIN",
              "OVAL", "BLOCK_TRIO", "STICKERS", "ARTBOOK"],
    "riso": ["BLOCK_TRIO", "COLORBLOCK", "STICKERS", "SPREAD_FULL", "QUOTE",
             "OVAL", "GRID_SMALL", "FIELD_MAIN", "ARTBOOK"],
}


def plan_zine(images, texts, seed=7, style="field"):
    """按「页数驱动」而不是「图片耗尽驱动」。
    参考里同一批照片会以满版 / 圆形 / 贴纸等不同裁切反复出现，所以图片允许复用；
    这样每本才不会变成一半页面只有文字。"""
    # ① 文字池：长文一律切句，不排双栏文章
    quotes, captions = [], []
    for t in texts:
        k = tkind(t)
        if k == "article":
            bits = split_long(t)
            quotes.extend(bits[:2])
            captions.extend(bits[2:5])
        elif k == "quote":
            quotes.append(t)
        else:
            captions.append(t)
    if not quotes:
        quotes = ["（这一页留给没拍到的东西）"]
    if not captions:
        captions = [""]

    # ② 目标页数：按素材量估，8–20 页之间取 4 的倍数
    #    8 图 + 8 段文字 → 12 页；素材少时不硬凑，避免后半本重复前面版式
    total = max(8, min(20, math.ceil((len(images) * .6 + len(texts) * .3 + 4) / 4) * 4))
    half, inner = total // 2, total - 4
    order = ORDER_BY_STYLE.get(style, ORDER_BY_STYLE["field"])

    # 骨架序列按 seed 打乱分块，保证「同一版式不机械复现」
    rng = __import__("random").Random(seed)
    seq = []
    while len(seq) < inner:
        block = list(order)
        rng.shuffle(block)
        seq.extend(block)
    seq = seq[:inner]

    # ③ 图片按「与总数互质的步长」轮转，保证每张照片都轮得到，且同一 seed 完全可复现。
    #    旧版固定步长 7 与 14 不互质，单图页只会在 2 张图之间来回，多张照片永远用不上。
    cnt = len(images)
    stride = 3
    if cnt:
        while math.gcd(stride, cnt) != 1 and stride < cnt:
            stride += 1
        if stride >= cnt:
            stride = 1
    cursor = [seed % cnt] if cnt else [0]

    def pick(i, n):
        if not cnt or n == 0:
            return []
        out = []
        for _ in range(n):
            out.append(images[cursor[0] % cnt])
            cursor[0] += stride
        return out

    slots, qi, ci = [], 0, 0
    for i in range(inner):
        sk = seq[i]
        n = NEED[sk]
        if sk in ("QUOTE", "ARTBOOK"):
            a = quotes[qi % len(quotes)]
            qi += 1
            b = quotes[qi % len(quotes)]
            qi += 1
            txt = (a + "  ／  " + b) if (b and b != a) else a
            imgs = pick(i, n) if sk == "ARTBOOK" else []
        else:
            txt = captions[ci % len(captions)]
            ci += 1
            imgs = pick(i, n)
        slots.append({"skeleton": sk, "images": imgs, "text": txt, "role": "content"})

    front, rear = slots[:half - 2], slots[half - 2:]
    pages = [{"role": "cover", "skeleton": "COVER", "images": [], "text": ""}]
    pages += front
    pages += [{"role": "center_l", "skeleton": "SPREAD_L", "images": [], "text": ""},
              {"role": "center_r", "skeleton": "SPREAD_R", "images": [], "text": ""}]
    pages += rear
    pages.append({"role": "back", "skeleton": "BACK", "images": [], "text": ""})

    # ④ 固定角色：封面用第一张，中心跨页用最宽的一张左右各取一半
    if images:
        pages[0]["images"] = [images[0]]
    wide = next((im for im in images if kind(im) == "L" and im["w"] / max(im["h"], 1) >= 1.35), None)
    if wide is None:
        wide = next((im for im in images if kind(im) == "L"), images[0] if images else None)
    if wide:
        pages[half - 1]["images"] = [wide]
        pages[half]["images"] = [wide]

    # ⑤ 同一种骨架不连着出现三次
    image_skeletons = set(SKELETONS) - {"QUOTE", "ARTBOOK"}
    for i in range(2, len(pages)):
        sk = pages[i]["skeleton"]
        if sk not in image_skeletons:
            continue
        if sk == pages[i - 1]["skeleton"] == pages[i - 2]["skeleton"]:
            pages[i]["skeleton"] = "STICKERS" if sk != "STICKERS" else "GRID_SMALL"

    for idx, p in enumerate(pages, 1):
        p["page"] = idx
    return {"total_pages": total, "seed": seed, "style": style, "pages": pages}


# ---------------------------------------------------------------------------
# 4b. story 模式：用户自己摆好的分组/顺序/原话/封面封底，直接驱动排版
#     这是「交互保留」的落地层。视觉仍是 v1 的骨架库，只是「谁先谁后、哪张跟哪张」
#     不再由随机数决定。引擎只读，不临场补写任何感受、地名或日期。
# ---------------------------------------------------------------------------

BAD_SOURCES = {"", "unfilled", "pending", "ai_guess", "user_confirmed_guess_pending"}


def _list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _text(v):
    return "" if v is None else str(v).strip()


def load_story(path):
    if not path or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_story(story, images):
    """兼容两种 story 写法，并守住「没确认的猜测不印进册子」：

    ① 摆台.html「下载 story.json」：cover/back 是字符串、ungrouped、confirmed/pending 是计数
    ② 对话草稿（interaction.md）：cover/back 是对象、order 是组 id 列表、dropped 是数组
    """
    def resolve(tok):
        t = _text(tok)
        if not t:
            return None
        for i, im in enumerate(images):
            if t == im["name"]:
                return i
        stem = Path(t).stem
        for i, im in enumerate(images):
            if stem and stem == Path(im["name"]).stem:
                return i
        if t.isdigit() and 1 <= int(t) <= len(images):
            return int(t) - 1
        return None

    def trusted(v, src):
        # 没标 source 的，视为 story.json 里人自己写的内容；显式标了「待确认/未填」的一律不印
        if src is None:
            return bool(_text(v))
        return (_text(src) not in BAD_SOURCES) and bool(_text(v))

    raw = list(story.get("groups") or [])
    order = story.get("order")
    if order:
        by_id = {(_text(g.get("id")) or str(i + 1)): g for i, g in enumerate(raw)}
        raw = [by_id[_text(o)] for o in order if _text(o) in by_id]

    groups, used = [], set()
    for i, g in enumerate(raw):
        idxs = []
        for tok in _list(g.get("images")):
            k = resolve(tok)
            if k is not None and k not in idxs:
                idxs.append(k)
        if not idxs:
            continue
        used.update(idxs)
        name_ok = trusted(g.get("name"), g.get("name_source"))
        note_ok = trusted(g.get("note"), g.get("note_source"))
        groups.append({
            "id": _text(g.get("id")) or chr(65 + i),
            "name": _text(g.get("name")) if name_ok else "",
            "name_pending": _text(g.get("name")) if not name_ok else "",
            "note": _text(g.get("note")) if note_ok else "",
            "note_pending": _text(g.get("note")) if not note_ok else "",
            "images": [images[k] for k in idxs],
            "indexes": idxs,
            "leftover": False,
        })

    # 「划掉」与「没归组、先不用」都尊重用户取舍；完全没提到的照片才补进尾组，
    # 这样既不会替她做主，也不会出现「有一张照片整本没露面」。
    excluded = set()
    for tok in _list(story.get("dropped")) + _list(story.get("ungrouped")):
        k = resolve(tok)
        if k is not None:
            excluded.add(k)
    left = [k for k in range(len(images)) if k not in used and k not in excluded]
    if left:
        groups.append({"id": "—", "name": "", "name_pending": "", "note": "",
                       "note_pending": "", "images": [images[k] for k in left],
                       "indexes": left, "leftover": True})

    def side(v, default_layout):
        d = v if isinstance(v, dict) else {"image": v}
        k = resolve(d.get("image"))
        ttl_ok = trusted(d.get("title"), d.get("title_source"))
        sub_ok = trusted(d.get("sub"), d.get("sub_source"))
        txt_ok = trusted(d.get("text"), d.get("text_source"))
        return {
            "image_index": k,
            "image": images[k] if k is not None else None,
            "layout": _text(d.get("layout")) or default_layout,
            "title": _text(d.get("title")) if ttl_ok else "",
            "sub": _text(d.get("sub")) if sub_ok else "",
            "text": _text(d.get("text")) if txt_ok else "",
            "title_pending": _text(d.get("title")) if not ttl_ok else "",
            "text_pending": _text(d.get("text")) if not txt_ok else "",
        }

    try:
        breath = max(0, min(4, int(story.get("breath") or 0)))
    except (TypeError, ValueError):
        breath = 0
    return {"groups": groups, "dropped": sorted(excluded), "cover": side(story.get("cover") or {}, "photo_full"),
            "back": side(story.get("back") or {}, "breath"), "breath": breath,
            "confirmed": story.get("confirmed"), "pending": story.get("pending")}


def _evenly_insert(seq, holes, make_marker):
    """把留白页/补页均匀撒在各组之间，不要全堆在册子末尾。"""
    gaps = len(seq) + 1
    base, extra = divmod(max(0, holes), gaps)
    counts = [base + (1 if i < extra else 0) for i in range(gaps)]
    out = []
    for i in range(gaps):
        out.extend(make_marker(j) for j in range(counts[i]))
        if i < len(seq):
            out.append(seq[i])
    return out


def plan_story(images, st, seed=7, style="field"):
    """按用户摆好的顺序排版：同一组照片连续、组内相邻不拆散、组之间可留白。
    视觉骨架仍完全取自 v1 的 ORDER_BY_STYLE；只额外避开用户圈出的三种「组合」。"""
    groups = st["groups"]
    if not groups:
        return plan_zine(images, [], seed=seed, style=style)

    rng = __import__("random").Random(seed)
    order = ORDER_BY_STYLE.get(style, ORDER_BY_STYLE["field"])
    cov, bak = st["cover"], st["back"]
    half_candidates = [k for k in range(len(images)) if k not in st["dropped"]]
    specified = {k for k in (cov["image_index"], bak["image_index"]) if k is not None}

    # ① 中心跨页：两张「不同」的照片各占左右一页，不是同一张左右复制。
    #    避开用户指定的封面／封底图，否则那张会被算到 3 次，越过「最多 2 次」的底线。
    big = max(groups, key=lambda g: len(g["indexes"]))
    pool = [k for k in big["indexes"] if k in half_candidates and k not in specified]
    pair = pool[:2]
    if len(pair) < 2:
        pair += [k for k in half_candidates
                 if k not in pair and k not in specified][:2 - len(pair)]
    pair = pair[:2]

    # ② 每组至少一页；照片超过 4 张再拆第二页
    primary = []
    for gi, g in enumerate(groups):
        for j in range(max(1, math.ceil(len(g["indexes"]) / 4))):
            primary.append({"gi": gi, "mode": "primary" if j == 0 else "revisit", "hole": None})

    breath = st["breath"]
    total = max(8, min(28, math.ceil((len(primary) + breath + 4) / 4) * 4))
    inner = total - 4
    half = total // 2
    # 多出来的页一律做留白，不拿旧照片凑数（用户明确说过不要重复图）
    auto_breath = max(0, inner - len(primary) - breath)
    auto_flags = [False] * breath + [True] * auto_breath
    marker = iter(auto_flags)
    slots = _evenly_insert(primary, len(auto_flags),
                           lambda j: {"hole": "breath", "auto": next(marker),
                                      "gi": None, "mode": "breath"})
    slots = slots[:inner]
    while len(slots) < inner:
        slots.append({"hole": "breath", "auto": True, "gi": None, "mode": "breath"})

    gi_cycle = 0
    for sp in slots:
        if sp["hole"] == "revisit":
            sp["gi"] = gi_cycle % len(groups)
            sp["mode"] = "revisit"
            gi_cycle += 1
        elif sp["hole"] == "breath":
            sp["gi"] = None
            sp["mode"] = "breath"

    # ③ 每张照片全本最多 2 次；取图与骨架都受这个上限约束，用尽就留白
    usage = {k: 0 for k in range(len(images))}
    for k in pair:
        usage[k] = usage.get(k, 0) + 1
    cursor = [seed % len(order)]
    prev_sk = [None]
    last_by_group = {}

    def choose(n, has_note, forbid):
        # 关键：优先挑「刚好装得下这一组所有照片」的骨架，
        # 否则一组 4 张图可能被塞进只要 2 张的版式，剩下 2 张整本不出现。
        cands = []
        for step in range(len(order)):
            sk = order[(cursor[0] + step) % len(order)]
            if NEED[sk] == 0 or NEED[sk] > n:
                continue
            if sk == "QUOTE" and not has_note:
                continue
            if sk == "GRID_SMALL" and prev_sk[0] in ("GRID_SMALL", "STICKERS"):
                continue                                   # 禁：等大徽章阵列连着出现
            if sk == forbid:
                continue                                   # 同一组第二页必须换角色
            cands.append((NEED[sk], -step, sk))
        if not cands:
            return "QUOTE" if has_note else "BREATH"
        best_need = max(c[0] for c in cands)
        pool = [c for c in cands if c[0] == best_need]
        pool = [c for c in pool if c[2] != prev_sk[0]] or pool
        best = pool[0]
        cursor[0] = (cursor[0] - best[1] + 1) % len(order)
        return best[2]

    def render(sp):
        if sp["mode"] == "breath":
            return {"role": "content", "skeleton": "BREATH", "images": [], "text": "",
                    "group": "", "label": "", "auto": sp.get("auto", True),
                    "layout": "", "story_mode": True}
        g = groups[sp["gi"]]
        has_note = bool(g["note"]) and sp["mode"] == "primary"
        avail = [k for k in g["indexes"] if usage.get(k, 0) < 2]
        sk = choose(min(4, len(avail)), has_note, last_by_group.get(sp["gi"]))
        need = NEED.get(sk, 0)
        chosen = avail[:need]
        if len(chosen) < need:                       # 图不够就降级骨架，绝不硬凑重复
            alt = [x for x in order if 0 < NEED[x] <= len(chosen) and x != last_by_group.get(sp["gi"])]
            sk = alt[0] if alt else ("QUOTE" if has_note else "BREATH")
            need = NEED.get(sk, 0)
            chosen = chosen[:need]
        for k in chosen:
            usage[k] = usage.get(k, 0) + 1
        prev_sk[0] = sk
        last_by_group[sp["gi"]] = sk
        return {"role": "content", "skeleton": sk, "images": [images[k] for k in chosen],
                "text": g["note"] if has_note else "",
                "group": ("" if g["leftover"] else g["id"]),
                "label": g["name"], "auto": sp["hole"] == "revisit", "layout": "",
                "story_mode": True}

    front, rear = slots[:half - 2], slots[half - 2:]

    cover_imgs = []
    if cov["image"]:
        cover_imgs.append(cov["image"])
    elif half_candidates:                              # 用户没定封面：用第 1 张，并在清单里明说
        cover_imgs.append(images[half_candidates[0]])
    if cov["layout"] == "paper_collage":
        # 补的贴纸不能碰中心跨页用过的图，也不能碰用户指定的封底图，
        # 否则同一张会凑到 3 次，越过「最多 2 次」的底线。
        for k in half_candidates:
            if len(cover_imgs) >= 3:
                break
            if k in pair or k in specified:
                continue
            if images[k] not in cover_imgs:
                cover_imgs.append(images[k])

    pages = [{"role": "cover", "skeleton": "COVER", "images": cover_imgs, "text": cov["title"],
              "group": "", "label": "", "auto": not bool(cov["image"]), "layout": cov["layout"]}]
    pages += [render(sp) for sp in front]
    pages += [{"role": "center_l", "skeleton": "SPREAD_L", "images": [images[pair[0]]] if pair else [],
               "text": "", "group": big["id"] if not big["leftover"] else "", "label": "",
               "auto": False, "layout": ""},
              {"role": "center_r", "skeleton": "SPREAD_R", "images": [images[pair[1]]] if len(pair) > 1 else [],
               "text": "", "group": big["id"] if not big["leftover"] else "", "label": "",
               "auto": False, "layout": ""}]
    pages += [render(sp) for sp in rear]
    pages.append({"role": "back", "skeleton": "BACK",
                  "images": [bak["image"]] if bak["image"] else [],
                  "text": bak["text"], "group": "", "label": "", "auto": False,
                  "layout": bak["layout"]})

    # ④ v1 节奏兜底：不许整本方方正正。
    #    若一个骨架重复出现，把靠后的那一页换成白边贴纸（倾斜、圆形、圆角都回来），
    #    这样既去掉重复、又保住「圆形/椭圆/贴纸/手绘线」这些第一版的玩心。
    content = [p for p in pages if p["role"] == "content" and p["skeleton"] != "BREATH"]
    counts = {}
    for p in content:
        counts[p["skeleton"]] = counts.get(p["skeleton"], 0) + 1
    if not any(p["skeleton"] == "STICKERS" for p in content):
        dup = next((sk for sk, c in counts.items() if c > 1 and sk in ("FIELD_MAIN", "GRID_SMALL")), None)
        cand = ([p for p in content if p["skeleton"] == dup] if dup else
                [p for p in content if len(p["images"]) >= 2 and p["skeleton"] != "QUOTE"])
        if cand:
            cand[-1]["skeleton"] = "STICKERS"
    round_skeletons = {"STICKERS", "FIELD_MAIN", "OVAL", "BLOCK_TRIO", "ARTBOOK", "GRID_SMALL"}
    if sum(1 for p in content if p["skeleton"] in round_skeletons) < 2:
        for p in content:
            if p["skeleton"] in ("GRID_SMALL", "COLORBLOCK") and len(p["images"]) >= 3:
                p["skeleton"] = "OVAL"
                break

    for idx, p in enumerate(pages, 1):
        p["page"] = idx
    seen = {}
    for p in pages:
        for im in p["images"]:
            seen[im["name"]] = seen.get(im["name"], 0) + 1
    return {
        "total_pages": total, "seed": seed, "style": style, "mode": "story", "pages": pages,
        "story": {
            "groups": [{"id": g["id"], "name": g["name"] or "（未确认，留白）",
                        "pending_name": g["name_pending"], "pending_note": g["note_pending"],
                        "images": [images[k]["name"] for k in g["indexes"]]} for g in groups],
            "dropped": [images[k]["name"] for k in st["dropped"]],
            "cover": {"image": cov["image"]["name"] if cov["image"] else "（自动取第 1 张）",
                      "layout": cov["layout"], "title": cov["title"]},
            "back": {"image": bak["image"]["name"] if bak["image"] else "",
                     "layout": bak["layout"], "text": bak["text"]},
            "breath_pages": breath,
            "image_usage": seen,
            "confirmed": st["confirmed"], "pending": st["pending"],
        },
    }


# ---------------------------------------------------------------------------
# 5. 渲染：把一页的「计划」翻译成这一页长什么样
# ---------------------------------------------------------------------------

def img_tag(im, cls=""):
    return '<img src="%s" class="%s" alt="">' % (data_uri(im["path"]), cls)


def dots_html(style, seed):
    s = STYLES[style]
    pos = [(18, 26), (72, 18), (84, 62), (26, 74), (58, 88), (12, 55)]
    out = ""
    for i, (x, y) in enumerate(pos):
        c = s["dots"][(i + seed) % len(s["dots"])]
        sm = " sm" if i % 3 == 0 else ""
        out += ('<div class="dot%s" style="left:%d%%;top:%d%%;background:%s"></div>'
                % (sm, x, y, c))
    return out


def squiggle(style, seed):
    if not STYLES[style]["hand"]:
        return ""
    c = STYLES[style]["accent2"]
    return ('<svg class="squiggle" viewBox="0 0 148 210" preserveAspectRatio="none">'
            '<path d="M2 %d C 30 %d, 48 %d, 72 %d S 120 %d, 146 %d" fill="none" '
            'stroke="%s" stroke-width=".35" stroke-dasharray="1.5 2"/>'
            '<path d="M0 %d Q 40 %d, 74 %d T 148 %d" fill="none" stroke="%s" '
            'stroke-width=".25" opacity=".7"/></svg>'
            % (40 + seed % 20, 30 + seed % 15, 62 + seed % 12, 48 + seed % 18,
               30 + seed % 14, 58 + seed % 20, c,
               150 - seed % 18, 140 + seed % 12, 158 - seed % 16, 145 + seed % 10, c))


def tiny(meta, page_no, style, extra=True, label=None):
    labels = meta.get("labels") or []
    # story 模式：该页所属组若已被用户确认命名，就用她的名字当 tiny 标签；
    # 没确认就退回中性的 FRAME 0x，绝不把 AI 猜的组名印上去。
    label = label or (labels[(page_no - 1) % len(labels)] if labels else
                      "%s · %02d" % (meta.get("issue", ""), page_no))
    out = '<div class="tiny top"><span>%s</span><span>%s</span></div>' % (
        html.escape(label), html.escape(meta.get("short_issue", "")))
    if extra:
        out += '<div class="tiny bottom"><span>%s</span><span>%02d</span></div>' % (
            html.escape(meta.get("credit", "SELF PUBLISHED")), page_no)
    return out


def page_html(p, style, total, meta):
    sk = p["skeleton"]
    imgs = p.get("images", [])
    txt = html.escape(p.get("text", "")).strip()
    s = STYLES[style]
    no = p["page"]
    seed = no + (meta.get("seed_offset", 0) or 0)
    inner = ""

    if sk == "COVER":
        # 封面性格可由 story 指定：photo_full（默认满版）/ paper_collage（错落贴纸）/ plain（纯纸）
        layout = p.get("layout") or "photo_full"
        if layout == "paper_collage":
            poses = [(10, 12, 46, 34, "r1"), (48, 7, 40, 28, "r3"), (26, 46, 44, 30, "r2")]
            for i, im in enumerate(imgs[:3]):
                x, y, w, h, rc = poses[i]
                inner += ('<div class="sticker %s" style="left:%d%%;top:%d%%;width:%d%%;height:%d%%">%s</div>'
                          % (rc, x, y, w, h, img_tag(im)))
            inner += squiggle(style, seed)
        elif layout == "plain":
            inner = '<div class="block pale" style="inset:0"></div>'
        else:
            inner = '<div class="full">%s</div>' % (img_tag(imgs[0]) if imgs else "")
        inner += dots_html(style, seed) if s["round"] else ""
        # 封面文字没填就整行留白，不拿 UNTITLED 之类的占位句补
        if txt:
            tone = "" if layout == "photo_full" else (' style="color:%s;text-shadow:none"' % s["ink"])
            inner += '<div class="cover-title"%s>%s<span>%s</span></div>' % (
                tone, txt, html.escape(meta.get("subtitle", "")))
        inner += '<div class="tiny top"><span>%s</span><span>%s</span></div>' % (
            html.escape(meta.get("issue", "")), html.escape(meta.get("short_issue", "")))

    elif sk in ("SPREAD_L", "SPREAD_R"):
        cls = "spread-l" if sk == "SPREAD_L" else "spread-r"
        inner = '<div class="full %s">%s</div>' % (cls, img_tag(imgs[0]) if imgs else "")
        inner += dots_html(style, seed)
        inner += squiggle(style, seed)
        inner += '<div class="tiny top"><span>%s</span></div>' % html.escape(meta.get("issue", ""))
        inner += '<div class="badge" style="right:9mm;top:14mm">%02d</div>' % no

    elif sk == "SPREAD_FULL":
        inner = '<div class="full">%s</div>' % (img_tag(imgs[0]) if imgs else "")
        inner += dots_html(style, seed) + squiggle(style, seed)
        if txt:
            inner += '<div class="caption onphoto">%s</div>' % txt
        inner += '<div class="badge tri" style="left:10mm;bottom:18mm">%d</div>' % (no % 9 + 1)

    elif sk == "FIELD_MAIN":
        # 左 2/3 大图 + 右 1/3 标本栏（参考图 9 的核心版式）
        left = '<div class="slot" style="position:absolute;left:0;top:0;bottom:0;width:66%%">%s</div>' \
               % (img_tag(imgs[0]) if imgs else "")
        items = ""
        for i, im in enumerate(imgs[1:4]):
            items += ('<div class="item"><div class="circle">%s</div>'
                      '<div class="lbl">%s %02d</div></div>'
                      % (img_tag(im), html.escape(meta.get("tag", "FIELD")), i + 1))
        right = '<div class="specimen">%s</div>' % items
        if txt:
            # story 模式：用户原话整段保留，不切成两半、不用「—」补空行
            right += ('<div class="list" style="right:8mm;bottom:12mm;width:45mm">'
                      '<li>%s</li></div>' % txt)
        inner = left + right + dots_html(style, seed) + squiggle(style, seed)
        inner += '<div class="tiny vert">%s</div>' % html.escape(meta.get("vert_title", meta["title"]))
        inner += '<div class="badge" style="right:7mm;top:6mm">%d</div>' % (no % 9 + 1)

    elif sk == "STICKERS":
        # 白底 + 3–5 张带白边小图错落贴 + 短句
        pos = [(8, 12, 34, 26), (52, 8, 38, 24), (12, 46, 30, 30),
               (50, 42, 42, 28), (20, 76, 34, 18)]
        for i, im in enumerate(imgs[:5]):
            x, y, w, h = pos[i]
            rc = "r%d" % (i % 4 + 1)
            shape = "circle" if (s["round"] and i % 3 == 0) else ("roundrect" if s["round"] else "")
            inner += ('<div class="sticker %s %s" style="left:%d%%;top:%d%%;width:%d%%;height:%d%%">'
                      '<div class="%s" style="width:100%%;height:100%%;overflow:hidden">%s</div></div>'
                      % (rc, shape, x, y, w, h, shape, img_tag(im)))
        inner += squiggle(style, seed)
        if txt:
            inner += '<div class="note hand" style="left:10%%;bottom:12%%;max-width:60%%">%s</div>' % txt
        inner += '<div class="tiny top"><span>%s</span><span>%02d:%02d</span></div>' % (
            html.escape(meta.get("issue", "")), 9 + no % 10, (no * 7) % 60)

    elif sk == "BLOCK_TRIO":
        # story 模式且本页没有用户原话时，色块退回纸色＋一道细线：
        # 不再构成「大高饱和填空色块＋圆图＋无真实文字」那种被圈掉的摆法，
        # 但圆图、错落、编号这些 v1 元素都还在（禁的是摆法，不是元素）。
        if p.get("story_mode") and not txt:
            inner = ('<div class="block" style="left:0;right:0;top:52%%;bottom:0;'
                     'background:%s;border-top:.2mm solid %s"></div>'
                     % (s["paper"], s["soft"]))
        else:
            inner = '<div class="block" style="left:0;right:0;top:52%;bottom:0"></div>'
        inner += '<div class="full" style="bottom:48%%">%s</div>' % (img_tag(imgs[0]) if imgs else "")
        for i, im in enumerate(imgs[1:4] or imgs[:3]):
            inner += ('<div class="circle" style="position:absolute;z-index:3;top:57%%;'
                      'left:%d%%;width:26%%;height:19%%;overflow:hidden">%s</div>'
                      % (8 + i * 31, img_tag(im)))
            inner += ('<div class="tiny" style="top:78%%;left:%d%%;font-size:6pt">%s</div>'
                      % (8 + i * 31, html.escape(["REST & TALK", "SPORTS & READING", "PEACE & QUIET"][i])))
        inner += '<div class="tiny top"><span>%s</span></div>' % html.escape(meta.get("issue", ""))
        inner += dots_html(style, seed) if style == "field" else ""
        if txt:
            # 有色块＋圆图的页必须有真实文字，否则就是用户圈的第二种坏摆法
            inner += ('<div class="note" style="left:8%%;bottom:8%%;max-width:82%%;'
                      'z-index:5;font-size:8pt">%s</div>' % txt)

    elif sk == "COLORBLOCK":
        pal = s.get("palette", [s["paper2"], s["accent2"]])
        c1 = pal[(no - 1) % len(pal)]
        c2 = pal[(no + 2) % len(pal)]
        inner = ('<div class="grid g-pair" style="padding:0;gap:0">'
                 '<div class="slot">%s</div>'
                 '<div class="slot" style="background:%s;position:relative">'
                 '  <div style="position:absolute;left:14%%;top:16%%;width:56%%;height:36%%;'
                 '  padding:1.4mm;background:#fff">%s</div>'
                 '  <div class="tiny" style="left:12%%;bottom:10%%;max-width:70%%;font-size:6.4pt;'
                 '  letter-spacing:0;text-transform:none;line-height:1.5;color:#111">%s</div>'
                 '</div></div>' % (img_tag(imgs[0]) if imgs else "", c1,
                                   img_tag(imgs[1]) if len(imgs) > 1 else "", txt))
        inner += '<div class="badge" style="left:4mm;top:4mm;background:%s">%02d</div>' % (c2, no)

    elif sk == "OVAL":
        inner = '<div class="full" style="background:%s"></div>' % s["ink"]
        inner += ('<div class="oval" style="position:absolute;z-index:2;left:8%%;top:14%%;'
                  'width:84%%;height:54%%;overflow:hidden">%s</div>' % (img_tag(imgs[0]) if imgs else ""))
        for i, im in enumerate(imgs[1:3]):
            inner += ('<div class="sticker r%d" style="left:%d%%;top:74%%;width:26%%;height:18%%">%s</div>'
                      % (i + 1, 12 + i * 42, img_tag(im)))
        inner += '<div class="badge tri" style="right:9%%;top:8%%">%d</div>' % (no % 9 + 1)
        if txt:
            inner += '<div class="note" style="left:10%%;bottom:5%%">%s</div>' % txt

    elif sk == "GRID_SMALL":
        n = 4 if len(imgs) <= 4 else 9
        cls = "g-four" if n == 4 else "g-nine"
        cells = ""
        for i, im in enumerate(imgs[:n]):
            sh = "circle" if (s["round"] and i % 4 == 0) else ("roundrect" if s["round"] else "")
            cells += ('<div class="slot %s" style="overflow:hidden">%s'
                      '<div class="tiny" style="left:1mm;bottom:1mm;font-size:5.8pt;color:#fff;'
                      'text-shadow:0 0 2mm #000">%02d</div></div>' % (sh, img_tag(im), i + 1))
        inner = '<div class="grid %s" style="padding:14mm 9mm 18mm">%s</div>' % (cls, cells)
        inner += dots_html(style, seed) if style == "field" else ""
        if txt:
            inner += '<div class="caption">%s</div>' % txt

    elif sk == "QUOTE":
        inner = ('<div class="quote"><div>%s<small>%s</small></div></div>'
                 % (txt, html.escape(meta.get("issue", ""))))
        inner += dots_html(style, seed) if s["round"] else ""

    elif sk == "ARTBOOK":
        inner = '<div class="block pale" style="left:0;right:0;top:38%;bottom:0"></div>'
        inner += '<div class="vellum" style="inset:auto;left:16%;top:14%;width:48%;height:44%"></div>'
        if imgs:
            inner += ('<div class="circle" style="position:absolute;z-index:4;left:30%%;top:28%%;'
                      'width:34%%;height:24%%;overflow:hidden">%s</div>' % img_tag(imgs[0]))
        inner += ('<div class="note" style="right:12%%;bottom:16%%;max-width:46%%;'
                  'font-size:7.4pt">%s</div>' % txt)
        inner += '<div class="tiny vert">%s</div>' % html.escape(meta.get("vert_title", meta["title"]))

    elif sk == "BREATH":
        # 用户要的留白页 / 页数凑 4 的倍数时自动补的呼吸页。
        # 不是纯白空页：留纸色、一条手绘线、一个圆点、一致的 tiny 页眉。
        inner = '<div class="block pale" style="left:0;right:0;top:0;height:1.2mm"></div>'
        inner += squiggle(style, seed)
        inner += dots_html(style, seed) if s["round"] else ""

    elif sk == "BACK":
        # 封底不写死任何用户没提供的信息（作者、印量、赠语）；留空就不渲染那一行。
        author = html.escape(meta.get("author", ""))
        credit_line = ("图片与文字：%s<br>" % author) if author else ""
        edition = html.escape(meta.get("edition", ""))
        stamp_html = ('<div class="stamp">%s</div>' % edition) if edition else ""
        colophon = html.escape(meta.get("colophon", "自出版"))
        # 风格 label 里的括号是给终端日志看的（如「（默认，最贴近参考）」），不该印在册子上
        style_label = s["label"].split("（")[0].strip()
        title_html = ('<h3>%s</h3><div class="rule"></div>'
                      % html.escape(meta["title"])) if meta.get("title") else ""
        # 用户为封底指定了图：贴在下半部，不盖住留白；layout=breath 则只留纸
        back_img = ""
        if imgs and (p.get("layout") or "breath") != "breath":
            back_img = ('<div class="slot" style="position:absolute;left:14mm;right:14mm;'
                        'bottom:16mm;height:50mm;z-index:2">%s</div>' % img_tag(imgs[0]))
        user_line = ('<div class="note" style="left:14mm;top:54mm;max-width:100mm;'
                     'font-size:9pt;z-index:5">%s</div>' % txt) if txt else ""
        # 纯拼接：用户文字里哪怕有 % 或 {} 也不会被当成格式符
        inner = ('<div class="block" style="left:0;right:0;bottom:0;height:26%"></div>'
                 + back_img + user_line
                 + '<div class="back">' + title_html + credit_line
                 + '规格：A5 · 骑马钉 · ' + str(total) + ' 页 · ' + html.escape(style_label)
                 + '<div class="meta" style="margin-top:12mm">'
                 + html.escape(meta.get("issue", "")) + '<br>' + colophon + '</div>'
                 + stamp_html + '</div>')
    else:
        inner = '<div class="quote"><div>%s</div></div>' % txt

    # 一致性元素：除封面/封底/引文页外，每页都有 tiny 页眉
    if sk not in ("COVER", "BACK", "QUOTE", "SPREAD_L", "SPREAD_R", "FIELD_MAIN", "STICKERS", "ARTBOOK"):
        inner += tiny(meta, no, style, label=p.get("label") or None)
    speckle = " speckle" if s["speckle"] else ""
    return '<div class="page%s">%s</div>' % (speckle, inner)


def build_html(pages, style, meta, imposed=False):
    total = len(pages)
    body = ""
    if imposed:
        seq = saddle_order(total)
        by_no = {p["page"]: p for p in pages}
        for k in range(0, len(seq), 2):
            body += '<div class="sheet"><div class="fold"></div>'
            for pn in seq[k:k + 2]:
                body += '<div class="half">%s</div>' % page_html(by_no[pn], style, total, meta)
            body += '</div>'
        hint = "拼版预览：每张 A4 横向纸放两页，双面短边翻转打印，折起来就是一本。"
    else:
        for p in pages:
            body += page_html(p, style, total, meta)
        hint = "阅读版：一页一页往下翻。打印请用 imposed.pdf。"

    screen_title = html.escape(meta.get("title") or "未命名 zine")
    toolbar = ('<div class="toolbar" style="position:fixed;top:0;left:0;right:0;z-index:99;'
               'background:#222;color:#fff;padding:7px 14px;font:12px sans-serif">'
               '%s ｜ %s ｜ 共 %d 页 ｜ %s ｜ 打印时这行会消失</div>'
               % (screen_title, html.escape(hint), total,
                  html.escape(STYLES[style]["label"])))
    return ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<title>%s</title><style>%s @media print{.toolbar{display:none!important}}</style>"
            "</head><body>%s%s</body></html>"
            % (screen_title, css(style, imposed), toolbar, body))


# ---------------------------------------------------------------------------
# 6. 出 PDF
# ---------------------------------------------------------------------------

def find_chrome():
    from shutil import which
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium"):
        if os.path.exists(c):
            return c
    for c in ("google-chrome", "chromium", "chromium-browser"):
        if which(c):
            return c
    return None


def print_pdf(chrome, html_path, pdf_path):
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--no-pdf-header-footer", "--virtual-time-budget=10000",
           "--print-to-pdf=%s" % str(pdf_path), "file://%s" % str(html_path)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        return pdf_path.exists() and pdf_path.stat().st_size > 1000
    except Exception as e:
        print("  （PDF 生成失败：%s）" % e)
        return False


def check_pdf_size(pdf_path, expect):
    import re
    pat = re.compile(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)")
    try:
        with open(pdf_path, "rb") as f:
            tail = b""
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                m = pat.search(tail + chunk)
                if m:
                    w, h = float(m.group(1)), float(m.group(2))
                    return ("%.0f x %.0f pt" % (w, h),
                            abs(w - expect[0]) < 12 and abs(h - expect[1]) < 12)
                tail = chunk[-256:]
    except Exception:
        pass
    return "读不到", False


# ---------------------------------------------------------------------------
# 7. 主流程
# ---------------------------------------------------------------------------

def load_texts(path, default_meta):
    meta = dict(default_meta)
    if path is None or not Path(path).exists():
        return meta, []
    p = Path(path)
    if p.suffix.lower() == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in ("title", "issue", "subtitle", "author", "labels", "credit",
                  "short_issue", "tag", "vert_title", "place2",
                  "edition", "colophon"):
            if k in d:
                meta[k] = d[k]
        texts = [str(t).strip() for t in d.get("texts", []) if str(t).strip()]
    else:
        texts = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return meta, texts


def write_text_audit(plan, st, meta, images):
    """story 模式专用：册子上出现的每一个字都标出来源，便于逐条回查「有没有编造」。"""
    L = ["文字来源对照（story 模式）", "=" * 44, "",
         "原则：册子上的文字只有两类——① 你给的原话（一字不改）；② 版式自带的功能性标记。",
         "脚本不代写感受、不写虚构地名／日期／期号／作者／印量；没给的地方一律留白。", "",
         "一、印出来的用户原话（逐页可回查 story.json）"]
    hit = 0
    for p in plan["pages"]:
        if p.get("text"):
            hit += 1
            src = {"cover": "cover.title", "back": "back.text"}.get(
                p["role"], "groups[%s].note" % (p.get("group") or "未归组"))
            L.append("  第 %2d 页｜%-11s｜「%s」" % (p["page"], p["skeleton"], p["text"]))
            L.append("      来源：story.json → %s｜原样，未润色、未扩写、未截断" % src)
    if meta.get("subtitle"):
        hit += 1
        L.append("  封面副标题｜「%s」｜来源：story.json → cover.sub｜原样" % meta["subtitle"])
    if not hit:
        L.append("  （这本没有印任何用户原话：story.json 的 note / cover.title / back.text 都未填，")
        L.append("    按「没填就留白」处理，不是漏排。聊出来后填进 story.json 重跑即可。）")

    L += ["", "二、版式自带的功能性文字（不是文案，也不是从照片里读出来的）",
          "  · FRAME 01…06：tiny 页眉标签，按页轮流出现，来自 texts.json labels[]／脚本默认值",
          "  · PHOTOS：中性题材标记，不是期号",
          "  · 页号 01/02…：由页序计算，不是拍摄日期或编号",
          "  · 规格：A5 · 骑马钉 · N 页 · 风格／自出版：装订信息，由脚本生成",
          "  · 竖排小字、FIELD 01 等标本编号：v1 版式装饰"]
    if any(p["skeleton"] == "STICKERS" for p in plan["pages"]):
        L.append("  · STICKERS 页的 09:xx 样式时间戳：由页码算出，不是真实拍摄时间")
    if any(p["skeleton"] == "BLOCK_TRIO" for p in plan["pages"]):
        L.append("  · REST & TALK / SPORTS & READING / PEACE & QUIET：v1 BLOCK_TRIO 装饰标签，")
        L.append("    与照片内容无关，不是从照片里读出来的；story 模式下本页若没有你的原话，")
        L.append("    下半部色块会退回纸色＋细线，避免「大色块＋圆图＋无文字」的坏摆法")
    if meta.get("author") or meta.get("edition"):
        L.append("  · 作者／印量：来自 story.json 的 author / edition，用户明确提供才出现")

    L += ["", "三、故意没有印出来的（等你说，或等你确认）"]
    for g in st["groups"]:
        if g["name_pending"]:
            L.append("  组 %s 的名字「%s」：标为待确认，没印；确认后把 name_source 改成 user_verbatim"
                     % (g["id"], g["name_pending"]))
        if g["note_pending"]:
            L.append("  组 %s 的话「%s」：标为待确认，没印" % (g["id"], g["note_pending"]))
        if not g["name"] and not g["name_pending"]:
            L.append("  组 %s：没起名字，该页 tiny 标签退回中性的 FRAME 0x" % g["id"])
    if st["cover"]["title_pending"]:
        L.append("  封面标题「%s」：标为待确认，没印" % st["cover"]["title_pending"])
    if not st["cover"]["title"] and not st["cover"]["title_pending"]:
        L.append("  封面标题：未填，封面不显示标题（不是用 UNTITLED 占位）")
    if st["back"]["text_pending"]:
        L.append("  末页文字「%s」：标为待确认，没印" % st["back"]["text_pending"])
    if not st["back"]["text"] and not st["back"]["text_pending"]:
        L.append("  末页文字：未填，末页只有留白与装订规格")

    L += ["", "四、回查方法",
          "  plan.json → pages[].text 是这一页实际印出的字；story → groups[] 是你摆的决定。",
          "  版式清单.txt 列出每页骨架、该页属于哪一组、哪些页是我补的。",
          "  照片编号沿用 images/ 里的文件名（01.jpg…），按数组下标可无损回查。",
          "", "生成时间不在册子上（脚本不写日期）；本文件是交付说明，不会被印进 zine。"]
    return "\n".join(L) + "\n"


README_TXT = """这本 zine 是怎么印出来的
============================

1. 打开 zine.html —— 阅读版，一页一页往下翻，先在屏幕上看顺不顺眼。
2. 想改版式：打开「版式清单.txt」看每页放什么；plan.json 里可以直接改
   某一页的 skeleton（例如 FIELD_MAIN 改成 STICKERS），改完重跑脚本。
3. 要打印：用 imposed.pdf（页码已按折纸顺序排好）。打印设置三件事缺一不可：
   · 双面打印，翻面选「短边翻转」
   · 缩放选「100% / 实际大小」，不要选「适合页面」
   · 关掉打印机自带的「小册子 / booklet」模式
4. 先只打第一张，对折核对封面与封底是否在同一张纸两面，再打整本。
5. 整叠对折，沿书脊订两枚订书钉（骑马钉）。

页数必须是 4 的倍数：一张纸对折正好提供 4 页。脚本会自动补「呼吸页」。

换风格：--style field（采集记录，默认）/ colorblock（色块拼贴）/
        artbook（艺术家书）/ xerox（黑白复印）/ riso（双色套印）。

如果先「摆」过（摆台.html 或对话里说好了分组）：
  加 --story /绝对路径/story.json，脚本会照你的分组顺序排版：
  · 同一组的照片连着出现，不拆散
  · dropped / ungrouped 里的照片不参与
  · cover.image / cover.title / cover.sub / cover.layout 定封面
  · back.image / back.text / back.layout 定末页
  · 每组的 note 原样放在该组第一页，不润色、不扩写
  · 标了「待确认 / unfilled」的组名与文案不会印，只留白
  · breath 是你指定的留白页数；为凑 4 的倍数自动补的页会在版式清单里写明
  没写文字的地方一律留白，这是故意的，不是漏排。

关于体积：PDF 由浏览器直接导出，内嵌了照片，文件会偏大；
只分享/预览用 zine.html 即可，需要用 macOS「预览」打开 PDF 后
选「文件 → 导出 → 缩小文件大小」可显著减小。
"""


def main():
    ap = argparse.ArgumentParser(description="给图片和文字，自动排一本可打印的 zine")
    ap.add_argument("--images", default="examples/sample-input/images")
    ap.add_argument("--texts", default="examples/sample-input/texts.json")
    ap.add_argument("--story", default=None,
                    help="摆台.html 下载的 story.json，或对话里写好的分组草稿")
    ap.add_argument("--out", default="out")
    ap.add_argument("--style", default="field", choices=list(STYLES.keys()))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()

    self_test()
    print("✓ 页序自检通过（8 页 / 16 页对照表）")

    RUNTIME["noise"], RUNTIME["speckle"] = make_tiles()

    img_dir = Path(args.images)
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    files = sorted([p for p in img_dir.iterdir() if p.suffix.lower() in exts]) if img_dir.exists() else []
    if not files:
        print("× 没找到图片：%s" % img_dir.resolve())
        sys.exit(1)
    images = []
    for p in files:
        w, h = image_size(p)
        images.append({"path": str(p), "name": p.name, "w": w, "h": h,
                       "dir": "横" if w / max(h, 1) >= 1.2 else ("竖" if w / max(h, 1) <= .83 else "方")})
    print("✓ 读到 %d 张图片（%s）" % (len(images), "、".join(i["dir"] for i in images)))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    images = compress_images(images, out)

    # 默认一律中性：绝不把示例里的地名、期号、作者、日期印到用户照片上。
    # 想要具体信息，请由用户在 texts.json 里显式提供。
    default_meta = {
        "title": "UNTITLED", "subtitle": "",
        "issue": "PHOTOS", "short_issue": "PHOTOS",
        "author": "", "credit": "", "edition": "", "colophon": "自出版",
        "tag": "FIELD", "vert_title": "UNTITLED", "place2": "",
        "labels": ["FRAME 01", "FRAME 02", "FRAME 03",
                   "FRAME 04", "FRAME 05", "FRAME 06"],
        "seed_offset": args.seed,
    }
    meta, texts = load_texts(args.texts, default_meta)
    meta.setdefault("seed_offset", args.seed)

    story_raw = load_story(args.story)
    st = None
    if story_raw:
        st = normalize_story(story_raw, images)
        cov = st["cover"]
        # story 模式：册子上出现的字只来自 story.json 里明确给过、且已确认的内容。
        # texts.json 这一层只当「规格参数」用（作者 / 印量 / 版权行），绝不当文案用，
        # 免得把示例文件夹里的「一个普通人 / 第 01 期」印到用户照片上。
        meta.update({
            "title": cov["title"], "subtitle": cov["sub"], "vert_title": cov["title"],
            "author": _text(story_raw.get("author")),
            "edition": _text(story_raw.get("edition")),
            "colophon": _text(story_raw.get("colophon")) or "自出版",
            "issue": "PHOTOS", "short_issue": "PHOTOS",
            # 把 texts.json 可能带进来的示例字段全部清回中性，避免串味
            "credit": "", "tag": "FIELD", "place2": "",
            "labels": ["FRAME 01", "FRAME 02", "FRAME 03",
                       "FRAME 04", "FRAME 05", "FRAME 06"],
        })
        print("✓ 读到 story.json：%d 组／划掉 %d 张／指定留白 %d 页"
              % (len(st["groups"]), len(st["dropped"]), st["breath"]))
        plan = plan_story(images, st, seed=args.seed, style=args.style)
        texts = []   # 用户原话只从 story.groups[].note 取，不混进示例句
    else:
        print("✓ 读到 %d 段文字（长文会自动切成短句）" % len(texts))
        plan = plan_zine(images, texts, seed=args.seed, style=args.style)

    total = plan["total_pages"]
    print("✓ 排成 %d 页（4 的倍数，骑马钉刚好）｜风格：%s｜模式：%s"
          % (total, STYLES[args.style]["label"], "story（我摆的）" if st else "自动"))

    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    brief = []
    for p in plan["pages"]:
        bits = []
        if p["images"]:
            bits.append("%d 张图" % len(p["images"]))
        if p.get("text"):
            bits.append("文字「%s」" % p["text"][:18])
        tag = []
        if p.get("group"):
            tag.append("组 %s" % p["group"])
        if p["skeleton"] == "BREATH":
            tag.append("留白页")
        if p.get("auto"):
            tag.append("〔封面图没指定，暂用第 1 张，你可以换〕" if p["role"] == "cover"
                       else "〔我补的页，你可以说换掉〕")
        brief.append("第 %d 页：%-12s %s%s"
                     % (p["page"], p["skeleton"], " + ".join(bits) or "（空）",
                        "　｜　" + "、".join(tag) if tag else ""))
    if st:
        brief += ["", "──── 我摆好的顺序 ────"]
        for g in plan["story"]["groups"]:
            brief.append("组 %s｜%s｜照片 %s"
                         % (g["id"], g["name"], " ".join(g["images"])))
        usage = plan["story"]["image_usage"]
        missing = [i["name"] for i in images if i["name"] not in usage]
        over = [k for k, v in usage.items() if v > 2]
        twice = [k for k, v in usage.items() if v == 2]
        brief += ["", "──── 每张照片出现次数 ────",
                  "、".join("%s×%d" % (k, v) for k, v in sorted(usage.items())) or "（无）",
                  "没用上的照片：" + ("、".join(missing) or
                                     "无（%d/%d 全用上）" % (len(usage), len(images))),
                  "出现 2 次的照片（第二次换了角色：封面／中心跨页 ≠ 组内小图）：" +
                  ("、".join(sorted(twice)) or "无") + "；你可以说去掉",
                  ("⚠ 超过 2 次，需要改：" + "、".join(sorted(over)) if over else "✓ 没有超过 2 次的照片"),
                  "划掉／先不用的：" + ("、".join(plan["story"]["dropped"]) or "无"),
                  "留白页：你指定 %d 页，其余为凑 4 的倍数自动补（上面标〔我补的〕）"
                  % plan["story"]["breath_pages"]]
    (out / "版式清单.txt").write_text("\n".join(brief), encoding="utf-8")
    for line in brief:
        print("   " + line)

    if st:
        (out / "文字来源对照.txt").write_text(
            write_text_audit(plan, st, meta, images), encoding="utf-8")

    zine_html, imposed_html = out / "zine.html", out / "imposed.html"
    zine_html.write_text(build_html(plan["pages"], args.style, meta, False), encoding="utf-8")
    imposed_html.write_text(build_html(plan["pages"], args.style, meta, True), encoding="utf-8")
    print("✓ 已生成网页：zine.html / imposed.html")

    if not args.no_pdf:
        chrome = find_chrome()
        if not chrome:
            print("  （没找到 Chrome，跳过 PDF；网页仍可在浏览器里打印）")
        else:
            for src, dst, expect, label in (
                (zine_html, out / "zine.pdf", (420, 595), "阅读版 A5"),
                (imposed_html, out / "imposed.pdf", (842, 595), "打印版 A4 横向"),
            ):
                if print_pdf(chrome, src.resolve(), dst.resolve()):
                    size, good = check_pdf_size(dst, expect)
                    print("✓ %s：%.1f MB ｜ 页面 %s ｜ %s"
                          % (label, dst.stat().st_size / 1048576, size,
                             "尺寸正确" if good else "尺寸可能不对"))

    (out / "README.txt").write_text(README_TXT, encoding="utf-8")
    print("✓ 打印说明：README.txt")
    print("\n完成。先看 %s，满意了再印 %s。" % (zine_html, out / "imposed.pdf"))


if __name__ == "__main__":
    main()
