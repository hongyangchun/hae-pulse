#!/opt/homebrew/bin/python3
"""HAE Pulse — SwiftBar renderer.

macOS port of the Omarchy plugin. The data layer is shared verbatim: this
module shells out to the very same `collector.py` and renders its single-line
JSON. Everything here replaces Main.qml (the Quickshell bar widget + popout
panel), which has no macOS equivalent.

Layout mirrors Main.qml:
  menubar  -> HRV number, tinted by recovery verdict
  dropdown -> sparkline, vitals rows, 7-day training table

**只有一个信息面：下拉。** 早期还有一个 `panel.html` 的 webview 弹层，但它和下拉
的内容是同一份（hero / sparkline / 行 / 训练表全都有），等于同一屏东西看两遍；
Omarchy 端也没有第二个面（bar 只放数字，弹层放全部）。所以面板整个删掉了 ——
下拉就是那个弹层，两个平台看到的是一件事。要更长的历史去网页仪表盘。
"""

import base64
import json
import os
import struct
import subprocess
import sys
import zlib
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
# The data layer is shared with the Omarchy build and lives at the repo root,
# one level up from this platform directory. See omarchy/hyc.hae-pulse/collector.py,
# which reaches the same file through an in-repo relative symlink.
COLLECTOR = os.path.normpath(os.path.join(ROOT, os.pardir, "collector.py"))
CACHE = os.path.join(ROOT, "cache.json")
ENV_FILE = os.path.join(ROOT, ".env")

# Verdict palette. SwiftBar takes "light,dark" pairs; the Omarchy originals
# (#8FF740 / #d7a55b / theme urgent) are dark-appearance hues, so light mode
# gets a darker sibling to stay legible on the default menu bar.
C_READY = "#3B6D11,#8FF740"
C_WATCH = "#854F0B,#d7a55b"
C_REST = "#A32D2D,#FF5C57"
C_DIM = "#6E6E73,#9A9A9F"
C_FG = "#1D1D1F,#E8E8EA"

VCOLOR = {"ready": C_READY, "watch": C_WATCH, "rest": C_REST}
# 三端统一中文，且与仪表盘状态条用同一套词（可以练 / 悠着点 / 该休息）。
# verdict 的取值仍是 ready/watch/rest —— 那是数据标识（collector.py 输出），不翻译。
VLABEL = {"ready": "可以练", "watch": "悠着点", "rest": "该休息"}

# Self-hosted HAE dashboard (password-gated HTML page on the same host as the
# API). Not healthyapps.dev — that is the upstream vendor's site; the data
# lives on qiaclass.
DASHBOARD = "https://hae.qiaclass.com/dashboard"

# Raw hex used when drawing the sparkline bitmap (RGBA).
PIX = {
    "ready": ((0x3B, 0x6D, 0x11), (0x8F, 0xF7, 0x40)),
    "watch": ((0x85, 0x4F, 0x0B), (0xD7, 0xA5, 0x5B)),
    "rest": ((0xA3, 0x2D, 0x2D), (0xFF, 0x5C, 0x57)),
}


def is_dark():
    return (os.environ.get("OS_APPEARANCE", "Light") or "").lower() == "dark"


def load_env():
    """Project-local .env, so the repo never touches ~/.hermes."""
    extra = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as fh:
            for raw in fh:
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    extra[k.strip()] = v.strip()
    return extra


# ---------------------------------------------------------------- data layer


def snapshot():
    """Run collector.py. On failure fall back to the last good snapshot."""
    env = dict(os.environ)
    env.update(load_env())

    if sys.version_info < (3, 10):
        return {"ok": False,
                "error": "need Python 3.10+ (running %d.%d)" % sys.version_info[:2]}

    try:
        proc = subprocess.run([sys.executable, COLLECTOR], capture_output=True,
                              text=True, timeout=40, env=env)
        lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln]
        data = json.loads(lines[-1]) if lines else {"ok": False, "error": "no output"}
    except Exception as exc:
        data = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    if data.get("ok"):
        try:
            with open(CACHE, "w") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            pass
        data["stale"] = False
        return data

    try:
        with open(CACHE) as fh:
            cached = json.load(fh)
        cached["stale"] = True
        cached["stale_error"] = str(data.get("error", "unknown"))[:120]
        return cached
    except Exception:
        data["stale"] = False
        return data


# ------------------------------------------------------------- formatting


def dwidth(text):
    """Display width in monospace cells (CJK counts as two)."""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def pad(text, width):
    """等宽填充。注意 width 是**下限**：内容刚好占满时会留 0 个空格，两列直接粘连
    （实测过 "Exercise  65 / 30 min585.1 kcal" 这种读数）。
    所以调用方必须先算好统一的列宽 w = max(下限, 最长内容宽 + 2)，不要让 pad 自己兜底。
    """
    text = str(text)
    return text + " " * max(0, width - dwidth(text))


def thousands(n):
    """大数加千分位：5695 步、585 kcal 不加分隔读不出量级。"""
    try:
        return "{:,}".format(int(round(float(n))))
    except (TypeError, ValueError):
        return str(n)


def day_suffix(day, fetched_at):
    """值不是当天时返回 ' · MM-DD'，是当天（或没有日期）就返回空串。

    **日结型指标要标日期。** 静息心率/睡眠/体重/心肺耐力(估)由整夜数据算出，
    Apple 清晨才定稿：清晨前最新点是昨天的，清晨后当天的点就有了。两种都会遇到，
    所以只能按日期比 —— 标出来是唯一能避免「昨天的读数被当成今天」的办法。
    值与快照抓取日期比较，与 Omarchy 侧 Main.qml 的写法完全一致
    （那边同样比 `day` 与 `fetched_at[:10]`）。
    """
    if not day or not fetched_at:
        return ""
    return "" if day == fetched_at[:10] else " · " + str(day)[5:]


def fmt_hours(hours):
    if hours is None:
        return "—"
    whole = int(hours)
    mins = round((hours - whole) * 60)
    if mins == 60:
        whole, mins = whole + 1, 0
    return "%dh%02dm" % (whole, mins)


def ago_text(iso):
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        secs = max(0, int((datetime.now(when.tzinfo) - when).total_seconds()))
    except Exception:
        return ""
    if secs < 90:
        return "刚刚更新"
    if secs < 3600:
        return "%d 分钟前更新" % (secs // 60)
    if secs < 86400:
        return "%d 小时前更新" % (secs // 3600)
    return "%d 天前更新" % (secs // 86400)


# ------------------------------------------------------------ sparkline png


def _chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def _encode_png(width, height, rows):
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))


def sparkline_png(series, avg, verdict, width=156, height=30):
    """7 bars (today verdict-tinted) over a dashed baseline, like Main.qml."""
    points = [p for p in (series or []) if p.get("value") is not None]
    if len(points) < 2:
        return None

    vals = [p["value"] for p in points]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1:
        hi = lo + 1.0
    pad_y = 4

    light_rgb, dark_rgb = PIX.get(verdict, PIX["ready"])
    accent = dark_rgb if is_dark() else light_rgb
    dim = (0x8A, 0x8A, 0x8E) if is_dark() else (0x7A, 0x7A, 0x7F)

    canvas = [[(0, 0, 0, 0)] * width for _ in range(height)]

    def put(x, y, color):
        if 0 <= x < width and 0 <= y < height:
            canvas[y][x] = color

    def ypos(value):
        span = (value - lo) / (hi - lo)
        return int(round(height - (pad_y + span * (height - 2 * pad_y))))

    if avg:
        base_y = ypos(avg)
        for x in range(0, width, 4):
            put(x, base_y, dim + (150,))
            put(x + 1, base_y, dim + (150,))

    slot = width / len(series)
    bar_w = max(3, min(16, int(slot * 0.45)))
    for idx, point in enumerate(series):
        value = point.get("value")
        if value is None:
            continue
        top = ypos(value)
        is_today = idx == len(series) - 1
        color = (accent if is_today else dim) + (255 if is_today else 140,)
        left = int(idx * slot + (slot - bar_w) / 2)
        for x in range(left, min(left + bar_w, width)):
            for y in range(top, height):
                put(x, y, color)

    png = _encode_png(width, height, canvas)
    return base64.b64encode(png).decode("ascii")


# ------------------------------------------------------------------ render


def menu(data):
    out = []

    if not data.get("ok"):
        out.append("● | color=%s size=13 font=Menlo" % C_DIM)
        out.append("---")
        out.append("HAE 健康 · 离线 | color=%s font=Menlo size=13" % C_REST)
        out.append(str(data.get("error", "无数据"))[:110] + " | color=%s size=11 font=Menlo" % C_DIM)
        out.append("---")
        out.append("立即刷新 | refresh=true font=Menlo size=12")
        out.append("打开健康仪表盘 | href=%s font=Menlo size=12" % DASHBOARD)
        return "\n".join(out)

    verdict = data.get("verdict", "ready")
    vcolor = VCOLOR.get(verdict, C_READY)
    vlabel = VLABEL.get(verdict, "可以练")
    hrv_today = data.get("hrv_today")
    stale = " ●" if data.get("stale") else ""

    # 菜单栏只承载 L1：一个数字（HRV）按恢复状态着色。
    out.append("%s | color=%s size=13 font=Menlo" % (
        round(hrv_today) if hrv_today is not None else "●", vcolor))

    out.append("---")
    out.append("HAE 健康 · %s%s | color=%s font=Menlo size=13" % (vlabel, stale, vcolor))

    delta = data.get("hrv_delta_pct")
    if delta is None:
        sub = "暂无基准"
    else:
        sub = "%s%.1f%% 对比 7 日均值" % ("+" if delta >= 0 else "", delta)
    out.append(sub + " | color=%s font=Menlo size=11" % C_DIM)

    # HRV 7 日柱状图（PNG 自绘，末柱按 verdict 着色，虚线是 7 日均值）
    png = sparkline_png(data.get("hrv_series"), data.get("hrv_avg7"), verdict)
    if png:
        out.append("---")
        out.append("HRV · 近 7 天 | image=%s width=156 height=30 font=Menlo size=11" % png)

    # ---- L2 关键量：标签 / 值 / 基准 三列 ----
    # 行序三端统一（macOS 与 Omarchy 曾经不同）：HRV → 静息心率 → 心肺耐力 → 睡眠 → 体重 → 锻炼。
    # 先收集成列表再统一算列宽 —— 等宽对齐要求所有行的列起点一致，
    # 逐行各自 pad 会让「心肺耐力(估)」这种更宽的标签把整行顶歪。
    #
    # 日期规则（三端共用）：**值不是今天的，右列就带一个 ' · MM-DD'**。
    # 静息心率/睡眠/体重/心肺耐力(估)是「日结型」：它们由整夜的数据算出，当天的点
    # 要到清晨才落库。清晨之前最新点仍是昨天的，清晨之后就和今天一致了 —— 两种
    # 情况都真实存在，所以规则不能写死成「永远标日期」，也不能不标：只能比较日期。
    # 不标的话，昨天的读数会被当成今天的。HRV 与锻炼是当天口径，不带日期
    # （HRV 取不到今天时走「昨日」文案，那是它自己的写法）。
    rows = []

    hrv_base = data.get("hrv_avg7")
    if hrv_today is not None:
        right = "7 日均 %s ms" % hrv_base if hrv_base is not None else ""
    else:
        right = "昨日 %s" % (
            "%s ms" % data["hrv_yesterday"] if data.get("hrv_yesterday") is not None else "—")
    rows.append(("HRV 今日", "%s ms" % hrv_today if hrv_today is not None else "—", right, vcolor))

    fetched = data.get("fetched_at")

    rhr_today, rhr_base = data.get("rhr_today"), data.get("rhr_avg7")
    rhr_right = "7 日均 %s bpm" % rhr_base if rhr_base is not None else ""
    rows.append(("静息心率", "%s bpm" % rhr_today if rhr_today is not None else "—",
                 rhr_right + day_suffix(data.get("rhr_day"), fetched), C_FG))

    # 心肺耐力估算值。放下拉而不是菜单栏：按 Uth 公式它是静息心率的单调变换，
    # 与上一行高度共线，占菜单栏不划算；但作为「心脏能力」的绝对量级看趋势有意义。
    # 标「(估)」以区别于 Apple 的实测值（本账号无户外步行/跑步，实测值恒为空）。
    # 它也继承了静息心率的滞后（rhr7 窗口要等静息心率），所以日期通常也是昨天。
    vo = data.get("vo2max")
    if vo:
        right = "7 日均 %s" % vo["avg7"] if vo.get("avg7") is not None else ""
        if vo.get("hrmax_ref") is not None:
            right = (right + " · " if right else "") + "HRmax %s" % vo["hrmax_ref"]
        rows.append(("心肺耐力(估)", "%s ml/kg" % vo["est"] if vo.get("est") is not None else "—",
                     right + day_suffix(vo.get("day"), fetched), C_FG))

    sleep = data.get("sleep")
    if sleep:
        deep = "深睡 %s" % fmt_hours(sleep.get("deep_hr"))
        if sleep.get("deep_pct") is not None:
            deep += " · %d%%" % sleep["deep_pct"]
        # 睡眠点的日期 = 醒来那天早晨，所以「昨晚」的点日期是今天；哪天标出了
        # 日期，就说明看到的是更早那一晚。
        rows.append(("睡眠", fmt_hours(sleep.get("total_hr")),
                     deep + day_suffix(sleep.get("day"), fetched), C_FG))

    weight = data.get("weight")
    if weight:
        wt_right = "7 日均 %s kg" % weight["avg7"] if weight.get("avg7") is not None else ""
        if weight.get("bf") is not None:
            bf_txt = " 体脂 %s%%" % weight["bf"]
            if weight.get("bf_est") is not None:
                bf_txt += "（真实约 %s%%）" % weight["bf_est"]
            wt_right += " ·" + bf_txt
        rows.append(("体重", "%s kg" % weight["kg"],
                     wt_right + day_suffix(weight.get("day"), fetched), C_FG))

    # 锻炼 = **今日已记录的训练时长**（来自 workouts，当天就有），不是锻炼环。
    # 锻炼环（apple_exercise_time）是日结型，清晨前当天的值拿不到，用它这一行会
    # 恒为 0。代价：训练时长是锻炼环的子集，不计入非训练的零星活动分钟。
    sessions = data.get("exercise_sessions_today") or 0
    ex_right = "%s kcal · %s 步" % (thousands(data.get("kcal_today", 0)),
                                    thousands(data.get("steps_today", 0)))
    if sessions:
        ex_right = "%d 次 · %s" % (sessions, ex_right)
    rows.append(("锻炼",
                 "%s / %s 分钟" % (data.get("exercise_min_today", 0), data.get("exercise_goal", 30)),
                 ex_right, C_FG))

    out.append("---")
    # 列宽 = max(下限, 最长内容 + 2) —— +2 保证两列之间至少有 2 格，不会粘连
    w1 = max(12, max(dwidth(r[0]) for r in rows) + 2)
    w2 = max(12, max(dwidth(r[1]) for r in rows) + 2)
    for label, value, right, color in rows:
        out.append("%s%s%s | color=%s font=Menlo size=12" % (
            pad(label, w1), pad(value, w2), right, color))

    # ---- 训练记录 ----
    workouts = data.get("workouts_7d") or []
    out.append("---")
    out.append("训练 · 近 7 天 | color=%s font=Menlo size=11" % C_DIM)
    if not workouts:
        out.append("暂无训练记录 | color=%s font=Menlo size=11" % C_DIM)
    wname = max([16] + [dwidth(str(w.get("name", "—"))) + 2 for w in workouts])
    for row in workouts:
        day = str(row.get("day", ""))[5:]
        detail = "%s 分钟 · %s kcal · %s" % (
            row.get("min", 0), thousands(row.get("kcal", 0)),
            "%s/%s bpm" % (round(row["avg_hr"]) if row.get("avg_hr") else "—",
                           round(row["max_hr"]) if row.get("max_hr") else "—"))
        out.append("%s %s%s | color=%s font=Menlo size=11" % (
            day, pad(str(row.get("name", "—")), wname), detail, C_FG))

    # ---- 页脚：新鲜度 ----
    # 放在内容之后、动作之前，与 Omarchy 弹层的底部状态行同一位置。
    stamp = ago_text(data.get("fetched_at"))
    if data.get("stale"):
        stamp = "数据陈旧 · %s · %s" % (stamp or "用的是缓存", data.get("stale_error", ""))
    if stamp:
        out.append("---")
        out.append(stamp.strip(" ·") + " | color=%s font=Menlo size=11" % C_DIM)

    # ---- 动作 ----
    # 没有第二个信息面：下拉本身就是那个弹层。要更长的历史去网页仪表盘。
    out.append("---")
    out.append("立即刷新 | refresh=true font=Menlo size=12")
    out.append("打开健康仪表盘 | href=%s font=Menlo size=12" % DASHBOARD)

    return "\n".join(out)


def main():
    try:
        print(menu(snapshot()))
    except Exception as exc:  # never leave the menubar blank
        print("● | color=%s size=13 font=Menlo" % C_DIM)
        print("---")
        print("HAE Pulse · render error | color=%s font=Menlo size=13" % C_REST)
        print("%s: %s | color=%s size=11" % (type(exc).__name__, exc, C_DIM))


if __name__ == "__main__":
    main()
