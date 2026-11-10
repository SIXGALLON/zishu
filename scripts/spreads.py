"""自书 · 手法库
每个手法 = 一个跨页模板（1120×794 CSS px，A5×2）。手法不写死颜色和字，全部从 Ctx 里的「感受 → 设计」结果取。
每个手法声明：亲和的感受（AFF）、家族（相邻跨页不许同家族）、是否满版、是否「图形来自照片本身」。"""
import html as _html
import math
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

import fx
from feel import AXIS_KEYS, hex2rgb, mix, note_axis

SW, SH, HW = 1120, 794, 560
PX = 2


def esc(s):
    return _html.escape(str(s))


# 页眉标题、填进人形 / 字河 / 圆圈里的「纹理字」不算「印了一次原话」
TEXTURE_FIELDS = {"title", "chapter.name", "silhouette_text", "river", "circle_text"}


class Ctx:
    def __init__(self, book_id, data, minfo, feeling, all_order):
        self.book = book_id
        self.D, self.MI, self.F = data, minfo, feeling
        self.all_order = all_order
        self.use = {n: 0 for n in all_order}
        self.texts = []       # (spread, text, source, field)
        self.notes = {}       # spread -> [旁注]
        self.rnd = random.Random(feeling.get("seed", 7))
        self.sid = None
        self.spread_used = set()
        self.reuse_notes = []
        self.page_no = 0
        self.roles = {}       # 照片 -> 用过的手法家族（第二次出现必须换家族）
        self.reuse_budget = max(2, len(all_order) // 5)   # 全书最多这么多张照片出现第二次
        self.fam = None
        self.pin = None       # 逐页指定（feeling.json → layout）：这一跨页用哪些照片、哪句大字、哪句小字
        self.marks = feeling.get("marks", True) is not False   # false = 不印 L63、#A79C7F 这类计算出来的记号

    # ---- 记号（亮度、色值、照片张数）：marks=false 时一律不印 ----
    def mk(self, html):
        return html if self.marks else ""

    def _pin_take(self, key):
        """逐页指定时按顺序取下一句；列表空了 / 写成 null 就是「这里不要字」。"""
        q = self.pin.get(key)
        if not q:
            return None
        if isinstance(q, str):
            self.pin[key] = []
            return q
        return q.pop(0)

    def _src_field(self, w):
        if w in (self.F.get("notes") or {}).values():
            return "notes"
        return "chapter.said" if w in (self.ch.get("said") or "") else "said"

    # ---- 章节 ----
    def set_chapter(self, ch):
        self.ch = ch
        self.ax, self.P, self.T, self.Lay = ch["ax"], ch["P"], ch["T"], ch["Lay"]
        self.pool = ch["photos"]

    # ---- 事务（模板做不成就回滚）----
    def begin(self, sid):
        self.sid = sid
        self._snap = (dict(self.use), len(self.texts), list(self.reuse_notes), {k: set(v) for k, v in self.roles.items()})
        self.spread_used = set()
        self.notes[sid] = []

    def rollback(self):
        self.use, n, self.reuse_notes, self.roles = self._snap[0], self._snap[1], self._snap[2], self._snap[3]
        self.texts = self.texts[:n]
        self.notes.pop(self.sid, None)

    # ---- 选照片 ----
    def info(self, n):
        return self.MI.get(n, {})

    def is_land(self, n):
        return self.D[n]["orient"] == "land"

    def has_mask(self, n):
        return self.info(n).get("has", False)

    def is_person(self, n):
        i = self.info(n)
        return i.get("has") and i.get("humans", 0) >= 1 and i.get("tall", 0) >= 1.15

    def is_object(self, n):
        i = self.info(n)
        return i.get("has") and i.get("humans", 0) == 0

    def avail(self, pred=None, fresh_only=False):
        p = pred or (lambda n: True)
        if self.pin and self.pin.get("photos") is not None:   # 逐页指定：只在指定的照片里按顺序挑
            return [n for n in self.pin["photos"] if n in self.D and n not in self.spread_used and p(n)]
        a = [n for n in self.pool if self.use[n] == 0 and p(n) and n not in self.spread_used]
        if a or fresh_only:
            return a
        if sum(1 for v in self.use.values() if v >= 2) >= self.reuse_budget:
            return []
        return [n for n in self.pool if self.use[n] == 1 and p(n) and n not in self.spread_used and self.fam not in self.roles.get(n, set())]

    def pick(self, pred=None, prefer=None, fresh_only=False, glob=False):
        cands = self.avail(pred, fresh_only)
        if self.pin and self.pin.get("photos") is not None:
            prefer, glob = None, False   # 按用户写的顺序，不再按分数挑
        if not cands and glob:
            p = pred or (lambda n: True)
            cands = [n for n in self.all_order if self.use[n] == 0 and p(n) and n not in self.spread_used]
        if not cands:
            return None
        if prefer:
            order = {n: i for i, n in enumerate(self.pool)}
            n = max(cands, key=lambda k: prefer(k) - .001 * order.get(k, 99))
        else:
            n = cands[0]
        if self.use[n] >= 1:
            self.reuse_notes.append(f"{self.sid}：{n} 第二次出现（换了裁切/角色），不想要可以说去掉")
        self.use[n] += 1
        self.spread_used.add(n)
        self.roles.setdefault(n, set()).add(self.fam)
        return n

    def count_avail(self, pred=None):
        return len(self.avail(pred))

    # ---- 文字（每个印出来的字都登记出处）----
    def say(self, text, source, field=""):
        self.texts.append((self.sid, str(text), source, field))
        return esc(text)

    def user_words(self):
        """用户原话片段：said 拆句 + big_words + 每张照片的 notes。只返回真在原话里的。"""
        out = []
        srcs = [(self.ch.get("said", ""), "chapter.said")] if self.ch.get("said") else [(self.F.get("said", ""), "said")]
        for s, field in srcs:
            for frag in _split(s):
                if frag not in [o[0] for o in out]:
                    out.append((frag, field))
        return out

    def big_word(self, maxlen=5, avoid=()):
        if self.pin and "big" in self.pin:
            return self._pin_take("big")
        bw = (self.ch.get("big_words") or []) if self.ch.get("said") else (self.F.get("big_words") or [])
        said_all = self.ch.get("said", "") or self.F.get("said", "")
        cands = [w for w in bw if w in said_all] + [w for w, _ in self.user_words()]
        cands = [w for w in dict.fromkeys(cands) if 2 <= len(w) <= maxlen and w not in avoid]
        fresh = [w for w in cands if self.printed(w) == 0]
        if fresh:
            return fresh[0]
        again = [w for w in cands if self.printed(w) < 2]
        return min(again, key=self.printed) if again else None

    def printed(self, w):
        """这句原话在正文里已经印了几次（页眉上的标题不算）。全书同一句最多 2 次。"""
        return sum(1 for _, t, src, f in self.texts if src == "user_verbatim" and f not in TEXTURE_FIELDS and t == w)

    def _used_big(self):
        return {t for s, t, src, f in self.texts if f == "big_word"}

    def line(self, avoid=()):
        """一句用户原话（任意长度），没用过的优先。"""
        if self.pin and "line" in self.pin:
            w = self._pin_take("line")
            return (w, self._src_field(w)) if w else (None, None)
        ws = [(w, f) for w, f in self.user_words() if w not in avoid]
        for lim in (1, 2):
            for w, f in ws:
                if self.printed(w) < lim:
                    return w, f
        return None, None   # 原话用完了就留白，不重复刷屏

    def note(self, n):
        nt = (self.F.get("notes") or {}).get(n)
        return nt

    def seen(self, n):
        return (self.F.get("see") or {}).get(n)

    def word_pool(self):
        """可以排进字河、人形里的字：用户原话优先，派生的画面描述其次（会标出处）。"""
        ws = [(w, "user_verbatim") for w, _ in self.user_words()]
        for n in self.all_order:
            if self.note(n):
                ws.append((self.note(n), "user_verbatim"))
        for n in self.all_order:
            if self.seen(n) and self.F.get("print_derived", True):
                ws.append((self.seen(n), "derived_visible"))
        return ws

    def lab(self, n):
        d = self.D[n]
        if not self.marks:
            return ""
        self.say(f"{n} L{d['L']} {d['hex']}", "computed", "photo_data")
        return f'{esc(n)}&ensp;L{d["L"]}&ensp;{d["hex"]}'

    def nb(self, text, axis=None):
        if axis:
            f = dict(self.F)
            f["said"] = self.ch.get("said", "") + "|" + self.F.get("said", "")
            f["because"] = dict(self.F.get("because") or {}, **(self.ch.get("because") or {}))
            self.notes[self.sid].append(note_axis(f, self.ax, axis, text))
        else:
            self.notes[self.sid].append(text)

    # ---- 素材 ----
    def asset(self, im, tag, q=88):
        name = f"{self.book}_{self.sid}_{tag}" + (".png" if im.mode == "RGBA" else ".jpg")
        fx.save(im, name, q)
        return f"_a/{name}"

    def treat(self, n, w, h, c=(.5, .5), mode=None):
        mode = mode or self.Lay["treat"]
        ax = self.ax
        if mode == "flash":
            im = fx.flash(n, w, h, c, k=.7 + .3 * max(ax["sharp"], 1))
        elif mode == "soft":
            im = fx.soft(n, w, h, c, k=1.0)
        elif mode == "duo":
            im = fx.duo(n, self.P["duo"][0], self.P["duo"][1], w, h, c, g=.05)
        elif mode == "duo_or_soft":
            im = fx.soft(n, w, h, c, k=.55)
        else:
            im = fx.grain(fx.fit(n, w, h, c), .03)
        if ax["warm"] > 0:
            im = fx.tint(im, (255, 168, 92), .025 * ax["warm"])
        elif ax["warm"] < 0:
            im = fx.tint(im, (88, 140, 205), .025 * -ax["warm"])
        if ax["heavy"]:
            im = ImageEnhance.Contrast(im).enhance(1 + .07 * ax["heavy"])
        return im

    def treat_im(self, im):
        """对一张已经裁好的图做和 treat 一样的冷暖 / 对比处理（不重新裁切）。"""
        ax = self.ax
        im = fx.grain(im.convert("RGB"), .03)
        if ax["warm"] > 0:
            im = fx.tint(im, (255, 168, 92), .025 * ax["warm"])
        elif ax["warm"] < 0:
            im = fx.tint(im, (88, 140, 205), .025 * -ax["warm"])
        if ax["heavy"]:
            im = ImageEnhance.Contrast(im).enhance(1 + .07 * ax["heavy"])
        return im

    def rot(self, k=1.0):
        r = self.Lay["rot"] * k
        return 0 if r == 0 else round(self.rnd.uniform(-r, r), 1)

    # ---- 字体样式 ----
    def f_disp(self, size, color, extra=""):
        T = self.T
        return f'font-family:{T["disp"]};font-weight:{T["dw"]};font-size:{size}px;line-height:1;color:{color};{extra}'

    def f_body(self, size, color, extra=""):
        return f'font-family:{self.T["body"]};font-size:{size}px;line-height:1.55;color:{color};{extra}'

    def f_lat(self, size, color, extra=""):
        T = self.T
        return f'font-family:{T["latin"]};font-weight:{T["lw"]};font-style:{T["lstyle"]};font-size:{size}px;line-height:1;color:{color};{extra}'

    def f_num(self, size, color, extra=""):
        return f'font-family:{self.T["num"]};font-weight:700;font-size:{size}px;line-height:.9;color:{color};letter-spacing:-.02em;{extra}'

    def run(self, ids, color, right_only=False, top=18):
        items = []
        if self.F.get("title") and self.F.get("title_source") == "user_verbatim" and self.F.get("title_pages", True) is not False:
            items.append(self.say(self.F["title"], "user_verbatim", "title"))
        if self.ch.get("name") and self.ch.get("name_source") == "user_verbatim":
            items.append(self.say(self.ch["name"], "user_verbatim", "chapter.name"))
        ids = [i for i in ids if i]
        if ids and self.marks:
            items.append(" / ".join(esc(i) for i in ids))
            Ls = sorted(self.D[i]["L"] for i in ids)
            if self.marks:
                items.append(f"L {Ls[0]}" + (f" — {Ls[-1]}" if len(Ls) > 1 else ""))
        p = self.page_no
        items.append(f"P.{p:02d}—{p + 1:02d}")
        self.say(" · ".join(_strip(x) for x in items), "header", "running_header")
        style = f"left:26px;right:26px;top:{top}px;color:{color}" if not right_only else f"left:auto;right:26px;top:{top}px;color:{color}"
        return f'<div class="run" style="{style}">' + "".join(f"<span>{x}</span>" for x in items) + "</div>"


def _strip(x):
    import re
    return re.sub("<[^>]+>", "", x)


def _split(s):
    import re
    return [p.strip() for p in re.split(r"[，。、；！？,.!?;\n|…]+", s or "") if p.strip()]


def box_fit(w0, h0, bw, bh):
    k = min(bw / w0, bh / h0)
    return int(w0 * k), int(h0 * k)


# ======================================================================
# 手法
# 每个函数返回 HTML（失败返回 None）。AFF：对 6 根轴的亲和度，用来打分。
# ======================================================================
REG = []


def tech(name, cn, family, aff, bleed=False, derive=False, max_use=1, min_photos=1):
    def deco(f):
        REG.append(dict(fn=f, name=name, cn=cn, family=family, aff=aff, bleed=bleed, derive=derive,
                        max_use=max_use, min_photos=min_photos))
        return f
    return deco


# ---------- 1 满版 ----------
@tech("bleed", "满版跨页", "bleed", dict(near=1, fast=-1, heavy=.5), bleed=True, max_use=2)
def t_bleed(c):
    n = c.pick(c.is_land, fresh_only=True) or c.pick(fresh_only=True) or c.pick(c.is_land) or c.pick()
    if not n:
        return None
    ink = "#fff"
    if c.is_land(n):
        img = c.asset(c.treat(n, SW * PX, SH * PX), "bleed")
        body = f'<img src="{img}" style="left:0;top:0;width:{SW}px;height:{SH}px">'
        c.nb("整个跨页只放一张，出血到纸边", "near")
    else:
        img = c.asset(c.treat(n, HW * PX, SH * PX), "bleed")
        body = f'<div style="left:0;top:0;width:{HW}px;height:{SH}px;background:{c.P["paper"]}"></div><img src="{img}" style="left:{HW}px;top:0;width:{HW}px;height:{SH}px">'
        ink = c.P["ink"]
        c.nb("竖图：右页出血，左页整页留空", "near")
    w, f = c.line()
    txt = ""
    if w:
        col = "#fff" if c.is_land(n) else c.P["ink"]
        txt = f'<div style="left:{40 if c.is_land(n) else 46}px;bottom:46px;{c.f_body(13, col, "letter-spacing:.12em")}">{c.say(w, "user_verbatim", f)}</div>'
    return f"""{body}{txt}
<div class="m" style="left:{HW + 26}px;bottom:20px;color:#fff">{c.lab(n)}</div>
{c.run([n], ink if not c.is_land(n) else "#fff")}"""


# ---------- 2 巨字 + 抠图 ----------
@tech("giant", "巨字压物", "type", dict(heavy=1.5, near=1.5, fast=1, warm=.5), min_photos=1)
def t_giant(c):
    word = c.big_word(4)
    if not word or len(word) < 2:
        return None
    a = c.pick(c.is_object) or c.pick(c.has_mask)
    if not a:
        return None
    b = c.pick(c.is_object) or c.pick(c.has_mask)
    col = c.P["accent"] if c.ax["heavy"] >= 0 else c.P["light"]
    k = len(word)
    big = c.T["big"] + (40 if k <= 3 else -20)
    pos = {2: [(20, 30), (600, 400)], 3: [(20, 44), (392, 430), (742, 452)], 4: [(10, 20), (290, 320), (570, 60), (830, 430)]}[k]
    chars = "".join(f'<div style="left:{x}px;top:{y}px;{c.f_disp(big, col)}">{esc(ch)}</div>' for (x, y), ch in zip(pos, word))
    c.say(word, "user_verbatim", "big_word")
    ca = fx.cutout(a, 1500)
    w1, h1 = box_fit(*ca.size, 380, 430)
    pa = c.asset(fx.halo(ca, 12 if c.ax["loose"] >= 1 else 0, (250, 246, 236, 255)), "a")
    g = 24 if c.ax["loose"] >= 1 else 0
    objs = f'<img src="{pa}" style="left:{150 - g}px;top:{352 - g}px;width:{w1 + 2 * (g + 10) if g else w1 + 20}px;transform:rotate({c.rot() - 3}deg)">'
    side = ""
    if b:
        cb = fx.cutout(b, 1700)
        w2, h2 = box_fit(*cb.size, 470, 470)
        pb = c.asset(fx.halo(cb, 12 if c.ax["loose"] >= 1 else 0), "b")
        objs += f'<img src="{pb}" style="left:{690}px;top:{-10}px;width:{w2 + 20}px;transform:rotate({c.rot()}deg)">'
        side = f'<div class="m" style="left:588px;top:640px;width:140px">{c.lab(b)}</div>'
    c.nb(f"「{word}」放到 {big}px，物件抠出来压在字上", "near")
    c.nb(f"字用{c.T['why']}", "heavy")
    return f"""{chars}{objs}
{c.mk(f"""<div style="left:452px;top:318px;{c.f_num(112, c.P['ink'], 'transform-origin:left top;transform:rotate(-90deg);white-space:nowrap')}">L{c.D[a]['L']}</div>""")}
<div class="m" style="left:588px;top:130px;width:120px">{c.lab(a)}</div>{side}
{c.run([a, b], c.P['ink'])}"""


# ---------- 3 椭圆窗 ----------
@tech("oval", "椭圆窗", "window", dict(near=0, fast=0, heavy=.5, sharp=-.3), min_photos=2)
def t_oval(c):
    n = c.pick(c.is_land, fresh_only=True) or c.pick(fresh_only=True) or c.pick()
    if not n:
        return None
    tree = fx.fit(n, SW * PX, 540 * PX, (.5, .55))
    dark = ImageEnhance.Brightness(tree.filter(ImageFilter.GaussianBlur(16))).enhance(.34 if c.ax["heavy"] >= 0 else .8)
    mk = Image.new("L", tree.size, 0)
    ImageDraw.Draw(mk).ellipse((116 * PX, 62 * PX, 1004 * PX, 480 * PX), fill=255)
    hero = c.treat(n, SW * PX, 540 * PX, (.5, .55))
    img = c.asset(Image.composite(hero, dark, mk.filter(ImageFilter.GaussianBlur(1))), "oval")
    g = fx.fit(n, 1120, 200).convert("L")
    pts = []
    for x in range(0, 1120, 4):
        v = g.crop((x, 0, x + 4, 200)).resize((1, 1), Image.BOX).getpixel((0, 0))
        pts.append(f"{x},{590 + (v - 70) * 1.2:.1f}")
    smalls, labs = "", ""
    s1 = c.pick()
    s2 = c.pick()
    if s1:
        smalls += f'<img src="{c.asset(c.treat(s1, 200 * PX, 262 * PX, (.5, .65)), "s1")}" style="left:60px;top:516px;width:200px;height:262px">'
        labs += c.lab(s1) + "<br>"
    if s2:
        smalls += f'<img src="{c.asset(c.treat(s2, 186 * PX, 262 * PX, (.5, .45)), "s2")}" style="left:880px;top:516px;width:186px;height:262px">'
        labs += c.lab(s2)
    w, f = c.line()
    big = f'<div style="left:300px;top:600px;width:540px;text-align:center;{c.f_disp(54, c.P["ink"])}">{c.say(w, "user_verbatim", f)}</div>' if w and len(w) <= 10 else ""
    c.nb("一张图只露出椭圆里的部分，四周压暗虚掉：视线被收进来", "sharp")
    c.nb("下面那条线是这张照片每一列的亮度，不是装饰")
    c.say(f"{n} 亮度曲线", "computed", "luma_line")
    return f"""<img src="{img}" style="left:0;top:0;width:{SW}px;height:540px">
<svg style="left:0;top:540px" width="1120" height="254" viewBox="0 540 1120 254"><polyline points="{' '.join(pts)}" fill="none" stroke="{c.P['ink']}" stroke-width=".7"/></svg>
<div class="c" style="left:60px;top:432px;width:60px;height:60px;background:{c.P['accent']};display:flex;align-items:center;justify-content:center"><span class="m">{c.mk("L" + str(c.D[n]['L']))}</span></div>
{smalls}{big}
<div class="m" style="left:280px;top:742px;color:{c.P['ink']};opacity:.6">{labs}</div>
{c.run([n, s1, s2], '#fff')}"""


# ---------- 4 人形填字 + 描线 ----------
@tech("silhouette", "人形填字", "derive", dict(sharp=-1, near=1, loose=.5), derive=True, min_photos=1)
def t_sil(c):
    n = c.pick(c.is_person)
    if not n:
        return None
    ws = c.word_pool()
    if not ws:
        return None
    text = "".join(w for w, _ in ws)
    for w, s in ws:
        c.say(w, s, "silhouette_text")
    fill = (255, 255, 255) if c.ax["heavy"] >= 0 else hex2rgb(c.P["paper"])
    sil = fx.text_in_silhouette(n, (HW * PX, SH * PX), (.5, .55), text, fsize=15, line=5, fill=fill, ink=hex2rgb(c.P["ink"]))
    left = c.asset(sil.convert("RGB"), "sil")
    m = c.pick(c.has_mask)
    right = ""
    if m:
        tr = fx.trace(m, HW * PX, SH * PX, hex2rgb(c.P["accent"]), thr=24)
        right += f'<img src="{c.asset(tr, "trace")}" style="left:{HW}px;top:0;width:{HW}px;height:{SH}px;opacity:.6">'
        cm = fx.cutout(m, 1500)
        w2, h2 = box_fit(*cm.size, 360, 620)
        right += f'<img src="{c.asset(cm, "cut")}" style="left:{HW + 560 - w2 - 30}px;top:{SH - h2 - 10}px;width:{w2}px">'
        right += f'<div class="m" style="left:596px;bottom:18px;width:150px">{c.lab(m)}</div>'
    dots = ""
    if c.ax["loose"] >= 0:
        for x, y, r in [(64, 92, 38), (214, 40, 26), (384, 120, 46), (470, 240, 22), (108, 244, 24)]:
            dots += f'<div class="c" style="left:{x}px;top:{y}px;width:{r}px;height:{r}px;background:#fff;opacity:.92"></div>'
    word = c.big_word(4)
    big = ""
    if word:
        c.say(word, "user_verbatim", "big_word")
        big = f'<div style="left:596px;top:60px;{c.f_disp(34, c.P["ink"], "letter-spacing:.5em;line-height:1.5;width:150px")}">{esc(word)}</div>'
    c.nb("人变成剪影，字排满人形：人在，但看不清脸", "sharp")
    c.nb("右页的线是另一张照片自己的边缘")
    return f"""<img src="{left}" style="left:0;top:0;width:{HW}px;height:{SH}px">{dots}{right}{big}
{c.mk(f"""<div style="left:{SW - 16}px;top:300px;{c.f_num(74, c.P['deep'], 'transform-origin:left top;transform:rotate(90deg);white-space:nowrap')}">L{c.D[n]['L']}</div>""")}
<div class="m" style="left:26px;bottom:18px;color:#fff">{c.lab(n)}</div>
{c.run([n, m], c.P['ink'])}"""


# ---------- 5 色带 ----------
@tech("slit", "照片压成色带", "derive", dict(fast=-1, near=-1, sharp=-1.5, loose=-1), derive=True, min_photos=0)
def t_slit(c):
    ids = [n for n in c.all_order if n in c.D]
    if len(ids) < 6:
        return None
    order = sorted(ids, key=lambda k: -c.D[k]["L"])[:16]
    bw = SW / len(order)
    bars = ""
    for i, n in enumerate(order):
        p = c.asset(fx.slit(n, int(bw * PX) + 2, SH * PX), f"bar{n}", 92)
        fg = "#fff" if c.D[n]["L"] < 55 else c.P["ink"]
        bars += f'<img src="{p}" style="left:{i * bw:.1f}px;top:0;width:{bw + .6:.1f}px;height:{SH}px">'
        bars += c.mk(f'<div style="left:{i * bw + 7:.1f}px;bottom:44px;{c.f_num(26, fg)}">{c.D[n]["L"]}</div><div class="m" style="left:{i * bw + 7:.1f}px;bottom:26px;color:{fg};font-size:7.5px">{esc(n)}</div>')
    if c.marks:
        c.say("各照片亮度 L", "computed", "slit_numbers")
    w, f = c.line()
    head = f'<div style="left:40px;top:40px;width:420px;{c.f_disp(42, c.P["night"], "line-height:1.25;font-weight:400")}">{c.say(w, "user_verbatim", f)}</div>' if w else ""
    c.nb("全书每张照片横着压成一条色带，从亮到暗排：不看内容，只看那天的颜色", "sharp")
    return f"""{bars}{head}<div class="run" style="left:auto;right:26px;color:#fff">P.{c.page_no:02d}—{c.page_no + 1:02d}</div>"""


# ---------- 6 人形窗 ----------
@tech("figure", "人形窗", "window", dict(near=1, heavy=1, sharp=-.5), derive=True, min_photos=2)
def t_figure(c):
    fig = c.pick(c.is_person, prefer=lambda k: c.info(k).get("tall", 0))
    if not fig:
        return None
    fill = c.pick(lambda k: c.info(k).get("humans", 0) == 0 and c.is_land(k)) or c.pick(lambda k: c.info(k).get("humans", 0) == 0) or c.pick(glob=True)
    if not fill:
        return None
    m = fx.mask(fig)
    bb = m.point(lambda v: 255 if v > 128 else 0).getbbox()
    asp = (bb[3] - bb[1]) / (bb[2] - bb[0])
    w = min(1080, int(640 / asp))
    w = max(w, 360)
    fw = fx.figure_window(fig, fill, w * PX)
    fh = fw.height / PX
    p = c.asset(fw, "fig")
    word = c.big_word(7)
    bgc = c.P["accent"] if c.ax["heavy"] >= 0 else c.P["paper"]
    top = f'<div style="left:0;top:0;width:{SW}px;height:{SH}px;background:{bgc}"></div>'
    if word:
        c.say(word, "user_verbatim", "big_word")
        top += f'<div style="left:0;right:0;top:6px;display:flex;justify-content:space-between;padding:0 18px;{c.f_disp(min(230, 1060 // len(word)), c.P["deep"])}">' + "".join(f"<span>{esc(ch)}</span>" for ch in word) + "</div>"
    c.nb(f"用 {fig} 里人的轮廓，框住 {fill} 的画面：人和那天的风景叠在一起", "near")
    x = (SW - w) / 2
    return f"""{top}<img src="{p}" style="left:{x:.0f}px;top:{max(128, SH - fh):.0f}px;width:{w}px">
<div class="m" style="left:26px;bottom:18px;color:{c.P['deep']}">{c.say(fig + ' 的轮廓 · ' + fill + ' 的画面', 'filename', 'figure_caption')}</div>
<div class="m" style="right:26px;bottom:18px;color:{c.P['deep']}">P.{c.page_no:02d}—{c.page_no + 1:02d}</div>"""


# ---------- 7 圆阵 ----------
@tech("circles", "圆阵", "grid", dict(loose=-1, fast=1.5), min_photos=3)
def t_circles(c):
    ph = []
    for _ in range(5):
        n = c.pick(fresh_only=len(ph) >= 3)
        if n:
            ph.append(n)
    if len(ph) < 3:
        return None
    ws = [w for w, _ in c.word_pool()][:15]
    cells, CD = [], 252
    slots = ["ph", "tx", "ph", "sol", "tx", "ph", "sol2", "dot", "ph", "sol", "tx", "num"]
    pi, ti = 0, 0
    tx_groups = [ws[i:i + 5] for i in range(0, len(ws), 5)]
    out = ""
    for i, kind in enumerate(slots):
        col, row = i % 4, i // 4
        x, y = 22 + col * 272, 22 + row * 254
        if kind == "ph" and pi < len(ph):
            n = ph[pi]; pi += 1
            out += f'<img class="c" src="{c.asset(c.treat(n, CD * PX, CD * PX, (.5, .4)), "c" + n)}" style="left:{x}px;top:{y}px;width:{CD}px;height:{CD}px">'
        elif kind == "tx" and ti < len(tx_groups):
            rows = ""
            grp = tx_groups[ti]
            y0 = (CD - 42 * len(grp)) // 2
            for j, t in enumerate(grp):
                yc = y0 + 42 * j + 21
                chord = 2 * math.sqrt(max(0, (CD / 2) ** 2 - (CD / 2 - yc) ** 2)) - 24
                fs = max(9, min(20, int(chord / max(len(t), 1))))
                rows += f'<div style="position:absolute;left:0;right:0;top:{yc - 21}px;border-bottom:1px solid {c.P["ink"]}33;height:42px;text-align:center;{c.f_body(fs, "#1A1A1C", "line-height:42px;white-space:nowrap")}">{esc(t)}</div>'
            for t in tx_groups[ti]:
                c.say(t, "user_verbatim" if any(t == w for w, _ in c.user_words()) else "see/notes", "circle_text")
            ti += 1
            out += f'<div class="c" style="left:{x}px;top:{y}px;width:{CD}px;height:{CD}px;background:#fff;overflow:hidden">{rows}</div>'
        elif kind == "dot":
            out += f'<div class="c" style="left:{x}px;top:{y}px;width:{CD}px;height:{CD}px;background-color:{c.P["light"]};background-image:radial-gradient({c.P["deep"]} 7px,transparent 7.6px);background-size:27px 27px"></div>'
        elif kind == "num":
            c.say(f"{len(c.all_order)}", "computed", "photo_count")
            out += f'<div class="c" style="left:{x}px;top:{y}px;width:{CD}px;height:{CD}px;background:{c.P["night"]};display:flex;align-items:center;justify-content:center;{c.f_num(120, c.P["accent"])}">{len(c.all_order)}</div>'
        else:
            colr = c.P["accent"] if kind == "sol" else c.P["second"]
            out += f'<div class="c" style="left:{x}px;top:{y}px;width:{CD}px;height:{CD}px;background:{colr}"></div>'
    c.nb("12 个一样大的圆排整齐：照片、字、颜色轮流出现，节奏是齐的", "loose")
    return out


# ---------- 8 渐暗 ----------
@tech("fade", "渐暗满版", "bleed", dict(fast=-2, heavy=1, warm=-1, near=-.5), bleed=True)
def t_fade(c):
    n = c.pick(c.is_land, fresh_only=True) or c.pick(fresh_only=True) or c.pick()
    if not n:
        return None
    im = c.treat(n, SW * PX, SH * PX, (.5, .7))
    img = c.asset(fx.fade_to(im, hex2rgb(c.P["night"]), .0, .9), "fade")
    w, f = c.line()
    t = f'<div style="left:600px;bottom:52px;{c.f_body(20, "#fff", "letter-spacing:.14em")}">{c.say(w, "user_verbatim", f)}</div>' if w else ""
    c.nb("满版照片从上往下慢慢沉到深色里，字很小", "fast")
    return f"""<img src="{img}" style="left:0;top:0;width:{SW}px;height:{SH}px">{t}
<div class="c" style="left:1040px;top:64px;width:16px;height:16px;background:#fff"></div>
{c.run([n], '#fff')}"""


# ---------- 9 两种墨：纸片 ----------
@tech("cards", "两种墨·纸片", "collage", dict(sharp=-1, loose=1, heavy=.5), bleed=True, min_photos=2)
def t_cards(c):
    bgp = c.pick(lambda k: c.info(k).get("humans", 0) == 0)
    p1 = c.pick()
    if not p1:
        return None
    p2 = c.pick()
    d0, d1 = c.P["duo"]
    if bgp:
        bg = c.asset(fx.duo(bgp, d0, d1, SW * PX, SH * PX, g=.04), "bg")
    else:
        im = Image.new("RGB", (SW * PX, SH * PX), hex2rgb(d1))
        dr = ImageDraw.Draw(im)
        for yy in range(0, SH * PX, 30):
            for xx in range((yy // 30) % 2 * 15, SW * PX, 30):
                dr.ellipse((xx, yy, xx + 9, yy + 9), fill=hex2rgb(d0))
        bg = c.asset(fx.grain(im, .04), "bg")
    card = mix(c.P["accent"], "#FFFFFF", .55)
    k1 = c.asset(fx.duo(p1, mix(c.P["second"], "#000", .2), card, 420 * PX, 420 * PX, (.5, .35), g=.05), "k1")
    inkc = mix(c.P["second"], "#000", .15)
    w1 = c.big_word(5)
    t1 = ""
    if w1:
        c.say(w1, "user_verbatim", "big_word")
        t1 = f'<div style="position:absolute;left:24px;top:22px;{c.f_disp(56, inkc)}">{esc(w1)}</div>'
    second = ""
    if p2:
        k2 = c.asset(c.treat(p2, 220 * PX, 310 * PX), "k2")
        w2 = c.big_word(5, avoid=(w1,))
        t2 = ""
        if w2:
            c.say(w2, "user_verbatim", "big_word")
            t2 = f'<div style="position:absolute;right:14px;bottom:6px;{c.f_disp(56, card)}">{esc(w2)}</div>'
        second = f"""<div style="left:650px;top:210px;width:300px;height:500px;background:{c.P['second']};transform:rotate({abs(c.rot()) + 2}deg);box-shadow:0 8px 24px rgba(0,0,30,.25)">
<img src="{k2}" style="position:absolute;left:40px;top:80px;width:220px;height:310px">{t2}</div>"""
    c.nb(f"底图和纸片都只用两种颜色：{d0} 和 {d1}", "sharp")
    c.nb("纸片歪着压在照片上，像随手放上去的", "loose")
    return f"""<img src="{bg}" style="left:0;top:0;width:{SW}px;height:{SH}px">
<div style="left:96px;top:70px;width:420px;height:640px;background:{card};transform:rotate({-abs(c.rot()) - 2}deg);box-shadow:0 8px 24px rgba(0,0,30,.25)">
<img src="{k1}" style="position:absolute;left:0;bottom:0;width:420px;height:420px;mix-blend-mode:multiply">{t1}</div>{second}"""


# ---------- 10 两种墨：大字 ----------
@tech("twoink", "两种墨·大字", "type", dict(sharp=-1, heavy=1.5, fast=1, loose=-.3), min_photos=2)
def t_twoink(c):
    a = c.pick(lambda k: not c.is_land(k)) or c.pick()
    b = c.pick()
    if not a or not b:
        return None
    Y = mix(c.P["accent"], "#FFFFFF", .6)
    B = c.P["flat2"] if c.ax["sharp"] >= 1 else mix(c.P["second"], "#FFFFFF", .1)
    dk = mix(B, "#000000", .3)
    ia = c.asset(fx.duo(a, dk, Y, HW * PX, 470 * PX, (.5, .4), g=.05, gamma=.75), "a")
    ib = c.asset(fx.duo(b, dk, Y, 318 * PX, 470 * PX, (.5, .42), g=.05, gamma=.85), "b")
    stack = ""
    for i in range(3):
        n = c.pick(fresh_only=True)
        if not n:
            break
        stack += f'<img src="{c.asset(fx.duo(n, dk, Y, 150 * PX, 150 * PX, (.5, .6), g=.04, gamma=.85), "s" + n)}" style="left:938px;top:{64 + i * 160}px;width:156px;height:150px">'
    w1 = c.big_word(4)
    w2 = c.big_word(4, avoid=(w1,))
    t1 = t2 = ""
    if w1:
        c.say(w1, "user_verbatim", "big_word")
        t1 = f'<div style="left:22px;top:22px;width:520px;{c.f_disp(148 if len(w1) <= 3 else 120, B, "line-height:.95")}">{esc(w1)}</div>'
    if w2:
        c.say(w2, "user_verbatim", "big_word")
        t2 = f'<div style="left:596px;top:560px;white-space:nowrap;{c.f_disp(170 if len(w2) <= 3 else 120, Y)}">{esc(w2)}</div>'
    c.nb(f"整个跨页只有两种墨：{Y} 和 {B}，蓝压在黄上就是全部颜色", "sharp")
    return f"""<div style="left:{HW}px;top:0;width:{HW}px;height:{SH}px;background:{B}"></div>
<img src="{ia}" style="left:0;top:324px;width:{HW}px;height:470px">{t1}
<img src="{ib}" style="left:600px;top:64px;width:318px;height:470px">{stack}{t2}
<div class="m" style="left:340px;top:30px;color:{dk};width:200px">{c.lab(a)}</div>"""


# ---------- 11 闪光撞色 ----------
@tech("flash", "闪光撞色", "flat", dict(sharp=2, fast=1, near=-1, heavy=1, warm=.5), min_photos=2)
def t_flash(c):
    a = c.pick()
    b = c.pick()
    if not a or not b:
        return None
    d = c.pick(fresh_only=True)
    c1, c2 = c.P["flat1"], c.P["flat2"]
    out = f'<div style="left:0;top:0;width:{HW}px;height:{SH}px;background:{c1}"></div><div style="left:{HW}px;top:0;width:{HW}px;height:{SH}px;background:{c2}"></div>'
    out += f'<img src="{c.asset(fx.flash(a, 430 * PX, 326 * PX, (.5, .4)), "a")}" style="left:0;top:0;width:430px;height:326px">'
    out += f'<img src="{c.asset(fx.flash(b, 230 * PX, 176 * PX, (.5, .4)), "b")}" style="left:826px;top:290px;width:230px;height:176px">'
    marks = [(768, 300, "(000)")]
    if d:
        out += f'<img src="{c.asset(fx.flash(d, 230 * PX, 176 * PX, (.5, .5)), "d")}" style="left:690px;top:520px;width:230px;height:176px">'
        marks.append((640, 530, "(001)"))
    for x, y, t in marks:
        out += f'<div class="m" style="left:{x}px;top:{y}px;font-size:13px">{t}</div>'
    rnd = c.rnd
    for colr in ["#E8392A", "#3CCB5D", c2, c1, "#FFFFFF"]:
        out += f'<div style="left:{rnd.randint(30, 1080)}px;top:{rnd.randint(30, 760)}px;width:9px;height:9px;background:{colr}"></div>'
    w, f = c.line()
    if w:
        out += f'<div style="left:596px;top:40px;width:320px;{c.f_body(13, "#111", "line-height:1.35")}">{c.say(w, "user_verbatim", f)}</div>'
    c.say("(000) (001)", "mark", "frame_no")
    nm = c.P.get("flat_names")
    c.nb(f"整页平涂两块颜色{('（接近 Riso 的 ' + nm[0] + ' / ' + nm[1] + '）') if nm else ''}，照片很小、开闪光灯一样亮", "sharp")
    return out + f'<div class="m" style="left:34px;bottom:30px;color:#fff">{c.lab(a)}</div>'


# ---------- 12 纸与物（版画） ----------
@tech("etch", "纸与物·版画", "paper", dict(fast=-1, heavy=-1, warm=.5, near=.5, sharp=-.5), derive=True, min_photos=1)
def t_etch(c):
    a = c.pick(c.is_object) or c.pick(c.has_mask)
    if not a:
        return None
    b = c.pick(c.is_object, fresh_only=True) or c.pick(c.has_mask, fresh_only=True)
    base = hex2rgb(c.P["paper"])
    paper = c.asset(fx.speckle_paper(SW * PX, SH * PX, base, c.rnd.randint(1, 99), c.ax["loose"] >= 1, 4200), "paper")
    blk = c.P["light"]
    ink = hex2rgb(mix(c.P["ink"], c.P["deep"], .3))
    hc = tuple(hex2rgb(mix(c.P["paper"], "#FFFFFF", .1))) + (215,) if c.P.get("dark") else (226, 216, 200, 215)
    ea = fx.etch(fx.cutout(a, 1600), ink=ink, halo_color=hc)
    w1, h1 = box_fit(*ea.size, 500, 560)
    out = f'<img src="{paper}" style="left:0;top:0;width:{SW}px;height:{SH}px">'
    out += f'<div style="left:620px;top:0;width:500px;height:{SH}px;background:{blk};opacity:.7;mix-blend-mode:multiply"></div>'
    out += f'<div style="left:330px;top:392px;width:390px;height:402px;background:{blk};opacity:.7;mix-blend-mode:multiply"></div>'
    out += f'<img src="{c.asset(ea, "a")}" style="left:{590}px;top:{max(120, SH - h1 - 60)}px;width:{w1}px;transform:rotate({c.rot(.5)}deg)">'
    labs = [a]
    if b:
        eb = fx.etch(fx.cutout(b, 1200), ink=ink, halo_color=hc)
        w2, h2 = box_fit(*eb.size, 200, 300)
        out += f'<img src="{c.asset(eb, "b")}" style="left:190px;top:118px;width:{w2}px;transform:rotate({c.rot(.5)}deg)">'
        labs.append(b)
    w, f = c.line()
    if w:
        out += f'<div style="left:628px;top:64px;width:300px;{c.f_body(12, c.P["ink"])}">{c.say(w, "user_verbatim", f)}</div>'
    if c.marks:
        c.say(" / ".join(labs), "filename", "etch_caption")
        out += f'<div class="m" style="left:60px;bottom:50px;color:{c.P["ink"]};opacity:.7">{" / ".join(esc(x) for x in labs)}</div>'
    c.nb("物件抠出来做成版画（只留一种墨），放在有斑点的纸上，大片留空", "heavy")
    return out


# ---------- 13 冷调留白 ----------
@tech("cold", "冷调留白", "space", dict(warm=-2, heavy=-1, fast=-1, near=-1), bleed=True, min_photos=1)
def t_cold(c):
    a = c.pick(lambda k: not c.is_land(k)) or c.pick()
    if not a:
        return None
    b = c.pick(fresh_only=True)
    im = ImageEnhance.Color(c.treat(a, HW * PX, SH * PX, (.5, .65))).enhance(.75)
    out = f'<img src="{c.asset(im, "a")}" style="left:{HW}px;top:0;width:{HW}px;height:{SH}px">'
    rings = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{c.P["ink"]}" stroke-width=".6" opacity=".8"/>' for x, y, r in [
        (240, 250, 96), (330, 200, 58), (186, 338, 54), (300, 330, 76), (380, 300, 36), (250, 420, 30), (150, 240, 40), (392, 392, 18)])
    out += f'<svg style="left:0;top:0" width="560" height="794">{rings}</svg>'
    for x, y, s in [(390, 110, 14), (84, 150, 12), (108, 520, 14), (448, 560, 12)]:
        out += f'<div style="left:{x}px;top:{y}px;width:{s}px;height:{s}px;background:{c.P["accent"]}"></div>'
    w, f = c.line()
    if w:
        out += f'<div style="left:92px;top:200px;width:200px;{c.f_disp(34, c.P["ink"], "line-height:1.2")}">{c.say(w, "user_verbatim", f)}</div>'
    if b:
        out += f'<div style="left:470px;top:462px;background:#F4F5F5;padding:9px 9px 26px;transform:rotate({c.rot(.4)}deg)"><img src="{c.asset(c.treat(b, 210 * PX, 150 * PX), "b")}" style="width:210px;height:150px;position:static"></div>'
        out += f'<div class="m" style="left:482px;top:632px;color:#5c666e;font-size:7.5px">{c.lab(b)}</div>'
    c.nb("左页只有细线和一点点字，右页一张降了饱和的照片：凉、空", "warm")
    return out + c.run([a, b], c.P["ink"])


# ---------- 14 字河 ----------
@tech("river", "字河", "text", dict(heavy=-1, fast=.5, near=-1, sharp=-.5), derive=True, min_photos=4)
def t_river(c):
    ws = c.word_pool()
    if len(ws) < 3:
        return None
    bgp = c.pick(c.is_land) or c.pick()
    if not bgp:
        return None
    trw = fx.trace(bgp, SW * PX, SH * PX, hex2rgb(mix(c.P["accent"], c.P["paper"], .35)), thr=34, blur=2.2)
    out = f'<img src="{c.asset(trw, "tr")}" style="left:0;top:0;width:{SW}px;height:{SH}px;opacity:.55">'
    out += f'<div style="left:500px;top:0;width:120px;height:{SH}px;background:linear-gradient(90deg,transparent,{c.P["light"]} 25%,{mix(c.P["second"], "#fff", .6)} 60%,transparent);opacity:.85"></div>'
    words = []
    for w, s in ws:
        words += [(x, s) for x in w.split()] if " " in w else [(w, s)]
    for w, s in ws:
        c.say(w, s, "river")
    RN = max(14, min(28, 22 + 3 * c.ax["fast"]))
    for i in range(RN):
        t = i / (RN - 1)
        wd = 180 + 440 * math.sin(math.pi * t) ** .75
        k = 4 if wd > 420 else (3 if wd > 300 else 2)
        row = [words[(i * 3 + j) % len(words)][0] for j in range(k)]
        out += f'<div style="left:{560 - wd / 2:.0f}px;top:{66 + i * (648 // RN)}px;width:{wd:.0f}px;display:flex;justify-content:space-between;{c.f_body(11.5, c.P["ink"], "line-height:1")}">' + "".join(f"<span>{esc(x)}</span>" for x in row) + "</div>"
    spots = [(90, 52, 190, 150), (26, 300, 150, 196), (150, 580, 170, 190), (880, 52, 190, 136), (888, 352, 206, 130), (800, 620, 150, 150)]
    ids = [bgp]
    for (x, y, w, h) in spots:
        n = c.pick(fresh_only=len(ids) > 3)
        if not n:
            break
        ids.append(n)
        out += f'<img src="{c.asset(c.treat(n, w * PX, h * PX), "p" + n)}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
        lab = c.note(n) or c.seen(n) or n
        src = "user_verbatim" if c.note(n) else ("derived_visible" if c.seen(n) else "filename")
        out += f'<div style="left:{x}px;top:{y + h + 6}px;{c.f_lat(12, c.P["ink"])}">{c.say(lab, src, "river_caption")}</div>'
    if len(ids) < 4:
        return None
    c.nb("字排成一条中间宽两头窄的河，照片散在两岸，很轻", "heavy")
    return out + c.run(ids[:3], c.P["ink"])


# ---------- 15 一张很小的照片（新） ----------
@tech("tiny", "大片空白里一张小照片", "space", dict(near=-2, fast=-2, heavy=-1, loose=-1), max_use=2)
def t_tiny(c):
    # 逐页指定了两张：第一张铺满左页，第二张照常小小地放在右页的空白里（左页不再空着）
    left = c.pick() if c.pin and len(c.pin.get("photos") or []) >= 2 else None
    n = c.pick()
    if not n:
        return None
    land = c.is_land(n)
    w, h = (190, 136) if land else (136, 190)
    x = 760 if c.rnd.random() < .6 else 140
    y = 430 + c.rnd.randint(-40, 60)
    if left:
        x = 760
    im = c.treat(n, w * PX, h * PX)
    out = f'<img src="{c.asset(fx.plain_paper(SW * PX, SH * PX, hex2rgb(c.P["paper"])), "pp")}" style="left:0;top:0;width:{SW}px;height:{SH}px">'
    if left:
        out += left_page(c, left, c.pin.get("left_style"))
    out += f'<img src="{c.asset(im, "t")}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
    out += f'<div class="m" style="left:{x}px;top:{y + h + 8}px;color:{c.P["ink"]};opacity:.65">{c.lab(n)}</div>'
    word = c.big_word(6)
    if word:
        c.say(word, "user_verbatim", "big_word")
        colr = c.P["light"] if c.ax["heavy"] <= 0 else c.P["accent"]
        if len(word) <= 2:
            sz = min(c.T["big"], 440 // len(word))
            tx = 60 if x > 500 else 600
            out += f'<div style="left:{tx}px;top:70px;{c.f_disp(sz, colr, "white-space:nowrap")}">{esc(word)}</div>'
        else:
            sz = min(int(c.T["big"] * .8), 700 // len(word))
            tx = (90 if x > 500 else 1030 - sz)
            out += f'<div style="left:{tx}px;top:40px;writing-mode:vertical-rl;{c.f_disp(sz, colr, "white-space:nowrap")}">{esc(word)}</div>'

    wl, f = c.line(avoid=(word,))
    if wl:
        out += f'<div style="left:{x}px;top:{y + h + 30}px;white-space:nowrap;{c.f_body(13, c.P["ink"], "letter-spacing:.16em")}">{c.say(wl, "user_verbatim", f)}</div>'
    if not left:
        c.nb(f"一张照片只占跨页约 {w * h / (SW * SH) * 100:.0f}%，四周全空", "near")
    return out + c.run([left, n] if left else [n], c.P["ink"])


def arch_mask(w, h):
    """拱形窗：上面是半圆，下面是直边。"""
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.ellipse((0, 0, w - 1, w - 1), fill=255)
    d.rectangle((0, w // 2, w - 1, h - 1), fill=255)
    return m


def left_page(c, n, style=None):
    """逐页指定时左页的照片怎么放（不整页铺满）：
    fade = 照片从上往下化进纸里；object = 抠出主体当实物摆在纸上（带影子、微斜）；
    arch = 拱形窗；strip = 一条窄窄的竖条（像门缝）；bleed = 整页铺满。"""
    paper = hex2rgb(c.P["paper"])
    if style == "object" and c.has_mask(n):
        rg = fx.cutout(n, 1100)
        if rg is not None:
            k = min(330 / rg.width, 470 / rg.height)
            w, h = int(rg.width * k), int(rg.height * k)
            rg = rg.resize((w * PX, h * PX), Image.LANCZOS)
            sh = Image.new("RGBA", (w * PX + 80, h * PX + 80), (40, 30, 20, 0))
            sh.putalpha(Image.new("L", sh.size, 0))
            al = Image.new("L", sh.size, 0)
            al.paste(rg.split()[3].point(lambda v: int(v * .32)), (40, 52))
            sh.putalpha(al.filter(ImageFilter.GaussianBlur(14)))
            sh.alpha_composite(rg, (40, 40))
            r = -4 if c.rnd.random() < .5 else 3
            x, y = (HW - w) // 2 - 10, (SH - h) // 2 + 10
            c.nb("这张照片里的东西被剪下来，像真的放在纸上一样（带一点影子、微微歪着）", "near")
            return f'<img src="{c.asset(sh, "lo")}" style="left:{x - 20}px;top:{y - 20}px;width:{w + 40}px;height:{h + 40}px;transform:rotate({r}deg)">'
    if style == "object_bg" and c.has_mask(n):
        m = fx.mask(n)
        im = fx.src(n)
        bb = m.getbbox() if m is not None else None
        if bb:
            # 主体外扩一圈，把周围的桌面（木纹）一起留下来；边缘羽化进纸里，不是硬邦邦的方框
            pw, ph = (bb[2] - bb[0]) * .45, (bb[3] - bb[1]) * .3
            box = (max(0, int(bb[0] - pw)), max(0, int(bb[1] - ph)), min(im.width, int(bb[2] + pw)), min(im.height, int(bb[3] + ph)))
            crop = im.crop(box)
            k = min(440 / crop.width, 620 / crop.height)
            w, h = int(crop.width * k), int(crop.height * k)
            crop = c.treat_im(crop.resize((w * PX, h * PX), Image.LANCZOS)).convert("RGBA")
            f = int(min(w, h) * PX * .05)
            al = Image.new("L", crop.size, 0)
            ImageDraw.Draw(al).rounded_rectangle((f, f, crop.width - f, crop.height - f), radius=f, fill=255)
            crop.putalpha(al.filter(ImageFilter.GaussianBlur(f * .55)))
            x, y = (HW - w) // 2, (SH - h) // 2 + 10
            c.nb("书和它下面的一块木桌面一起留下来，四边慢慢化进纸里：保留桌面的木纹，又不是一整页照片", "near")
            return f'<img src="{c.asset(crop, "lob")}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
    if style == "fade":
        w, h = 420, 560
        im = fx.fade_to(c.treat(n, w * PX, h * PX, (.5, .4)), paper, start=.5, strength=1.0)
        c.nb("左页照片不铺满：上面清楚，往下慢慢化进纸里", "fast")
        return f'<img src="{c.asset(im, "lf")}" style="left:70px;top:0;width:{w}px;height:{h}px">'
    if style in ("arch", "strip"):
        w, h = (300, 440) if style == "arch" else (150, 560)
        im = c.treat(n, w * PX, h * PX, c.pin.get("left_center", (.5, .5)) if c.pin else (.5, .5)).convert("RGBA")
        if style == "arch":
            im.putalpha(arch_mask(w * PX, h * PX))
        x, y = (HW - w) // 2, (SH - h) // 2 + 20
        c.nb("左页只开一扇拱形的窗" if style == "arch" else "左页只留一条窄窄的竖缝，像从门缝里看", "near")
        return f'<img src="{c.asset(im, "la")}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
    c.nb("左页一整张铺满，右页一大片空白里只放一张小照片：一边满、一边空", "near")
    return f'<img src="{c.asset(c.treat(n, HW * PX, SH * PX, (.5, .5)), "tl")}" style="left:0;top:0;width:{HW}px;height:{SH}px">'


# ---------- 20 门与窗（两张照片各开一个形状窗，大片留纸） ----------
@tech("windows", "门缝与拱窗", "window", dict(near=-1, fast=-1), max_use=1, min_photos=2)
def t_windows(c):
    a = c.pick()
    b = c.pick()
    if not a or not b:
        return None
    out = f'<img src="{c.asset(fx.plain_paper(SW * PX, SH * PX, hex2rgb(c.P["paper"])), "pp")}" style="left:0;top:0;width:{SW}px;height:{SH}px">'
    w1, h1 = 160, 560
    ia = c.treat(a, w1 * PX, h1 * PX, tuple((c.pin or {}).get("center_a", (.5, .5))))
    out += f'<img src="{c.asset(ia, "wa")}" style="left:150px;top:118px;width:{w1}px;height:{h1}px">'
    right_bleed = (c.pin or {}).get("right_style") == "bleed"
    if right_bleed:   # 右页照片整页铺满（用户要保留原来的样子）
        out += f'<img src="{c.asset(c.treat(b, HW * PX, SH * PX, (.5, .5)), "wb")}" style="left:{HW}px;top:0;width:{HW}px;height:{SH}px">'
    else:
        w2, h2 = 300, 450
        ib = c.treat(b, w2 * PX, h2 * PX, (.5, .5)).convert("RGBA")
        ib.putalpha(arch_mask(w2 * PX, h2 * PX))
        out += f'<img src="{c.asset(ib, "wb")}" style="left:{HW + 130}px;top:{SH - h2 - 90}px;width:{w2}px;height:{h2}px">'
    w, f = c.line()
    if w:
        out += f'<div style="left:{150 + w1 + 30}px;top:{118 + h1 - 14}px;white-space:nowrap;{c.f_body(13, c.P["ink"], "letter-spacing:.16em")}">{c.say(w, "user_verbatim", f)}</div>'
    c.nb("左页只留一条窄缝，像从门缝里看；右页整页铺满，像推门进去" if right_bleed else
         "两张照片都不铺满：左边一条窄缝，右边一扇拱窗，四周留着纸——从门外看进店里", "near")
    return out + c.run([a, b], "#fff" if right_bleed else c.P["ink"])


REG[-1]["pin_only"] = True


# ---------- 16 散落贴纸（新） ----------
@tech("scatter", "散落贴纸", "collage", dict(loose=2, fast=2, near=1, warm=.5, sharp=.5), max_use=1, min_photos=3)
def t_scatter(c):
    ids = []
    for _ in range(6):
        n = c.pick(fresh_only=len(ids) >= 3)
        if n:
            ids.append(n)
    if len(ids) < 3:
        return None
    bg = c.P["accent"] if c.ax["heavy"] >= 1 else c.P["paper"]
    out = f'<div style="left:0;top:0;width:{SW}px;height:{SH}px;background:{bg}"></div>'
    if c.ax["heavy"] < 1:
        out += f'<img src="{c.asset(fx.speckle_paper(SW * PX, SH * PX, hex2rgb(c.P["paper"]), 3, True, 1600), "pp")}" style="left:0;top:0;width:{SW}px;height:{SH}px">'
    word = c.big_word(6)
    slots = [(40, 50, 330), (390, 270, 320), (700, 40, 360), (760, 400, 330), (460, 20, 230), (120, 330, 250)]
    if not word:
        slots[5] = (120, 430, 300)
    c.rnd.shuffle(slots)
    for n, (x, y, s) in zip(ids, slots):
        r = c.rot(1.4)
        if c.has_mask(n):
            cu = fx.cutout(n, 1200)
            h0 = fx.halo(cu, 16, (252, 250, 244, 255))
            w, h = box_fit(*h0.size, s, s)
            out += f'<img src="{c.asset(h0, "h" + n)}" style="left:{x}px;top:{y}px;width:{w}px;transform:rotate({r}deg)">'
        else:
            im = c.treat(n, int(s * .78) * PX, int(s * .78 * .75) * PX)
            out += f'<div style="left:{x}px;top:{y}px;background:#FBFAF5;padding:8px;box-shadow:0 4px 14px rgba(0,0,0,.18);transform:rotate({r}deg)"><img src="{c.asset(im, "p" + n)}" style="position:static;width:{int(s * .78)}px;height:{int(s * .78 * .75)}px"></div>'
    for _ in range(14):
        rr = c.rnd.choice([10, 14, 22, 30, 44])
        out += f'<div class="c" style="left:{c.rnd.randint(10, 1090)}px;top:{c.rnd.randint(10, 770)}px;width:{rr}px;height:{rr}px;background:{c.rnd.choice([c.P["second"], c.P["deep"], "#fff", c.P["light"]])}"></div>'
    if word:
        c.say(word, "user_verbatim", "big_word")
        out += f'<div style="left:44px;top:{SH - 40 - min(150, 680 // len(word))}px;white-space:nowrap;transform:rotate(-4deg);{c.f_disp(min(150, 680 // len(word)), c.P["deep"] if bg != c.P["deep"] else "#fff")}">{esc(word)}</div>'
    c.nb("照片抠出来带一圈纸边，歪着叠着撒在页上，还有散落的圆点", "loose")
    c.nb("一个跨页塞了 %d 张" % len(ids), "fast")
    return out + c.run(ids[:3], c.P["ink"])


# ---------- 17 规矩的小样张（新） ----------
@tech("grid", "规矩的小样张", "grid", dict(loose=-2, fast=1, near=-1, heavy=-.5), max_use=1, min_photos=4)
def t_grid(c):
    ids = []
    for _ in range(8):
        n = c.pick(fresh_only=len(ids) >= 4)
        if n:
            ids.append(n)
    if len(ids) < 4:
        return None
    out = f'<img src="{c.asset(fx.plain_paper(SW * PX, SH * PX, hex2rgb(c.P["paper"])), "pp")}" style="left:0;top:0;width:{SW}px;height:{SH}px">'
    cw, chh, gx, gy = 104, 140, 22, 62
    x0, y0 = HW + (HW - (4 * cw + 3 * gx)) // 2, 150
    for i, n in enumerate(ids):
        col, row = i % 4, i // 4
        x, y = x0 + col * (cw + gx), y0 + row * (chh + gy)
        out += f'<img src="{c.asset(c.treat(n, cw * PX, chh * PX), "g" + n)}" style="left:{x}px;top:{y}px;width:{cw}px;height:{chh}px">'
        out += f'<div style="left:{x}px;top:{y + chh + 8}px;{c.f_num(14, c.P["ink"])}">{i + 1:02d}</div>' + c.mk(f'<div class="m" style="left:{x + 26}px;top:{y + chh + 10}px;color:{c.P["ink"]};opacity:.6">{esc(n)}</div>')
    c.say("01–%02d 序号 + 文件名" % len(ids), "mark", "grid_index")
    w, f = c.line()
    if w:
        out += f'<div style="left:60px;top:150px;width:380px;{c.f_disp(40, c.P["ink"], "line-height:1.3")}">{c.say(w, "user_verbatim", f)}</div>'
    out += c.mk(f'<div style="left:60px;top:{SH - 120}px;{c.f_num(c.T["big"] // 2, c.P["accent"])}">{len(ids):02d}</div>')
    c.nb("照片一样大、对齐成网格、编上号：克制，像整理标本", "loose")
    return out + c.run(ids[:3], c.P["ink"])


# ---------- 19 对开（两张竖图各占一页，都出血） ----------
@tech("pair", "对开两张", "bleed", dict(near=1.5, fast=.5, sharp=.3), bleed=True, max_use=1, min_photos=2)
def t_pair(c):
    a = c.pick(lambda k: not c.is_land(k))
    b = c.pick(lambda k: not c.is_land(k))
    if not a or not b:
        return None
    ia = c.asset(c.treat(a, HW * PX, SH * PX, (.5, .5)), "a")
    ib = c.asset(c.treat(b, HW * PX, SH * PX, (.5, .45)), "b")
    out = f'<img src="{ia}" style="left:0;top:0;width:{HW}px;height:{SH}px"><img src="{ib}" style="left:{HW}px;top:0;width:{HW}px;height:{SH}px">'
    w, f = c.line()
    if w:
        out += f'<div style="left:{HW + 40}px;bottom:46px;{c.f_body(13, "#fff", "letter-spacing:.12em;text-shadow:0 1px 6px rgba(0,0,0,.35)")}">{c.say(w, "user_verbatim", f)}</div>'
    c.nb("两张竖图一页一张，都出血到纸边：像同时看着两样东西", "near")
    return out + c.run([a, b], "#fff")


REG[-1]["pin_only"] = True   # 只在逐页指定（layout）里用，不参与自动挑选，免得改变已有书的排法


# ---------- 18 呼吸页（只用于凑页数，不放照片） ----------
@tech("breath", "呼吸页", "breath", dict(fast=-1), max_use=2, min_photos=0)
def t_breath(c):
    out = f'<img src="{c.asset(fx.plain_paper(SW * PX, SH * PX, hex2rgb(c.P["paper"])), "pp")}" style="left:0;top:0;width:{SW}px;height:{SH}px">'
    out += f'<div class="c" style="left:{HW + 250}px;top:380px;width:30px;height:30px;background:{c.P["accent"]}"></div>'
    if c.pin is not None:
        c.nb("一个跨页什么都不放，当作段落之间的停顿", "fast")
    w, f = c.line()
    if w:
        out += f'<div style="left:{HW + 60}px;top:{SH - 110}px;{c.f_body(13, c.P["ink"], "letter-spacing:.2em")}">{c.say(w, "user_verbatim", f)}</div>'
    if c.pin is None:
        c.nb("留一个跨页什么都不放，让前后两页喘口气（也让页数凑成 4 的倍数）", "fast")
    return out + f'<div class="m" style="right:26px;top:18px;color:{c.P["ink"]}">P.{c.page_no:02d}—{c.page_no + 1:02d}</div>'


REG[-1]["pad_only"] = True


# ======================================================================
# 封面 + 封底（一个外跨页：左=封底，右=封面）
# ======================================================================
def cover(c, n):
    P, ax = c.P, c.ax
    title = c.F.get("title") if c.F.get("title_source") == "user_verbatim" else None
    out = ""
    if title:
        c.say(title, "user_verbatim", "title")
    if ax["near"] <= -1 and ax["heavy"] <= 0:
        # 远、淡：纸上一张小照片
        out += f'<img src="{c.asset(fx.plain_paper(SW * PX, SH * PX, hex2rgb(P["paper"])), "pp")}" style="left:0;top:0;width:{SW}px;height:{SH}px">'
        w, h = (230, 300) if not c.is_land(n) else (300, 214)
        out += f'<img src="{c.asset(c.treat(n, w * PX, h * PX), "cv")}" style="left:{HW + 560 - w - 70}px;top:{120}px;width:{w}px;height:{h}px">'
        if title:
            out += f'<div style="left:{HW + 60}px;top:{560}px;{c.f_disp(64, P["ink"], "line-height:1.2;width:420px")}">{esc(title)}</div>'
        c.nb("封面：纸上一张小照片，标题不大", "near")
    elif ax["loose"] >= 2:
        out += f'<div style="left:0;top:0;width:{SW}px;height:{SH}px;background:{P["accent"]}"></div>'
        cu = fx.cutout(n, 1400) if c.has_mask(n) else None
        if cu:
            h0 = fx.halo(cu, 20, (252, 250, 244, 255))
            w, h = box_fit(*h0.size, 470, 500)
            out += f'<img src="{c.asset(h0, "cv")}" style="left:{HW + 50}px;top:{SH - h - 20}px;width:{w}px;transform:rotate({c.rot()}deg)">'
        else:
            out += f'<div style="left:{HW + 60}px;top:180px;background:#fff;padding:10px;transform:rotate({c.rot()}deg)"><img src="{c.asset(c.treat(n, 420 * PX, 520 * PX), "cv")}" style="position:static;width:420px;height:520px"></div>'
        if title:
            out += f'<div style="left:{HW + 30}px;top:30px;width:520px;{c.f_disp(min(110, 1000 // max(len(title), 1)), P["deep"], "line-height:1.05;transform:rotate(-3deg)")}">{esc(title)}</div>'
        for _ in range(10):
            r = c.rnd.choice([12, 20, 34])
            out += f'<div class="c" style="left:{c.rnd.randint(20, 1090)}px;top:{c.rnd.randint(20, 770)}px;width:{r}px;height:{r}px;background:{c.rnd.choice([P["second"], "#fff", P["deep"]])}"></div>'
        c.nb("封面：整面主色，抠出来的照片带纸边歪着贴，手写大标题", "loose")
    else:
        out += f'<div style="left:0;top:0;width:{HW}px;height:{SH}px;background:{P["deep"]}"></div>'
        cim = c.treat(n, HW * PX, SH * PX)
        out += f'<img src="{c.asset(cim, "cv")}" style="left:{HW}px;top:0;width:{HW}px;height:{SH}px">'
        # 透出来的圆放在照片最「空」的地方（细节最少），不压住路牌、人脸这类要紧的东西
        ed = cim.convert("L").resize((HW // 4, SH // 4)).filter(ImageFilter.FIND_EDGES)
        spots = [(80, 232), (80, 60), (268, 60), (268, 232), (80, 480), (268, 480)]
        mk_ = fx.mask(n)
        mk_ = ImageOps.fit(mk_, (HW // 4, SH // 4), Image.LANCZOS, centering=(.5, .5)) if mk_ is not None else None
        box = lambda xy: (xy[0] // 4, xy[1] // 4, (xy[0] + 212) // 4, (xy[1] + 212) // 4)
        # 细节多的地方扣分；压到抠图识别出的主体（人、手、物）扣得更重
        busy = lambda xy: ImageStat.Stat(ed.crop(box(xy))).mean[0] + (ImageStat.Stat(mk_.crop(box(xy))).mean[0] / 255 * 60 if mk_ is not None else 0)
        cx, cy = min(spots, key=lambda xy: busy(xy) + (0 if xy == (80, 232) else 1.5))   # 原位置不太乱就不挪
        out += f'<div class="c" style="left:{HW + cx}px;top:{cy}px;width:212px;height:212px;background:{P["accent"]};mix-blend-mode:screen;opacity:.9"></div>'
        if title:
            size = 138 if len(title) <= 5 else max(70, int(700 / len(title)))
            side = "right"
            if mk_ is not None:
                # 竖排标题不压主体（手、人、物）：先在右边缩小试，放不下再换到左边
                def top_of(x0, x1):
                    col = mk_.crop((max(0, x0 // 4), 0, min(HW // 4, x1 // 4), SH // 4)).point(lambda v: 255 if v > 100 else 0)
                    bb = col.getbbox()
                    return bb[1] * 4 if bb else SH
                best = None
                for sd in ("right", "left"):
                    for sz in range(size, 79, -6):
                        x0 = HW - 30 - sz if sd == "right" else 30
                        if 24 + len(title) * sz * 1.02 < top_of(x0, x0 + sz) - 14:
                            if not best or sz > best[1] + 20:
                                best = (sd, sz)
                            break
                if best:
                    side, size = best
            pos = "right:30px" if side == "right" else f"left:{HW + 30}px"
            out += f'<div style="{pos};top:24px;writing-mode:vertical-rl;{c.f_disp(size, "#fff", "letter-spacing:-.02em")}">{esc(title)}</div>'
        out += f'<div class="c" style="left:248px;top:366px;width:62px;height:62px;background:{P["accent"]}"></div>'
        c.nb("封面：右页满版照片 + 一个透出来的圆，封底整面深色", "heavy")
    if c.marks:
        out += f'<div class="m" style="left:26px;bottom:24px;color:{P["light"] if ax["near"] > -1 or ax["heavy"] > 0 else P["ink"]};width:300px">{len(c.all_order)} PHOTOS<br>{c.lab(n)}</div>'
        c.say(f"{len(c.all_order)} PHOTOS", "computed", "photo_count")
    return out


def score(t, ax):
    a = t["aff"]
    return sum(a.get(k, 0) * ax[k] for k in AXIS_KEYS) / (1 + sum(abs(v) for v in a.values()) ** .5)
