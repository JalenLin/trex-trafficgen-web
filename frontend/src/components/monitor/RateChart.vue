<script setup lang="ts">
// Line chart of TX/RX rates over time, drawn from samples the stats stream already
// received (no extra requests). One unit per chart (bps or pps), never two axes.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { NDataTable } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { RateSample } from '../../composables/useStatsStream'
import { formatBps, formatPps } from '../../utils/format'
import { persisted } from '../../utils/prefs'

const props = defineProps<{
  history: RateSample[]
  portIds: number[]
  metric: 'bps' | 'pps'
  scope: 'total' | 'tx' | 'rx'
  windowSec: number
  showTable: boolean
  /** Plot height in px (default 240). */
  height?: number
}>()

const { t } = useI18n()
const MAX_SERIES = 8
const PAD = { top: 10, right: 16, bottom: 24 }
const GAP_S = 5 // a longer pause between samples (socket dropped) breaks the line

const box = ref<HTMLDivElement | null>(null)
const width = ref(600)
let ro: ResizeObserver | null = null
onMounted(() => {
  ro = new ResizeObserver(([e]) => (width.value = Math.max(280, Math.floor(e.contentRect.width))))
  if (box.value) ro.observe(box.value)
})
onBeforeUnmount(() => ro?.disconnect())

const fmt = (v: number) => (props.metric === 'bps' ? formatBps(v) : formatPps(v))
// Axis labels: no trailing zeros ("375 Mbps", "62.5 Kpps"), and room for the widest one.
const axisFmt = (v: number) => fmt(v).replace(/(\.\d*?)0+(?= )/, '$1').replace(/\.(?= )/, '')

interface Series {
  key: string
  label: string
  slot: number
  /** stroke-dasharray: RX is dashed so it stays visible where it lies on TX. */
  dash?: string
  values: (number | null)[]
}

const samples = computed(() => {
  const last = props.history.at(-1)?.ts ?? 0
  return props.history.filter((s) => s.ts >= last - props.windowSec)
})

const allSeries = computed<Series[]>(() => {
  const s = samples.value
  const ids = props.portIds.map(String)
  const get = (sample: RateSample, id: string, dir: 'tx' | 'rx') => {
    const p = sample.ports[id]
    return p ? p[`${dir}_${props.metric}`] : null
  }
  if (props.scope === 'total') {
    const sum = (dir: 'tx' | 'rx') => s.map((x) => ids.reduce((acc, id) => acc + (get(x, id, dir) ?? 0), 0))
    return [
      { key: 'tx', label: t('monitor.chart.tx'), slot: 1, values: sum('tx') },
      { key: 'rx', label: t('monitor.chart.rx'), slot: 2, dash: '7 5', values: sum('rx') },
    ]
  }
  const dir = props.scope
  return ids.slice(0, MAX_SERIES).map((id, i) => ({
    key: id,
    label: t('common.portN', { n: id }),
    slot: i + 1,
    values: s.map((x) => get(x, id, dir)),
  }))
})

// Lines the user hid from the legend, remembered per browser and per "show" mode.
const hidden = persisted<Record<string, string[]>>('monitor.hiddenSeries', {})
const hiddenNow = computed(() => new Set(hidden.value[props.scope] ?? []))
const series = computed(() => allSeries.value.filter((s) => !hiddenNow.value.has(s.key)))

function toggle(key: string) {
  const set = new Set(hiddenNow.value)
  if (set.has(key)) set.delete(key)
  else if (series.value.length > 1) set.add(key) // keep at least one line
  hidden.value = { ...hidden.value, [props.scope]: [...set] }
}

// --- scales ---
const plotW = computed(() => width.value - padLeft.value - PAD.right - (series.value.length <= 4 ? 44 : 0))
const HEIGHT = computed(() => props.height ?? 240)
const plotH = computed(() => HEIGHT.value - PAD.top - PAD.bottom)
const t1 = computed(() => samples.value.at(-1)?.ts ?? 0)
const t0 = computed(() => t1.value - props.windowSec)
const yMax = computed(() => {
  const m = Math.max(0, ...series.value.flatMap((s) => s.values.filter((v): v is number => v != null)))
  if (m <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(m))
  const n = m / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p
})
const x = (ts: number) => padLeft.value + ((ts - t0.value) / props.windowSec) * plotW.value
const y = (v: number) => PAD.top + plotH.value - (v / yMax.value) * plotH.value
const yTicks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax.value))
const padLeft = computed(() => 14 + 6.6 * Math.max(...yTicks.value.map((v) => axisFmt(v).length)))
const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const xTicks = computed(() => [0, 1 / 3, 2 / 3, 1].map((f) => t0.value + f * props.windowSec))

function path(values: (number | null)[]): string {
  let d = ''
  let prev: number | null = null
  samples.value.forEach((s, i) => {
    const v = values[i]
    if (v == null) {
      prev = null
      return
    }
    d += `${prev == null || s.ts - prev > GAP_S ? 'M' : 'L'}${x(s.ts).toFixed(1)},${y(v).toFixed(1)}`
    prev = s.ts
  })
  return d
}

// End labels when there are few series, so identity isn't color-only.
const endLabels = computed(() => {
  if (series.value.length > 4) return []
  const n = samples.value.length - 1
  const raw = series.value
    .map((s) => ({ s, v: s.values[n] }))
    .filter((e): e is { s: Series; v: number } => e.v != null)
    .map((e) => ({ key: e.s.key, label: e.s.label, slot: e.s.slot, y: y(e.v) }))
    .sort((a, b) => a.y - b.y)
  for (let i = 1; i < raw.length; i++) raw[i].y = Math.max(raw[i].y, raw[i - 1].y + 13)
  return raw
})

// --- hover ---
const hover = ref<number | null>(null)
function onMove(ev: PointerEvent) {
  const svg = ev.currentTarget as SVGSVGElement
  const px = ev.clientX - svg.getBoundingClientRect().left
  if (!samples.value.length || px < padLeft.value || px > padLeft.value + plotW.value) {
    hover.value = null
    return
  }
  const ts = t0.value + ((px - padLeft.value) / plotW.value) * props.windowSec
  let best = 0
  samples.value.forEach((s, i) => {
    if (Math.abs(s.ts - ts) < Math.abs(samples.value[best].ts - ts)) best = i
  })
  hover.value = best
}
const tip = computed(() => {
  const i = hover.value
  if (i == null || !samples.value[i]) return null
  const left = x(samples.value[i].ts)
  return {
    x: left,
    flip: left > width.value * 0.6,
    time: clock(samples.value[i].ts),
    rows: series.value.map((s) => ({ ...s, v: s.values[i] })),
  }
})

// --- table view (accessibility / exact values): the latest 30 samples ---
const tableColumns = computed(() => [
  { title: t('monitor.chart.time'), key: 'time', width: 100 },
  ...series.value.map((s) => ({ title: s.label, key: s.key, align: 'right' as const })),
])
const tableRows = computed(() =>
  samples.value
    .slice(-30)
    .reverse()
    .map((s) => {
      const i = samples.value.indexOf(s)
      return Object.fromEntries([
        ['time', clock(s.ts)],
        ...series.value.map((se) => [se.key, se.values[i] == null ? '–' : fmt(se.values[i]!)]),
      ])
    }),
)
</script>

<template>
  <div ref="box" class="viz-root">
    <div class="legend">
      <button
        v-for="s in allSeries"
        :key="s.key"
        type="button"
        class="item"
        :class="{ off: hiddenNow.has(s.key) }"
        :aria-pressed="!hiddenNow.has(s.key)"
        @click="toggle(s.key)"
      >
        <svg width="18" height="10" aria-hidden="true">
          <line x1="1" y1="5" x2="17" y2="5" :stroke="`var(--series-${s.slot})`" stroke-width="2.5" :stroke-dasharray="s.dash ? '5 3' : undefined" />
        </svg>
        {{ s.label }}
      </button>
      <span class="legend-hint">{{ t('monitor.chart.legendHint') }}</span>
    </div>
    <div class="plot">
      <svg :width="width" :height="HEIGHT" role="img" :aria-label="t('monitor.chart.title')" @pointermove="onMove" @pointerleave="hover = null">
        <g class="grid">
          <line v-for="v in yTicks" :key="v" :x1="padLeft" :x2="padLeft + plotW" :y1="y(v)" :y2="y(v)" />
        </g>
        <g class="axis">
          <text v-for="v in yTicks" :key="`l${v}`" :x="padLeft - 8" :y="y(v) + 4" text-anchor="end">{{ axisFmt(v) }}</text>
          <text
            v-for="(ts, i) in xTicks"
            :key="`x${i}`"
            :x="x(ts)"
            :y="HEIGHT - 6"
            :text-anchor="i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'"
          >
            {{ clock(ts) }}
          </text>
        </g>
        <path
          v-for="s in series"
          :key="s.key"
          :d="path(s.values)"
          fill="none"
          :stroke="`var(--series-${s.slot})`"
          :stroke-dasharray="s.dash"
          stroke-width="2"
          stroke-linejoin="round"
          stroke-linecap="round"
        />
        <g class="end-labels">
          <text v-for="l in endLabels" :key="l.key" :x="padLeft + plotW + 6" :y="l.y + 4">{{ l.label }}</text>
        </g>
        <g v-if="tip">
          <line class="crosshair" :x1="tip.x" :x2="tip.x" :y1="PAD.top" :y2="PAD.top + plotH" />
          <template v-for="r in tip.rows" :key="r.key">
            <circle
              v-if="r.v != null"
              :cx="tip.x"
              :cy="y(r.v)"
              r="4"
              :fill="`var(--series-${r.slot})`"
              stroke="var(--surface-1)"
              stroke-width="2"
            />
          </template>
        </g>
      </svg>
      <div v-if="tip" class="tooltip" :style="tip.flip ? { right: `${width - tip.x + 12}px` } : { left: `${tip.x + 12}px` }">
        <div class="tip-time">{{ tip.time }}</div>
        <div v-for="r in tip.rows" :key="r.key" class="tip-row">
          <span class="swatch" :style="{ background: `var(--series-${r.slot})` }" />
          <span class="tip-label">{{ r.label }}</span>
          <span class="tip-value">{{ r.v == null ? '–' : fmt(r.v) }}</span>
        </div>
      </div>
      <div v-if="!samples.length" class="empty">{{ t('monitor.chart.waiting') }}</div>
    </div>
    <NDataTable v-if="showTable" size="small" :columns="tableColumns" :data="tableRows" :max-height="260" style="margin-top: 8px" />
  </div>
</template>

<style scoped>
.viz-root {
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
:global(html.dark .viz-root) {
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
.end-labels text {
  font-size: 11px;
  fill: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.end-labels text {
  fill: var(--text-secondary);
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
  min-width: 150px;
}
.tip-time {
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
