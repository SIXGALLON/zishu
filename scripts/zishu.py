#!/usr/bin/env python3
"""自书 · 主命令
照片 + 「那天的感觉」(feeling.json) → 一本 zine：阅读版、两种 PDF、每个跨页的截图、设计旁注、文字来源、读回。

  python3 zishu.py --images DIR --feeling feeling.json --out OUT
  python3 zishu.py --images DIR --feeling feeling.json --out OUT --pick      # 看图二选一：6 组 A/B 对照图

任何终端（Claude Code / Codex / Gemini CLI / WorkBuddy …）、任何系统都用这一条。
必需：Python 3.9+ 与 Pillow。可选：Chrome/Edge/Chromium 或 Playwright（截图/PDF）、fontTools（字体子集）、
macOS Vision 或 rembg（抠图）。缺什么、会怎样降级，运行 doctor.py 查看。"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PIL import Image, ImageDraw, ImageFont, ImageStat, ImageFilter  # noqa: E402

import platform_kit as kit  # noqa: E402
import fx  # noqa: E402
import feel  # noqa: E402
import spreads as S  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# ---------------------------------------------------------------- 工具
def log(*a):
    print(*a, flush=True)


def list_images(d):
    files = {}
    for p in sorted(Path(d).iterdir()):
        if p.suffix.lower() in EXTS and not p.name.startswith("."):
            files[p.stem] = p
    return files


def run_lift(img_dir, cut_dir, files):
    be, miss = kit.run_cutout(img_dir, cut_dir, files)
    tip = {"vision": "macOS Vision", "rembg": "rembg", "none": "不抠图（需要抠图的手法会自动避开）"}[be]
    log(f"· 抠图：{tip}" + (f"；识别不到主体：{', '.join(miss)}" if miss else ""))


# ---------------------------------------------------------------- 章节 & 设计
def build_chapters(F, data, files):
    order = F.get("order") or []
    dropped = set(str(x) for x in (F.get("dropped") or []))
    norm = lambda x: str(x).rsplit(".", 1)[0] if str(x).rsplit(".", 1)[0] in files else (f"{int(x):02d}" if str(x).isdigit() and f"{int(x):02d}" in files else str(x))
    base_ax, ax_src = feel.resolve_axes(F)
    chs = []
    if F.get("chapters"):
        for ch in F["chapters"]:
            photos = [norm(p) for p in ch.get("photos", []) if norm(p) in files and norm(p) not in dropped]
            ax = dict(base_ax)
            for k, v in (ch.get("axes") or {}).items():
                ax[k] = feel.clamp(round(v))
            chs.append(dict(ch, photos=photos, ax=ax))
        seen = {p for c in chs for p in c["photos"]}
        rest = [p for p in files if p not in seen and p not in dropped]
        if rest:
            chs[-1]["photos"] += rest
    else:
        photos = [norm(p) for p in order if norm(p) in files] or list(files)
        photos += [p for p in files if p not in photos]
        photos = [p for p in photos if p not in dropped]
        chs.append(dict(photos=photos, ax=dict(base_ax), said=""))
    have = {f.split("|")[0] for f, p in kit.fonts_status().items() if p}
    for ch in chs:
        sub = {p: data[p] for p in ch["photos"]}
        key = ch.get("key") or F.get("key")
        key = norm(key) if key else None
        ch["P"] = feel.derive_palette(ch["ax"], sub, key)
        ch["T"] = feel.derive_type(ch["ax"], have)
        ch["Lay"] = feel.derive_layout(ch["ax"])
    return chs, ax_src


# ---------------------------------------------------------------- 规划
def plan_book(c, chs, F, max_spreads=None, with_cover=True):
    out = []
    family_prev = None
    used_tech = {}
    flags = {"bleed": False, "derive": False}
    total_photos = sum(len(ch["photos"]) for ch in chs)

    # 封面
    if with_cover:
        c.set_chapter(chs[F.get("cover_chapter", 0)])
        cv = F.get("cover")
        cv = (f"{int(cv):02d}" if str(cv).isdigit() and f"{int(cv):02d}" in c.D else str(cv)) if cv else None
        if not cv or cv not in c.D:
            cands = [p for p in c.pool if c.D[p]["orient"] != "land"] or c.pool
            cv = cands[0]
        c.fam = "cover"
        c.begin("A0")
        c.use[cv] += 1
        c.roles.setdefault(cv, set()).add("cover")
        html = S.cover(c, cv)
        out.append(dict(sid="A0", tech="cover", cn="封面＋封底", chapter=0, html=html, photos=[cv], bg=c.P["paper"], fg=c.P["ink"]))

    if F.get("layout") and with_cover and not max_spreads:
        return plan_pinned(c, chs, F, out, flags)

    # 每章分几个跨页
    alloc = []
    for ch in chs:
        alloc.append(max(1, round(len(ch["photos"]) / ch["Lay"]["per_spread"])))
    while sum(alloc) > 11:
        j = max(range(len(alloc)), key=lambda q: alloc[q])
        alloc[j] -= 1
    while sum(alloc) > 11:
        j = max(range(len(alloc)), key=lambda q: alloc[q])
        alloc[j] -= 1
    if max_spreads:
        alloc = [max_spreads] + [0] * (len(chs) - 1)

    idx = 0
    for ci, ch in enumerate(chs):
        if not alloc[ci]:
            continue
        c.set_chapter(ch)
        i, extra = 0, 0
        while i < alloc[ci] or (any(c.use[p] == 0 for p in ch["photos"]) and extra < 4 and not max_spreads):
            if i >= alloc[ci]:
                extra += 1
            i += 1
            idx += 1
            sid = f"S{idx:02d}"
            c.page_no = 2 * idx
            last_chapter = ci == len(chs) - 1
            remaining_here = alloc[ci] - i
            need = [k for k, v in flags.items() if not v]
            force = need[0] if (last_chapter and need and remaining_here < len(need) and not max_spreads) else None
            cands = []
            for t in S.REG:
                if t.get("pad_only") or t.get("pin_only") or used_tech.get(t["name"], 0) >= t["max_use"]:
                    continue
                if F.get("_force") and t["name"] not in F["_force"]:
                    continue
                if t["name"] in (F.get("avoid") or []):
                    continue
                if t["family"] == family_prev:
                    continue
                if force and not t[force]:
                    continue
                sc = S.score(t, ch["ax"])
                if t["bleed"] and not flags["bleed"]:
                    sc += .35
                if t["derive"] and not flags["derive"]:
                    sc += .25
                if idx == 1 and t["family"] in ("bleed", "type", "window"):
                    sc += .3
                if t["name"] == "slit" and total_photos < 8:
                    sc -= 9
                sc += c.rnd.uniform(0, .12)
                cands.append((sc, t))
            cands.sort(key=lambda x: -x[0])
            done = False
            for sc, t in cands:
                c.fam = t["family"]
                c.begin(sid)
                try:
                    html = t["fn"](c)
                except Exception as e:  # 模板失败不拖垮整本
                    log(f"  ! {sid} {t['name']} 失败：{e}")
                    html = None
                if html:
                    out.append(dict(sid=sid, tech=t["name"], cn=t["cn"], chapter=ci, html=html,
                                    photos=sorted(c.spread_used), bg=c.P["paper"], fg=c.P["ink"], score=round(sc, 2)))
                    used_tech[t["name"]] = used_tech.get(t["name"], 0) + 1
                    family_prev = t["family"]
                    if t["bleed"]:
                        flags["bleed"] = True
                    if t["derive"]:
                        flags["derive"] = True
                    done = True
                    break
                c.rollback()
            if not done:
                idx -= 1
                break
    # 页数凑 4 的倍数：内跨页数必须是奇数（封面封底 2 页 + 2k 页）
    if with_cover and not max_spreads:
        inner = len(out) - 1
        tries = 0
        while inner % 2 == 0 and tries < 6:
            tries += 1
            c.set_chapter(chs[-1])
            idx += 1
            sid = f"S{idx:02d}"
            c.page_no = 2 * idx
            ranked = sorted(S.REG, key=lambda t: (used_tech.get(t["name"], 0), -S.score(t, chs[-1]["ax"])))
            for t in ranked:
                name = t["name"]
                if t.get("pin_only") or t["family"] == family_prev or used_tech.get(name, 0) >= t["max_use"] or name in (F.get("avoid") or []):
                    continue
                c.fam = t["family"]
                c.begin(sid)
                try:
                    html = t["fn"](c)
                except Exception as e:
                    log(f"  ! {sid} {name} 失败：{e}")
                    html = None
                if html:
                    out.append(dict(sid=sid, tech=name, cn=t["cn"] + "〔为凑页数补的〕", chapter=len(chs) - 1, html=html,
                                    photos=sorted(c.spread_used), bg=c.P["paper"], fg=c.P["ink"]))
                    c.notes[sid].append("这个跨页是为了让页数凑成 4 的倍数补的，可以换掉或删掉别的页")
                    family_prev = t["family"]
                    used_tech[name] = used_tech.get(name, 0) + 1
                    inner += 1
                    break
                c.rollback()
            else:
                idx -= 1
    return out, flags


def plan_pinned(c, chs, F, out, flags):
    """逐页指定：用户看过成品后说「第几页换成什么、字改成什么」，Agent 把它写进 feeling.json → layout。
    每项：{"tech": 手法名, "chapter": 段号, "photos": [...], "big": [...]/null, "line": [...]/null}
    photos 不写 = 让手法在这一段里自己挑；big / line 写 null 或 [] = 这页不要大字 / 小字。"""
    reg = {t["name"]: t for t in S.REG}
    norm = lambda x: f"{int(x):02d}" if str(x).isdigit() and f"{int(x):02d}" in c.D else str(x)
    for i, item in enumerate(F["layout"], 1):
        t = reg.get(item.get("tech"))
        if not t:
            log(f"  ! layout 第 {i} 项：没有叫「{item.get('tech')}」的手法，跳过")
            continue
        ci = min(int(item.get("chapter", 0)), len(chs) - 1)
        c.set_chapter(chs[ci])
        pin = {k: (list(v) if isinstance(v, list) else v) for k, v in item.items() if k in ("big", "line")}
        pin.update({k: v for k, v in item.items() if k in ("left_style", "left_center", "center_a", "right_style")})
        if "photos" in item:
            pin["photos"] = [norm(p) for p in item["photos"]]
        c.pin = pin
        sid = f"S{len(out):02d}"
        c.page_no = 2 * len(out)
        c.fam = t["family"]
        c.begin(sid)
        try:
            html = t["fn"](c)
        except Exception as e:
            log(f"  ! {sid} {t['name']} 失败：{e}")
            html = None
        if not html:
            c.rollback()
            log(f"  ! layout 第 {i} 项（{t['name']}）做不成：照片不合适（比如需要抠图 / 竖图），跳过")
            continue
        left = [p for p in pin.get("photos") or [] if p not in c.spread_used]
        if left:
            c.notes[sid].append("指定了但这个手法放不下：" + " ".join(left))
        c.notes[sid].append("这一页是按你逐页说的改的")
        out.append(dict(sid=sid, tech=t["name"], cn=t["cn"], chapter=ci, html=html, photos=sorted(c.spread_used),
                        bg=c.P["paper"], fg=c.P["ink"], pinned=True))
        flags["bleed"] |= t["bleed"]
        flags["derive"] |= t["derive"]
    c.pin = None
    if (len(out) - 1) % 2 == 0:   # 内跨页数要是奇数，页数才是 4 的倍数
        c.set_chapter(chs[-1])
        sid = f"S{len(out):02d}"
        c.page_no = 2 * len(out)
        c.fam = "breath"
        c.begin(sid)
        c.pin = {"line": None}
        html = reg["breath"]["fn"](c)
        c.pin = None
        c.notes[sid] = ["为了让页数凑成 4 的倍数补的空白跨页，可以在 layout 里多加或去掉一页换掉它"]
        out.append(dict(sid=sid, tech="breath", cn="呼吸页〔为凑页数补的〕", chapter=len(chs) - 1, html=html, photos=[], bg=c.P["paper"], fg=c.P["ink"]))
        log("  · 逐页指定的跨页数是偶数，最后补了一个空白跨页凑页数")
    return out, flags


# ---------------------------------------------------------------- 渲染
BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
.s{width:1120px;height:794px;position:relative;overflow:hidden}
.s>*{position:absolute}
img{display:block}
.run{display:flex;gap:22px;justify-content:space-between;font-weight:600;font-size:7.5px;line-height:1;font-family:'ZGrotesk','ZSans','Helvetica Neue','Hiragino Sans GB','Microsoft YaHei',sans-serif;letter-spacing:.09em;text-transform:uppercase}
.m{font-weight:500;font-size:8px;line-height:1.35;font-family:'ZGrotesk','ZSans','Helvetica Neue','Hiragino Sans GB','Microsoft YaHei',sans-serif;letter-spacing:.02em}
.c{border-radius:50%}
"""
GUTTER = '.s::after{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(90deg,transparent 48.6%,rgba(0,0,0,.05) 49.7%,rgba(0,0,0,.13) 50%,rgba(255,255,255,.07) 50.15%,transparent 51.2%)}'


def sub_faces(faces):
    """_html/ 子目录里的单页：字体相对路径要多退一层。"""
    return faces.replace('url("_a/', 'url("../_a/')


_MIME = {".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml"}


def _data_uri(p):
    """把一个本地资源变成 data: URI。照片重新压缩以控制单文件体积：
    JPG → JPEG q84；带透明的 PNG → WebP q88（保留透明）；字体原样。尺寸不变（已是 2 倍图）。"""
    import base64
    import io
    ext = p.suffix.lower()
    raw, mime = None, _MIME.get(ext, "application/octet-stream")
    try:
        if ext in (".jpg", ".jpeg"):
            buf = io.BytesIO()
            Image.open(p).convert("RGB").save(buf, "JPEG", quality=84, optimize=True, progressive=True)
            raw = buf.getvalue() if buf.tell() < p.stat().st_size else None
        elif ext == ".png":
            im = Image.open(p)
            if im.mode in ("RGBA", "LA", "P"):
                buf = io.BytesIO()
                im.convert("RGBA").save(buf, "WEBP", quality=88, method=5)
                raw, mime = buf.getvalue(), "image/webp"
    except Exception:
        raw = None
    if raw is None:
        raw = p.read_bytes()
        mime = _MIME.get(ext, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def inline_assets(html, base):
    """把 html 里所有指向 _a/ 的 src="…" 和 url(…) 换成内嵌数据，得到一个可以单独发送的文件。
    找不到的文件保持原样（不会让整页失败）。"""
    cache = {}

    def rep(m):
        rel = m.group(2)
        p = (Path(base) / rel)
        if not p.exists():
            return m.group(0)
        if rel not in cache:
            cache[rel] = _data_uri(p)
        return f'{m.group(1)}{cache[rel]}{m.group(3)}'

    html = re.sub(r'(src=")(_a/[^"]+)(")', rep, html)
    html = re.sub(r'(url\(["\']?)(_a/[^"\')]+)(["\']?\))', rep, html)
    return html


def section(sp):
    return f'<section class="s" id="{sp["sid"]}" style="background:{sp["bg"]};color:{sp.get("fg", "#1A1A1C")}">{sp["html"]}</section>'


def render(out, plan, c, chs, F, faces):
    title = F.get("title") if F.get("title_source") == "user_verbatim" else "未命名"
    # 阅读版
    blocks = ""
    for sp in plan:
        notes = "".join(f"<li>{S.esc(n)}</li>" for n in c.notes.get(sp["sid"], []))
        blocks += f'<div class="row"><div class="lab">{sp["sid"]} · {S.esc(sp["cn"])}</div>{section(sp)}<ol class="note">{notes}</ol></div>'
    reading = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>{S.esc(title)}</title>
<style>{faces}{BASE_CSS}{GUTTER}
body{{background:#111;color:#ddd;font-size:13px;line-height:1.6;font-family:'ZSans','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif}}
.top{{padding:22px 40px;display:flex;gap:18px;align-items:center}} .top b{{font-size:16px;color:#fff}}
button{{background:#333;color:#fff;border:0;padding:6px 12px;border-radius:6px;cursor:pointer}}
.row{{padding:0 40px 34px}} .lab{{font-size:11px;color:#999;margin:0 0 8px}}
.note{{margin:10px 0 0 18px;color:#cfc6b8;max-width:1120px;font-size:12.5px}} body.hide .note{{display:none}}
@media print{{.top,.lab,.note{{display:none}} body{{background:#fff}} .row{{padding:0}} .s{{break-after:page}} .s::after{{display:none}} @page{{size:297mm 210mm;margin:0}}}}
</style><body><div class="top"><b>{S.esc(title)}</b><span>{len(plan) * 2} 页 · 每个跨页下面是「为什么这样排」</span><button onclick="document.body.classList.toggle('hide')">显示 / 隐藏 旁注</button></div>{blocks}</body></html>"""
    # 阅读版要能单独发给别人：图片、字体全部内嵌成一个文件（不依赖旁边的 _a/ 文件夹）
    (out / "zine.html").write_text(inline_assets(reading, out), encoding="utf-8")

    # 单页 html（截图用）
    hd = out / "_html"
    hd.mkdir(exist_ok=True) if not hd.exists() else None
    for sp in plan:
        one = f'<!doctype html><html lang="zh"><meta charset="utf-8"><style>{sub_faces(faces)}{BASE_CSS}{GUTTER} html,body{{width:1120px;height:794px;overflow:hidden;background:#000}}</style><body>{section(sp).replace("_a/", "../_a/")}</body></html>'
        (hd / f"{sp['sid']}.html").write_text(one, encoding="utf-8")

    # 页序：封面跨页 = (末页, 第1页)；内跨页 i = (2i, 2i+1)
    pages = {}
    inner = [sp for sp in plan if sp["sid"] != "A0"]
    N = 2 + 2 * len(inner)
    cov = plan[0]
    pages[1] = (cov, "R")
    pages[N] = (cov, "L")
    for i, sp in enumerate(inner, 1):
        pages[2 * i] = (sp, "L")
        pages[2 * i + 1] = (sp, "R")

    def half(p):
        sp, side = pages[p]
        off = 0 if side == "L" else -560
        return f'<div class="half"><div style="position:absolute;left:{off}px;top:0">{section(sp)}</div></div>'

    sheets = ""
    seq = []
    for s in range(N // 4):
        a, b = N - 2 * s, 1 + 2 * s
        cc, d = 2 + 2 * s, N - 1 - 2 * s
        sheets += f'<div class="sheet">{half(a)}{half(b)}</div><div class="sheet">{half(cc)}{half(d)}</div>'
        seq.append(((a, b), (cc, d)))
    imposed = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>拼版</title><style>{faces}{BASE_CSS}
@page{{size:297mm 210mm;margin:0}} body{{margin:0;background:#fff}}
.sheet{{width:1122px;height:793px;display:flex;justify-content:center;overflow:hidden;break-after:page;position:relative}}
.half{{width:560px;height:793px;overflow:hidden;position:relative}}
</style><body>{sheets}</body></html>"""
    (out / "imposed.html").write_text(imposed, encoding="utf-8")

    # 按页码顺序：一页一张 A5，第 1 页封面 … 第 N 页封底（屏幕翻看、普通打印、交给打印店自己拼版都用这个）
    def single(p):
        sp, side = pages[p]
        off = 0 if side == "L" else -560
        return f'<div class="pg"><div style="position:absolute;left:{off}px;top:0">{section(sp)}</div></div>'
    seq_html = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>按页顺序</title><style>{faces}{BASE_CSS}
@page{{size:148mm 210mm;margin:0}} body{{margin:0;background:#fff}}
.pg{{width:148mm;height:209.5mm;overflow:hidden;position:relative;break-after:page}}
</style><body>{"".join(single(p) for p in range(1, N + 1))}</body></html>"""
    (out / "pages.html").write_text(seq_html, encoding="utf-8")
    return N, seq


def shoot(out, plan):
    sd = out / "spreads"
    sd.mkdir(exist_ok=True) if not sd.exists() else None
    ok = 0
    for sp in plan:
        png = sd / f"{sp['sid']}.png"
        if kit.browser().screenshot(out / "_html" / (sp["sid"] + ".html"), png):
            Image.open(png).convert("RGB").save(sd / f"{sp['sid']}.jpg", quality=88)
            png.unlink()
            ok += 1
    return ok


def contact(out, plan, cols=3, name="总览.jpg", title=None):
    ims = []
    for sp in plan:
        p = out / "spreads" / f"{sp['sid']}.jpg"
        if p.exists():
            ims.append((sp, Image.open(p)))
    if not ims:
        return None
    w = 800
    h = int(w * 794 / 1120)
    rows = math.ceil(len(ims) / cols)
    top = 60 if title else 0
    sheet = Image.new("RGB", (cols * (w + 20) + 20, top + rows * (h + 46) + 20), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    f = kit.pil_font(18)
    if title:
        d.text((20, 18), title, fill=(240, 240, 240), font=kit.pil_font(26))
    for k, (sp, im) in enumerate(ims):
        x, y = 20 + (k % cols) * (w + 20), top + 20 + (k // cols) * (h + 46)
        sheet.paste(im.resize((w, h)), (x, y + 26))
        d.text((x, y), f"{sp['sid']}  {sp['cn']}", fill=(220, 220, 220), font=f)
    p = out / name
    sheet.save(p, quality=86)
    return p


# ---------------------------------------------------------------- 读回（粗测）
def measure(p):
    im = Image.open(p).convert("RGB").resize((560, 397))
    st = ImageStat.Stat(im)
    L = sum(ImageStat.Stat(im.convert("L")).mean) / 255 * 100
    r, g, b = st.mean
    warm = (r - b) / 255 * 100
    hsv = im.convert("HSV")
    sat = ImageStat.Stat(hsv).mean[1] / 255 * 100
    gray = im.convert("L")
    edges = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
    # 平的区域（纸、纯色）占比
    flat, tot = 0, 0
    for y in range(0, 397 - 16, 16):
        for x in range(0, 560 - 16, 16):
            s = ImageStat.Stat(gray.crop((x, y, x + 16, y + 16))).stddev[0]
            tot += 1
            flat += s < 5
    return dict(L=round(L, 1), warm=round(warm, 1), sat=round(sat, 1), edges=round(edges, 1), flat=round(flat / tot, 3))


def readback(out, plan, chs):
    rows = []
    for sp in plan:
        p = out / "spreads" / f"{sp['sid']}.jpg"
        if p.exists():
            rows.append(measure(p))
    if not rows:
        return None
    avg = {k: sum(r[k] for r in rows) / len(rows) for k in rows[0]}
    clamp = feel.clamp
    # 系数用 3 本示例书粗校过：只当「方向对不对」的提醒，不是精确测量
    # 系数用 3 本示例书粗校过：只当「方向对不对」的提醒，不是精确测量
    got = {
        "heavy": clamp(round((60 - avg["L"]) / 10 + (avg["sat"] - 30) / 20)),
        "warm": clamp(round((avg["warm"] - 8) / 7)),
        "fast": clamp(round(((.55 - avg["flat"]) / .035 + (avg["edges"] - 11.8) / 1.6) / 2)),
        "near": clamp(round((.56 - avg["flat"]) / .04)),
    }
    n = sum(len(ch["photos"]) for ch in chs) or 1
    want = {k: round(sum(ch["ax"][k] * len(ch["photos"]) for ch in chs) / n, 1) for k in got}
    lines = []
    for k in got:
        l, r = feel.AXIS_LABEL[k]
        d = got[k] - want[k]
        flag = "  ← 差得有点多，看看要不要调" if abs(d) >= 1.5 else ""
        lines.append(f"{l} ↔ {r}：想要 {want[k]:+}，成品粗测 {got[k]:+}{flag}")
    res = dict(measured=avg, got=got, want=want, lines=lines, per_spread=rows)
    (out / "readback.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


# ---------------------------------------------------------------- 文字出处 & 旁注
def write_reports(out, plan, c, chs, F, flags, N, seq, ax_src):
    said_all = F.get("said", "") + "|" + "|".join(ch.get("said", "") for ch in chs) + "|" + "|".join((F.get("notes") or {}).values())
    bad = []
    lines = ["# 文字来源：册子上印出来的每一段字", "# user_verbatim=用户原话  derived_visible=Agent 从画面看到的（派生，可删）",
             "# computed=从照片算出来的数值  filename=文件名  mark/header=排版记号", ""]
    for sid, t, src, field in c.texts:
        ok = ""
        if src == "user_verbatim" and t not in said_all and t != F.get("title") and t not in [ch.get("name") for ch in chs]:
            ok = "  !! 原话里找不到"
            bad.append((sid, t))
        lines.append(f"{sid}\t{src}\t{field}\t{t}{ok}")
    if F.get("example"):
        lines.insert(0, "# 注意：这一本的「感受」是示例（Agent 写的），不是用户原话\n")
    (out / "文字来源.txt").write_text("\n".join(lines), encoding="utf-8")

    nb = ["# 设计旁注：每个设计决定，都对应你说的哪句话", ""]
    if F.get("example"):
        nb.append("（这一本的感受是示例，用来演示同一组照片在不同感受下会长成什么样）\n")
    nb.append(f"你说的：{F.get('said', '')}")
    for ci, ch in enumerate(chs):
        P, T, Lay, ax = ch["P"], ch["T"], ch["Lay"], ch["ax"]
        nb.append(f"\n## 第 {ci + 1} 段" + (f"：{ch.get('said')}" if ch.get("said") else "") + f"（{len(ch['photos'])} 张：{' '.join(ch['photos'])}）")
        nb.append("轴：" + "  ".join(f"{feel.plain(ax, k)}" for k in feel.AXIS_KEYS))
        nb.append(f"颜色：主色 {P['accent']}（取自 {P['accent_from'] or '色表'}）、第二色 {P['second']}、深色 {P['deep']}、纸 {P['paper']}"
                  + (f"；平涂色接近 Riso {P['flat_names'][0]} / {P['flat_names'][1]}" if P.get("flat_names") else ""))
        nb.append(f"字：大字 {T['big']}px，最小 {T['small']}px，相差 {T['big'] // T['small']} 倍；{T['why']}")
        nb.append(f"版面：每跨页约 {Lay['per_spread']} 张；主图约占 {int(Lay['hero'] * 100)}%；最大倾斜 {Lay['rot']:.0f}°；照片处理 = {Lay['treat']}")
        for k in feel.AXIS_KEYS:
            l, r = feel.AXIS_MEANS[k]
            if ax[k]:
                nb.append(f"  · {feel.plain(ax, k)} → {r if ax[k] > 0 else l}")
    nb.append("\n## 每个跨页")
    for sp in plan:
        nb.append(f"\n{sp['sid']} {sp['cn']}（照片 {' '.join(sp['photos'])}）")
        for n in c.notes.get(sp["sid"], []):
            nb.append(f"  - {n}")
    (out / "设计旁注.txt").write_text("\n".join(nb), encoding="utf-8")

    cnt = {}
    for _, t, src, field in c.texts:
        if src == "user_verbatim" and field not in S.TEXTURE_FIELDS:
            cnt[t] = cnt.get(t, 0) + 1
    over = [(w, n) for w, n in cnt.items() if n > 2]
    use = {n: v for n, v in c.use.items()}
    unused = [n for n, v in use.items() if v == 0]
    twice = [n for n, v in use.items() if v >= 2]
    adj = all(plan[i]["tech"] != plan[i + 1]["tech"] for i in range(len(plan) - 1))
    fam = [next((t["family"] for t in S.REG if t["name"] == sp["tech"]), "cover") for sp in plan]
    adj_f = all(fam[i] != fam[i + 1] for i in range(1, len(fam) - 1))
    checks = [
        ("页数是 4 的倍数", N % 4 == 0, f"{N} 页"),
        ("每张照片都用上", not unused, "没用上：" + " ".join(unused) if unused else "全部用上"),
        ("同一张最多 2 次", max(use.values()) <= 2, "出现 2 次：" + " ".join(twice) if twice else "无重复"),
        ("至少 1 个满版跨页", flags["bleed"], ""),
        ("至少 1 个「图形来自照片本身」", flags["derive"], ""),
        ("相邻跨页手法不同、家族不同", adj and adj_f, " → ".join(sp["tech"] for sp in plan)
         + ("（逐页指定：顺序按用户说的，这一项只提醒）" if F.get("layout") and not (adj and adj_f) else "")),
        ("最大字 / 最小字 ≥ 30 倍", all(ch["T"]["big"] / ch["T"]["small"] >= 30 for ch in chs), ""),
        ("印出来的原话都能在原话里找到", not bad, "; ".join(f"{a}:{b}" for a, b in bad)),
        ("同一句原话正文里最多印 2 次", not over, "; ".join(f"「{w}」{n} 次" for w, n in over)),
    ]
    vl = ["# 版式清单", ""]
    for p in range(1, N + 1):
        pass
    for sp in plan:
        pg = "封底 + 封面" if sp["sid"] == "A0" else f"P.{int(sp['sid'][1:]) * 2:02d}—{int(sp['sid'][1:]) * 2 + 1:02d}"
        vl.append(f"{sp['sid']}\t{pg}\t{sp['cn']}\t照片 {' '.join(sp['photos'])}")
    vl += ["", "# 两个 PDF", "按页顺序.pdf：A5 一页一张，第 1 页封面 … 第 %d 页封底。屏幕看、普通打印、交给打印店都用它。" % N,
           "骑马钉拼版.pdf：A4 横向，一张纸正反面放 4 页，顺序是故意打乱的——双面打印后整叠对折、订书脊，翻开就是 1→%d。" % N,
           "", "# 骑马钉拼版.pdf 的页序（A4 横向双面，短边翻转）"]
    for i, (f1, b1) in enumerate(seq, 1):
        vl.append(f"第 {i} 张纸  正面 {f1[0]} | {f1[1]}   反面 {b1[0]} | {b1[1]}")
    vl += ["", "# 自检"] + [f"{'✓' if ok else '✗'} {name}  {info}" for name, ok, info in checks]
    if c.reuse_notes:
        vl += ["", "# 第二次出现的照片"] + c.reuse_notes
    (out / "版式清单.txt").write_text("\n".join(vl), encoding="utf-8")
    plan_json = dict(feeling=F, axes_source=ax_src, chapters=[dict(photos=ch["photos"], ax=ch["ax"], P=ch["P"], T={k: v for k, v in ch["T"].items()}, Lay=ch["Lay"]) for ch in chs],
                     spreads=[{k: v for k, v in sp.items() if k != "html"} | {"notes": c.notes.get(sp["sid"], [])} for sp in plan],
                     usage=use, pages=N, checks=[(a, b, i) for a, b, i in checks])
    (out / "plan.json").write_text(json.dumps(plan_json, ensure_ascii=False, indent=1), encoding="utf-8")
    return checks


# ---------------------------------------------------------------- 主流程
def prepare(images, out):
    files = list_images(images)
    if not files:
        sys.exit("没找到图片：" + str(images))
    cut = out / "_cut"
    if not cut.exists():
        cut.mkdir(parents=True)
    run_lift(Path(images), cut, files)
    fx.setup(images, cut, out / "_a", files)
    data = {n: fx.photo_data(n) for n in files}
    minfo = {n: fx.mask_info(n) for n in files}
    return files, data, minfo


def build(F, images, out, files, data, minfo, max_spreads=None, with_cover=True, pdf=True, shots=True, book_id="z"):
    fx.CFG["asset"] = out / "_a"
    if not fx.CFG["asset"].exists():
        fx.CFG["asset"].mkdir(parents=True)
    chs, ax_src = build_chapters(F, data, files)
    order = [p for ch in chs for p in ch["photos"]]
    c = S.Ctx(book_id, data, minfo, F, order)
    plan, flags = plan_book(c, chs, F, max_spreads, with_cover)
    faces, _ = feel.font_faces(book_chars(plan, c, F), out)
    if with_cover:
        N, seq = render(out, plan, c, chs, F, faces)
    else:
        N, seq = 0, []
        render_simple(out, plan, faces)
    n_shot = shoot(out, plan) if shots else 0
    res = {"plan": plan, "c": c, "chs": chs, "N": N, "shots": n_shot}
    if with_cover:
        res["checks"] = write_reports(out, plan, c, chs, F, flags, N, seq, ax_src)
        if n_shot:
            contact(out, plan, title=(F.get("title") or "") + ("　（示例感受）" if F.get("example") else ""))
            res["readback"] = readback(out, plan, chs)
        if pdf:
            for old in ("imposed.pdf", "zine.pdf"):   # 旧文件名容易让人以为页序乱了
                if (out / old).exists():
                    (out / old).unlink()
            b = kit.browser()
            res["pdf"] = b.pdf(out / "pages.html", out / "按页顺序.pdf") and b.pdf(out / "imposed.html", out / "骑马钉拼版.pdf")
    return res


def book_chars(plan, c, F):
    """这本书里会出现的所有字（用来做字体子集）。"""
    txt = [re.sub(r"<[^>]+>", " ", sp["html"]) for sp in plan]
    txt += [n for v in c.notes.values() for n in v]
    txt += [str(F.get("title") or ""), str(F.get("said") or ""), "未命名页显示隐藏旁注为什么这样排「」（）·，。、"]
    import html as _h
    return _h.unescape("".join(txt))


def render_simple(out, plan, faces):
    hd = out / "_html"
    if not hd.exists():
        hd.mkdir(parents=True)
    for sp in plan:
        one = f'<!doctype html><html lang="zh"><meta charset="utf-8"><style>{sub_faces(faces)}{BASE_CSS}{GUTTER} html,body{{width:1120px;height:794px;overflow:hidden;background:#000}}</style><body>{section(sp).replace("_a/", "../_a/")}</body></html>'
        (hd / f"{sp['sid']}.html").write_text(one, encoding="utf-8")


PROBE_SAME = {"warm": ["giant", "scatter", "etch"]}


def probe(F, images, out, files, data, minfo):
    """看图二选一：每根轴出一对 A/B（只改这一根，其它不动），让用户「看图选」而不是「说设计词」。"""
    base = {k: 0 for k in feel.AXIS_KEYS}   # 中性为底：每对只有一根轴被推到两端，差别才看得出来
    pd = out / "probe"
    if not pd.exists():
        pd.mkdir(parents=True)
    pairs = []
    for k in feel.AXIS_KEYS:
        imgs = []
        for v, tag in [(-2, "L"), (2, "R")]:
            F2 = json.loads(json.dumps(F))
            F2.pop("chapters", None)
            ax = dict(base)
            ax[k] = v
            F2["axes"] = ax
            if k in PROBE_SAME:   # 只体现在颜色上的轴：左右用同一个手法，只让颜色变
                F2["_force"] = PROBE_SAME[k]
            sub = pd / f"{k}_{tag}"
            if not sub.exists():
                sub.mkdir(parents=True)
            r = build(F2, images, sub, files, data, minfo, max_spreads=1, with_cover=False, pdf=False, book_id=f"p{k}{tag}")
            sp = r["plan"][0] if r["plan"] else None
            p = sub / "spreads" / f"{sp['sid']}.jpg" if sp else None
            imgs.append((p if p and p.exists() else None, sp["cn"] if sp else "—"))
        pairs.append((k, imgs))
    # 拼成一张：每行一根轴，左 = 负向，右 = 正向
    w, h = 700, int(700 * 794 / 1120)
    sheet = Image.new("RGB", (2 * w + 60, len(pairs) * (h + 70) + 30), (246, 244, 240))
    d = ImageDraw.Draw(sheet)
    f1, f2 = kit.pil_font(26), kit.pil_font(15)
    for i, (k, imgs) in enumerate(pairs):
        y = 20 + i * (h + 70)
        l, r = feel.AXIS_LABEL[k]
        for j, ((p, cn), lab) in enumerate(zip(imgs, (l, r))):
            x = 20 + j * (w + 20)
            d.text((x, y), ("A　" if j == 0 else "B　") + lab, fill=(30, 30, 30), font=f1)
            d.text((x + 260, y + 8), f"（{cn}）", fill=(130, 130, 130), font=f2)
            if p:
                sheet.paste(Image.open(p).resize((w, h)), (x, y + 40))
    sheet.save(out / "看图二选一.jpg", quality=86)
    log(f"· 看图二选一：{out / '看图二选一.jpg'}")
    return out / "看图二选一.jpg"


def apply_no_cutout(F, files, minfo):
    """feeling.json → no_cutout：这些照片不抠图（抠出来形状难看时用），当整张照片排。"""
    for k in F.get("no_cutout") or []:
        n = f"{int(k):02d}" if str(k).isdigit() and f"{int(k):02d}" in files else str(k).rsplit(".", 1)[0]
        if n in minfo:
            minfo[n]["has"] = False
            minfo[n]["no_cutout"] = True


def apply_people(F, files, minfo):
    """Agent 看图后写的「画面里有几个人」（feeling.json → people），优先于检测器。"""
    for k, v in (F.get("people") or {}).items():
        n = str(k).rsplit(".", 1)[0]
        n = n if n in files else (f"{int(n):02d}" if n.isdigit() and f"{int(n):02d}" in files else n)
        if n in minfo:
            try:
                minfo[n]["humans"], minfo[n]["humans_src"] = int(v), "agent"
            except (TypeError, ValueError):
                pass


def main():
    kit.utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True)
    ap.add_argument("--feeling", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pick", "--probe", dest="probe", action="store_true", help="只出「看图二选一」的 A/B 对照图")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--no-shot", action="store_true")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if not out.exists():
        out.mkdir(parents=True)
    F = json.loads(Path(a.feeling).read_text(encoding="utf-8"))
    files, data, minfo = prepare(Path(a.images).resolve(), out)
    apply_people(F, files, minfo)
    apply_no_cutout(F, files, minfo)
    (out / "photo_data.json").write_text(json.dumps({"data": data, "mask": minfo}, ensure_ascii=False, indent=1))
    log(f"· 截图 / PDF：{kit.browser().describe()}")
    if a.probe:
        probe(F, Path(a.images).resolve(), out, files, data, minfo)
        kit.browser().close()
        return
    r = build(F, Path(a.images).resolve(), out, files, data, minfo, pdf=not a.no_pdf, shots=not a.no_shot)
    log(f"· {r['N']} 页，{len(r['plan'])} 个跨页，截图 {r['shots']} 张")
    for name, ok, info in r["checks"]:
        log(f"  {'✓' if ok else '✗'} {name}  {info}")
    if r.get("readback"):
        log("· 读回（粗测）：")
        for l in r["readback"]["lines"]:
            log("  " + l)
    log("· 产物：" + ", ".join(sorted(p.name for p in out.iterdir() if not p.name.startswith("_"))))
    kit.browser().close()


if __name__ == "__main__":
    main()
