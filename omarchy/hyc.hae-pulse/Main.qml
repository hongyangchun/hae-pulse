import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "hyc.hae-pulse"
  ipcTarget: "hyc.hae-pulse"

  // ---- state ---------------------------------------------------------------
  property var snap: null            // collector JSON
  property bool loading: false
  property bool failed: false
  property string failMsg: ""
  property real updatedAt: 0         // Date.now() of last successful sync
  property int updatedTick: 0        // bumped while open to re-render "Xm ago"

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color barForeground: bar ? bar.barForeground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.4)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Recovery colors: rest reuses the theme's urgent color so it follows the
  // active Omarchy theme; ready/watch keep fixed hues (Color.qml has no
  // semantic green/amber tokens).
  readonly property color cReady: "#8FF740"
  readonly property color cWatch: "#d7a55b"
  readonly property color cRest: Color.urgent

  readonly property color verdictColor: {
    if (!snap || !snap.ok) return dim
    if (snap.verdict === "ready") return cReady
    if (snap.verdict === "watch") return cWatch
    return cRest
  }
  readonly property string verdictLabel: {
    if (!snap || !snap.ok) return "OFFLINE"
    if (loading) return "SYNCING"
    if (snap.verdict === "ready") return "READY"
    if (snap.verdict === "watch") return "EASE OFF"
    return "RECOVERY"
  }

  function fmtHours(h) {
    var hh = Math.floor(h)
    var mm = Math.round((h - hh) * 60)
    if (mm === 60) { hh += 1; mm = 0 }
    return hh + "h" + (mm < 10 ? "0" : "") + mm + "m"
  }

  function agoText() {
    if (!root.updatedAt) return ""
    var s = Math.max(0, Math.floor((Date.now() - root.updatedAt) / 1000))
    if (s < 60) return "updated just now"
    if (s < 3600) return "updated " + Math.floor(s / 60) + "m ago"
    return "updated " + Math.floor(s / 3600) + "h ago"
  }

  // ---- data refresh ---------------------------------------------------------
  function refresh() {
    if (loading) return
    loading = true
    proc.command = [pluginDir + "/collector.py"]
    proc.running = true
  }

  readonly property string pluginDir: String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "")

  Timer {
    interval: 10 * 60 * 1000            // 10 min
    running: true
    repeat: true
    triggeredOnStart: false
    onTriggered: root.refresh()
  }

  Timer {
    interval: 4000                       // retry backoff after failure
    running: root.failed
    repeat: false
    onTriggered: { root.failed = false; root.refresh() }
  }

  Timer {
    interval: 30000                      // keep "updated Xm ago" fresh while open
    running: root.opened
    repeat: true
    onTriggered: root.updatedTick++
  }

  // Panel root exposes `opened`; KeyboardPanel child only has `open`.
  onOpenedChanged: if (opened) root.refresh()
  Component.onCompleted: refresh()

  Process {
    id: proc
    stdout: StdioCollector {
      onStreamFinished: {
        root.loading = false
        try {
          var j = JSON.parse(this.text)
          if (j.ok) {
            root.snap = j
            root.failed = false
            root.updatedAt = Date.now()
            root.updatedTick++
          } else { root.failed = true; root.failMsg = j.error || "unknown" }
        } catch (e) {
          root.failed = true; root.failMsg = String(e).slice(0, 80)
        }
      }
    }
    onExited: function(code) {
      root.loading = false
      if (code !== 0) { root.failed = true; root.failMsg = "collector exit " + code }
    }
  }

  // ---- bar widget -------------------------------------------------------------
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // HRV number tinted by recovery verdict; falls back to the bar's own
    // foreground while offline.
    foreground: root.snap && root.snap.ok ? root.verdictColor : root.barForeground
    text: {
      if (!root.snap || !root.snap.ok) return "●"
      var h = root.snap.hrv_today
      return h != null ? String(Math.round(h)) : "●"
    }
    tooltipText: {
      if (root.loading && !root.snap) return "HAE Pulse · syncing…"
      if (!root.snap || !root.snap.ok) return "HAE Pulse · " + (root.failMsg || "no data")
      var s = root.snap
      var lines = []
      if (s.hrv_today != null)
        lines.push("HRV " + s.hrv_today + " ms (" + (s.hrv_delta_pct >= 0 ? "+" : "") + s.hrv_delta_pct + "% vs base) · " + root.verdictLabel)
      else
        lines.push("HRV awaiting sync · yesterday " + (s.hrv_yesterday != null ? s.hrv_yesterday + " ms" : "—"))
      lines.push("Exercise " + s.exercise_min_today + "/" + s.exercise_goal + " min · " + s.kcal_today + " kcal · " + s.steps_today + " steps")
      if (s.sleep)
        lines.push("Sleep " + root.fmtHours(s.sleep.total_hr) + " · deep " + (s.sleep.deep_pct != null ? s.sleep.deep_pct + "%" : root.fmtHours(s.sleep.deep_hr)))
      if (s.weight)
        lines.push("Weight " + s.weight.kg + " kg" + (s.weight.avg7 != null ? " · 7d avg " + s.weight.avg7 + " kg" : ""))
      if (s.vo2max)
        lines.push("VO2max " + s.vo2max.est + " ml/kg (est)" + (s.vo2max.avg7 != null ? " · 7d base " + s.vo2max.avg7 : ""))
      if (s.workouts_7d && s.workouts_7d.length) {
        var w = s.workouts_7d[0]
        lines.push("Last: " + w.day.slice(5) + " " + w.name + " " + w.min + "min " + w.kcal + "kcal")
      }
      return lines.join("\n")
    }
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.RightButton) root.refresh()
      else root.toggle()
    }
  }

  // ---- popout panel -----------------------------------------------------------
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(640))

    Column {
      id: column
      width: parent.width
      spacing: Style.space(12)

      PanelHero {
        width: parent.width
        title: "HAE PULSE"
        detail: root.verdictLabel
        meta: {
          if (!root.snap || !root.snap.ok) return "waiting for data"
          if (root.snap.hrv_delta_pct == null) return "no baseline yet"
          var d = root.snap.hrv_delta_pct
          return (d >= 0 ? "+" : "") + d + "% vs 7d baseline"
        }
        foreground: root.foreground
        fontFamily: root.fontFamily
        iconComponent: Component {
          Text {
            text: "♥"
            color: root.verdictColor
            font.family: root.fontFamily
            font.pixelSize: Style.font.display
          }
        }
      }

      // HRV 7-day trend: today is the last bar (verdict-colored), dashed line
      // is the 7-day baseline.
      Canvas {
        id: spark
        width: parent.width
        height: Style.space(64)
        visible: root.snap && root.snap.ok && root.snap.hrv_series && root.snap.hrv_series.length > 1
        onPaint: {
          var ctx = getContext("2d")
          ctx.clearRect(0, 0, width, height)
          var s = root.snap.hrv_series
          var vals = []
          for (var i = 0; i < s.length; i++)
            if (s[i].value != null) vals.push(s[i].value)
          if (vals.length < 2) return
          var lo = Math.min.apply(null, vals)
          var hi = Math.max.apply(null, vals)
          if (hi - lo < 1) hi = lo + 1
          var pad = 6
          var slot = width / s.length
          var bw = Math.min(20, slot * 0.45)
          function y(v) { return height - (pad + (v - lo) / (hi - lo) * (height - 2 * pad)) }
          if (root.snap.hrv_avg7) {
            ctx.globalAlpha = 0.45
            ctx.strokeStyle = String(root.dim)
            ctx.setLineDash([3, 3])
            ctx.beginPath()
            ctx.moveTo(0, y(root.snap.hrv_avg7))
            ctx.lineTo(width, y(root.snap.hrv_avg7))
            ctx.stroke()
            ctx.setLineDash([])
            ctx.globalAlpha = 1
          }
          for (var j = 0; j < s.length; j++) {
            var v = s[j].value
            if (v == null) continue
            var isToday = j === s.length - 1
            ctx.fillStyle = String(isToday ? root.verdictColor : root.dim)
            ctx.globalAlpha = isToday ? 1 : 0.55
            ctx.fillRect(j * slot + (slot - bw) / 2, y(v), bw, height - y(v))
          }
          ctx.globalAlpha = 1
        }
        Connections {
          target: root
          function onSnapChanged() { spark.requestPaint() }
        }
      }

      // vitals rows
      Repeater {
        model: {
          if (!root.snap || !root.snap.ok) return []
          var s = root.snap
          var rows = []
          rows.push({
            label: "HRV today",
            value: s.hrv_today != null ? s.hrv_today + " ms" : "—",
            base: s.hrv_today != null
                    ? (s.hrv_avg7 != null ? "7d base " + s.hrv_avg7 + " ms" : "")
                    : ("yesterday " + (s.hrv_yesterday != null ? s.hrv_yesterday + " ms" : "—")),
            tint: root.verdictColor
          })
          rows.push({
            label: "Resting HR",
            value: s.rhr_today != null ? s.rhr_today + " bpm" : "—",
            base: s.rhr_avg7 != null ? "7d base " + s.rhr_avg7 + " bpm" : "",
            tint: root.foreground
          })
          if (s.sleep)
            rows.push({
              label: "Sleep",
              value: root.fmtHours(s.sleep.total_hr),
              base: "deep " + root.fmtHours(s.sleep.deep_hr) + (s.sleep.deep_pct != null ? " · " + s.sleep.deep_pct + "%" : ""),
              tint: root.foreground
            })
          if (s.weight)
            rows.push({
              label: "Weight",
              value: s.weight.kg + " kg",
              base: (s.weight.avg7 != null ? "7d avg " + s.weight.avg7 + " kg" : "") +
                    (s.weight.day && s.fetched_at && s.weight.day !== s.fetched_at.slice(0, 10) ? " · " + s.weight.day.slice(5) : ""),
              tint: root.foreground
            })
          // VO2max is an estimate (Uth formula, from resting HR) — Apple only
          // measures Cardio Fitness during outdoor walk/run, which this account
          // never logs. Hence the "est" suffix.
          if (s.vo2max)
            rows.push({
              label: "VO2max est",
              value: s.vo2max.est != null ? s.vo2max.est + " ml/kg" : "—",
              base: (s.vo2max.avg7 != null ? "7d base " + s.vo2max.avg7 : "") +
                    (s.vo2max.hrmax_ref != null ? (s.vo2max.avg7 != null ? " · " : "") + "HRmax " + s.vo2max.hrmax_ref : ""),
              tint: root.foreground
            })
          rows.push({
            label: "Exercise",
            value: s.exercise_min_today + " / " + s.exercise_goal + " min",
            base: s.kcal_today + " kcal · " + s.steps_today + " steps",
            tint: root.foreground
          })
          return rows
        }
        delegate: Row {
          width: parent.width
          spacing: Style.space(8)
          Text { width: Style.space(106); text: modelData.label; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.body; elide: Text.ElideRight }
          Text { width: Style.space(112); text: modelData.value; color: modelData.tint; font.family: root.fontFamily; font.pixelSize: Style.font.body; font.bold: true; elide: Text.ElideRight }
          Text { width: parent.width - Style.space(234); text: modelData.base; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight }
        }
      }

      PanelSeparator { width: parent.width; foreground: root.foreground }

      PanelSectionHeader {
        width: parent.width
        text: "TRAINING · 7 DAYS"
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      Repeater {
        model: (root.snap && root.snap.ok && root.snap.workouts_7d) ? root.snap.workouts_7d : []
        delegate: Row {
          width: parent.width
          spacing: Style.space(8)
          // fixed columns + 4 gaps; name gets whatever is left (elided)
          readonly property real fixedCells: Style.space(46 + 52 + 66 + 78) + 4 * spacing
          Text { width: Style.space(46); text: modelData.day.slice(5); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: parent.width - parent.fixedCells; text: modelData.name; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: Style.space(52); text: modelData.min + "min"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: Style.space(66); text: modelData.kcal + "kcal"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: Style.space(78); text: Math.round(modelData.avg_hr) + "/" + Math.round(modelData.max_hr); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight }
        }
      }

      Text {
        width: parent.width
        visible: root.failed || root.updatedLabel !== ""
        text: root.failed
                ? ("Sync failed: " + root.failMsg + " · retrying…")
                : (root.loading ? root.updatedLabel + " · syncing…" : root.updatedLabel)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
  }

  // re-evaluated by updatedTick so the footer age stays honest
  readonly property string updatedLabel: {
    root.updatedTick
    return root.agoText()
  }
}
