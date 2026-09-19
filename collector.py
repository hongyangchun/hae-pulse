#!/usr/bin/env python3
"""HAE Pulse collector — fetch health snapshot from Health Auto Export cloud.

Output: single JSON line on stdout
{
  "ok": true,
  "hrv_today": 36.7, "hrv_avg7": 34.1, "hrv_delta_pct": 7.6,
  "rhr_today": 55,   "rhr_avg7": 59.3, "rhr_day": "2026-09-16",
  "vo2max": {"day": "2026-09-16", "est": 47.5, "rhr7": 55.6, "avg7": 47.3, "hrmax_ref": 176},
  "exercise_min_today": 4, "exercise_sessions_today": 1, "exercise_goal": 30,
  "steps_today": 3573,
  "kcal_today": 295.9,
  "workouts_7d": [{"day":"2026-09-05","name":"传统力量训练","min":74,"kcal":428,"avg_hr":110,"max_hr":154}, ...],
  "fetched_at": "2026-09-11T21:40:00+08:00"
}
On any failure: {"ok": false, "error": "..."} (exit 0 — the widget reads JSON).

**指标分两类，取值口径必须区别对待**（详见 latest() 的注释）：
- 实时型（心率/HRV/步数/活动能量/血氧）：当天随时就有值，可以直接取今天。
- **日结型**（静息心率/睡眠/体重/心肺耐力/锻炼环）：由**整夜**的数据算出，当天的点
  要到**清晨**才落库。清晨之前最新点仍是昨天的，清晨之后当天的点就有了 ——
  两种状态都真实存在，所以不能写死「永远取昨天」，也不能只取今天。

正确做法：取**最后一个非空值**，并把它的日期一起返回（`rhr_day`、`sleep.day`、
`weight.day`），由界面决定要不要标出来。只取今天会让这些指标在清晨前恒为空。

Read-only. Key comes from ~/.hermes/.env (HAE_READ_KEY). Never writes to HAE.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
import ssl
from datetime import date, datetime, timedelta, timezone

BASE = "https://hae.qiaclass.com"
UA = "hae-pulse/0.1"
ENV_PATH = os.path.expanduser("~/.hermes/.env")

TODAY = date.today()
WEEK_AGO = TODAY - timedelta(days=6)          # 7-day window incl. today
TREND_START = TODAY - timedelta(days=13)      # baseline window excludes today


def load_key() -> str:
    if os.environ.get("HAE_READ_KEY"):
        return os.environ["HAE_READ_KEY"].strip()
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH):
            line = line.strip()
            if line.startswith("HAE_READ_KEY") and "=" in line:
                return line.split("=", 1)[1].strip()
    raise RuntimeError("HAE_READ_KEY not found")


def get(path: str, params: dict):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "api-key": load_key(),
        "User-Agent": UA,
        "Accept": "application/json",
    })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.loads(r.read().decode())


def series(name: str, start: str, end: str, convert: str | None = None):
    params = {"name": name, "from": start, "to": end}
    if convert:
        params["convert"] = convert
    pts = get("/api/query", params).get("points", [])
    return {p["date"]: p["qty"] for p in pts if p.get("qty") is not None}


def mean(vals):
    return sum(vals) / len(vals) if vals else None


def latest(hist: dict):
    """最后一个非空值 → (日期, 值)；空则 (None, None)。

    **必须能往前找，不能只取今天。** 指标分成两类（用 `/api/metrics` 的
    first_day/last_day 就能分组）：

      实时型 —— 当天随时就有：heart_rate、heart_rate_variability、step_count、
                active_energy、blood_oxygen_saturation …
      日结型 —— 当天清晨才落库：resting_heart_rate、sleep_analysis、
                weight_body_mass、apple_exercise_time、walking_speed …

    日结型由整夜数据算出，Apple 要到清晨才定稿。所以 `hist.get(str(TODAY))`
    在清晨之前恒定是 None，清晨之后就有值了 —— 两种状态都会遇到：
      · 2026-09-16 查 resting_heart_rate：last_day = 09-16，当天无点 → 恒为 —
      · 2026-09-17 查 resting_heart_rate：last_day = 09-17，当天的点已落库 → 58
    仪表盘一直显示正常，正是因为它的 `stat()` 取「最后一个非空值」；插件曾经
    只取今天，于是清晨前静息心率恒为 `—`、锻炼恒为 0。取到哪一天要一起返回，
    界面按日期决定要不要标 —— 否则昨天的数看着像今天的。
    """
    for d in sorted(hist, reverse=True):
        if hist[d] is not None:
            return d, hist[d]
    return None, None


def main():
    out = {"ok": False}

    # --- daily scalar series -------------------------------------------------
    # apple_exercise_time 不再取：它是日结型，当天的值拿不到，用它做「今日锻炼」
    # 会恒为 0。今日训练时长改由 workouts 现算（见下方 workouts 段）。
    hrv = series("heart_rate_variability", str(TREND_START), str(TODAY))
    rhr = series("resting_heart_rate", str(TREND_START), str(TODAY))
    steps = series("step_count", str(WEEK_AGO), str(TODAY))
    kcal = series("active_energy", str(WEEK_AGO), str(TODAY), convert="kcal")

    t = str(TODAY)
    hrv_today = hrv.get(t)
    hrv_yesterday = next((v for d, v in sorted(hrv.items(), reverse=True) if d < t), None)
    hrv_base = mean([v for d, v in hrv.items() if d < t][-7:])   # prior 7 days

    # 静息心率是日结型：清晨前当天的点还没有，所以取最后一个非空值，
    # 并把实际日期一起带出去（界面据此决定标不标 · MM-DD）。
    # 基准取 rhr_day 之**前**的 7 天（不含当前值），与仪表盘 stat() 的
    # `mean(vs.slice(-8,-1))` 同一口径 —— 两处实现、一处定义。
    rhr_day, rhr_today = latest(rhr)
    rhr_base = mean([v for d, v in sorted(rhr.items()) if rhr_day and d < rhr_day][-7:])

    out.update({
        "hrv_today": round(hrv_today, 1) if hrv_today is not None else None,
        "hrv_yesterday": round(hrv_yesterday, 1) if hrv_yesterday is not None else None,
        "hrv_avg7": round(hrv_base, 1) if hrv_base else None,
        "hrv_delta_pct": (round((hrv_today - hrv_base) / hrv_base * 100, 1)
                          if hrv_today is not None and hrv_base else None),
        "hrv_series": [{"day": d, "value": round(v, 1)}
                       for d, v in sorted(hrv.items()) if d >= str(WEEK_AGO)],
        "rhr_today": round(rhr_today) if rhr_today is not None else None,
        "rhr_day": rhr_day,
        "rhr_avg7": round(rhr_base, 1) if rhr_base else None,
        "exercise_goal": 30,
        "steps_today": round(steps.get(t, 0)),
        "kcal_today": round(kcal.get(t, 0), 1),
    })

    # --- sleep (points carry total/deep hours; date = wake morning) ----------
    try:
        pts = get("/api/query", {"name": "sleep_analysis",
                                 "from": str(WEEK_AGO), "to": str(TODAY)}).get("points", [])
        nights = [p for p in pts if (p.get("total", p.get("qty", 0)) or 0) >= 1.0]
        nights.sort(key=lambda p: p["date"])
        if nights:
            n = nights[-1]
            total, deep = n.get("total", 0) or 0, n.get("deep", 0) or 0
            out["sleep"] = {
                "day": n["date"],
                "total_hr": round(total, 1),
                "deep_hr": round(deep, 1),
                "deep_pct": round(deep / total * 100) if total else None,
            }
    except Exception:
        pass

    # --- weight ---------------------------------------------------------------
    try:
        wt = series("weight_body_mass", str(TREND_START), str(TODAY))
        if wt:
            wd, wv = sorted(wt.items())[-1]
            prior = [v for d, v in sorted(wt.items()) if d < wd][-7:]
            base = mean(prior)
            out["weight"] = {
                "day": wd,
                "kg": round(wv, 1),
                "avg7": round(base, 1) if base else None,
            }
    except Exception:
        pass

    # --- body fat percentage（华为秤 BIA，系统性高估约 5 点）---
    try:
        bf = series("body_fat_percentage", str(TREND_START), str(TODAY))
        if bf and "weight" in out:
            bd, bv = sorted(bf.items())[-1]
            out["weight"]["bf"] = round(bv, 1)
            out["weight"]["bf_est"] = round(bv - 5.5, 1)
            out["weight"]["bf_day"] = bd
    except Exception:
        pass

    # --- VO2max estimate ------------------------------------------------------
    # Apple Watch only estimates Cardio Fitness during outdoor walk/run with GPS,
    # so vo2_max is permanently empty for this account (verified: zero rows in
    # the API). Read the server-side fallback instead — Uth formula,
    # 15 x HRmax / HRrest, computed in hae-api's worker.js so the dashboard and
    # this plugin share one implementation. Estimate only (~±10-15% per person):
    # trust the trend, not the absolute number.
    try:
        est = get("/api/query", {"name": "vo2_max_est",
                                 "from": str(TREND_START), "to": str(TODAY)})
        byday = {p["date"]: p for p in est.get("points", []) if p.get("qty") is not None}
        if byday:
            day = str(TODAY) if str(TODAY) in byday else max(byday)
            cur = byday[day]
            prior = [byday[d]["qty"] for d in sorted(byday) if d < day][-7:]
            out["vo2max"] = {
                "day": day,
                "est": round(cur["qty"], 1),
                "rhr7": cur.get("rhr7"),
                "avg7": round(mean(prior), 1) if prior else None,
                "hrmax_ref": est.get("hrmax_ref"),
            }
    except Exception:
        pass

    # --- workouts ------------------------------------------------------------
    workouts = get("/api/workouts", {"from": str(WEEK_AGO), "to": str(TODAY)})
    rows = []
    for w in workouts if isinstance(workouts, list) else workouts.get("workouts", []):
        rows.append({
            "day": w.get("day"),
            "name": w.get("name"),
            "min": round(w.get("duration_min") or 0),
            "kcal": round(w.get("kcal") or 0),
            "avg_hr": w.get("avg_hr"),
            "max_hr": w.get("max_hr"),
        })
    rows.sort(key=lambda r: r["day"], reverse=True)
    out["workouts_7d"] = rows

    # 今日训练时长 = 今天已记录的训练时长之和。
    # 为什么不用 apple_exercise_time（锻炼环）：它是日结型指标，清晨之前当天的值
    # 拿不到，`ex.get(t, 0)` 会恒为 0，而 workouts 当天就有记录 —— 只有它能让
    # 「N / 30 分钟」这一行在当天真正动起来。代价是训练时长是锻炼环的子集，
    # 不计入非训练的零星活动分钟，所以它标的是「训练」而不是「活动」。
    today_rows = [r for r in rows if r["day"] == t]
    out["exercise_min_today"] = round(sum(r["min"] for r in today_rows))
    out["exercise_sessions_today"] = len(today_rows)

    # --- recovery verdict -----------------------------------------------------
    # ready  = HRV at/above baseline          -> green-ish, go train
    # watch  = HRV 5-15% below baseline       -> amber, keep it easy
    # rest   = HRV >15% below baseline        -> red-ish, recovery day
    delta = out.get("hrv_delta_pct")
    out["verdict"] = ("ready" if delta is None or delta >= -5
                      else "watch" if delta >= -15 else "rest")

    out["ok"] = True
    out["fetched_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:200]}, ensure_ascii=False))
