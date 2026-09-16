# HAE Pulse — macOS 端

[hae-pulse](https://github.com/hongyangchun/hae-pulse) 的 macOS 一半：与 Omarchy 端共用
同一份数据层，只有渲染层是各写各的。总览见[仓库根 README](../README.md)。

菜单栏常驻今天的 HRV，按恢复状态着色；点开是 sparkline、生命体征和 7 天训练记录。

数据只读，不回写 Health Auto Export。

## 它长什么样

**菜单栏**：今天的 HRV 整数，颜色即恢复状态。

| 状态 | 条件 | 浅色外观 | 深色外观 |
|---|---|---|---|
| READY | HRV ≥ 基线 −5% | `#3B6D11` | `#8FF740` |
| EASE OFF | −15% ≤ HRV < −5% | `#854F0B` | `#d7a55b` |
| RECOVERY | HRV < 基线 −15% | `#A32D2D` | `#FF5C57` |

**下拉菜单**：HRV 7 日 sparkline 位图、生命体征三列（当前值 / 7 日基线）、7 天训练表。

**面板**：点「Open panel」打开 440×620 的深色弹层，即 Omarchy 版那个 panel 的等价物。

## 架构

移植只替换了渲染层。数据层与 Omarchy 端共用仓库根的同一份 `collector.py`，未作任何修改。

```
../collector.py          从 hae.qiaclass.com 拉数据，输出单行 JSON   ← Omarchy 端引用同一文件
render.py                SwiftBar 渲染：菜单栏 + 下拉菜单 + 生成面板  ← 替代 Main.qml
plugins/
  hyc.hae-pulse.10m.py   SwiftBar 插件薄壳（10 分钟刷新）
panel.template.html      深色面板模板，数据由 render.py 内联写入
panel.html               运行时生成（勿提交）
cache.json               最后一次成功快照，断网时回退显示（勿提交）
.env                     可选：本平台独立凭证，优先级高于 ~/.hermes（勿提交）
```

`render.py` 通过 `../collector.py` 找到共享数据层；Omarchy 端则在插件目录里放一个指向
仓库根的符号链接，因为它的 `Main.qml` 用 `pluginDir + "/collector.py"`。

## 安装

```sh
brew install --cask swiftbar
cd ..              # 仓库根
./install.sh macos
```

脚本会把 SwiftBar 的插件目录指向 `macos/plugins/`、给插件加执行位、设置 `StealthMode`，
然后重启 SwiftBar。手动等价操作：

```sh
defaults write com.ameba.SwiftBar PluginDirectory -string "$PWD/plugins"
```

## 配置

key 可以放两处，优先级不同 —— 这一点是**实测出来的**，不是读代码猜的：

| 放置位置 | 经 `render.py`（SwiftBar 插件） | 直接跑 `collector.py` |
|---|---|---|
| 本项目 `.env` | ✅ **优先** | ❌ 不参与 |
| `~/.hermes/.env` | ✅ 次之 | ✅ 优先 |
| 环境变量 `HAE_READ_KEY` | — | ✅ 最高 |

机制：`render.py` 的 `load_env()` 读本项目 `.env`，再用 `env.update()` **注入子进程环境变量**
（`render.py:56-66, 74-75`）；而 `collector.py` 的 `load_key()` 先查环境变量、再查
`~/.hermes/.env`（`collector.py:36-44`）。所以项目 `.env` 借环境变量这一跳胜出。

两端共用同一把 key 的话，推荐放 `~/.hermes/.env`：

```sh
# 追加，不要覆盖 —— 这个文件里还有 hermes 的其他配置
printf 'HAE_READ_KEY=%s\n' 'your-key-here' >> ~/.hermes/.env
chmod 600 ~/.hermes/.env
```

想让 macOS 侧独立于 Omarchy，就在本目录建 `.env`（**不要提交**，已在仓库根的
`.gitignore` 中）：

```sh
cp .env.example .env && $EDITOR .env
```

> 验证方法：把项目 `.env` 的 key 改成错误值，经插件取数应显示 `HTTP Error 401` 并回退到
> 上一次成功的快照（菜单栏数字后出现 `●`）；直接跑 `collector.py` 则不受影响。

## 要求

- **Python 3.10+**。`collector.py` 用了 `str | None` 注解语法，macOS 自带的
  `/usr/bin/python3` 是 3.9.6，会在运行时抛 `TypeError`（注意 `py_compile` 不会报，
  因为注解在函数定义时才求值）。插件 shebang 已指向 `/opt/homebrew/bin/python3`。
- SwiftBar 2.x（要求 macOS 12+）。

## 命名

三个「名字」是分开的，别混：

| 位置 | 值 | 能否改 |
|---|---|---|
| 菜单栏文字 | 插件自己输出的 HRV 数字（如 `42`） | 改 `render.py` 的 `menu()` |
| 下拉菜单首行 | `HAE PULSE · READY` | 改 `render.py` 的 `menu()` |
| 悬挂提示 / 偏好面板里的插件名 | 文件名去掉 `.10m.py` → `hyc.hae-pulse` | 改文件名 |
| SwiftBar 应用本身 | `SwiftBar.app` | **不要改** —— 它有代码签名和 Sparkle 自动更新，改名会破坏两者 |

SwiftBar 的偏好键里没有「显示插件名」这一项（已核对 `PreferencesStore.swift` 的
`PreferencesKeys` 全部枚举），所以菜单里的文字完全由脚本输出决定。

⚠️ 如果菜单栏上直接出现 **`SwiftBar` 字样**，那不是命名问题，而是**插件没被加载**：
SwiftBar 在没有任何插件输出时会退化成显示自己的名字。

## 隐藏 SwiftBar 自身

SwiftBar 会在两个不同层次露出自己，机制和开关都不一样 —— 两个都已配好：

| 露出的位置 | 控制手段 | 已设的值 |
|---|---|---|
| 菜单栏上独立的 SwiftBar 图标 | 偏好 `StealthMode` | `YES` |
| 本插件下拉菜单顶部的 `SwiftBar` 子菜单项 | 插件头部标记 `<swiftbar.hideSwiftBar>` | `true` |

**`StealthMode` 的准确语义**（源码 `PluginManger.swift`）：

```swift
func shouldShowDefaultBarItem(hasVisiblePlugins: Bool, stealthMode: Bool) -> Bool {
    !stealthMode && !hasVisiblePlugins
}
```

即那个默认图标**只在「没有任何可见插件」时才出现**。所以插件正常工作时它本来就是隐藏的，
`StealthMode=YES` 是兜底 —— 防止插件报错或被禁用时菜单栏突然多出一个 SwiftBar 图标。

```sh
defaults write com.ameba.SwiftBar StealthMode -bool YES
```

**别用 `HideSwiftBarIcon` 来「隐藏」** —— 它在 `MenuBarItem.swift` 里的实际行为只是
`swiftBarItem.image = nil`，菜单项本身仍然存在，只是没图标。

菜单项被隐藏后，**Option(⌥) + 点击**插件的菜单栏项可以临时显示全部默认项（含
Preferences / Quit），这是隐藏后的找回入口；也可以直接在 Spotlight 里启动 SwiftBar。

## 与 Omarchy 版的行为差异

1. **失败时回退到缓存**。原版取数失败只显示 `●`。这里保留最后一次成功的快照，
   状态行标注 `stale`，菜单栏数字后加一个 `●` 标记。笔记本合盖、断网时更实用。
2. **配色双份**。原版直接用 `#8FF740` / `#d7a55b` 这套深色主题色。macOS 菜单栏
   默认是浅色背景，所以浅色外观下换用了同色系的深色变体，深色外观下保持原色。
3. **sparkline 在菜单里是位图**。Omarchy 用 QML Canvas 实时绘制；SwiftBar 的菜单项
   只能放图片，所以 `render.py` 手写 PNG 编码生成位图（stdlib 的 `zlib` + `struct`，
   无第三方依赖）。面板里仍然是实时 Canvas。

## 验证渲染

不需要真实 key，用构造数据检查输出格式：

```sh
/opt/homebrew/bin/python3 -c "
import sys; sys.path.insert(0,'.')
import render, json
d = json.load(open('cache.json'))
print(render.menu(d))
"
```
