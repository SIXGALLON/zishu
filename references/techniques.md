# 手法库（18 种跨页手法）

来源：用户给的 25 张参考（小红书 Wasabilazydog、ikkonz、椅子 zine、冷调留白、粉绿胡同、関西寻夏等）拆出的 13 种做法，
加上 v6 新增的 5 种（tiny / scatter / grid / fade / breath）。实现全在 `scripts/spreads.py`，一个函数一个跨页（1120×794 CSS，A5×2）。

「家族」用于节奏：**相邻跨页不许同家族**。「派生」= 图形来自照片本身（抠图轮廓、边缘线、色带、亮度曲线）。

| 名字 | 中文 | 家族 | 满版 | 派生 | 偏向的感受 | 需要 |
|---|---|---|---|---|---|---|
| bleed | 满版跨页 | bleed | ✓ | | 近、安静、浓 | 1 张（横图最好） |
| fade | 渐暗满版 | bleed | ✓ | | 很安静、浓、凉 | 1 张 |
| giant | 巨字压物 | type | | | 浓、近、热闹 | 1 个 ≤4 字的原话 + 能抠图的物件 |
| twoink | 两种墨·大字 | type | | | 恍惚、浓、热闹 | 2–5 张 |
| oval | 椭圆窗（+亮度曲线） | window | | | 中性、略恍惚 | 1–3 张 |
| figure | 人形窗 | window | | ✓ | 近、浓、恍惚 | 1 张能抠出人 + 1 张风景 |
| silhouette | 人形填字（+描线） | derive | | ✓ | 恍惚、近 | 1 张能抠出人 + 有原话 |
| slit | 照片压成色带 | derive | ✓ | ✓ | 安静、远、恍惚、规矩 | 全书 ≥ 8 张 |
| circles | 圆阵 | grid | | | 规矩、热闹 | ≥ 3 张 |
| grid | 规矩的小样张 | grid | | | 很规矩、热闹、远 | ≥ 4 张 |
| cards | 两种墨·纸片 | collage | ✓ | | 恍惚、乱、浓 | ≥ 2 张 |
| scatter | 散落贴纸 | collage | | | 很乱、很热闹、近 | ≥ 3 张 |
| flash | 闪光撞色 | flat | | | 很清楚、热闹、远、浓 | ≥ 2 张 |
| etch | 纸与物·版画 | paper | | ✓ | 安静、淡、暖 | 能抠图的物件 |
| cold | 冷调留白 | space | ✓ | | 很凉、淡、安静、远 | 1–2 张 |
| tiny | 大片空白里一张小照片 | space | | | 很远、很安静、淡、规矩 | 1 张 |
| river | 字河 | text | | ✓ | 淡、远 | ≥ 4 张 + 有字 |
| breath | 呼吸页 | breath | | | 安静 | 只在凑页数时用 |
| pair | 对开两张 | bleed | ✓ | | 贴近 | 两张竖图一页一张都出血；**只在逐页指定（layout）里用**，自动排版不会选它 |
| windows | 门缝与拱窗 | window | | | 安静、隔着点距离 | 左页一条窄竖缝、右页一扇拱窗，四周留纸（right_style=bleed 时右页铺满）；只在逐页指定里用 |

## 每个手法的「不许」

- giant：字必须是用户原话（`big_words` 或 `said` 拆出的短句），不许拿 Agent 的话当大字。
- silhouette / river / circles：排进去的字只能是原话 + 标为 `derived_visible` 的画面描述（`see`），并在文字来源里登记。
- figure / silhouette / etch：照片没抠出主体就自动跳过，不硬做。
- slit：数字是真实计算的亮度，不是装饰。
- 任何手法：同一张照片第二次出现必须换家族（换角色），全书重复的张数有上限（照片数 / 5）。

## 新增手法时

1. 写一个 `@tech(...)` 函数，声明 family / aff / bleed / derive / max_use / min_photos。
2. 颜色只用 `c.P[...]`，字只用 `c.f_disp / f_body / f_lat / f_num`，照片只用 `c.pick()` + `c.treat()`。
3. 印出的每个字走 `c.say(text, source, field)`；每个设计决定写一条 `c.nb(说明, 轴)`。
4. 跑三本示例书，看图批改后再提交。
