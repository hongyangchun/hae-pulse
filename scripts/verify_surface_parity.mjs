/* 文案面一致性检查 —— 同一个量在几处出现，就有几处会各自漂移。
 *
 * 背景：Omarchy 一个 Main.qml 里其实有 4 份文案面（bar 数字 / hover tooltip /
 * popout 行 / macOS SwiftBar 下拉）。删掉一层 UI 不等于只剩一份文案。
 * 本次复查就发现 tooltip 漏了静息心率（用户报的正是「静息心率不显示」）、
 * 行序与 popout 不同、且没走日期后缀与千分位。
 *
 * 这个脚本不复制渲染逻辑（复制就会跟着一起漂），只做**结构对拍**：
 * 从 QML 里把两个面的行序与规则调用抽出来，比它们是否一致。
 *
 * 用法: node scripts/verify_surface_parity.mjs
 * 无依赖、不联网，可以进 CI 或 pre-commit。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const QML = path.join(HERE, '..', 'omarchy', 'hyc.hae-pulse', 'Main.qml');
const src = fs.readFileSync(QML, 'utf8');

/** 日结型指标：值不是当天就该带日期后缀。规则必须在每一处都调用到。 */
const DAY_FIELDS = ['rhr_day', 'vo2max.day', 'sleep.day', 'weight.day'];
/** 三端统一的行序（见 hae-pulse/README.md 的「两端一致的约定」）。 */
const WANT_ORDER = ['HRV', '静息心率', '心肺耐力(估)', '睡眠', '体重', '锻炼'];

let pass = 0; const failures = [];
const chk = (ok, msg) => { ok ? pass++ : failures.push(msg); console.log((ok ? '  ✅ ' : '  ❌ ') + msg); };

/* ---- 切出两个面 ---- */
const tipStart = src.indexOf('tooltipText: {');
const tipEnd = src.indexOf('onPressed: function');
if (tipStart < 0 || tipEnd < 0) { console.error('找不到 tooltipText 块，Main.qml 结构变了'); process.exit(1); }
const tipBlock = src.slice(tipStart, tipEnd);

const popStart = src.indexOf('// vitals rows');
const popEnd = src.indexOf('delegate: Row', popStart);
if (popStart < 0 || popEnd < 0) { console.error('找不到 popout 的 vitals rows 块，Main.qml 结构变了'); process.exit(1); }
const popBlock = src.slice(popStart, popEnd);

/* ---- 抽行序 ---- */
const canonical = (s) => s.replace(/\s+/g, '').replace(/今日$/, '');

// popout: rows.push({ label: "静息心率", ... })  —— label 在三行内出现
const popLabels = [...popBlock.matchAll(/rows\.push\(\{\s*label:\s*"([^"]+)"/g)].map(m => canonical(m[1]));
// tooltip: lines.push("静息心率 " + ...) —— 取 push 内容的标签前缀
const TIP_PREFIXES = ['HRV', '静息心率', '心肺耐力(估)', '睡眠', '体重', '锻炼'];
const tipLabels = [...tipBlock.matchAll(/lines\.push\("([^"]*)/g)]
  .map(m => m[1])
  .map(s => TIP_PREFIXES.find(p => s.startsWith(p)))
  .filter(Boolean)
  // if/else 两个分支各 push 一次 HRV，去连续重复
  .filter((v, i, a) => i === 0 || v !== a[i - 1]);

console.log('[1] 行序：popout vs tooltip');
console.log('    popout :', popLabels.join(' → '));
console.log('    tooltip:', tipLabels.join(' → '));
chk(popLabels.join(',') === WANT_ORDER.join(','), 'popout 行序 = 三端统一行序');
chk(tipLabels.join(',') === WANT_ORDER.join(','), 'tooltip 行序 = 三端统一行序');

console.log('\n[2] 不变量：日结型指标在每一处都走日期规则');
for (const [name, blk] of [['popout', popBlock], ['tooltip', tipBlock]]) {
  const called = DAY_FIELDS.filter(f => blk.includes(f));
  chk(called.length === DAY_FIELDS.length, `${name} 覆盖 ${called.length}/${DAY_FIELDS.length} 个日结型字段（缺 ${DAY_FIELDS.filter(f => !blk.includes(f)).join(',') || '无'}）`);
  chk(blk.includes('daySuffix('), `${name} 调用了 daySuffix()`);
}

console.log('\n[3] 千分位：kcal_today / steps_today 每次引用都必须被 thousands() 包住');
for (const [name, blk] of [['popout', popBlock], ['tooltip', tipBlock]]) {
  const all = [...blk.matchAll(/s\.(kcal_today|steps_today)/g)].length;
  const wrapped = [...blk.matchAll(/thousands\(\s*s\.(kcal_today|steps_today)\s*\)/g)].length;
  chk(all > 0 && all === wrapped, `${name}：${wrapped}/${all} 处引用经过 thousands()`);
}

console.log('\n[4] macOS 下拉与 Omarchy 的字段口径一致（同一批 snap 键）');
const PY = path.join(HERE, '..', 'macos', 'render.py');
const py = fs.readFileSync(PY, 'utf8');
const keys = ['rhr_today', 'rhr_avg7', 'vo2max', 'sleep', 'weight', 'exercise_min_today',
  'exercise_sessions_today', 'kcal_today', 'steps_today'];
for (const k of keys) {
  const inPy = py.includes(`"${k}"`) || py.includes(`("${k}"`);
  const inQml = src.includes(`s.${k}`) || src.includes(`data.get("${k}")`);
  chk(inPy === inQml, `${k}：macOS ${inPy ? '用' : '不用'} / Omarchy ${inQml ? '用' : '不用'}（应一致）`);
}

console.log('\n' + (failures.length === 0
  ? `全部通过 ✅ (${pass} 项)`
  : `${failures.length} 项失败 ❌（通过 ${pass} 项）`));
process.exit(failures.length ? 1 : 0);
