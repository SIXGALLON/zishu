# 自书 · Zishu

**照片 + 那天的感觉 → 一本有审美、可打印的小册子。**

你对 AI 说「那天是什么感觉」，它把这句话翻译成设计：颜色、字、大小、松紧、照片怎么处理、每一页用哪种排法。
每个设计决定旁边都有一行小字，写着「因为你说了……」。同一组照片，说「热闹」和说「舍不得」，会长成两本完全不同的书。

这是一个 Agent Skill（一个文件夹 + 一份 `SKILL.md`，开放标准），同一份文件能在多个 AI 终端里用：

| 终端 | 装到哪 | 怎么叫它 |
|---|---|---|
| Claude Code | `~/.claude/skills/zishu` | 直接说「把这些照片做成小册子」，或 `/zishu` |
| Codex（CLI / IDE / 桌面版） | `~/.agents/skills/zishu` | 直接说，或 `$zishu` |
| Gemini CLI | `~/.gemini/skills/zishu` | 直接说 |
| WorkBuddy | `~/.workbuddy/skills/zishu` | 直接说 |
| 其它支持 SKILL.md 的终端 | 该终端的 skills 目录 | 直接说 |

## 安装

```bash
python3 install.py          # Windows：py install.py
```

它会做四件事：
1. 把这个文件夹链接进你电脑上检测到的每个终端（只建链接，不复制、不覆盖别人的东西）；
2. 装 Python 依赖：Pillow、fonttools、brotli；
3. 下载 8 款开源字体（约 95 MB，只需一次）；
4. 自检，告诉你这台电脑能做什么、缺什么。

装完确认一下：`python3 scripts/doctor.py --smoke`（用自带的 8 张示例照片真跑一本，约 30 秒）。

其它用法：`--only claude,codex` 只装指定终端；`--project 某目录` 装进项目里和团队共享；`--copy` 复制而不是链接；`--uninstall` 卸载（只删本脚本建的链接）。

## 需要什么

| | 必需？ | 没有会怎样 |
|---|---|---|
| Python 3.9+、Pillow | 必需 | 跑不了 |
| Chrome / Edge / Chromium | 强烈建议 | 改用 Playwright（`pip install playwright`）；两样都没有就只出网页，没有截图和 PDF |
| 开源字体 | 建议 | 退到系统字体，不同电脑上效果会不一样 |
| 抠图 | 可选 | macOS 自带；Windows / Linux 可 `pip install rembg`。没有的话，剪影、人形窗、巨型抠图这几种排法会自动不用 |

macOS、Windows、Linux 都能用。排版引擎是纯代码，不调任何模型：**同一份感受文件，在哪个终端、哪台电脑上跑，出来都是同一本书。**
和你聊天、把话变成感受参数、看图挑毛病，这些交给终端背后的模型。

## 文件夹里有什么

```
SKILL.md            给 AI 看的说明（流程、命令、字段、红线）
install.py          一键安装
requirements.txt    Python 依赖
agents/openai.yaml  Codex / ChatGPT 里的显示名
scripts/
  zishu.py          主命令：照片 + feeling.json → 一本书
  feel.py           感受 → 颜色、字、版面参数
  spreads.py        20 种跨页排法
  fx.py             图像效果（抠图贴纸、版画、描线、色带、双色……）
  platform_kit.py   跨平台：字体、浏览器、抠图
  doctor.py         自检
  cutout/           macOS 抠图
references/         给 AI 看的细则：感受怎么变成设计、怎么聊、审美规则、拼版
examples/           示例照片（Unsplash，无人物）和示例感受
legacy/             旧版本归档
```

## 许可

代码：MIT（见 `LICENSE`）。字体由 install.py 从原作者处下载，均为 SIL Open Font License 1.1：
思源宋体 / 思源黑体（Noto Serif SC / Noto Sans SC）、霞鹜文楷、小赖字体、Inter、Oswald、Bodoni Moda。
每本书输出时只打包用到的字（子集），许可证文件与字体放在一起。示例照片来自 Unsplash（经 picsum.photos），遵循 Unsplash License。
