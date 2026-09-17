# HAE Pulse

把今天的 HRV 和恢复状态常驻在 **Omarchy 面板** 和 **macOS 菜单栏** 上。
两端共用同一份数据层，只有渲染是各写各的。

数据来自自建的 HAE 服务（`hae.qiaclass.com`）——只读，不回写任何健康数据。
服务端代码与接口契约见 [**hae-api**](https://github.com/hongyangchun/hae-api)，
同一服务还托管网页版仪表盘 `/dashboard`。

## 两个前端

| | Omarchy | macOS |
|---|---|---|
| 渲染 | `Main.qml`（Quickshell bar widget） | `render.py` + SwiftBar 插件 |
| 菜单栏 | HRV 数字，按恢复状态着色 | 同 |
| 展开 | HRV 7 日 sparkline、生命体征、7 天训练表 | 同（**一个面：下拉本身就是弹层**） |
| 安装 | `./install.sh omarchy` | `./install.sh macos` |
| 细节 | [omarchy/hyc.hae-pulse/README.md](omarchy/hyc.hae-pulse/README.md) | [macos/README.md](macos/README.md) |

## 结构

```
collector.py                      数据层：查 hae.qiaclass.com，输出单行 JSON
omarchy/hyc.hae-pulse/
  Main.qml                        Quickshell 面板与弹层
  manifest.json                   Omarchy 插件清单
  collector.py -> ../../collector.py
macos/
  render.py                       SwiftBar 渲染层（替代 Main.qml）
  plugins/hyc.hae-pulse.10m.py    SwiftBar 插件薄壳（10 分钟刷新）
  .env.example                    可选的项目独立凭证
install.sh                        安装到各端的运行位置
LICENSE
```

`collector.py` 在仓库里**只有一份**，放在根目录。两端都按「自身所在目录的相对路径」
找到它，因为两个平台的加载器都要求插件目录能自包含地定位到这个文件：

- **macOS**：`render.py` 用 `../collector.py`。
- **Omarchy**：插件目录里的 `collector.py` 是指向仓库根的符号链接。`Main.qml` 里是
  `pluginDir + "/collector.py"`，所以该文件必须出现在插件目录中。

改一次 `collector.py`，两端同时生效。

## 展开面板里的字段

行序三端一致（菜单栏只放 L1 结论数字，展开才有 L2）：

| 行 | 含义 |
|---|---|
| HRV 今日 | 今日 HRV，按恢复状态着色；带 7 日均值。取不到今天时显示「昨日 X ms」 |
| 静息心率 | 最近一次静息心率 + 7 日均值。**日结型指标，当天通常还没有**，所以右列带数据日期（如 ` · 09-16`） |
| 心肺耐力(估) | 心肺耐力**估算值**（`ml/kg`）。Apple Watch 只在户外步行/跑步时才测 Cardio Fitness，力量/间歇/骑行训练下 `vo2_max` 恒为空，所以走服务端的 Uth 公式回退估算 `15 × HRmax / HRrest`（HRmax 取 90 天实测最大值，HRrest 取 7 日滚动均值）。个体误差约 ±10~15%，**只看趋势**。它继承了静息心率的滞后，日期通常也是昨天 |
| 睡眠 | 最近一晚总时长 + 深睡占比。日期 = 醒来那天早晨，所以标出日期就说明看到的不是昨晚 |
| 体重 | 最新体重 + 7 日均值，带数据日期 |
| 锻炼 | **今日已记录的训练时长** / 目标，附训练次数、热量与步数。来自 `/api/workouts`，不是 Apple 锻炼环 —— 见下 |

**静息心率/睡眠/体重/心肺耐力这几行右边会带一个 ` · MM-DD`**，那是数据的日期。它们都是
**日结型**指标：Apple 在当天结束后才定稿，所以当天根本不会有当天的点，显示的几乎总是昨天的数。
不标日期就会被读成今天的读数。规则在 `collector.py` 的 `latest()` 与 `render.py` 的
`day_suffix()` / `Main.qml` 的 `daySuffix()` —— 三端一致。

**「锻炼」用的是今日训练时长，不是 Apple 锻炼环。** 锻炼环（`apple_exercise_time`）是日结型，
当天的值在源端不存在，拿它算「今日锻炼」会恒为 0；`/api/workouts` 是当天实时写入的，只有它当天会动。
代价是训练时长属于锻炼环的子集，不计入非训练的零星活动分钟 —— 所以这一行叫「锻炼」而不是「活动」。

心肺耐力**只放在展开面板里，不进菜单栏**：按公式它是静息心率的单调变换，和
「静息心率」那行高度共线，占菜单栏不划算；但作为一个可横向对比的绝对量级，看趋势有意义。
算法在服务端（`hae-api` 的 `worker.js`），与网页仪表盘共用同一份，避免两端各写一套后漂移。

## 恢复状态判定

由今天的 HRV 相对**前 7 天基线均值**的偏离幅度得出：

| 状态（内部取值） | 界面文案 | 条件 | 含义 |
|---|---|---|---|
| `ready` | 可以练 | 偏离 ≥ −5% | 状态正常，可以按计划训练 |
| `watch` | 悠着点 | −15% ≤ 偏离 < −5% | 略低于基线，建议降强度 |
| `rest` | 该休息 | 偏离 < −15% | 恢复日，避免高强度 |

取值保持英文（那是数据标识，仪表盘也读它），**界面文案统一中文**，与网页仪表盘的状态条用同一套词。
阈值两处实现、一处定义：`collector.py` 与 `hae-api` 的 `dashboard.js`，**改要同时改**。

## 界面规范

三端（含网页仪表盘）共用一套规范：三层信息架构（结论 / 关键量 / 明细）、统一行序、中文文案、
排版 token、颜色语义、加载·空·失败三态。**动界面之前先读**
[design-notes 第四节](https://github.com/hongyangchun/hae-api/blob/main/docs/design-notes.md)。

最容易踩的四条：

- **行序**：`HRV → 静息心率 → 心肺耐力(估) → 睡眠 → 体重 → 锻炼`。
  两端曾经不同（macOS 把心肺耐力排在前、Omarchy 排在后），改一端必须同时改另一端。
- **日结型指标别取「今天」**：静息心率/睡眠/体重/心肺耐力/锻炼环当天在源端不存在，
  只取今天会恒为空。取「最近可用值」+ 把日期标出来。判断某指标属于哪类最快的入口是
  `/api/metrics` 的 `last_day`（今天 = 实时型，昨天 = 日结型）。
- **下拉是等宽菜单**，中文按 2 格计。列宽要**先收集所有行再统一算** `max(下限, 最长内容 + 2)` ——
  `+2` 是硬要求：值恰好占满列宽时 `pad()` 留 0 个空格，历史上出现过 `min585.1` 这种粘连读数。
- **一个信息面就够**：macOS 曾经还有一个 `panel.html` 的 webview 弹层，内容与下拉完全重复
  （等于同一屏看两遍），已删除。**新增信息面之前先问：下拉真的放不下吗？**

## 安装

```sh
git clone https://github.com/hongyangchun/hae-pulse.git
cd hae-pulse

./install.sh omarchy    # 链接到 ~/.config/omarchy/plugins
./install.sh macos      # 指向 SwiftBar 并重启它
```

**每台机器各跑一次** —— 软链用的是相对于仓库的路径，必须在实际所在的那台机器上求值。

脚本是幂等的，重复运行不会破坏已正确的配置。遇到同名真目录会先备份到
`~/.local/state/hae-pulse/backups/` —— 备份**刻意不放在插件目录里**：宿主会扫描
该目录下的每一个条目，一份带 `manifest.json` 的备份会被当成第二个插件加载
（同一个 manifest id 出现两次）。

## 凭证

一个只读 key，两端共用，放 `~/.hermes/.env`：

```sh
# 追加，不要覆盖 —— 这个文件里还有 hermes 的其他配置
printf 'HAE_READ_KEY=%s\n' 'your-key' >> ~/.hermes/.env
chmod 600 ~/.hermes/.env
```

macOS 侧可以额外建 `macos/.env` 让该平台独立于 Omarchy（优先级更高，已在
`.gitignore` 中）。查找顺序见 [macos/README.md](macos/README.md#配置)。

## 要求

- **Python 3.10+**。`collector.py` 用了 `str | None` 注解语法，macOS 自带的
  `/usr/bin/python3` 是 3.9.6，会在运行时抛 `TypeError`（`py_compile` 不报，因为注解
  在函数定义时才求值）。
- Omarchy + Quickshell（Omarchy 端）。
- SwiftBar 2.x，要求 macOS 12+（macOS 端）。
