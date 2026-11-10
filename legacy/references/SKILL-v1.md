---
name: zine-maker
description: 把一组照片和几段文字自动排成一本可打印的 zine（自出版小册子 / 生活记录册 / photozine / 豆本 / 独立出版）。产出阅读版网页与 PDF、以及按折纸顺序拼好版的打印 PDF。Use when 用户说「把这些照片做成 zine / 小册子 / 自出版 / 排版成册 / 摄影 zine / photozine / 豆本 / 8 页折页 / 骑马钉册子 / 生活记录册 / 独立杂志」，或要求把图片加文字自动完成版式、想做一本可打印的个人小册子。Not for 单张海报、PPT、普通相册导出、网页设计、长篇文章排版。
description_zh: 照片+文字自动排成 zine
description_en: Auto-layout photos and text into a printable zine
disable: false
agent_created: true
---

# zine-maker

> **当前规范（2026-11-04 22:21 用户决策）：视觉回退第一版，交互保留后续成果。**
>
> **生成依据（回到 v1）**：
> - `references/zine-dna.md` — 纸不纯白、极省颜色但留一个荧光/高饱和强调色、白边贴纸式小图、
>   圆形/椭圆裁切、tiny 时间地点标签、时间戳编号清单、手绘波浪线、彩色圆点、大量留白
> - `references/layout-catalog.md` — v1 的 11 种骨架（FIELD_MAIN / STICKERS / OVAL / COLORBLOCK /
>   GRID_SMALL / BLOCK_TRIO / QUOTE / ARTBOOK / SPREAD_FULL / COVER / SPREAD / BACK）
> - 五种风格 `field / colorblock / artbook / xerox / riso` 全部恢复可用
>
> **交互保留（不回退）**：
> - `references/interaction.md` — AI 负责印和装订，用户负责摆和说；陪聊、场景分组、可推翻草稿、
>   允许跳过反悔；决策落进 `story.json`
> - 摆台（卡片墙）→「复制我摆好的结果」→ 对话 → `story.json`
> - `make_zine.py --story <path>` — 读 story.json 排版：分组顺序、组内相邻、封面封底指定图、
>   每组原话、划掉的照片不参与
> - 封面/封底属性：`cover.image/layout/title/sub`、`back.image/layout/text`、`edition`、`colophon`
>
> **三条不随回退放宽的底线**（用户自己提过，属于质量而非风格）：
> 1. 她圈的三种**组合**仍禁：徽章阵列（4 张等大白边圆角图＋波浪线＋彼此无关）、填空色块
>    （≥40% 纯高饱和＋一个圆图＋无真实文字）、复制跨页（同一张图左右各半＋随机点）。
>    **单个元素不禁**：波点、圆形、白边、荧光色、手绘线、倾斜叠压全都回来。
>    约束只有「有出处／不整齐／会变化」（见 `anti-patterns.md` §零）。
> 2. 每张照片都要用到；同一张全本最多 2 次，第二次必须换裁切或角色，并在版式清单里标注，
>    用户可以说去掉。不许回到「01 用 7 次、5 张没出现」。
> 3. 文字只放用户原话（`user_verbatim` 或已确认的猜测），不润色、不代写感受、
>    不写虚构地名日期印量。没填就留白，不用占位句补。
>
> **已归档、非生成依据**（保留作过程记录）：`zine-dna-v2.md`、`composition-system.md`、
> `sample-A/B/C`、`三方向对照`、`组合示例`。`anti-patterns.md` 只取「三条禁用组合 + 硬约束」。

## 这个 skill 解决什么

用户给一堆照片和几段文字，不懂设计也能得到一本**可屏幕翻看、可打印折页**的 zine。
它负责：版式分配、图片裁切与风格化、tiny 时间地点标签、页数凑 4 的倍数、按骑马钉钉口序拼版。
它**不负责**：替用户写文案、重画或修改照片内容、联网上传素材、做交互产品（那是后续形态）。

## 何时用 / 何时不用

- 用：用户明确提到 zine / 自出版 / 小册子 / photozine / 豆本，或「给图给字帮我排成一本」。
- 不用：只要一张图、一张海报、一份 PPT、一个网页；也不要把它当图片编辑器。
- 「Zine」这个同名 App（zine.la，手机图文长文工具）与本 skill 无关，注意实体消歧。

## 输入约定

```
images/      照片文件夹，支持 jpg/png/webp/gif，按文件名排序
texts.json 或 texts.txt
  json 可含：title / subtitle / issue / short_issue / author / credit /
             edition / colophon / tag / vert_title / place2 / labels[] / texts[]
  txt 则一行一段
story.json   可选，「先摆后排」模式，见下
```

`story.json` 两种写法都认，不用转换：

| 来源 | 差异 |
|---|---|
| `摆台.html`「下载 story.json」 | `cover`/`back` 是字符串、`ungrouped`、`confirmed/pending` 是计数 |
| 对话草稿（`interaction.md` §五） | `cover`/`back` 是对象、`order` 是组 id 列表、`dropped` 是数组 |

字段：`groups[].images/name/note`、`order`、`dropped`/`ungrouped`、
`cover.image/title/sub/layout`、`back.image/text/layout`、`breath`、
`name_source`/`note_source`/`title_source`/`text_source`。
`cover.layout`：`photo_full`（默认）/ `paper_collage` / `plain`；
`back.layout`：`breath`（默认）/ `photo`。
来源标记只允许 `user_verbatim` / `user_confirmed_guess` / `unfilled`；
`user_confirmed_guess_pending` 的内容**不印**，只留白。
`palette` / `mood` 是保留字段，暂不驱动排版。
`labels[]` 是每页顶部轮流出现的 tiny 标签，是「记录感」的主要来源；不填则用中性的 `FRAME 0x`。
`texts[]` 里超过 80 字的长文会被**自动切成短句**，不会排成双栏文章。

**零编造规则（重要）**：用户没给的地点、日期、期号、作者、印量，一律不要替他填。
脚本默认值全是中性占位（`UNTITLED` / `PHOTOS` / `FRAME 0x` / 空作者 / 空印量），
`author`、`edition` 留空时封底那一行会直接不渲染。只有用户明确提供，才写进 `texts.json`。
若用户只给照片不给文字，用「从画面客观可见的名词」（如「海边」「柠檬茶」）当采集标签，
并在交付时附上「文字 → 照片编号」对照表，标明这是派生标签而非用户文案。

样例在 `examples/sample-input/`，可直接跑通。

## 推荐流程：先摆，后排（这是交互层，不随视觉回退）

1. 收到照片后**先看图**，给一份可推翻的分组草稿（哪几张是一件事），不要上来列问题。
2. 一次只搭一句话地聊事情，不问「请提供文案」；用户随口说的原话直接留下，不润色、不扩写。
3. 定封面／封底、气质；允许跳过、含糊、反悔（「先这样吧」「这页不放字」都是合法输入）。
4. 把决定写进 `story.json`：分组与顺序、每组原话、封面封底、`dropped`、`confirmed/pending`。
   来源标记只允许 `user_verbatim` / `user_confirmed_guess` / `unfilled`。
5. 用 `--story` 跑排版；先给 2–3 页样张确认节奏，再出整本。改的时候用户说人话即可。

用户也可以完全不用摆台，直接在对话里说「1、5、12 是一组，叫那天下午；封面用 08」。
详见 `references/interaction.md`。

## 主命令

```bash
python3 ~/.workbuddy/skills/zine-maker/scripts/make_zine.py \
  --images /绝对路径/images \
  --texts /绝对路径/texts.json \
  --out /绝对路径/out \
  --style field \
  --seed 7
```

摆完之后改用 story 模式（`--images` 仍指向原图目录，脚本会按 story 的分组顺序取图）：

```bash
python3 ~/.workbuddy/skills/zine-maker/scripts/make_zine.py \
  --images /绝对路径/images \
  --story /绝对路径/story.json \
  --out /绝对路径/out \
  --style field --seed 7
```

参数：`--style` 五选一（见下）；`--seed` 固定版式结果，便于复现与 A/B；`--no-pdf` 只出网页；
`--story` 读摆台结果（分组顺序、每组原话、封面封底指定图、划掉的照片）。
脚本只用 Python 标准库即可运行；Pillow（图片压缩、纸纹）与 Chrome（导出 PDF）是可选增强，缺失时自动降级。

`--story` 实际做的事（在 `plan_story()` / `normalize_story()`）：

- 按 `order` 排版，同一组照片连续、组内按写的顺序取图；`dropped`/`ungrouped` 排除；
  完全没提到的照片补进尾组，保证「每张照片都露面」。
- 骨架优先挑「刚好装得下这一组照片」的，不把一组 4 张塞进只要 2 张的版式。
- 每张照片全本最多 2 次；第二次换角色并写进 `版式清单.txt`，用户可以说去掉。
- 中心跨页强制用**两张不同的照片**（不再是同一张左右复制），且避开用户指定的封面/封底图。
- 用户原话原样渲染，不截断、不切两半、不润色；没填的文字位一律留白，
  封面不拿 `UNTITLED` 补，封底不写虚构作者/印量。
- 为凑 4 的倍数自动补的页标〔我补的〕；额外的页做留白，不拿旧照片凑数。
- 额外写 `文字来源对照.txt`：逐条标出印出来的字是「用户原话」还是「版式自带的功能性编号」。
- `--story` 模式下 `texts.json` 只当规格参数用（作者/印量/版权行），**不当文案用**，
  避免示例文件里的句子串到用户照片上。

## 五种风格（v1，已恢复为默认）

| 值 | 名称 | 什么时候选 |
|---|---|---|
| `field` | 采集 / 散步记录（**默认**） | 用户说「记录生活、生活方式、旅行、散步」时用这个，最贴近用户提供的 20 张参考 |
| `colorblock` | 色块拼贴 | 想要更跳、更高饱和、更年轻 |
| `artbook` | 艺术家书 / 豆本 | 想安静、纸感、极简、一页只放一个东西 |
| `xerox` | 黑白复印机 / 朋克 | 宣言、牢骚、剪贴、粗糙感 |
| `riso` | Riso 双色套印 | 活动、海报感、荧光双色 |

## 版式骨架（v1，已恢复为默认）

`references/layout-catalog.md` 是 11 种骨架字典，重新成为生成依据。
`STICKERS / COLORBLOCK / OVAL / ARTBOOK / BLOCK_TRIO / GRID_SMALL / SPREAD_FULL` 全部可用，
注意按 v1 **原意**实现（错落、有主次、带手写短句与时间戳），不要退化成「四枚等大徽章阵列」。
唯一仍停用：`SPREAD_L`／`SPREAD_R` 的「同一张图左右各半复制」版本（见底线 1）。
`references/zine-dna.md` 是从真实作品里数出来的 10 条共同元素与反例清单——**改风格前先读它**。
决策树有两个入口：**自动模式** `plan_zine()`（页数驱动、图片按互质步长轮转、长文切句、中心跨页固定在物理正中、同骨架不连续三次）；**story 模式** `plan_story()`（组顺序驱动、组内相邻、骨架按该组照片数选、最多 2 次、中心跨页两张不同图）。两者共用同一套 v1 骨架与渲染函数。

## 输出（全在 --out 目录）

| 文件 | 用途 |
|---|---|
| `plan.json` | 版式计划，纯文本可手工改 skeleton 后重跑 |
| `版式清单.txt` | 大白话版：第几页放什么 |
| `zine.html` | 阅读版，一页一页翻，屏幕验收用这个 |
| `zine.pdf` | 阅读版 A5 |
| `imposed.html` | 拼版预览（A4 横向，一张纸放两页） |
| `imposed.pdf` | **打印用这个**，页序已排好 |
| `README.txt` | 打印设置说明 |
| `文字来源对照.txt` | `--story` 模式才有：册子上每个字的来源，逐条可回查 |

## 打印设置（务必转达用户）

双面打印 + **短边翻转** + **100% 实际大小**（禁用「适合页面」）+ **关掉打印机自带 booklet 模式**。
先只打第一张对折核对，再打整本；整叠对折后沿书脊订两钉。
页数必须是 4 的倍数，脚本会自动补呼吸页。原理见 `references/imposition.md`。

## 验收 checklist

1. 脚本打印「页序自检通过」，且 `阅读版 A5 尺寸正确 / 打印版 A4 横向 尺寸正确`。
2. `版式清单.txt` 里中心两页恰好是第 `total/2` 与 `total/2+1` 页（SPREAD_L / SPREAD_R）。
3. 至少 2 页出现非直角裁切（圆形 / 椭圆 / 圆角），至少 1 页出现白边贴纸式小图；
   **整本不许方方正正**（波点、手绘线、倾斜叠压要在）。页数少时按页数折算，不为凑数硬加页。
4. 每页都有 tiny 页眉（封面 / 封底 / 中心跨页除外），标签全本一致。
5. 单页最多 1 个大面积彩色；没有「满版图 + 长文」同页；没有连续三页同一骨架。
6. 打开 `zine.html` 肉眼翻一遍：字没有被裁掉、没有纯白空页、没有图片裂图。

`--story` 模式额外验收：

- `版式清单.txt` 的组顺序与 `story.json` 的 `order` 一致，同一组照片连着出现。
- 每张照片都露面；`image_usage` 里没有 `×3` 及以上；出现 2 次的都点名标注。
- 中心跨页左右是**两张不同**照片。
- 未确认的组名 / `unfilled` 的文案一个字都没印；封面没标题时不出现 `UNTITLED`。
- `文字来源对照.txt` 里每一条印出的原话都能回查到 `story.json` 的具体字段。
- 自动补的页、暂用的封面图都在清单里标了「你可以换掉」。

## 红线

- 不改写用户文字、不重画照片、不引入素材库以外的图。
- 不用纯白 `#FFFFFF` 当纸色；禁止把 zine 排成商业杂志（条码 / 目录 / 双栏长文 / 统一圆角卡片）。
- 不把示例图的内容、配色当成用户素材；示例只用于验证链路。
- 输出前不删用户原图；`_assets/` 是压缩缓存，可随时重建。

## 排错

| 现象 | 处理 |
|---|---|
| 没找到图片 | 检查 `--images` 是否为绝对路径、扩展名是否支持 |
| PDF 没生成 | 没装 Chrome 时自动跳过；网页可直接用浏览器「打印 → 另存为 PDF」 |
| PDF 尺寸不对 | 浏览器打印时手动选 A5 / A4 横向、100% 缩放 |
| PDF 太大 | 内嵌照片所致；分享用 HTML，或用 macOS 预览「导出 → 缩小文件大小」 |
| 想换某页版式 | 改 `plan.json` 里该页 `skeleton`，再跑脚本（脚本会重算，改完需自行比对） |
| 页数太多 / 太少 | 自动模式调 `--seed` 或增减图片（公式在 `plan_zine()` 第②步）；story 模式改分组数或 `breath` |
| story 里某组照片没排完 | 该组照片超过 4 张会自动拆第二页；检查 `images` 编号是否写错（写 `08`、`08.jpg`、序号 `8` 都认） |
| 我写的组名/文案没印 | 检查 `name_source` / `note_source` 是不是写成了 `unfilled` 或 `…pending`；改成 `user_verbatim` 才会印 |
| 有些照片整本没出现 | 看 `版式清单.txt` 末尾「没用上的照片」；被 `dropped`/`ungrouped` 划掉的不会参与，去掉该字段即可 |

## 后续形态（当前不做）

用户提到「后续也许做成一个交互产品」。届时把 `plan.json` 当作前后端契约：
前端做拖拽换页 / 换骨架 / 调色，后端仍跑同一个渲染与拼版引擎。当前 skill 已把决策、渲染、拼版分离，便于迁移。
