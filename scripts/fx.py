"""自书 · 图像效果库
所有效果都只从用户自己的照片里算出来：抠图、纸边、版画、描线、色带、人形窗、人形填字、双色、闪光、斑点纸。
不引入任何外部素材。由 zishu.py 调用 setup() 指定目录后使用。"""
import json
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

CFG = {"img": None, "cut": None, "asset": None, "files": {}}
import platform_kit as kit


def setup(img_dir, cut_dir, asset_dir, files):
    CFG.update(img=Path(img_dir), cut=Path(cut_dir), asset=Path(asset_dir), files=files)
    if not CFG["asset"].exists():
        CFG["asset"].mkdir(parents=True)
    _src.cache_clear()
    _mask.cache_clear()


# ---------------- 读图 ----------------
@lru_cache(maxsize=64)
def _src(n):
    im = ImageOps.exif_transpose(Image.open(CFG["files"][n]))
    return im.convert("RGB")


def src(n):
    return _src(n).copy()


def fit(n, w, h, c=(.5, .5)):
    return ImageOps.fit(_src(n), (int(w), int(h)), Image.LANCZOS, centering=c)


def save(im, name, q=88):
    p = CFG["asset"] / name
    if name.endswith(".png"):
        im.save(p, optimize=False)
    else:
        im.convert("RGB").save(p, quality=q)
    return p


@lru_cache(maxsize=64)
def _mask(n):
    p = CFG["cut"] / f"{n}_mask.png"
    if not p.exists():
        return None
    return Image.open(p).convert("L")


def mask(n):
    m = _mask(n)
    return None if m is None else m.copy()


def mask_info(n):
    """主体信息：有无蒙版、覆盖率、外接框比例、画面里检测到几个人。"""
    info = {"has": False, "cover": 0, "tall": 0, "humans": 0, "humans_src": "unknown"}
    ip = CFG["cut"] / f"{n}_info.json"
    if ip.exists():
        try:
            h = json.loads(ip.read_text()).get("humans")
            if h is not None:          # rembg / 不抠图时数不了人 → 记为未知（0），可由 feeling.json 的 people 补上
                info["humans"], info["humans_src"] = int(h), "detector"
        except Exception:
            pass
    m = _mask(n)
    if m is None:
        return info
    small = m.resize((96, 96))
    h = small.histogram()
    cover = sum(h[128:]) / (96 * 96)
    bb = m.point(lambda v: 255 if v > 128 else 0).getbbox()
    if not bb:
        return info
    info.update(has=.03 < cover < .85, cover=round(cover, 3),
                tall=round((bb[3] - bb[1]) / max(bb[2] - bb[0], 1), 2))
    return info


# ---------------- 基础处理 ----------------
def grain(im, amt=.06):
    n = Image.effect_noise(im.size, 60).convert("L")
    n = Image.merge("RGB", [n] * 3)
    return Image.blend(im.convert("RGB"), ImageChops.overlay(im.convert("RGB"), n), min(amt * 4, 1))


def tint(im, color, amt):
    """整体往一个颜色偏一点（暖/冷）。amt 0–.2。"""
    if amt <= 0:
        return im
    layer = Image.new("RGB", im.size, color)
    return Image.blend(im.convert("RGB"), ImageChops.soft_light(im.convert("RGB"), layer), amt * 3)


def duo(n, dark, light, w, h, c=(.5, .5), cutoff=1, gamma=1.0, g=.05):
    gr = ImageOps.autocontrast(fit(n, w, h, c).convert("L"), cutoff=cutoff)
    if gamma != 1:
        gr = gr.point(lambda v: int(255 * (v / 255) ** gamma))
    return grain(ImageOps.colorize(gr, dark, light), g)


def flash(n, w, h, c=(.5, .5), k=1.0):
    im = fit(n, w, h, c)
    im = ImageEnhance.Contrast(im).enhance(1 + .22 * k)
    im = ImageEnhance.Color(im).enhance(1 + .32 * k)
    return im


def soft(n, w, h, c=(.5, .5), k=1.0):
    """恍惚：轻微失焦、抬亮暗部、降饱和、加颗粒。"""
    im = fit(n, w, h, c)
    b = im.filter(ImageFilter.GaussianBlur(1.6 * k + .4))
    im = Image.blend(im, b, .55)
    im = ImageEnhance.Color(im).enhance(1 - .28 * k)
    im = ImageEnhance.Contrast(im).enhance(1 - .18 * k)
    im = im.point(lambda v: int(18 * k + v * (1 - 18 * k / 255)))
    return grain(im, .05 + .03 * k)


def fade_to(im, color, start=.0, strength=.9, vertical=True):
    over = Image.new("RGB", im.size, color)
    g = Image.linear_gradient("L").resize(im.size)
    if not vertical:
        g = g.rotate(90, expand=False)
    g = g.point(lambda v: 0 if v < start * 255 else int((v - start * 255) / max(1, 255 - start * 255) * 255 * strength))
    return Image.composite(over, im.convert("RGB"), g)


# ---------------- 抠图类 ----------------
def cutout(n, maxside=1500, pad=8):
    """抠图，返回紧贴主体的 RGBA。没有蒙版返回 None。"""
    m = mask(n)
    if m is None:
        return None
    im = src(n)
    m = m.filter(ImageFilter.GaussianBlur(1)).point(lambda v: 255 if v > 120 else 0).filter(ImageFilter.GaussianBlur(.8))
    bb = m.getbbox()
    if not bb:
        return None
    bb = (max(bb[0] - pad, 0), max(bb[1] - pad, 0), min(bb[2] + pad, im.width), min(bb[3] + pad, im.height))
    rgba = im.convert("RGBA")
    rgba.putalpha(m)
    rgba = rgba.crop(bb)
    if max(rgba.size) > maxside:
        rgba.thumbnail((maxside, maxside), Image.LANCZOS)
    return rgba


def halo(rgba, grow=14, color=(250, 246, 236, 255), shadow=True):
    """纸边：抠图外扩一圈，像手剪下来的贴纸。"""
    p = grow + 10
    W, H = rgba.width + 2 * p, rgba.height + 2 * p
    a = Image.new("L", (W, H), 0)
    a.paste(rgba.split()[3], (p, p))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if grow > 0:
        big = a.filter(ImageFilter.GaussianBlur(grow / 1.6)).point(lambda v: 255 if v > 22 else 0).filter(ImageFilter.GaussianBlur(1.2))
        if shadow:
            s = Image.new("RGBA", (W, H), (40, 30, 20, 0))
            s.putalpha(big.point(lambda v: int(v * .22)).filter(ImageFilter.GaussianBlur(7)))
            out.paste(s, (0, 5), s)
        paper = Image.new("RGBA", (W, H), color)
        paper.putalpha(big)
        out.alpha_composite(paper)
    out.alpha_composite(rgba, (p, p))
    return out


def etch(rgba, ink=(44, 36, 32), halo_color=(226, 216, 200, 215), grow=16, pct=.42):
    """抠图变一块版画：只留墨色 + 半透明纸边。阈值按物体自身明暗的分位数取，深色物体也不会糊。"""
    gr = ImageOps.autocontrast(rgba.convert("RGB").convert("L"), cutoff=2)
    nz = Image.effect_noise(gr.size, 46).convert("L")
    gr = ImageChops.add(gr, nz, scale=1, offset=-128)
    hist = gr.histogram(mask=rgba.split()[3].point(lambda v: 255 if v > 128 else 0))
    tot, acc, t = sum(hist), 0, 118
    for i, c in enumerate(hist):
        acc += c
        if acc >= tot * pct:
            t = i
            break
    gr = gr.point(lambda v, t=t: 255 if v > t else 0).filter(ImageFilter.GaussianBlur(.5))
    ink_a = ImageChops.multiply(ImageOps.invert(gr), rgba.split()[3])
    layer = Image.new("RGBA", rgba.size, tuple(ink) + (255,))
    layer.putalpha(ink_a)
    bb = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    bb.alpha_composite(layer)
    a = rgba.split()[3].point(lambda v: 1 if v > 40 else 0)
    bb.putalpha(ImageChops.lighter(bb.split()[3], a))
    return halo(bb, grow, halo_color, shadow=False)


# ---------------- 从照片里提取图形 ----------------
def trace(n, w, h, ink, c=(.5, .5), thr=26, blur=1.1):
    """线稿：线都是照片自己的边缘。"""
    g = fit(n, w, h, c).convert("L").filter(ImageFilter.GaussianBlur(blur))
    e = g.filter(ImageFilter.FIND_EDGES)
    e = e.point(lambda v: 255 if v > thr else 0).filter(ImageFilter.GaussianBlur(.45))
    out = Image.new("RGBA", (int(w), int(h)), tuple(ink) + (255,))
    out.putalpha(e)
    return out


def slit(n, w, h):
    """整张照片横向压成 1 像素再拉宽：一条保留上下色彩变化的色带。"""
    return _src(n).resize((1, int(h)), Image.BOX).resize((int(w), int(h)), Image.NEAREST)


def figure_window(fig, fill, w):
    """人形窗：用 fig 的主体轮廓框住 fill 这张照片。"""
    m = mask(fig)
    m = m.crop(m.point(lambda v: 255 if v > 128 else 0).getbbox())
    h = int(m.height * w / m.width)
    m = m.resize((int(w), h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(3)).point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.GaussianBlur(1))
    ph = ImageOps.fit(_src(fill), (int(w), h), Image.LANCZOS)
    ph = ImageEnhance.Color(ph).enhance(1.15).convert("RGBA")
    ph.putalpha(m)
    return ph


def text_in_silhouette(n, page_wh, c, text, fsize=19, fill=(255, 255, 255), ink=(20, 20, 20), line=4, font=None):
    """裁切后的照片里，人物变成纯色剪影，字逐行排满人形。text 必须是有出处的字。"""
    W, H = int(page_wh[0]), int(page_wh[1])
    im = fit(n, W, H, c)
    m = ImageOps.fit(mask(n), (W, H), Image.LANCZOS, centering=c)
    m = m.filter(ImageFilter.GaussianBlur(2.5)).point(lambda v: 255 if v > 120 else 0)
    out = im.convert("RGBA")
    ring = m.filter(ImageFilter.MaxFilter(7))
    edge = ImageChops.subtract(ring, m)
    out.paste(Image.new("RGBA", (W, H), tuple(ink) + (255,)), (0, 0), edge)
    out.paste(Image.new("RGBA", (W, H), tuple(fill) + (255,)), (0, 0), m)
    d = ImageDraw.Draw(out)
    try:
        f = ImageFont.truetype(font, fsize) if font else kit.pil_font(fsize, bold=True)
    except Exception:
        f = kit.pil_font(fsize, bold=True)
    chars = [ch for ch in text if not ch.isspace()] or ["·"]
    k, lh = 0, fsize + line
    bb = m.getbbox()
    if not bb:
        return out
    y = bb[1] + 4
    while y + fsize < bb[3]:
        row = m.crop((0, y + fsize // 2, W, y + fsize // 2 + 1))
        px = list(row.tobytes())
        x, spans = 0, []
        while x < W:
            if px[x] > 128:
                s = x
                while x < W and px[x] > 128:
                    x += 1
                spans.append((s, x))
            else:
                x += 1
        for s, e in spans:
            usable = e - s - 8
            cnt = usable // fsize
            if cnt < 1:
                continue
            gap = (usable - cnt * fsize) / max(cnt - 1, 1) if cnt > 1 else 0
            for i in range(cnt):
                d.text((s + 4 + i * (fsize + gap), y), chars[k % len(chars)], font=f, fill=tuple(ink) + (255,))
                k += 1
        y += lh
    return out


def speckle_paper(w, h, base=(246, 240, 226), seed=4, colored=False, n=2400):
    rnd = random.Random(seed)
    im = Image.new("RGB", (int(w), int(h)), tuple(base))
    d = ImageDraw.Draw(im)
    pal = [(150, 120, 80), (90, 70, 50), (190, 160, 110)]
    if colored:
        pal += [(222, 130, 120), (120, 170, 200), (230, 190, 90), (150, 190, 140)]
    for _ in range(n):
        x, y = rnd.random() * w, rnd.random() * h
        r = rnd.choice([.6, .8, 1, 1, 1.3, 1.8, 2.4])
        d.ellipse((x - r, y - r * rnd.uniform(.6, 1.2), x + r, y + r), fill=rnd.choice(pal))
    tex = Image.effect_noise((int(w), int(h)), 14).convert("L").filter(ImageFilter.GaussianBlur(1))
    return Image.blend(im, ImageChops.multiply(im, Image.merge("RGB", [tex.point(lambda v: 228 + v // 9)] * 3)), .8)


def plain_paper(w, h, base, amt=.035):
    """普通纸：极轻的纤维噪点，避免纯色的电子感。"""
    im = Image.new("RGB", (int(w), int(h)), tuple(base))
    tex = Image.effect_noise((int(w), int(h)), 22).convert("L").filter(ImageFilter.GaussianBlur(.8))
    return Image.blend(im, ImageChops.multiply(im, Image.merge("RGB", [tex.point(lambda v: 225 + v // 8)] * 3)), amt * 12)


# ---------------- 照片数据（真实计算值） ----------------
def photo_data(n):
    im = _src(n)
    small = im.resize((64, 64), Image.BOX)
    g = small.convert("L")
    L = round(sum(g.tobytes()) / (64 * 64) / 255 * 100)
    q = sorted(small.quantize(6).convert("RGB").getcolors(4096), reverse=True)
    cols = [(cnt, c) for cnt, c in q]
    r, gg, b = cols[0][1]
    # 暖度：R-B 的平均
    px = list(small.getdata())
    warm = round(sum(p[0] - p[2] for p in px) / len(px) / 255 * 100)
    hsv = small.convert("HSV")
    sat = round(sum(p[1] for p in hsv.getdata()) / len(px) / 255 * 100)
    return {"L": L, "hex": f"#{r:02X}{gg:02X}{b:02X}", "warm": warm, "sat": sat,
            "size": list(im.size), "orient": "land" if im.width > im.height * 1.1 else ("port" if im.height > im.width * 1.1 else "sq"),
            "colors": [[cnt, f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"] for cnt, c in cols]}
