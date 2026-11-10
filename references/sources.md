# 来源与证据等级

## 证据分级

| 级别 | 含义 |
|---|---|
| 【一手·图】 | 用户提供的 20 张参考图，或调研时下载到本地、用图像查看工具逐张打开看过的图 |
| 【一手·文】 | 实际打开原文的页面 / 仓库文件 / 官方文档 |
| 【二手】 | 检索摘要、多源交叉一致但未逐字抓原文 |
| 【推断】 | 本报告基于上述事实的规则化、参数化、工程推导 |

## 1. 主证据：用户提供的 20 张 zine 参考（2026-11-04 微信）

- 来源：微信聊天记录 zip `聊天记录_20261104_194452.zip`，20 张 jpg，均由用户本人挑选。
- 处理：先拼成 4×5 总览图逐格看，再放大细看 **1 / 2 / 4 / 6 / 9 / 14 / 16 / 17 / 19 / 20** 共 10 张。
- 观察结论见 `../legacy/references/zine-dna.md`。图上的黑底、相册页码 `2/9`、`1/10`、右下角小红书号水印均为平台 UI，未计入设计元素。
- **诚实标注**：这些图多为「多个内页样例的截图合集」，因此「出现频率」按看到的样例格数估，不是精确统计；
  韩文/中文/英文混排未逐字 OCR，统一按「tiny 标签」抽象；具体 hex 是从图上取的近似值，非官方色卡。
- 图中可见的小红书号（Wasabilazydog、jkronz_ 等）仅作为出处标识，未据此抓取原帖内容。

## 2. 小红书抓取限制（必须如实告知）

小红书搜索页 / 笔记页需要登录态，内容由 JS 动态渲染、接口带签名与反爬校验，公开搜索引擎不索引笔记正文。
调研时直接打开搜索页返回「你访问的页面不见了」，**无法逐条给出小红书原帖 URL**。
因此本 skill 关于中文 zine 模板的判断，主要依据用户这 20 张图 + 可打开的站外转载与中文教程，不冒充原帖。
另：中文搜「zine 排版」会被同名 App「Zine」(zine.la，手机长文排版工具) 大量污染，已在 SKILL.md 做实体消歧。

## 3. 反例：站外 6 张「Zine Template」预览图（已逐张看过）

来源 Envato Tuts+《30 Best Zine Templates》文章内 `cms-assets.tutsplus.com` 模板预览图
（ZineTemplates01/02/09/17/19/34.jpg，均 `curl` 下载到本地并打开）。
判定：实为**商业杂志 / 作品集模板**——条码、期号、目录、双栏长文、统一圆角卡片、广告式大标题。
已列入 `../legacy/references/zine-dna.md` §4 反例清单，明确禁止 skill 采用其语言。

## 4. 可打开的中文与印刷资料

| 内容 | URL | 级别 |
|---|---|---|
| RISO 工艺（A3 上限、一次一色、半调网点、未涂布纸、套印错位、分色） | `http://mp.weixin.qq.com/s?__biz=MzA4ODczODIxNg==&mid=2652083614&idx=1&sn=fcebb3aa7d261275d1b0a23f546920a8` | 一手·文 |
| 小册子排版（骑马钉 4 倍数、封面只放名称+一句+一图、一页一件事、不留纯白页） | `https://www.yunzhan365.com/blog/13063.html` | 二手 |
| 出版作为艺术实践（zine 定义：独立自主出版、少量发行、自由印刷品） | `https://map.tfam.museum/content/JO0042_03` | 二手 |
| 香蕉鱼书店 Zine in Processing / 豆本微出版 | `https://bananafish-books.com/projects` | 二手 |

## 5. 模板与页序资料

| 内容 | URL | 级别 |
|---|---|---|
| Canva one-page mini-zine（8 格、US Letter 横向、上排倒置） | `https://www.canva.com/design/DAGgukM9p6Q/_tluaISBPsz7u5dqscmb1Q/edit` | 一手·文 |
| Figma Community 8-page zine template（设计页 ↔ 拼版页联动） | `https://www.figma.com/community/file/1505262187439288444/8-page-zine-template` | 二手 |
| InDesignSkills 免费 12 页 A5 zine 模板 | `https://indesignskills.com/templates/zine/` | 一手·文 |
| Envato Tuts+ 30 Best Zine Templates（14–52 页模板合集） | `https://design.tutsplus.com/articles/21-best-zine-templates-creative-design-layouts-to-download--cms-36689` | 一手·文 |
| Booklet Imposer 8 页示例与 3mm gutter | `https://bookletimposer.com/examples/8-page-booklet` | 一手·文 |
| StaticFast Free Zine Maker（one-sheet `5 4 3 2 / 6 7 8 1`） | `https://staticfast.com/free-zine-maker` | 二手 |
| Fliplink 折页说明 | `https://fliplink.me/blog/how-to-fold-a-zine` | 二手 |
| 出血 3mm / 安全边距 10mm / 300DPI | `https://imprintdigital.com/blog/how-to-make-a-zine`、`https://www.krumzi.com/blog/how-to-make-a-zine` | 二手 |
| Adobe 官方 zine 页教程（Cooper Bold、Acrobat Booklet、长臂订书机 2 钉） | `https://www.adobe.com/gr_en/learn/illustrator/web/design-zine-pages` | 二手 |

## 6. 设计史与流派（文字调研）

1930s 科幻 fanzine《The Comet》→ 1970s punk《Sniffin' Glue》复印机美学 → 1980–90s riot grrrl
→ 当代 photozine / 生活记录型 zine（日本豆本、艺术书展）。Riso 与 xerox 的视觉特征来自工艺约束
（一次一个色筒 / 只有黑色墨粉 / 过细线条印不实），不是装饰性滤镜。
案例与更多 URL 见调研笔记；本 skill 采用的只是其中可参数化的部分。

## 7. 明确待补证（不要当结论用）

1. 1950s 波点时装史、CMYK 具体网屏角度、Riso 官方油墨 hex —— 未拿一手色卡。
2. 中文平台（B站 / 知乎 / 豆瓣 / 淘宝）的 zine 模板细节，未取得稳定可打开的 URL，仅作后续采集方向。
3. 目录站上的 stars / 安装量 / 安全评分，来自第三方，未逐一核。
4. `legacy/references/zine-dna.md` 里的 hex 与百分比是从截图取的近似值，属于工程起点。
5. 参考图中「一张 A4 折 8 页」的折法未在本 skill 实现，只在 `imposition.md` 记录备用。
6. 用户提供的 20 张图无法直接访问原帖，因此未做「作者 / 出版方 / 年代」级别的考据。
