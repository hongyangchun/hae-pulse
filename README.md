# HAE Pulse

A health-recovery bar widget plugin for [Omarchy](https://omarchy.org): today's
HRV vs your 7-day baseline, a recovery verdict color dot, and a click-to-open
panel with resting HR, exercise ring, and a 7-day training log.

Read-only feed from the [Health Auto Export](https://healthyapis.com) (HAE)
cloud API. The plugin never writes anything back.

## Bar widget

- HRV number tinted by recovery verdict: **ready** (green, at/above
  baseline), **ease off** (amber, watch), **recovery** (theme urgent, rest)
- Verdict is computed by comparing today's HRV against the previous 7-day
  baseline
- Left click opens the panel; right click forces an immediate refresh
- Tooltip shows HRV delta, exercise minutes, calories, steps, sleep, weight,
  and the last workout
- Data refreshes every 10 minutes; the collector is a short-lived process, so
  there is no resident background load

## Panel

- HRV 7-day trend sparkline (today's bar verdict-colored, dashed baseline)
- HRV / resting HR today vs 7-day baseline (falls back to yesterday's HRV
  until today's value syncs)
- Sleep (total + deep) and weight (vs 7-day average)
- Exercise minutes, calories, steps
- 7-day workout table (name, duration, kcal, avg/max HR)
- Footer shows data freshness ("updated 5m ago")

## Requirements

- Python 3 (stdlib only, no pip dependencies)
- A Health Auto Export cloud API key with **read** access, provided via the
  `HAE_READ_KEY` environment variable or `~/.hermes/.env`:

  ```
  HAE_READ_KEY=your-key-here
  ```

## Install

```sh
omarchy plugin add hongyangchun/omarchy-hae-pulse
```

or clone it into your plugins directory:

```sh
git clone https://github.com/hongyangchun/omarchy-hae-pulse \
  ~/.config/omarchy/plugins/hyc.hae-pulse
omarchy plugin enable hyc.hae-pulse
```

Then add **HAE Pulse** to your bar layout (plugin manager or `shell.json`,
default section: right) and restart the shell.

## Files

| File           | Purpose                                        |
| -------------- | ---------------------------------------------- |
| `Main.qml`     | Bar widget + popout panel (Quickshell/QML)     |
| `collector.py` | HAE cloud fetcher, returns a JSON snapshot     |
| `manifest.json`| Omarchy plugin manifest (bar-widget kind)      |

## License

MIT
