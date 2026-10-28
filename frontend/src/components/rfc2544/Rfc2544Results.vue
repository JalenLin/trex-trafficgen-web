<script setup lang="ts">
// Result tables and charts of one RFC 2544 job (running, finished or from history), with JSON / CSV export.
import { computed, h } from 'vue'
import { NAlert, NButton, NDataTable, NEmpty, NSpace, NTag, NText, type DataTableColumns } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { Rfc2544Dir, Rfc2544Job } from '../../api'
import PctChart, { type ChartSeries } from './PctChart.vue'
import { dateTime, dirLabel, directions, download, lossPct, num, testName, type Translate } from './util'

const props = defineProps<{ job: Rfc2544Job }>()
const { t: i18nT } = useI18n()
const t: Translate = (k, p) => (p ? i18nT(k, p) : i18nT(k))

const r = computed(() => props.job.results ?? {})
const tests = computed(() => props.job.tests ?? [])
const running = computed(() => props.job.state === 'running')
const hasAny = computed(() => Object.values(r.value).some((v) => Array.isArray(v) && v.length))

const cfgText = computed(() => {
  const c = props.job.config
  if (!c) return ''
  const dirs = directions(c.pairs, c.bidirectional).map(([a, b]) => dirLabel(a, b)).join(', ')
  return t('rfc2544.results.config', { dirs, trial: num(c.trial_s), max: num(c.max_rate_pct), loss: num(c.loss_tolerance_pct, 4) })
})
const speedsText = computed(() => {
  const s = Object.entries(props.job.speeds ?? {})
  return s.length ? t('rfc2544.results.speeds', { list: s.map(([p, g]) => `${t('common.portN', { n: p })} ${num(g)} Gbps`).join(', ') }) : ''
})
const pct = (v: number) => `${num(v, 2)} %`
const worst = (dirs: Rfc2544Dir[] | undefined) => {
  const l = (dirs ?? []).map((d) => d.loss_pct).filter((v): v is number => v != null)
  return l.length ? Math.max(...l) : null
}

// --- throughput ---
type TpRow = NonNullable<typeof r.value.throughput>[number]
const tpRows = computed(() => r.value.throughput ?? [])
// Runs saved before offered_pct existed: the requested rate is all there is.
const offered = (x: TpRow) => x.offered_pct ?? x.rate_pct
const tpColumns = computed<DataTableColumns<TpRow>>(() => [
  { title: t('rfc2544.results.size'), key: 'size', width: 90 },
  { title: t('rfc2544.results.requested'), key: 'rate_pct', align: 'right', render: (x) => num(x.rate_pct, 3) },
  {
    title: t('rfc2544.results.offeredPct'),
    key: 'offered_pct',
    align: 'right',
    width: 150,
    render: (x) =>
      h(NSpace, { size: 6, justify: 'end', align: 'center', wrap: false }, () => [
        x.tx_limited ? h(NTag, { size: 'small', bordered: false, type: 'warning' }, () => t('rfc2544.results.txLimited')) : null,
        num(offered(x), 3),
      ]),
  },
  { title: t('rfc2544.results.mpps'), key: 'mpps', align: 'right', render: (x) => num(x.mpps, 4) },
  { title: t('rfc2544.results.gbpsL1'), key: 'gbps_l1', align: 'right', render: (x) => num(x.gbps_l1, 3) },
  { title: t('rfc2544.results.gbpsL2'), key: 'gbps_l2', align: 'right', render: (x) => num(x.gbps_l2, 3) },
  { title: t('rfc2544.results.worstLoss'), key: 'loss', align: 'right', render: (x) => lossPct(worst(x.trial?.dirs)) },
])
const tpSeries = computed<ChartSeries[]>(() => [
  { key: 'tp', label: t('rfc2544.tests.throughput'), points: tpRows.value.map((x) => ({ x: x.size, y: offered(x) })) },
])
const txLimited = computed(() => tpRows.value.filter((x) => x.tx_limited).map((x) => x.size))

// --- latency ---
type LatRow = NonNullable<typeof r.value.latency>[number]
const latRows = computed(() => r.value.latency ?? [])
const latDirs = computed(() => {
  const seen = new Map<string, [number, number]>()
  for (const row of latRows.value) for (const d of row.dirs) seen.set(dirLabel(d.tx, d.rx), [d.tx, d.rx])
  return [...seen.entries()]
})
const LAT_FIELDS = [
  ['total_min', 'min'],
  ['average', 'avg'],
  ['total_max', 'max'],
  ['jitter', 'jitter'],
] as const
const latValue = (row: LatRow, dir: string, field: (typeof LAT_FIELDS)[number][0]) =>
  row.dirs.find((d) => dirLabel(d.tx, d.rx) === dir)?.latency?.[field] ?? null
const latColumns = computed<DataTableColumns<LatRow>>(() => [
  { title: t('rfc2544.results.size'), key: 'size', width: 90, fixed: 'left' },
  { title: t('rfc2544.results.ratePct'), key: 'rate_pct', align: 'right', width: 110, render: (x) => num(x.rate_pct, 3) },
  ...latDirs.value.map(([label]) => ({
    title: label,
    key: label,
    align: 'center' as const,
    children: LAT_FIELDS.map(([field, word]) => ({
      title: t(`rfc2544.results.${word}`),
      key: `${label}-${field}`,
      align: 'right' as const,
      width: 90,
      render: (x: LatRow) => num(latValue(x, label, field), field === 'average' || field === 'jitter' ? 2 : 1),
    })),
  })),
])
const latScroll = computed(() => 200 + latDirs.value.length * 360)

// --- frame loss ---
type FlRow = NonNullable<typeof r.value.frame_loss>[number]
const flRows = computed(() => r.value.frame_loss ?? [])
const flRates = computed(() => [...new Set(flRows.value.flatMap((x) => x.points.map((p) => p.rate_pct)))].sort((a, b) => b - a))
const flColumns = computed<DataTableColumns<FlRow>>(() => [
  { title: t('rfc2544.results.size'), key: 'size', width: 90, fixed: 'left' },
  ...flRates.value.map((rate) => ({
    title: t('rfc2544.results.offered', { pct: num(rate, 3) }),
    key: `r${rate}`,
    align: 'right' as const,
    width: flAnyDiffers.value ? 120 : 80,
    render: (x: FlRow) => {
      const p = x.points.find((q) => q.rate_pct === rate)
      if (!p) return ''
      const loss = h(NText, { depth: p.loss_pct ? undefined : 3 }, () => lossPct(p.loss_pct))
      return differs(p) ? [loss, h(NText, { depth: 3, type: 'warning' }, () => t('rfc2544.results.sentPct', { pct: num(p.offered_pct, 2) }))] : loss
    },
  })),
])
type FlPoint = FlRow['points'][number]
// Show the offered load next to a cell only when TRex fell visibly short of the requested one.
const differs = (p: FlPoint) => p.offered_pct != null && Math.abs(p.offered_pct - p.rate_pct) > Math.max(0.5, p.rate_pct * 0.02)
const flAnyDiffers = computed(() => flRows.value.some((x) => x.points.some(differs)))
const flScroll = computed(() => 90 + flRates.value.length * (flAnyDiffers.value ? 120 : 80))
const flSeries = computed<ChartSeries[]>(() =>
  flRows.value.map((x) => ({
    key: String(x.size),
    label: t('rfc2544.results.sizeLabel', { size: x.size }),
    points: x.points.map((p) => ({ x: p.offered_pct ?? p.rate_pct, y: p.loss_pct })),
  })),
)

// --- back-to-back ---
type BbRow = NonNullable<typeof r.value.back_to_back>[number]
const bbRows = computed(() => r.value.back_to_back ?? [])
const bbColumns = computed<DataTableColumns<BbRow>>(() => [
  { title: t('rfc2544.results.size'), key: 'size', width: 90 },
  {
    title: t('rfc2544.results.frames'),
    key: 'frames',
    align: 'right',
    render: (x) =>
      h(NSpace, { size: 6, justify: 'end', align: 'center', wrap: false }, () => [
        x.capped ? h(NTag, { size: 'small', bordered: false, type: 'info' }, () => t('rfc2544.results.capped')) : null,
        x.frames.toLocaleString(),
      ]),
  },
  { title: t('rfc2544.results.seconds'), key: 'seconds', align: 'right', render: (x) => num(x.seconds, 6) },
])
const anyCapped = computed(() => bbRows.value.some((x) => x.capped))

// --- export ---
const baseName = computed(() => `rfc2544-${props.job.id}`)
function exportJson() {
  download(`${baseName.value}.json`, JSON.stringify(props.job, null, 1), 'application/json')
}
const cell = (v: unknown) => {
  const s = v == null ? '' : typeof v === 'number' ? String(Number(v.toFixed(6))) : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
function exportCsv() {
  const out: string[][] = []
  const section = (title: string, head: string[], rows: unknown[][]) => {
    if (out.length) out.push([])
    out.push([title], head, ...rows.map((row) => row.map(cell)))
  }
  if (tpRows.value.length)
    section(
      testName(t, 'throughput'),
      ['size', 'requested_pct', 'offered_pct', 'tx_limited', 'mpps', 'gbps_l1', 'gbps_l2', 'worst_loss_pct'],
      tpRows.value.map((x) => [x.size, x.rate_pct, offered(x), x.tx_limited ? 'yes' : 'no', x.mpps, x.gbps_l1, x.gbps_l2, worst(x.trial?.dirs)]),
    )
  if (latRows.value.length)
    section(
      testName(t, 'latency'),
      ['size', 'rate_pct', ...latDirs.value.flatMap(([d]) => LAT_FIELDS.map(([, w]) => `${d} ${w}_us`))],
      latRows.value.map((x) => [x.size, x.rate_pct, ...latDirs.value.flatMap(([d]) => LAT_FIELDS.map(([f]) => latValue(x, d, f)))]),
    )
  if (flRows.value.length)
    section(
      testName(t, 'frame_loss'),
      ['size', ...flRates.value.flatMap((rate) => [`loss_pct_at_${num(rate, 3)}`, `offered_pct_at_${num(rate, 3)}`])],
      flRows.value.map((x) => [
        x.size,
        ...flRates.value.flatMap((rate) => {
          const p = x.points.find((q) => q.rate_pct === rate)
          return [p?.loss_pct ?? null, p ? p.offered_pct ?? p.rate_pct : null]
        }),
      ]),
    )
  if (bbRows.value.length)
    section(
      testName(t, 'back_to_back'),
      ['size', 'frames', 'seconds', 'capped'],
      bbRows.value.map((x) => [x.size, x.frames, x.seconds, x.capped ? 'yes' : 'no']),
    )
  // BOM so spreadsheet apps read the Chinese section titles as UTF-8
  download(`${baseName.value}.csv`, '﻿' + out.map((row) => row.join(',')).join('\r\n') + '\r\n', 'text/csv;charset=utf-8')
}
</script>

<template>
  <div class="rfc-results">
    <div class="head">
      <div class="head-text">
        <NText depth="3" class="note">{{ cfgText }}</NText>
        <NText v-if="speedsText" depth="3" class="note">{{ speedsText }}</NText>
        <NText v-if="running" type="info" class="note">{{ t('rfc2544.results.partial') }}</NText>
      </div>
      <NSpace :size="6">
        <NButton size="small" @click="exportJson">{{ t('rfc2544.results.exportJson') }}</NButton>
        <NButton size="small" :disabled="!hasAny" @click="exportCsv">{{ t('rfc2544.results.exportCsv') }}</NButton>
      </NSpace>
    </div>

    <NEmpty v-if="!hasAny" size="small" :description="t('rfc2544.results.noResults')" class="empty" />

    <section v-if="tests.includes('throughput') && tpRows.length" class="test">
      <NText strong class="test-title">{{ t('rfc2544.tests.throughput') }}</NText>
      <PctChart
        kind="bar"
        :series="tpSeries"
        :title="t('rfc2544.results.chartThroughput')"
        :x-label="t('rfc2544.results.axisSize')"
        :y-label="t('rfc2544.results.axisRate')"
        :y-max="100"
        :y-fmt="pct"
        :height="220"
      />
      <NDataTable size="small" :columns="tpColumns" :data="tpRows" :row-key="(x: TpRow) => x.size" :scroll-x="780" class="table" />
      <NAlert v-if="txLimited.length" type="warning" :show-icon="false" class="limited">
        {{ t('rfc2544.results.txLimitedNote', { sizes: txLimited.join(', ') }) }}
      </NAlert>
      <NText depth="3" class="note">{{ t('rfc2544.results.perDirection') }}</NText>
    </section>

    <section v-if="tests.includes('latency') && latRows.length" class="test">
      <NText strong class="test-title">{{ t('rfc2544.tests.latency') }}</NText>
      <NDataTable
        size="small"
        :columns="latColumns"
        :data="latRows"
        :row-key="(x: LatRow) => x.size"
        :scroll-x="latScroll"
        :single-line="false"
        class="table"
      />
      <NText depth="3" class="note">{{ t('rfc2544.results.latencyNote') }}</NText>
    </section>

    <section v-if="tests.includes('frame_loss') && flRows.length" class="test">
      <NText strong class="test-title">{{ t('rfc2544.tests.frame_loss') }}</NText>
      <PctChart
        kind="line"
        :series="flSeries"
        :title="t('rfc2544.results.chartFrameLoss')"
        :x-label="t('rfc2544.results.axisOffered')"
        :y-label="t('rfc2544.results.axisLoss')"
        :x-fmt="(v: number) => num(v, 2)"
        :y-fmt="pct"
        :height="240"
      />
      <NDataTable size="small" :columns="flColumns" :data="flRows" :row-key="(x: FlRow) => x.size" :scroll-x="flScroll" class="table" />
      <NText depth="3" class="note">{{ t('rfc2544.results.frameLossNote') }}</NText>
    </section>

    <section v-if="tests.includes('back_to_back') && bbRows.length" class="test">
      <NText strong class="test-title">{{ t('rfc2544.tests.back_to_back') }}</NText>
      <NDataTable size="small" :columns="bbColumns" :data="bbRows" :row-key="(x: BbRow) => x.size" :scroll-x="380" class="table" />
      <NText v-if="anyCapped" depth="3" class="note">{{ t('rfc2544.results.cappedNote') }}</NText>
    </section>

    <NText depth="3" class="note started">{{ dateTime(job.started) }} · {{ job.id }}</NText>
  </div>
</template>

<style scoped>
.rfc-results {
  min-width: 0;
}
.head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px 16px;
  margin-bottom: 8px;
}
.head-text {
  min-width: 0;
  flex: 1 1 260px;
}
.note {
  display: block;
  font-size: 12px;
  margin-top: 4px;
}
.test {
  margin-top: 16px;
  min-width: 0;
}
.test-title {
  display: block;
  font-size: 14px;
  margin-bottom: 6px;
}
.table {
  margin-top: 8px;
}
.empty {
  margin: 16px 0;
}
.limited {
  margin-top: 8px;
}
.started {
  margin-top: 14px;
}
</style>
