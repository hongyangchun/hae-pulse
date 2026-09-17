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
  // 三端统一中文，且与 macOS 下拉、仪表盘状态条用同一套词。
  // verdict 的取值仍是 ready/watch/rest —— 那是数据标识，不翻译。
  readonly property string verdictLabel: {
    if (!snap || !snap.ok) return "离线"
    if (loading) return "同步中"
    if (snap.verdict === "ready") return "可以练"
    if (snap.verdict === "watch") return "悠着点"
    return "该休息"
  }

  function fmtHours(h) {
    var hh = Math.floor(h)
    var mm = Math.round((h - hh) * 60)
    if (mm === 60) { hh += 1; mm = 0 }
    return hh + "h" + (mm < 10 ? "0" : "") + mm + "m"
  }

  // 大数加千分位：5695 步、585 kcal 不加分隔读不出量级。
  // 与 macOS 侧 render.py 的 thousands() 同一行为 —— 之前只有 macOS 加分隔，
  // 同一份数据在两个平台显示的位数格式不同。
  function thousands(n) {
    var v = Math.round(Number(n))
    if (!isFinite(v)) return String(n)
    return String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  }

  // 值不是当天时返回 " · MM-DD"，是当天（或没日期）返回空串。
  // **日结型指标要标日期**：静息心率/睡眠/体重/心肺耐力(估)由整夜数据算出，
  // Apple 清晨才定稿 —— 清晨前最新点是昨天的，清晨后当天的点就出现了，两种都会
  // 遇到，所以只能按日期比，不能写死成「永远标」。规则与 macOS 侧 render.py 的
  // day_suffix() 完全一致（那边同样比 day 与 fetched_at[:10]）。
  function daySuffix(day) {
    if (!day || !root.snap || !root.snap.fetched_at) return ""
    return day === root.snap.fetched_at.slice(0, 10) ? "" : " · " + String(day).slice(5)
  }

  function agoText() {
    if (!root.updatedAt) return ""
    var s = Math.max(0, Math.floor((Date.now() - root.updatedAt) / 1000))
    if (s < 60) return "刚刚更新"
    if (s < 3600) return Math.floor(s / 60) + " 分钟前更新"
    return Math.floor(s / 3600) + " 小时前更新"
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
          } else { root.failed = true; root.failMsg = j.error || "未知错误" }
        } catch (e) {
          root.failed = true; root.failMsg = String(e).slice(0, 80)
        }
      }
    }
    onExited: function(code) {
      root.loading = false
      if (code !== 0) { root.failed = true; root.failMsg = "collector 退出码 " + code }
    }
  }

  // ---- bar widget -------------------------------------------------------------
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // 菜单栏只承载 L1：HRV 数字按恢复状态着色，离线时退回栏自身的前景色。
    foreground: root.snap && root.snap.ok ? root.verdictColor : root.barForeground
    text: {
      if (!root.snap || !root.snap.ok) return "●"
      var h = root.snap.hrv_today
      return h != null ? String(Math.round(h)) : "●"
    }
    tooltipText: {
      if (root.loading && !root.snap) return "HAE 健康 · 同步中…"
      if (!root.snap || !root.snap.ok) return "HAE 健康 · " + (root.failMsg || "无数据")
      var s = root.snap
      var lines = []
      // 悬停提示是第 4 个文案面（栏图标 / tooltip / popout / macOS 下拉）。
      // 行序、口径、日期规则必须与 popout 完全一致，否则同一份数据会有两种读法：
      //   HRV → 静息心率 → 心肺耐力(估) → 睡眠 → 体重 → 锻炼
      // 提示行只放一行一条，所以不带 popout 的三列对齐；但日结型指标的日期后缀
      // 和千分位一个都不能少 —— 那两条是正确性规则，不是排版偏好。
      if (s.hrv_today != null)
        lines.push("HRV " + s.hrv_today + " ms (" + (s.hrv_delta_pct >= 0 ? "+" : "") + s.hrv_delta_pct + "% 对比基准) · " + root.verdictLabel)
      else
        lines.push("HRV 待同步 · 昨日 " + (s.hrv_yesterday != null ? s.hrv_yesterday + " ms" : "—"))
      lines.push("静息心率 " + (s.rhr_today != null ? s.rhr_today + " bpm" : "—") +
                 (s.rhr_avg7 != null ? " · 7 日均 " + s.rhr_avg7 + " bpm" : "") + root.daySuffix(s.rhr_day))
      if (s.vo2max)
        lines.push("心肺耐力(估) " + s.vo2max.est + " ml/kg" +
                   (s.vo2max.avg7 != null ? " · 7 日均 " + s.vo2max.avg7 : "") + root.daySuffix(s.vo2max.day))
      if (s.sleep)
        lines.push("睡眠 " + root.fmtHours(s.sleep.total_hr) + " · 深睡 " +
                   (s.sleep.deep_pct != null ? s.sleep.deep_pct + "%" : root.fmtHours(s.sleep.deep_hr)) +
                   root.daySuffix(s.sleep.day))
      if (s.weight)
        lines.push("体重 " + s.weight.kg + " kg" +
                   (s.weight.avg7 != null ? " · 7 日均 " + s.weight.avg7 + " kg" : "") + root.daySuffix(s.weight.day))
      lines.push("锻炼 " + s.exercise_min_today + "/" + s.exercise_goal + " 分钟" +
                 (s.exercise_sessions_today > 0 ? " · " + s.exercise_sessions_today + " 次" : "") +
                 " · " + root.thousands(s.kcal_today) + " kcal · " + root.thousands(s.steps_today) + " 步")
      if (s.workouts_7d && s.workouts_7d.length) {
        var w = s.workouts_7d[0]
        lines.push("最近：" + w.day.slice(5) + " " + w.name + " " + w.min + " 分钟 " + root.thousands(w.kcal) + " kcal")
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
        title: "HAE 健康"
        detail: root.verdictLabel
        meta: {
          if (!root.snap || !root.snap.ok) return "等待数据"
          if (root.snap.hrv_delta_pct == null) return "暂无基准"
          var d = root.snap.hrv_delta_pct
          return (d >= 0 ? "+" : "") + d + "% 对比 7 日均值"
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
      // 行序与 macOS 下拉三端统一（此前 macOS 把心肺耐力排在睡眠前、这里排在体重后）：
      // HRV → 静息心率 → 心肺耐力(估) → 睡眠 → 体重 → 锻炼
      Repeater {
        model: {
          if (!root.snap || !root.snap.ok) return []
          var s = root.snap
          var rows = []
          rows.push({
            label: "HRV 今日",
            value: s.hrv_today != null ? s.hrv_today + " ms" : "—",
            base: s.hrv_today != null
                    ? (s.hrv_avg7 != null ? "7 日均 " + s.hrv_avg7 + " ms" : "")
                    : ("昨日 " + (s.hrv_yesterday != null ? s.hrv_yesterday + " ms" : "—")),
            tint: root.verdictColor
          })
          rows.push({
            label: "静息心率",
            value: s.rhr_today != null ? s.rhr_today + " bpm" : "—",
            base: (s.rhr_avg7 != null ? "7 日均 " + s.rhr_avg7 + " bpm" : "") + root.daySuffix(s.rhr_day),
            tint: root.foreground
          })
          // 心肺耐力是估算值（Uth 公式，来源是静息心率）：Apple 只在户外步行/跑步时
          // 测 Cardio Fitness，本账号没有这类训练，实测值恒为空。所以标「(估)」。
          // 它也继承了静息心率的滞后（rhr7 窗口要等静息心率），日期通常也是昨天。
          if (s.vo2max)
            rows.push({
              label: "心肺耐力(估)",
              value: s.vo2max.est != null ? s.vo2max.est + " ml/kg" : "—",
              base: (s.vo2max.avg7 != null ? "7 日均 " + s.vo2max.avg7 : "") +
                    (s.vo2max.hrmax_ref != null ? (s.vo2max.avg7 != null ? " · " : "") + "HRmax " + s.vo2max.hrmax_ref : "") +
                    root.daySuffix(s.vo2max.day),
              tint: root.foreground
            })
          if (s.sleep)
            rows.push({
              label: "睡眠",
              value: root.fmtHours(s.sleep.total_hr),
              base: "深睡 " + root.fmtHours(s.sleep.deep_hr) + (s.sleep.deep_pct != null ? " · " + s.sleep.deep_pct + "%" : "") +
                    root.daySuffix(s.sleep.day),
              tint: root.foreground
            })
          if (s.weight)
            rows.push({
              label: "体重",
              value: s.weight.kg + " kg",
              base: (s.weight.avg7 != null ? "7 日均 " + s.weight.avg7 + " kg" : "") + root.daySuffix(s.weight.day),
              tint: root.foreground
            })
          // 锻炼 = 今日已记录的训练时长（来自 workouts，当天就有），不是锻炼环。
          // 锻炼环（apple_exercise_time）是日结型，清晨前当天的值拿不到，用它这一行
          // 会恒为 0。代价：训练时长是锻炼环的子集，不计入非训练的零星活动分钟。
          rows.push({
            label: "锻炼",
            value: s.exercise_min_today + " / " + s.exercise_goal + " 分钟",
            base: (s.exercise_sessions_today > 0 ? s.exercise_sessions_today + " 次 · " : "") +
                  root.thousands(s.kcal_today) + " kcal · " + root.thousands(s.steps_today) + " 步",
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
        text: "训练 · 近 7 天"
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      Text {
        width: parent.width
        visible: !(root.snap && root.snap.ok && root.snap.workouts_7d && root.snap.workouts_7d.length)
        text: "暂无训练记录"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Repeater {
        model: (root.snap && root.snap.ok && root.snap.workouts_7d) ? root.snap.workouts_7d : []
        delegate: Row {
          width: parent.width
          spacing: Style.space(8)
          // fixed columns + 4 gaps; name gets whatever is left (elided)
          readonly property real fixedCells: Style.space(46 + 66 + 66 + 78) + 4 * spacing
          Text { width: Style.space(46); text: modelData.day.slice(5); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: parent.width - parent.fixedCells; text: modelData.name; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: Style.space(66); text: modelData.min + " 分钟"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: Style.space(66); text: root.thousands(modelData.kcal) + " kcal"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
          Text { width: Style.space(78); text: Math.round(modelData.avg_hr) + "/" + Math.round(modelData.max_hr); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight }
        }
      }

      Text {
        width: parent.width
        visible: root.failed || root.updatedLabel !== ""
        text: root.failed
                ? ("同步失败：" + root.failMsg + " · 重试中…")
                : (root.loading ? root.updatedLabel + " · 同步中…" : root.updatedLabel)
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
