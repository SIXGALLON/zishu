"""自书 · 跨平台适配层
把引擎里所有「跟电脑有关」的东西集中在这里，让 Claude Code / Codex / Gemini CLI / WorkBuddy 等任何终端、
macOS / Windows / Linux 任何系统都跑出同一本书：

  1. 字体：开源字体（SIL OFL），装在共享目录；出书时按用到的字做子集，放进输出目录 → 输出目录自包含、换电脑打开也一样。
  2. 浏览器：截图和 PDF 用本机 Chrome / Edge / Chromium（命令行无头模式）；都没有时用 Playwright。
  3. 抠图：macOS Vision → rembg（跨平台，可选）→ 不抠（需要抠图的手法自动避开）。
  4. 画面里有几个人：抠图后端能数就用它的；Agent 也可以看图后写进 feeling.json 的 "people"（优先）。

只依赖 Python 3.9+ 与 Pillow；fontTools / playwright / rembg 都是可选增强。
环境变量：ZISHU_FONTS（字体目录）、ZISHU_BROWSER（浏览器可执行文件）、ZISHU_CUTOUT（auto|vision|rembg|none）。"""
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SYSTEM = platform.system()          # Darwin / Windows / Linux


def log(*a):
    print(*a, flush=True)


def utf8_console():
    """Windows 终端默认 GBK，打印中文路径/符号会报错。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def uri(p):
    """file:// 链接（Windows 盘符、空格、中文都正确转义）。"""
    return Path(p).resolve().as_uri()


# ============================================================ 1. 字体
GF = "https://github.com/google/fonts/raw/main/ofl/"
JSD = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/"
# family → (本地文件名, [下载地址…], 许可证文件地址, 中文说明)
FONTS = {
    "ZSerif":      ("NotoSerifSC-VF.ttf", [GF + "notoserifsc/NotoSerifSC%5Bwght%5D.ttf"], GF + "notoserifsc/OFL.txt", "思源宋体（Noto Serif SC），可变字重 200–900"),
    "ZSans":       ("NotoSansSC-VF.ttf", [JSD + "notosanssc/NotoSansSC%5Bwght%5D.ttf", GF + "notosanssc/NotoSansSC%5Bwght%5D.ttf"], GF + "notosanssc/OFL.txt", "思源黑体（Noto Sans SC），可变字重"),
    "ZKai":        ("LXGWWenKai-Regular.ttf", ["https://github.com/lxgw/LxgwWenKai/releases/latest/download/LXGWWenKai-Regular.ttf"],
                    "https://github.com/lxgw/LxgwWenKai/raw/main/OFL.txt", "霞鹜文楷：淡、慢、像手写的楷"),
    "ZHand":       ("Xiaolai-Regular.ttf", ["https://github.com/lxgw/kose-font/releases/latest/download/Xiaolai-Regular.ttf"],
                    "https://github.com/lxgw/kose-font/raw/master/OFL.txt", "小赖字体：随手写的字，乱糟糟、热闹"),
    "ZGrotesk":    ("Inter-VF.ttf", [JSD + "inter/Inter%5Bopsz,wght%5D.ttf", GF + "inter/Inter%5Bopsz,wght%5D.ttf"], GF + "inter/OFL.txt", "Inter：西文无衬线（替代 Helvetica）"),
    "ZCond":       ("Oswald-VF.ttf", [JSD + "oswald/Oswald%5Bwght%5D.ttf", GF + "oswald/Oswald%5Bwght%5D.ttf"], GF + "oswald/OFL.txt", "Oswald：窄体数字（替代 DIN Condensed）"),
    "ZDidone":     ("BodoniModa-VF.ttf", [JSD + "bodonimoda/BodoniModa%5Bopsz,wght%5D.ttf", GF + "bodonimoda/BodoniModa%5Bopsz,wght%5D.ttf"], GF + "bodonimoda/OFL.txt", "Bodoni Moda：西文细衬线（替代 Didot）"),
    "ZDidone|italic": ("BodoniModa-Italic-VF.ttf", [JSD + "bodonimoda/BodoniModa-Italic%5Bopsz,wght%5D.ttf", GF + "bodonimoda/BodoniModa-Italic%5Bopsz,wght%5D.ttf"], None, "Bodoni Moda 斜体"),
}
VARIABLE = {"ZSerif", "ZSans", "ZGrotesk", "ZCond", "ZDidone", "ZDidone|italic"}

# CSS 字体栈：先用随 skill 分发的开源字体，缺了再退到各系统自带字体
STACK = {
    "serif": "'ZSerif','Songti SC','Noto Serif CJK SC','Source Han Serif SC','SimSun',serif",
    "sans": "'ZSans','PingFang SC','Hiragino Sans GB','Noto Sans CJK SC','Microsoft YaHei',sans-serif",
    "kai": "'ZKai','Kaiti SC','STKaiti','KaiTi',",
    "hand": "'ZHand','Hannotate SC','HanziPen SC',",
    "grotesk": "'ZGrotesk','Helvetica Neue',Arial,",
    "cond": "'ZCond','DIN Condensed','Arial Narrow',",
    "didone": "'ZDidone','Didot','Bodoni 72',",
}


def font_dirs():
    ds = []
    if os.environ.get("ZISHU_FONTS"):
        ds.append(Path(os.environ["ZISHU_FONTS"]))
    ds.append(SKILL / "assets" / "fonts")
    ds.append(shared_font_dir())
    return ds


def shared_font_dir():
    if SYSTEM == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "zishu" / "fonts"


def _apple_asset(fname):
    """macOS 上系统按需下载的字体（楷体、手札体）——只在开源字体缺失时兜底。"""
    if SYSTEM != "Darwin":
        return None
    import glob
    hits = glob.glob(f"/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/{fname}")
    return hits[0] if hits else None


APPLE_FALLBACK = {"ZKai": "Kaiti.ttc", "ZHand": "Hannotate.ttc"}


def font_file(fam):
    fname = FONTS[fam][0]
    for d in font_dirs():
        p = d / fname
        if p.exists() and p.stat().st_size > 10000:
            return p
    if fam in APPLE_FALLBACK:
        p = _apple_asset(APPLE_FALLBACK[fam])
        if p:
            return Path(p)
    return None


def fonts_status():
    return {fam: font_file(fam) for fam in FONTS}


def fetch_fonts(dest=None, only=None, quiet=False):
    """下载开源字体到共享目录（约 95 MB，只需一次）。返回 {family: 成功与否}。"""
    dest = Path(dest or shared_font_dir())
    dest.mkdir(parents=True, exist_ok=True)
    res = {}
    for fam, (fname, urls, lic, cn) in FONTS.items():
        if only and fam not in only:
            continue
        p = dest / fname
        if p.exists() and p.stat().st_size > 10000:
            res[fam] = True
            continue
        ok = False
        for u in urls:
            try:
                if not quiet:
                    log(f"  ↓ {cn} …")
                req = urllib.request.Request(u, headers={"User-Agent": "zishu-skill"})
                with urllib.request.urlopen(req, timeout=180) as r, open(str(p) + ".part", "wb") as f:
                    shutil.copyfileobj(r, f)
                os.replace(str(p) + ".part", p)
                ok = p.stat().st_size > 10000
                if ok:
                    break
            except Exception as e:
                if not quiet:
                    log(f"    × {u.split('/')[2]} 失败：{e}")
        res[fam] = ok
        if ok and lic:
            try:
                req = urllib.request.Request(lic, headers={"User-Agent": "zishu-skill"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    (dest / (fname.rsplit(".", 1)[0] + ".LICENSE.txt")).write_bytes(r.read())
            except Exception:
                pass
    return res


def _subset(src, dst, chars):
    from fontTools import subset
    opts = subset.Options()
    opts.flavor = "woff2" if _has("brotli") else None
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.drop_tables += ["DSIG"]
    font = subset.load_font(str(src), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=chars)
    sub.subset(font)
    subset.save_font(font, str(dst), opts)


def _has(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def font_faces(chars=None, out=None):
    """返回 (@font-face CSS, 已就绪的 family 集合)。
    给了 chars + out：把用到的字做成子集放进 out/_a/fonts/，CSS 用相对路径 → 输出目录可以整个拷走。
    否则（或没有 fontTools）：CSS 直接指向字体文件的绝对路径（只在本机有效）。"""
    css, have = "", set()
    can_subset = chars is not None and out is not None and _has("fontTools")
    if can_subset:
        fd = Path(out) / "_a" / "fonts"
        fd.mkdir(parents=True, exist_ok=True)
        chars = "".join(sorted(set(chars) | set(" 0123456789·—–-.,:;!?()[]%/+&'\"#*@abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")))
    for fam, spec in FONTS.items():
        p = font_file(fam)
        if not p:
            continue
        name, style = (fam.split("|") + ["normal"])[:2]
        url = None
        if can_subset and p.suffix.lower() != ".ttc":
            ext = ".woff2" if _has("brotli") else ".ttf"
            dst = fd / (fam.replace("|", "-") + ext)
            try:
                _subset(p, dst, chars)
                url = "_a/fonts/" + dst.name
            except Exception as e:
                log(f"  · 字体子集失败（{fam}），改用原文件：{e}")
            lic = p.with_name(p.name.rsplit(".", 1)[0] + ".LICENSE.txt")
            if url and lic.exists() and not (fd / lic.name).exists():
                shutil.copyfile(lic, fd / lic.name)       # OFL 要求随字体附许可证
        if url is None:
            url = uri(p)
        weight = "font-weight:100 900;" if fam in VARIABLE else ""
        css += f'@font-face{{font-family:"{name}";src:url("{url}");font-style:{style};{weight}font-display:block}}\n'
        have.add(name)
    return css, have


def pil_font(size, bold=False):
    """Pillow 画中文用（总览图标题、人形填字）。优先开源黑体，再找系统中文字体。"""
    from PIL import ImageFont
    p = font_file("ZSans")
    if p:
        f = ImageFont.truetype(str(p), size)
        try:
            f.set_variation_by_axes([700 if bold else 400])
        except Exception:
            pass
        return f
    cands = {
        "Darwin": ["/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"],
        "Windows": [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"],
        "Linux": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc"],
    }.get(SYSTEM, [])
    for c in cands:
        if os.path.exists(c):
            idx = 1 if (bold and c.endswith(".ttc") and "Hiragino" in c) else 0
            try:
                return ImageFont.truetype(c, size, index=idx)
            except Exception:
                continue
    log("  ! 找不到任何中文字体，总览图上的中文会显示成方块：请先运行 install.py 下载字体")
    return ImageFont.load_default()


# ============================================================ 2. 浏览器（截图 / PDF）
def _browser_candidates():
    if os.environ.get("ZISHU_BROWSER"):
        yield os.environ["ZISHU_BROWSER"]
    if SYSTEM == "Darwin":
        for app in ["Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser", "Google Chrome Canary"]:
            exe = {"Google Chrome": "Google Chrome", "Chromium": "Chromium", "Microsoft Edge": "Microsoft Edge",
                   "Brave Browser": "Brave Browser", "Google Chrome Canary": "Google Chrome Canary"}[app]
            for root in ["/Applications", str(Path.home() / "Applications")]:
                yield f"{root}/{app}.app/Contents/MacOS/{exe}"
    elif SYSTEM == "Windows":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for r in filter(None, roots):
            yield os.path.join(r, "Google", "Chrome", "Application", "chrome.exe")
            yield os.path.join(r, "Microsoft", "Edge", "Application", "msedge.exe")
            yield os.path.join(r, "Chromium", "Application", "chrome.exe")
            yield os.path.join(r, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")
    for n in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable",
              "brave-browser", "chrome", "msedge"]:
        w = shutil.which(n)
        if w:
            yield w


def find_browser():
    for p in _browser_candidates():
        if p and os.path.exists(p):
            return p
    return None


class Browser:
    """截图 / 打印 PDF。mode = cli（本机浏览器命令行）| playwright | None。"""

    def __init__(self):
        self.exe = None if os.environ.get("ZISHU_FORCE_PLAYWRIGHT") else find_browser()
        self.mode = "cli" if self.exe else ("playwright" if _has("playwright") else None)
        self._pw = self._br = None

    def describe(self):
        if self.mode == "cli":
            return f"本机浏览器 {Path(self.exe).name}"
        if self.mode == "playwright":
            return "Playwright"
        return "无（截图、PDF、读回、总览会跳过）"

    # ---- 命令行无头模式
    def _cli(self, args, expect="written", tries=3):
        for _ in range(tries):
            d = tempfile.mkdtemp(prefix="zishu-chrome-")
            try:
                r = subprocess.run([self.exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                                    "--no-first-run", "--no-default-browser-check", f"--user-data-dir={d}",
                                    "--virtual-time-budget=6000"] + args, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=180)
                if expect in (r.stdout + r.stderr):
                    return True
            except Exception:
                pass
            finally:
                shutil.rmtree(d, ignore_errors=True)
        return False

    # ---- Playwright（没有本机浏览器时）
    def _page(self, w=1120, h=794):
        if self._br is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            for ch in ("chrome", "msedge", None):
                try:
                    self._br = self._pw.chromium.launch(channel=ch) if ch else self._pw.chromium.launch()
                    break
                except Exception:
                    continue
            if self._br is None:
                raise RuntimeError("Playwright 没有可用的浏览器：运行 `python -m playwright install chromium`")
        pg = self._br.new_page(viewport={"width": w, "height": h})
        return pg

    def screenshot(self, html, png, w=1120, h=794):
        html, png = Path(html), Path(png)
        if self.mode == "cli":
            return self._cli([f"--window-size={w},{h}", f"--screenshot={png}", uri(html)])
        if self.mode == "playwright":
            try:
                pg = self._page(w, h)
                pg.goto(uri(html))
                pg.evaluate("document.fonts.ready")
                pg.wait_for_timeout(300)
                pg.screenshot(path=str(png))
                pg.close()
                return png.exists()
            except Exception as e:
                log(f"  ! 截图失败：{e}")
        return False

    def pdf(self, html, pdf):
        html, pdf = Path(html), Path(pdf)
        if self.mode == "cli":
            return self._cli(["--no-pdf-header-footer", f"--print-to-pdf={pdf}", uri(html)])
        if self.mode == "playwright":
            try:
                pg = self._page()
                pg.goto(uri(html))
                pg.evaluate("document.fonts.ready")
                pg.pdf(path=str(pdf), prefer_css_page_size=True, print_background=True)
                pg.close()
                return pdf.exists()
            except Exception as e:
                log(f"  ! PDF 失败：{e}")
        return False

    def close(self):
        try:
            if self._br:
                self._br.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._br = self._pw = None


_BROWSER = None


def browser():
    global _BROWSER
    if _BROWSER is None:
        _BROWSER = Browser()
    return _BROWSER


# ============================================================ 3. 抠图 + 数人
def cutout_backend():
    want = (os.environ.get("ZISHU_CUTOUT") or "auto").lower()
    have_vision = SYSTEM == "Darwin" and shutil.which("swift") is not None
    have_rembg = _has("rembg")
    if want == "none":
        return "none"
    if want == "vision":
        return "vision" if have_vision else "none"
    if want == "rembg":
        return "rembg" if have_rembg else "none"
    return "vision" if have_vision else ("rembg" if have_rembg else "none")


def run_cutout(img_dir, cut_dir, files):
    """为每张照片写 <stem>_mask.png（主体蒙版）与 <stem>_info.json（{"humans": n 或 null, "backend": …}）。已有就跳过。"""
    cut_dir = Path(cut_dir)
    cut_dir.mkdir(parents=True, exist_ok=True)
    be = cutout_backend()
    todo = [n for n in files if not (cut_dir / f"{n}_info.json").exists()]
    if not todo:
        return be, []
    miss = []
    if be == "vision":
        r = subprocess.run(["swift", str(HERE / "cutout" / "vision_lift.swift"), str(img_dir), str(cut_dir)],
                           capture_output=True, text=True, timeout=900)
        miss = [l.split()[0] for l in r.stdout.splitlines() if "no subject" in l]
        for n in todo:   # 标记后端
            ip = cut_dir / f"{n}_info.json"
            if ip.exists():
                try:
                    d = json.loads(ip.read_text())
                    d["backend"] = "vision"
                    ip.write_text(json.dumps(d))
                except Exception:
                    pass
    elif be == "rembg":
        from PIL import Image, ImageOps
        from rembg import new_session, remove
        sess = new_session("u2net")
        for n in todo:
            im = ImageOps.exif_transpose(Image.open(files[n])).convert("RGB")
            m = remove(im, session=sess, only_mask=True)
            m = m.convert("L")
            if m.getbbox() is None or max(m.getextrema()) < 128:
                miss.append(n)
            else:
                m.save(cut_dir / f"{n}_mask.png")
            (cut_dir / f"{n}_info.json").write_text(json.dumps({"humans": None, "backend": "rembg"}))
    else:
        for n in todo:
            (cut_dir / f"{n}_info.json").write_text(json.dumps({"humans": None, "backend": "none"}))
    return be, miss


# ============================================================ 自检
def doctor():
    """返回 [(项目, 状态✓/△/✗, 说明)]。"""
    rows = []
    v = sys.version_info
    rows.append(("Python", "✓" if v >= (3, 9) else "✗", f"{v.major}.{v.minor}.{v.micro}（需要 3.9+）"))
    try:
        import PIL
        rows.append(("Pillow", "✓", PIL.__version__))
    except Exception:
        rows.append(("Pillow", "✗", "必需：pip install Pillow"))
    b = browser()
    rows.append(("截图 / PDF", "✓" if b.mode else "✗", b.describe() if b.mode else "装 Chrome / Edge，或 pip install playwright && python -m playwright install chromium"))
    be = cutout_backend()
    rows.append(("抠图", "✓" if be != "none" else "△", {"vision": "macOS Vision（会顺便数人）", "rembg": "rembg（不会数人：请让 Agent 在 feeling.json 写 people）",
                                                       "none": "不抠图：剪影、人形窗、巨型抠图等手法会自动避开；想要可 pip install rembg"}[be]))
    st = fonts_status()
    missing = [FONTS[k][3].split("：")[0].split("（")[0] for k, p in st.items() if not p]
    rows.append(("开源字体", "✓" if not missing else "△", "全部就绪" if not missing else "缺：" + "、".join(missing) + "（运行 install.py 下载；缺了会退到系统字体，换电脑效果会不一样）"))
    rows.append(("字体子集化", "✓" if _has("fontTools") else "△", "输出目录自包含，可整个拷走" if _has("fontTools") else "pip install fonttools brotli（否则输出目录换电脑打开字体会变）"))
    return rows
