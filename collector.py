#!/usr/bin/env python3
"""HAE Pulse collector — fetch health snapshot from Health Auto Export cloud.

Output: single JSON line on stdout
{
  "ok": true,
  "hrv_today": 36.7, "hrv_avg7": 34.1, "hrv_delta_pct": 7.6,
  "rhr_today": 55,   "rhr_avg7": 59.3,
  "exercise_min_today": 4, "exercise_goal": 30,
  "steps_today": 3573,
  "kcal_today": 295.9,
  "workouts_7d": [{"day":"2026-09-05","name":"传统力量训练","min":74,"kcal":428,"avg_hr":110,"max_hr":154}, ...],
  "fetched_at": "2026-09-11T21:40:00+08:00"
}
On any failure: {"ok": false, "error": "..."} (exit 0 — the widget reads JSON).

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


def main():
    out = {"ok": False}

    # --- daily scalar series -------------------------------------------------
    ex = series("apple_exercise_time", str(WEEK_AGO), str(TODAY))
    hrv = series("heart_rate_variability", str(TREND_START), str(TODAY))
    rhr = series("resting_heart_rate", str(TREND_START), str(TODAY))
    steps = series("step_count", str(WEEK_AGO), str(TODAY))
    kcal = series("active_energy", str(WEEK_AGO), str(TODAY), convert="kcal")

    t = str(TODAY)
    hrv_today = hrv.get(t)
    hrv_yesterday = next((v for d, v in sorted(hrv.items(), reverse=True) if d < t), None)
    hrv_base = mean([v for d, v in hrv.items() if d < t][-7:])   # prior 7 days
    rhr_today = rhr.get(t)
    rhr_base = mean([v for d, v in rhr.items() if d < t][-7:])

    out.update({
        "hrv_today": round(hrv_today, 1) if hrv_today is not None else None,
        "hrv_yesterday": round(hrv_yesterday, 1) if hrv_yesterday is not None else None,
        "hrv_avg7": round(hrv_base, 1) if hrv_base else None,
        "hrv_delta_pct": (round((hrv_today - hrv_base) / hrv_base * 100, 1)
                          if hrv_today is not None and hrv_base else None),
        "hrv_series": [{"day": d, "value": round(v, 1)}
                       for d, v in sorted(hrv.items()) if d >= str(WEEK_AGO)],
        "rhr_today": round(rhr_today) if rhr_today is not None else None,
        "rhr_avg7": round(rhr_base, 1) if rhr_base else None,
        "exercise_min_today": round(ex.get(t, 0)),
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
