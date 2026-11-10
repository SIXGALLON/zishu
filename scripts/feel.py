"""自书 · 感受 → 设计
把用户说的「那天的感觉」落成 6 根轴，再从 6 根轴推出：颜色、字、尺度、密度、节奏、照片处理、手法偏好。
每一个决定都带一条「旁注」：这样做，是因为你说了哪句话。"""
import colorsys
import random

import platform_kit as kit

# ---------------- 6 根轴 ----------------
# 每根轴 -2..+2。左边是负，右边是正。label 用感受词，不用设计词。
AXES = [
    ("near",  "隔着一点距离", "贴得很近"),
    ("warm",  "凉的",         "暖的"),
    ("fast",  "安静",         "热闹"),
    ("heavy", "淡",           "浓"),
    ("sharp", "恍恍惚惚",     "清清楚楚"),
    ("loose", "规规矩矩",     "乱糟糟"),
]
AXIS_KEYS = [a[0] for a in AXES]
AXIS_LABEL = {k: (l, r) for k, l, r in AXES}

# 每根轴在设计上意味着什么（写进旁注、写进报告）
AXIS_MEANS = {
    "near":  ("照片缩小、四周留大片空白、不抠图", "照片放大到出血、抠出来贴近你、字压在物上"),
    "warm":  ("纸偏灰白、颜色取照片里的蓝绿紫", "纸偏米黄、颜色取照片里的橙红黄"),
    "fast":  ("一页一张、多留呼吸页、翻得慢", "一页挤好几张、贴纸叠着放、翻得快"),
    "heavy": ("细字、浅色、低对比", "粗黑大字、深色大面积、高对比"),
    "sharp": ("轻微失焦、双色、颗粒、只留线条", "闪光灯感、饱和、边缘利落"),
    "loose": ("对齐网格、不旋转、等距", "倾斜、叠压、散落的圆点"),
}

# 常见感受词 → 轴（Agent 的起点，必须再跟用户核对，不是结论）
LEXICON = {
    "热闹": {"fast": 2, "loose": 1, "heavy": 1}, "吵": {"fast": 2, "loose": 1}, "开心": {"warm": 1, "fast": 1, "sharp": 1},
    "乱七八糟": {"loose": 2, "fast": 1}, "晒": {"warm": 2, "sharp": 1}, "阳光": {"warm": 2, "sharp": 1},
    "饱": {"warm": 1, "heavy": 1, "near": 1}, "松弛": {"fast": -1, "loose": 1, "heavy": -1},
    "舍不得": {"fast": -2, "near": -1, "sharp": -1}, "想念": {"near": -1, "sharp": -2, "fast": -1},
    "遗憾": {"near": -1, "heavy": 1, "warm": -1}, "孤独": {"near": -2, "fast": -2, "warm": -1},
    "安静": {"fast": -2, "heavy": -1}, "平静": {"fast": -1, "loose": -1, "heavy": -1},
    "恍惚": {"sharp": -2, "fast": -1}, "困": {"sharp": -1, "fast": -2, "heavy": -1},
    "自由": {"loose": 2, "near": 0, "heavy": -1}, "累": {"heavy": 1, "fast": -1, "sharp": -1},
    "亲密": {"near": 2, "warm": 1}, "天黑": {"warm": -1, "heavy": 1, "fast": -1}, "冷": {"warm": -2},
    "清爽": {"warm": -1, "sharp": 1, "heavy": -1}, "浓烈": {"heavy": 2, "sharp": 1},
    "温柔": {"heavy": -1, "warm": 1, "loose": 0, "sharp": -1}, "克制": {"loose": -2, "heavy": -1},
}

RISO = {  # 常见 Riso 油墨色的近似值（参考 stencil.wiki 色表，打印前以实物色卡为准）
    "Yellow": "#FFE800", "Sunflower": "#FFB511", "Orange": "#FF6C2F", "Bright Red": "#F15060",
    "Fluorescent Pink": "#FF48B0", "Coral": "#FF8E91", "Bisque": "#F2CDCF", "Light Lime": "#E3ED55",
    "Green": "#00A95C", "Kelly Green": "#67B346", "Teal": "#00838A", "Sea Foam": "#62C2B1", "Mint": "#82D8D5",
    "Aqua": "#5EC8E5", "Cornflower": "#62A8E5", "Blue": "#0078BF", "Medium Blue": "#3255A4",
    "Federal Blue": "#3D5588", "Indigo": "#484D7A", "Purple": "#765BA7", "Violet": "#9D7AD2",
    "Burgundy": "#914E72", "Brown": "#925F52", "Flat Gold": "#BB8B41",
}


def clamp(v, a=-2, b=2):
    return max(a, min(b, v))


def hex2rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb2hex(c):
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, round(x)))) for x in c[:3])


def mix(a, b, t):
    a, b = hex2rgb(a), hex2rgb(b)
    return rgb2hex([a[i] * (1 - t) + b[i] * t for i in range(3)])


def hsv(h):
    r, g, b = [x / 255 for x in hex2rgb(h)]
    return colorsys.rgb_to_hsv(r, g, b)


def from_hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1, max(0, min(1, s)), max(0, min(1, v)))
    return rgb2hex((r * 255, g * 255, b * 255))


def hue_dist(a, b):
    d = abs(a - b) % 1
    return min(d, 1 - d)


def is_warm(h):
    return h < .15 or h > .9


def is_cool(h):
    return .42 < h < .8


def nearest_riso(hx, bright=True):
    h, s, v = hsv(hx)
    pool = [(k, c) for k, c in RISO.items() if not bright or (hsv(c)[1] > .55 and hsv(c)[2] > .74)]
    return min(pool, key=lambda kv: hue_dist(hsv(kv[1])[0], h) * 3 + abs(hsv(kv[1])[1] - max(s, .7)) * .3)


# ---------------- 轴 ----------------
def resolve_axes(feeling):
    """axes 优先用 Agent 跟用户核对过的值；没有就从 said 里查词典起步。"""
    ax = {k: 0 for k in AXIS_KEYS}
    src = {}
    if feeling.get("axes"):
        for k, v in feeling["axes"].items():
            if k in ax:
                ax[k] = clamp(round(float(v)))
                src[k] = "confirmed"
        return ax, src
    said = feeling.get("said", "")
    for w, vec in LEXICON.items():
        if w in said:
            for k, v in vec.items():
                ax[k] = clamp(ax[k] + v)
                src[k] = f"词典：{w}"
    return ax, src


# ---------------- 颜色 ----------------
def derive_palette(ax, data, key=None):
    pool = []
    for n, d in data.items():
        wgt = 3 if n == key else 1
        for cnt, hx in d["colors"]:
            h, s, v = hsv(hx)
            pool.append((cnt * wgt, hx, h, s, v, n))
    want = "warm" if ax["warm"] > 0 else ("cool" if ax["warm"] < 0 else "any")

    def tmatch(h):
        if want == "warm":
            return 1.0 if is_warm(h) else .15
        if want == "cool":
            return 1.0 if is_cool(h) else .15
        return .7

    cands = [p for p in pool if p[3] > .22 and p[4] > .32]
    boosted = False
    if want in ("cool", "warm"):
        test = is_cool if want == "cool" else is_warm
        if not any(test(p[2]) for p in cands):
            # 照片里这个温度的颜色都很灰：取其中最鲜的一块，再提饱和（色相仍来自照片）
            grey = [p for p in pool if test(p[2]) and p[3] > .04 and p[4] > .25]
            if grey:
                g = max(grey, key=lambda p: p[3] * (p[0] ** .25))
                cands = [(g[0], g[1], g[2], .42, max(g[4], .7), g[5])] + cands
                boosted = True
    if cands:
        acc = max(cands, key=lambda p: p[3] * (p[4] ** .5) * tmatch(p[2]) * (p[0] ** .25))
        ah, as_, av = acc[2], acc[3], acc[4]
        acc_from = acc[5]
    else:
        ah, as_, av, acc_from = (.06, .7, .95, None) if want != "cool" else (.6, .7, .8, None)
    # 浓淡、清晰调整饱和与明度
    s = as_ * (1 + .22 * ax["heavy"] + .15 * ax["sharp"])
    v = av * (1 + .06 * ax["heavy"]) if ax["heavy"] >= 0 else min(1, av * 1.08)
    if ax["heavy"] < 0:
        s *= .62 + .1 * (2 + ax["heavy"])
    accent = from_hsv(ah, max(s, .28), max(v, .55))

    # 深色：池子里最暗、色相接近目标温度的颜色，压深
    darks = [p for p in pool if p[4] < .55 and p[3] > .12]
    if darks:
        dk = max(darks, key=lambda p: (tmatch(p[2]) + .3) * (1 - p[4]) * (p[0] ** .2))
        dh, ds = dk[2], dk[3]
    else:
        dh, ds = (ah + .5) % 1, .4
    if want == "warm" and not is_warm(dh) and ax["warm"] >= 2:
        dh = .02
    deep = from_hsv(dh, max(ds, .38), .3 - .04 * ax["heavy"])
    night = from_hsv(dh, max(ds, .35), .14)

    # 第二个颜色：跟主色色相拉开，用来撞色 / 双色
    others = [p for p in cands if hue_dist(p[2], ah) > .22]
    if others:
        o = max(others, key=lambda p: p[3] * p[4] * (p[0] ** .25))
        second = from_hsv(o[2], max(o[3] * (1 + .2 * ax["heavy"]), .35), max(o[4], .6))
    else:
        second = from_hsv(ah + .5, max(s * .9, .35), max(v, .6))

    paper = {"warm": "#F5EFE3", "cool": "#EDF0F1", "any": "#F3F1EC"}[want]
    if ax["warm"] >= 2:
        paper = "#F7EEDD"
    light = mix(accent, paper, .72)
    ink = mix("#1A1A1C", deep, .18)
    dark_mode = ax["heavy"] >= 1 and ax["warm"] <= -1
    if dark_mode:   # 「天黑了」又「浓」：纸本身变深，字变浅
        paper = mix(night, deep, .35)
        ink = "#EDE6DA"
        light = mix(accent, paper, .45)
    if boosted and acc_from:
        acc_from = f"{acc_from}（照片里这类颜色很灰，提了饱和）"
    P = dict(paper=paper, ink=ink, accent=accent, second=second, deep=deep, night=night, light=light, dark=dark_mode,
             accent_from=acc_from)
    if ax["sharp"] >= 1 or ax["fast"] >= 2:
        P["flat1"] = nearest_riso(accent)[1]
        P["flat2"] = nearest_riso(second)[1]
        P["flat_names"] = (nearest_riso(accent)[0], nearest_riso(second)[0])
    else:
        P["flat1"], P["flat2"], P["flat_names"] = accent, second, None
    # 双色：深 + 浅（安静）或 主色 + 第二色（浓）
    if ax["sharp"] >= 1:
        P["duo"] = (mix(P["flat2"], "#000000", .35), mix(P["flat1"], "#FFFFFF", .25))
    elif ax["heavy"] >= 1:
        P["duo"] = (deep, mix(second, "#FFFFFF", .35))
    else:
        P["duo"] = (mix(deep, accent, .25), mix(accent, "#FFFFFF", .55))
    return P


# ---------------- 字 ----------------
# 字体全部是开源字体（SIL OFL），由 platform_kit 管理；缺了会退到各系统自带字体。
def font_faces(chars=None, out=None):
    return kit.font_faces(chars, out)


def derive_type(ax, have):
    K = kit.STACK
    serif, sans = K["serif"], K["sans"]

    def ok(f, fallback):
        key = {"ZHand": "hand", "ZKai": "kai"}[f]
        return K[key] + fallback if f in have else fallback

    if ax["loose"] >= 2 and ax["fast"] >= 1:
        disp, dw, why = ok("ZHand", serif), 700, "手写体：乱糟糟、热闹"
    elif ax["heavy"] >= 1:
        disp, dw, why = serif, 900, "宋体最粗一档：浓"
    elif ax["heavy"] <= -1:
        disp, dw, why = (ok("ZKai", serif), 400, "楷体：淡、像手写的慢") if ax["sharp"] <= 0 else (serif, 300, "宋体最细一档：淡")
    else:
        disp, dw, why = serif, 700, "宋体粗一档"
    if ax["loose"] >= 1:
        body = ok("ZHand", sans)
    elif ax["heavy"] <= -1:
        body = serif
    else:
        body = sans
    if ax["heavy"] >= 1 or ax["fast"] >= 1:
        latin, lw, lstyle = K["grotesk"] + "sans-serif", 900, "normal"
        num = K["cond"] + K["grotesk"] + "sans-serif"
    else:
        latin, lw, lstyle = K["didone"] + "serif", 400, "italic"
        num = K["didone"] + "serif"
    big = 300 + 30 * ax["heavy"] + 20 * ax["near"]
    return dict(disp=disp, dw=dw, body=body, latin=latin, lw=lw, lstyle=lstyle, num=num,
                big=max(big, 240), small=8, why=why)


# ---------------- 版面参数 ----------------
def derive_layout(ax):
    return dict(
        rot=max(0, ax["loose"]) * 3.2,                        # 最大旋转角
        margin=int(40 - 9 * ax["fast"] - 6 * ax["near"]),     # 边距
        per_spread={-2: 1.45, -1: 1.7, 0: 2.0, 1: 2.4, 2: 2.8}[ax["fast"]],
        hero={-2: .07, -1: .16, 0: .32, 1: .52, 2: .8}[ax["near"]],
        dots=max(0, ax["loose"] + ax["fast"]) >= 2,
        treat="flash" if ax["sharp"] >= 1 else ("soft" if ax["sharp"] <= -2 else ("duo_or_soft" if ax["sharp"] == -1 else "natural")),
    )


def plain(ax, k):
    v = ax[k]
    l, r = AXIS_LABEL[k]
    if v == 0:
        return f"{l}/{r}之间"
    word = r if v > 0 else l
    return ("很" if abs(v) == 2 else "有点") + word if not word.startswith("很") else word


def note_axis(feeling, ax, k, what):
    """旁注：「这样做」← 「因为你说…」。只引用 said 里真实存在的片段。"""
    said = feeling.get("said", "")
    because = (feeling.get("because") or {}).get(k)
    if because and because in said:
        return f"{what} ← 你说「{because}」（{plain(ax, k)}）"
    picks = feeling.get("picked") or {}
    if k in picks:
        return f"{what} ← 对照时你选了「{picks[k]}」"
    return f"{what} ← {plain(ax, k)}"
