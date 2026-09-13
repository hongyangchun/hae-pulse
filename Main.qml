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

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Recovery colors (theme-tinted fallbacks)
  // "ready" green; no semantic color token exists in Color.qml
  readonly property color cReady: "#8FF740"
  readonly property color cWatch: "#d7a55b"   // amber
  readonly property color cRest:  "#EC081F"   // red

  readonly property color verdictColor: {
    if (!snap || !snap.ok) return dim
    if (snap.verdict === "ready") return cReady
    if (snap.verdict === "watch") return cWatch
    return cRest
  }
  readonly property string verdictLabel: {
    if (!snap || !snap.ok) return "OFFLINE"
    if (snap.verdict === "ready") return "READY"
    if (snap.verdict === "watch") return "EASE OFF"
    return "RECOVERY"
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

  Component.onCompleted: refresh()

  // Panel root exposes `opened`; KeyboardPanel child only has `open`.
  onOpenedChanged: if (opened) root.refresh()

  Process {
    id: proc
    stdout: StdioCollector {
      onStreamFinished: {
        root.loading = false
        try {
          var j = JSON.parse(this.text)
          if (j.ok) { root.snap = j; root.failed = false }
          else { root.failed = true; root.failMsg = j.error || "unknown" }
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
    text: {
      if (!root.snap || !root.snap.ok) return "●"
      var h = root.snap.hrv_today
      return h != null ? String(Math.round(h)) : "●"
    }
    tooltipText: {
      if (root.loading) return "HAE Pulse · syncing…"
      if (!root.snap || !root.snap.ok) return "HAE Pulse · " + (root.failMsg || "no data")
      var s = root.snap
      var line = "HRV " + s.hrv_today + " (" + (s.hrv_delta_pct >= 0 ? "+" : "") + s.hrv_delta_pct + "% vs base) · " + root.verdictLabel
      line += "\nExercise " + s.exercise_min_today + "/" + s.exercise_goal + " min · " + s.kcal_today + " kcal · " + s.steps_today + " steps"
      if (s.workouts_7d && s.workouts_7d.length) {
        var w = s.workouts_7d[0]
        line += "\nLast: " + w.day.slice(5) + " " + w.name + " " + w.min + "min " + w.kcal + "kcal"
      }
      return line
    }
    // Dot colors with the verdict; text stays theme foreground
    onPressed: function(mouseButton) { root.toggle() }
  }

  // tiny colored verdict dot in the slot's top-right corner
  Rectangle {
    width: 6; height: 6; radius: 3
    color: root.verdictColor
    anchors.top: parent.top
    anchors.topMargin: 5
    anchors.right: parent.right
    anchors.rightMargin: 3
    visible: root.snap && root.snap.ok
    z: 10
  }

  // ---- popout panel -----------------------------------------------------------
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    Column {
      id: column
      width: parent.width
      spacing: Style.space(12)

      // header
      Item {
        width: parent.width
        height: Style.space(44)
        Text {
          text: "HAE PULSE"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }
        Text {
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          text: root.verdictLabel
          color: root.verdictColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }

      // HRV / RHR rows
      Repeater {
        model: {
          if (!root.snap || !root.snap.ok) return []
          var s = root.snap
          return [
            {label: "HRV today", value: s.hrv_today != null ? s.hrv_today + " ms" : "—",
             base: s.hrv_avg7 != null ? "7d base " + s.hrv_avg7 + " ms" : "", tint: root.verdictColor},
            {label: "Resting HR", value: s.rhr_today != null ? s.rhr_today + " bpm" : "—",
             base: s.rhr_avg7 != null ? "7d base " + s.rhr_avg7 + " bpm" : "", tint: root.foreground},
            {label: "Exercise", value: s.exercise_min_today + " / " + s.exercise_goal + " min",
             base: s.kcal_today + " kcal · " + s.steps_today + " steps", tint: root.foreground}
          ]
        }
        delegate: Row {
          width: parent.width
          spacing: Style.space(8)
          // 3 cells + 2 gaps must equal row width
          readonly property real cell: (width - 2 * spacing) / 3
          Text { width: parent.cell; text: modelData.label; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.body; elide: Text.ElideRight }
          Text { width: parent.cell; text: modelData.value; color: modelData.tint; font.family: root.fontFamily; font.pixelSize: Style.font.body; font.bold: true; elide: Text.ElideRight }
          Text { width: parent.cell; text: modelData.base; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight }
        }
      }

      // divider
      Rectangle { width: parent.width; height: 1; color: Qt.rgba(1,1,1,0.08) }

      // 7-day workouts
      Text { text: "TRAINING · 7 DAYS"; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption }

      Repeater {
        model: (root.snap && root.snap.ok && root.snap.workouts_7d) ? root.snap.workouts_7d : []
        delegate: Row {
          width: parent.width
          spacing: Style.space(8)
          // 4 cells + 3 gaps must equal row width
          readonly property real avail: width - 3 * spacing
          Text { width: parent.avail * 0.14; text: modelData.day.slice(5); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: parent.avail * 0.40; text: modelData.name; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: parent.avail * 0.20; text: modelData.min + "min"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: parent.avail * 0.26; text: modelData.kcal + "kcal · " + modelData.avg_hr + "/" + modelData.max_hr; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight }
        }
      }

      Text {
        visible: !root.snap || !root.snap.ok
        width: parent.width
        text: root.failed ? ("Sync failed: " + root.failMsg + " · retrying…") : "Loading…"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
  }
}
