#!/opt/homebrew/bin/python3
"""HAE Pulse — SwiftBar renderer.

macOS port of the Omarchy plugin. The data layer is shared verbatim: this
module shells out to the very same `collector.py` and renders its single-line
JSON. Everything here replaces Main.qml (the Quickshell bar widget + popout
panel), which has no macOS equivalent.

Layout mirrors Main.qml:
  menubar  -> HRV number, tinted by recovery verdict
  dropdown -> sparkline, vitals rows, 7-day training table
  panel    -> the same data as a styled popout (see panel.template.html)
"""

import base64
import json
import os
import struct
import subprocess
import sys
import zlib
from datetime import datetime, timezone
from urllib.parse import quote

ROOT = os.path.dirname(os.path.abspath(__file__))
# The data layer is shared with the Omarchy build and lives at the repo root,
# one level up from this platform directory. See omarchy/hyc.hae-pulse/collector.py,
# which reaches the same file through an in-repo relative symlink.
COLLECTOR = os.path.normpath(os.path.join(ROOT, os.pardir, "collector.py"))
CACHE = os.path.join(ROOT, "cache.json")
ENV_FILE = os.path.join(ROOT, ".env")
TEMPLATE = os.path.join(ROOT, "panel.template.html")
PANEL = os.path.join(ROOT, "panel.html")

# Verdict palette. SwiftBar takes "light,dark" pairs; the Omarchy originals
# (#8FF740 / #d7a55b / theme urgent) are dark-appearance hues, so light mode
# gets a darker sibling to stay legible on the default menu bar.
C_READY = "#3B6D11,#8FF740"
C_WATCH = "#854F0B,#d7a55b"
C_REST = "#A32D2D,#FF5C57"
C_DIM = "#6E6E73,#9A9A9F"
C_FG = "#1D1D1F,#E8E8EA"

VCOLOR = {"ready": C_READY, "watch": C_WATCH, "rest": C_REST}
VLABEL = {"ready": "READY", "watch": "EASE OFF", "rest": "RECOVERY"}

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
    text = str(text)
    return text + " " * max(0, width - dwidth(text))


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
        return "updated just now"
    if secs < 3600:
        return "updated %dm ago" % (secs // 60)
    if secs < 86400:
        return "updated %dh ago" % (secs // 3600)
    return "updated %dd ago" % (secs // 86400)


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


# ------------------------------------------------------------ panel output


def write_panel(data):
    """Regenerate panel.html with the snapshot inlined (no fetch in webview)."""
    if not os.path.exists(TEMPLATE):
        return None
    try:
        with open(TEMPLATE) as fh:
            tpl = fh.read()
        payload = json.dumps(data, ensure_ascii=False)
        html = tpl.replace("/*__HAE_DATA__*/null", payload)
        with open(PANEL, "w") as fh:
            fh.write(html)
    except OSError:
        return None
    return PANEL


# ------------------------------------------------------------------ render


def menu(data):
    out = []

    if not data.get("ok"):
        out.append("● | color=%s size=13 font=Menlo" % C_DIM)
        out.append("---")
        out.append("HAE Pulse · offline | color=%s font=Menlo size=13" % C_REST)
        out.append(str(data.get("error", "no data"))[:110] + " | color=%s size=11 font=Menlo" % C_DIM)
        out.append("---")
        panel = write_panel(data)
        if panel:
            out.append("Open panel | href=file://%s webview=true webvieww=440 webviewh=620 font=Menlo size=12"
                       % quote(panel))
        out.append("Retry now | refresh=true font=Menlo size=12")
        return "\n".join(out)

    verdict = data.get("verdict", "ready")
    vcolor = VCOLOR.get(verdict, C_READY)
    vlabel = VLABEL.get(verdict, "READY")
    hrv_today = data.get("hrv_today")
    stale = " ●" if data.get("stale") else ""

    # menubar: HRV number tinted by verdict
    out.append("%s | color=%s size=13 font=Menlo" % (
        round(hrv_today) if hrv_today is not None else "●", vcolor))

    out.append("---")
    out.append("HAE PULSE · %s%s | color=%s font=Menlo size=13" % (vlabel, stale, vcolor))

    delta = data.get("hrv_delta_pct")
    if delta is None:
        sub = "no baseline yet"
    else:
        sub = "%s%.1f%% vs 7d baseline" % ("+" if delta >= 0 else "", delta)
    out.append(sub + " | color=%s font=Menlo size=11" % C_DIM)

    stamp = ago_text(data.get("fetched_at"))
    if data.get("stale"):
        stamp = "stale · %s · %s" % (stamp or "cached", data.get("stale_error", ""))
    if stamp:
        out.append(stamp.strip(" ·") + " | color=%s font=Menlo size=11" % C_DIM)

    # sparkline
    png = sparkline_png(data.get("hrv_series"), data.get("hrv_avg7"), verdict)
    if png:
        out.append("---")
        out.append("HRV · 7 days | image=%s width=156 height=30 font=Menlo size=11" % png)

    # vitals — label / value / baseline, mirroring Main.qml's three columns
    out.append("---")
    hrv_base = data.get("hrv_avg7")
    if hrv_today is not None:
        right = "7d base %s ms" % hrv_base if hrv_base is not None else ""
    else:
        right = "yesterday %s" % (
            "%s ms" % data["hrv_yesterday"] if data.get("hrv_yesterday") is not None else "—")
    out.append("%s%s%s | color=%s font=Menlo size=12" % (
        pad("HRV today", 14), pad("%s ms" % hrv_today if hrv_today is not None else "—", 11),
        pad(right, 18), vcolor))

    rhr_today, rhr_base = data.get("rhr_today"), data.get("rhr_avg7")
    out.append("%s%s%s | color=%s font=Menlo size=12" % (
        pad("Resting HR", 14), pad("%s bpm" % rhr_today if rhr_today is not None else "—", 11),
        pad("7d base %s bpm" % rhr_base if rhr_base is not None else "", 18), C_FG))

    # VO2max 估算值。放在下拉里而不是菜单栏：它按公式是静息心率的单调变换，
    # 和上面那行 Resting HR 高度共线，占菜单栏不划算；但作为一个「心脏能力」的
    # 绝对数字量级，看趋势时有意义。标 est 以区别于 Apple 的实测值。
    vo = data.get("vo2max")
    if vo:
        right = "7d base %s" % vo["avg7"] if vo.get("avg7") is not None else ""
        if vo.get("hrmax_ref") is not None:
            right = (right + " · " if right else "") + "HRmax %s" % vo["hrmax_ref"]
        out.append("%s%s%s | color=%s font=Menlo size=12" % (
            pad("VO2max est", 14),
            pad("%s ml/kg" % vo["est"] if vo.get("est") is not None else "—", 11),
            pad(right, 18), C_FG))

    sleep = data.get("sleep")
    if sleep:
        deep = "deep %s" % fmt_hours(sleep.get("deep_hr"))
        if sleep.get("deep_pct") is not None:
            deep += " · %d%%" % sleep["deep_pct"]
        out.append("%s%s%s | color=%s font=Menlo size=12" % (
            pad("Sleep", 14), pad(fmt_hours(sleep.get("total_hr")), 11), pad(deep, 18), C_FG))

    weight = data.get("weight")
    if weight:
        right = "7d avg %s kg" % weight["avg7"] if weight.get("avg7") is not None else ""
        out.append("%s%s%s | color=%s font=Menlo size=12" % (
            pad("Weight", 14), pad("%s kg" % weight["kg"], 11), pad(right, 18), C_FG))

    out.append("%s%s%s | color=%s font=Menlo size=12" % (
        pad("Exercise", 14),
        pad("%s / %s min" % (data.get("exercise_min_today", 0), data.get("exercise_goal", 30)), 11),
        pad("%s kcal · %s steps" % (data.get("kcal_today", 0), data.get("steps_today", 0)), 18),
        C_FG))

    # training log
    rows = data.get("workouts_7d") or []
    out.append("---")
    out.append("TRAINING · 7 DAYS | color=%s font=Menlo size=11" % C_DIM)
    if not rows:
        out.append("no workouts logged | color=%s font=Menlo size=11" % C_DIM)
    for row in rows:
        day = str(row.get("day", ""))[5:]
        name = pad(str(row.get("name", "—")), 16)
        detail = "%s · %s kcal · %s" % (
            row.get("min", 0), row.get("kcal", 0),
            "%s/%s bpm" % (round(row["avg_hr"]) if row.get("avg_hr") else "—",
                           round(row["max_hr"]) if row.get("max_hr") else "—"))
        out.append("%s %s%s | color=%s font=Menlo size=11" % (
            day, name, detail, C_FG))

    # actions
    panel = write_panel(data)
    out.append("---")
    if panel:
        out.append("Open panel | href=file://%s webview=true webvieww=440 webviewh=620 font=Menlo size=12"
                   % quote(panel))
    out.append("Refresh now | refresh=true font=Menlo size=12")
    out.append("Open HAE dashboard | href=%s font=Menlo size=12" % DASHBOARD)

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
