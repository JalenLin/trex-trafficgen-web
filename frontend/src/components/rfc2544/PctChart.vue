<script setup lang="ts">
// Small SVG chart for RFC 2544 results, in the style of monitor/RateChart.vue:
// 'bar' = one value per category (throughput % per frame size),
// 'line' = one line per series over a numeric x (loss % vs offered load).
// Both have a single percent y axis.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

export interface ChartSeries {
  key: string
  label: string
  points: { x: number; y: number | null }[]
}

const props = defineProps<{
  kind: 'bar' | 'line'
  series: ChartSeries[]
  /** Accessible name / what the chart shows. */
  title: string
  xLabel: string
  yLabel: string
  /** Fixed top of the y axis (e.g. 100 for % of line rate); otherwise from the data. */
  yMax?: number
  xFmt?: (x: number) => string
  yFmt?: (y: number) => string
  height?: number
}>()

const { t } = useI18n()
const PAD = { top: 22, right: 16, bottom: 40 }
const HEIGHT = computed(() => props.height ?? 240)

const box = ref<HTMLDivElement | null>(null)
const width = ref(600)
let ro: ResizeObserver | null = null
onMounted(() => {
  ro = new ResizeObserver(([e]) => (width.value = Math.max(260, Math.floor(e.contentRect.width))))
  if (box.value) ro.observe(box.value)
})
onBeforeUnmount(() => ro?.disconnect())

const trim = (v: number, d: number) => String(Number(v.toFixed(d)))
const xf = (x: number) => (props.xFmt ? props.xFmt(x) : trim(x, 2))
const yf = (y: number) => (props.yFmt ? props.yFmt(y) : trim(y, 3))

// Fixed palette order; past 8 series the colors repeat with a dashed line.
const slot = (i: number) => (i % 8) + 1
const dash = (i: number) => (i >= 8 ? '6 4' : undefined)

// --- legend (line chart only; a single-series bar chart is named by its title) ---
const hidden = ref(new Set<string>())
const indexed = computed(() => props.series.map((s, i) => ({ ...s, i })))
const shown = computed(() => indexed.value.filter((s) => !hidden.value.has(s.key)))
function toggle(key: string) {
  const set = new Set(hidden.value)
  if (set.has(key)) set.delete(key)
  else if (shown.value.length > 1) set.add(key)
  hidden.value = set
}

// --- y scale ---
const yTop = computed(() => {
  if (props.yMax) return props.yMax
  const m = Math.max(0, ...shown.value.flatMap((s) => s.points.map((p) => p.y ?? 0)))
  if (m <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(m))
  const n = m / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p
})
const yTicks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((f) => f * yTop.value))
const padLeft = computed(() => 14 + 6.6 * Math.max(...yTicks.value.map((v) => yf(v).length)))
const plotW = computed(() => Math.max(40, width.value - padLeft.value - PAD.right))
const plotH = computed(() => HEIGHT.value - PAD.top - PAD.bottom)
const y = (v: number) => PAD.top + plotH.value - (Math.min(v, yTop.value) / yTop.value) * plotH.value
const baseY = computed(() => PAD.top + plotH.value)

// --- x: categories (bar) or numeric (line) ---
const xs = computed(() => [...new Set(shown.value.flatMap((s) => s.points.map((p) => p.x)))].sort((a, b) => a - b))
const band = computed(() => plotW.value / Math.max(1, xs.value.length))
const xDomain = computed(() => {
  const v = xs.value
  if (!v.length) return [0, 100]
  const lo = v[0]
  const hi = v[v.length - 1]
  return lo === hi ? [Math.max(0, lo - 10), hi + (lo - 10 < 0 ? 10 : 0)] : [lo, hi]
})
function x(v: number): number {
  if (props.kind === 'bar') return padLeft.value + band.value * (xs.value.indexOf(v) + 0.5)
  const [lo, hi] = xDomain.value
  return padLeft.value + ((v - lo) / (hi - lo || 1)) * plotW.value
}
// Thin out tick labels so they never overlap (about 7 px per character + gap).
const xTicks = computed(() => {
  const v = xs.value
  if (!v.length) return []
  const widest = Math.max(...v.map((n) => xf(n).length)) * 7 + 12
  if (props.kind === 'bar') {
    const every = Math.max(1, Math.ceil(widest / Math.max(1, band.value)))
    return v.filter((_, i) => i % every === 0)
  }
  // Lines: x values can sit unevenly (and nearly on top of each other when they are measured
  // loads), so walk down from the highest one and keep labels that have room.
  const out: number[] = []
  for (const n of [...v].reverse()) {
    const last = out.at(-1)
    if (last === undefined || (x(last) - x(n) >= widest && xf(last) !== xf(n))) out.push(n)
  }
  return out
})
const tickAnchor = (v: number) => {
  if (props.kind === 'bar') return 'middle'
  const px = x(v)
  return px - padLeft.value < 12 ? 'start' : padLeft.value + plotW.value - px < 12 ? 'end' : 'middle'
}

// --- bars ---
const bars = computed(() => {
  const s = shown.value[0]
  if (props.kind !== 'bar' || !s) return []
  const w = Math.max(4, Math.min(56, band.value * 0.66))
  return s.points
    .filter((p): p is { x: number; y: number } => p.y != null)
    .map((p) => {
      const cx = x(p.x)
      const top = y(p.y)
      const h = baseY.value - top
      const r = Math.min(4, w / 2, h)
      const l = cx - w / 2
      // rounded data end, square on the baseline
      const d = h <= 0 ? '' : `M${l},${baseY.value}V${top + r}Q${l},${top} ${l + r},${top}H${l + w - r}Q${l + w},${top} ${l + w},${top + r}V${baseY.value}Z`
      return { key: p.x, d, cx, top, label: yf(p.y), w }
    })
})
const barLabels = computed(() => bars.value.length <= 12 && bars.value.every((b) => b.w >= 26))

// --- lines ---
function path(points: { x: number; y: number | null }[]): string {
  let d = ''
  let pen = false
  for (const p of [...points].sort((a, b) => a.x - b.x)) {
    if (p.y == null) {
      pen = false
      continue
    }
    d += `${pen ? 'L' : 'M'}${x(p.x).toFixed(1)},${y(p.y).toFixed(1)}`
    pen = true
  }
  return d
}

// --- hover ---
const hover = ref<number | null>(null)
function onMove(ev: PointerEvent) {
  const svg = ev.currentTarget as SVGSVGElement
  const px = ev.clientX - svg.getBoundingClientRect().left
  if (!xs.value.length || px < padLeft.value - 8 || px > padLeft.value + plotW.value + 8) {
    hover.value = null
    return
  }
  let best = xs.value[0]
  for (const v of xs.value) if (Math.abs(x(v) - px) < Math.abs(x(best) - px)) best = v
  hover.value = best
}
const tip = computed(() => {
  const hx = hover.value
  if (hx == null) return null
  const left = x(hx)
  if (props.kind === 'bar') {
    const s = shown.value[0]
    const rows = s ? [{ key: s.key, label: s.label, slot: slot(s.i), v: s.points.find((p) => p.x === hx)?.y ?? null }] : []
    return { x: left, flip: left > width.value * 0.6, head: `${props.xLabel}: ${xf(hx)}`, rows }
  }
  // Lines may have their points at different x (e.g. the load TRex really offered per frame size):
  // each line shows its point nearest the pointer, when it is close enough.
  const rows: { key: string; label: string; slot: number; v: number | null; px: number }[] = []
  for (const s of shown.value) {
    let best: { x: number; y: number | null } | null = null
    for (const p of s.points) if (!best || Math.abs(x(p.x) - left) < Math.abs(x(best.x) - left)) best = p
    if (best && Math.abs(x(best.x) - left) <= 24)
      rows.push({ key: s.key, label: xf(best.x) === xf(hx) ? s.label : `${s.label} (${xf(best.x)})`, slot: slot(s.i), v: best.y, px: best.x })
  }
  return { x: left, flip: left > width.value * 0.6, head: `${props.xLabel}: ${xf(hx)}`, rows }
})
</script>

<template>
  <div ref="box" class="rfc-viz">
    <div v-if="kind === 'line' && series.length > 1" class="legend">
      <button
        v-for="s in indexed"
        :key="s.key"
        type="button"
        class="item"
        :class="{ off: hidden.has(s.key) }"
        :aria-pressed="!hidden.has(s.key)"
        @click="toggle(s.key)"
      >
        <svg width="18" height="10" aria-hidden="true">
          <line x1="1" y1="5" x2="17" y2="5" :stroke="`var(--series-${slot(s.i)})`" stroke-width="2.5" :stroke-dasharray="dash(s.i) ? '5 3' : undefined" />
        </svg>
        {{ s.label }}
      </button>
      <span class="legend-hint">{{ t('rfc2544.results.legendHint') }}</span>
    </div>
    <div class="plot">
      <svg :width="width" :height="HEIGHT" role="img" :aria-label="title" @pointermove="onMove" @pointerleave="hover = null">
        <text class="axis-title" :x="padLeft" :y="12" text-anchor="start">{{ yLabel }}</text>
        <g class="grid">
          <line v-for="v in yTicks" :key="v" :x1="padLeft" :x2="padLeft + plotW" :y1="y(v)" :y2="y(v)" />
        </g>
        <g class="axis">
          <text v-for="v in yTicks" :key="`l${v}`" :x="padLeft - 8" :y="y(v) + 4" text-anchor="end">{{ yf(v) }}</text>
          <text v-for="v in xTicks" :key="`x${v}`" :x="x(v)" :y="baseY + 16" :text-anchor="tickAnchor(v)">{{ xf(v) }}</text>
        </g>
        <text class="axis-title" :x="padLeft + plotW / 2" :y="HEIGHT - 4" text-anchor="middle">{{ xLabel }}</text>

        <template v-if="kind === 'bar'">
          <rect
            v-if="tip"
            class="band-hi"
            :x="tip.x - band / 2"
            :y="PAD.top"
            :width="band"
            :height="plotH"
          />
          <path v-for="b in bars" :key="b.key" :d="b.d" fill="var(--series-1)" />
          <g v-if="barLabels" class="bar-labels">
            <text v-for="b in bars" :key="`v${b.key}`" :x="b.cx" :y="b.top - 5" text-anchor="middle">{{ b.label }}</text>
          </g>
        </template>

        <template v-else>
          <line v-if="tip" class="crosshair" :x1="tip.x" :x2="tip.x" :y1="PAD.top" :y2="baseY" />
          <g v-for="s in shown" :key="s.key">
            <path
              :d="path(s.points)"
              fill="none"
              :stroke="`var(--series-${slot(s.i)})`"
              :stroke-dasharray="dash(s.i)"
              stroke-width="2"
              stroke-linejoin="round"
              stroke-linecap="round"
            />
            <template v-for="p in s.points" :key="p.x">
              <circle
                v-if="p.y != null"
                :cx="x(p.x)"
                :cy="y(p.y)"
                :r="tip?.rows.some((r) => r.key === s.key && 'px' in r && r.px === p.x) ? 5 : 3.5"
                :fill="`var(--series-${slot(s.i)})`"
                stroke="var(--surface-1)"
                stroke-width="2"
              />
            </template>
          </g>
        </template>
      </svg>
      <div v-if="tip" class="tooltip" :style="tip.flip ? { right: `${width - tip.x + 12}px` } : { left: `${tip.x + 12}px` }">
        <div class="tip-head">{{ tip.head }}</div>
        <div v-for="r in tip.rows" :key="r.key" class="tip-row">
          <span class="swatch" :style="{ background: `var(--series-${r.slot})` }" />
          <span class="tip-label">{{ r.label }}</span>
          <span class="tip-value">{{ r.v == null ? '–' : yf(r.v) }}</span>
        </div>
      </div>
      <div v-if="!xs.length" class="empty">{{ t('rfc2544.results.noResults') }}</div>
    </div>
  </div>
</template>

<style scoped>
.rfc-viz {
  --surface-1: #fcfcfb;
  --text-secondary: #52514e;
  --text-muted: #7a7974;
  --grid: rgba(128, 128, 128, 0.18);
  --series-1: #2a78d6;
  --series-2: #eb6834;
  --series-3: #1baf7a;
  --series-4: #eda100;
  --series-5: #e87ba4;
  --series-6: #008300;
  --series-7: #6250d6;
  --series-8: #e34948;
  position: relative;
  min-width: 0;
}
:global(html.dark .rfc-viz) {
  --surface-1: #18181c;
  --text-secondary: #c3c2b7;
  --text-muted: #9a998f;
  --series-1: #3987e5;
  --series-2: #d95926;
  --series-3: #199e70;
  --series-4: #c98500;
  --series-5: #d55181;
  --series-6: #008300;
  --series-7: #9085e9;
  --series-8: #e66767;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 1px 6px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.item:hover {
  border-color: var(--grid);
}
.item.off {
  opacity: 0.45;
  text-decoration: line-through;
}
.legend-hint {
  color: var(--text-muted);
  font-size: 11px;
  align-self: center;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex: none;
}
.plot {
  position: relative;
}
svg {
  display: block;
  touch-action: pan-y;
}
.grid line {
  stroke: var(--grid);
  stroke-width: 1;
}
.axis text,
.bar-labels text {
  font-size: 11px;
  fill: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.bar-labels text {
  fill: var(--text-secondary);
}
.axis-title {
  font-size: 11px;
  fill: var(--text-secondary);
}
.band-hi {
  fill: var(--grid);
  opacity: 0.6;
}
.crosshair {
  stroke: var(--text-muted);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.tooltip {
  position: absolute;
  top: 8px;
  pointer-events: none;
  background: var(--surface-1);
  border: 1px solid var(--grid);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  min-width: 140px;
  z-index: 1;
}
.tip-head {
  color: var(--text-muted);
  margin-bottom: 4px;
}
.tip-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tip-label {
  color: var(--text-secondary);
  flex: 1;
}
.tip-value {
  font-variant-numeric: tabular-nums;
}
.empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--text-muted);
  font-size: 13px;
}
</style>
