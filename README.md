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
| 展开 | HRV 7 日 sparkline、生命体征、7 天训练表 | 同（SwiftBar 用 `webview` 弹层） |
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
  panel.template.html             深色面板模板
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

| 行 | 含义 |
|---|---|
| HRV today | 今日 HRV，按恢复状态着色；带 7 日基线 |
| Resting HR | 今日静息心率 + 7 日基线 |
| VO2max est | 心肺耐力**估算值**（`ml/kg`）。Apple Watch 只在户外步行/跑步时才测 Cardio Fitness，力量/间歇/骑行训练下 `vo2_max` 恒为空，所以走服务端的 Uth 公式回退估算 `15 × HRmax / HRrest`（HRmax 取 90 天实测最大值，HRrest 取 7 日滚动均值）。个体误差约 ±10~15%，**只看趋势** |
| Sleep | 昨晚总时长 + 深睡占比 |
| Weight | 最新体重 + 7 日均值 |
| Exercise | 今日锻炼环分钟数 / 目标，附热量与步数 |

VO2max **只放在展开面板里，不进菜单栏**：按公式它是静息心率的单调变换，和
`Resting HR` 那行高度共线，占菜单栏不划算；但作为一个可横向对比的绝对量级，看趋势有意义。
算法在服务端（`hae-api` 的 `worker.js`），与网页仪表盘共用同一份，避免两端各写一套后漂移。

## 恢复状态判定

由今天的 HRV 相对**前 7 天基线均值**的偏离幅度得出：

| 状态 | 条件 | 含义 |
|---|---|---|
| READY | 偏离 ≥ −5% | 状态正常，可以按计划训练 |
| EASE OFF | −15% ≤ 偏离 < −5% | 略低于基线，建议降强度 |
| RECOVERY | 偏离 < −15% | 恢复日，避免高强度 |

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
