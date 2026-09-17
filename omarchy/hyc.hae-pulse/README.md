# HAE Pulse

A health-recovery bar widget plugin for [Omarchy](https://omarchy.org): today's
HRV vs your 7-day baseline, a recovery verdict color dot, and a click-to-open
panel with resting HR, today's training minutes, and a 7-day training log.

Read-only feed from the [Health Auto Export](https://healthyapis.com) (HAE)
cloud API. The plugin never writes anything back.

This directory is the Omarchy half of the [hae-pulse](../../README.md) repo. The
macOS half renders the same snapshot as a menu bar item via SwiftBar, and both
share the single `collector.py` at the repo root.

## Bar widget

- HRV number tinted by recovery verdict. The verdict values stay English
  (`ready` / `watch` / `rest` — they are data identifiers), but the UI copy is
  Chinese: **可以练** (green, at/above baseline), **悠着点** (amber, watch),
  **该休息** (theme urgent, rest)
- Verdict is computed by comparing today's HRV against the previous 7-day
  baseline
- Left click opens the panel; right click forces an immediate refresh
- Tooltip carries the same six metrics in the same order as the panel
  (`HRV → 静息心率 → 心肺耐力(估) → 睡眠 → 体重 → 锻炼`), one line each, plus the
  last workout. Date suffixes and thousands separators are applied here too —
  those are correctness rules, not panel-only decoration
- Data refreshes every 10 minutes; the collector is a short-lived process, so
  there is no resident background load

## Panel

Row order is shared with the macOS dropdown and the web dashboard:
`HRV → 静息心率 → 心肺耐力(估) → 睡眠 → 体重 → 锻炼`.

- HRV 7-day trend sparkline (today's bar verdict-colored, dashed baseline)
- HRV today / resting HR vs 7-day baseline (falls back to yesterday's HRV
  until today's value syncs)
- **Day-finalized metrics are dated when they are not today's.** Resting HR,
  sleep, weight and the VO2max estimate are computed from a whole night's data,
  so Apple only finalizes the day's point in the **morning**. Before that the
  latest point is still yesterday's and the panel appends its date (` · 09-16`);
  once the same-day point lands, no date is shown. Without the suffix,
  yesterday's reading would be mistaken for today's.
- Sleep (total + deep) and weight (vs 7-day average)
- Today's training minutes / goal, plus session count, calories and steps.
  Sourced from `/api/workouts`, **not** Apple's exercise ring — the ring is
  day-finalized too and reads 0 until the morning finalization.
- 7-day workout table (name, duration, kcal, avg/max HR)
- Footer shows data freshness ("X 分钟前更新")

## Requirements

- **Python 3.10+** (stdlib only, no pip dependencies). `collector.py` uses the
  `str | None` annotation syntax, so 3.9 fails at runtime — and note that
  `py_compile` does *not* catch it, because annotations are evaluated when the
  function is defined.
- A Health Auto Export cloud API key with **read** access, provided via the
  `HAE_READ_KEY` environment variable or `~/.hermes/.env`:

  ```
  HAE_READ_KEY=your-key-here
  ```

## Install

Clone the whole repo, then run the installer — the plugin directory is a
subdirectory, so cloning it directly into `plugins/` no longer works:

```sh
git clone https://github.com/hongyangchun/hae-pulse.git
cd hae-pulse
./install.sh omarchy
omarchy plugin enable hyc.hae-pulse
```

`install.sh` symlinks `omarchy/hyc.hae-pulse` into
`~/.config/omarchy/plugins/hyc.hae-pulse`, so the plugin always runs the
checked-out sources. Then add **HAE Pulse** to your bar layout (plugin manager
or `shell.json`, default section: right) and restart the shell.

## Files

| File           | Purpose                                        |
| -------------- | ---------------------------------------------- |
| `Main.qml`     | Bar widget + popout panel (Quickshell/QML)     |
| `collector.py` | Symlink to `../../collector.py` (shared with the macOS build) |
| `manifest.json`| Omarchy plugin manifest (bar-widget kind)      |

The symlink is not a stylistic choice: `Main.qml` invokes
`pluginDir + "/collector.py"`, so the file has to exist *inside* the plugin
directory even though the canonical copy lives at the repo root.

## License

MIT
