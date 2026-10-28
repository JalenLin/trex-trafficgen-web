<script setup lang="ts">
import { computed, h, watch } from 'vue'
import { NButton, NDataTable, NEmpty, NSpace, NSwitch, NTag, NText, useMessage, type DataTableColumns } from 'naive-ui'
import { api, type LatencyStats, type PgStats, type StatsMessage } from '../api'
import { useI18n } from 'vue-i18n'
import { useHostsStore } from '../stores/hosts'
import { useStreamsStore } from '../stores/streams'
import { formatCount, formatPps } from '../utils/format'
import { persisted } from '../utils/prefs'

const props = defineProps<{ hostId: string; latest: Extract<StatsMessage, { type: 'stats' }> | null }>()

const hosts = useHostsStore()
const streams = useStreamsStore()
const message = useMessage()
const { t } = useI18n()

// Map pg_id -> the streams that use it, from the GUI's stream definitions.
const ports = computed(() => hosts.ports[props.hostId] ?? [])
watch(
  () => ports.value.map((p) => p.id).join(','),
  () => Promise.all(ports.value.map((p) => streams.ensure(props.hostId, p.id))).catch(() => undefined),
  { immediate: true },
)
const owners = computed(() => {
  const out: Record<string, { label: string; type: string }[]> = {}
  for (const p of ports.value) {
    for (const s of streams.get(props.hostId, p.id) ?? []) {
      if (s.flow_stats.type === 'none' || s.flow_stats.pg_id == null) continue
      ;(out[s.flow_stats.pg_id] ??= []).push({ label: `P${p.id} ${s.name}`, type: s.flow_stats.type })
    }
  }
  return out
})

const onlyChecked = persisted('pg.onlyChecked', false)
const checked = computed(() => new Set((hosts.checked[props.hostId] ?? []).map(String)))

interface Row extends PgStats {
  pg: string
}
const rows = computed<Row[]>(() =>
  Object.entries(props.latest?.pgids ?? {})
    .map(([pg, s]) => ({ pg, ...s }))
    .filter((r) => !onlyChecked.value || Object.keys(r.tx_ports).some((p) => checked.value.has(p)))
    .sort((a, b) => Number(a.pg) - Number(b.pg)),
)

const us = (v: number | null | undefined) => (v == null ? '—' : `${Number.isInteger(v) ? v : v.toFixed(1)}`)
const n = (v: number | null | undefined) => (v == null ? '—' : formatCount(v))
const lat = (r: Row, k: keyof LatencyStats) => (r.latency ? (r.latency[k] as number | null) : null)

function diff(r: Row) {
  if (r.tx_pkts == null || r.rx_pkts == null) return '—'
  const d = r.tx_pkts - r.rx_pkts
  const pct = r.tx_pkts ? (d / r.tx_pkts) * 100 : 0
  return `${formatCount(d)} (${pct.toFixed(pct && Math.abs(pct) < 0.01 ? 4 : 2)}%)`
}

function histogram(l: LatencyStats, rx: number | null) {
  const buckets = Object.entries(l.histogram)
    .map(([k, v]) => [Number(k), v] as const)
    .sort((a, b) => a[0] - b[0])
  const max = Math.max(1, ...buckets.map(([, v]) => v))
  // TRex's histogram leaves out packets faster than its first bucket (10 μs).
  const counted = buckets.reduce((sum, [, v]) => sum + v, 0)
  const below = rx != null && rx > counted ? rx - counted : 0
  return h('div', { class: 'hist' }, [
    h(NText, { depth: 3, style: 'font-size:12px' }, () => t('stats.pg.histTitle')),
    below
      ? h(NText, { depth: 3, style: 'font-size:12px; display:block' }, () =>
          t('stats.pg.histBelow', { n: formatCount(below) }),
        )
      : null,
    ...buckets.map(([k, v], i) =>
      h('div', { class: 'bar-row' }, [
        h('span', { class: 'bar-label' }, `${k}${buckets[i + 1] ? `–${buckets[i + 1][0]}` : '+'}`),
        h('span', { class: 'bar', style: { width: `${(v / max) * 100}%` } }),
        h('span', { class: 'bar-count' }, formatCount(v)),
      ]),
    ),
  ])
}

const portCounts = (r: Row) =>
  h('div', { class: 'ports' }, [
    h(NText, { depth: 3, style: 'font-size:12px' }, () => t('stats.pg.perPort')),
    ...[...new Set([...Object.keys(r.tx_ports), ...Object.keys(r.rx_ports)])]
      .sort((a, b) => Number(a) - Number(b))
      .map((p) => h('div', null, `${t('common.portN', { n: p })}: TX ${n(r.tx_ports[p])} · RX ${n(r.rx_ports[p])}`)),
  ])

const columns = computed<DataTableColumns<Row>>(() => [
  {
    type: 'expand',
    renderExpand: (r) => h('div', { class: 'expand' }, [portCounts(r), r.latency ? histogram(r.latency, r.rx_pkts) : null]),
  },
  { title: 'pg_id', key: 'pg', width: 70, fixed: 'left' },
  {
    title: 'Stream',
    key: 'owners',
    minWidth: 160,
    render: (r) =>
      h(NSpace, { size: 4 }, () =>
        (owners.value[r.pg] ?? []).map((o) =>
          h(NTag, { size: 'small', bordered: false, type: o.type === 'latency' ? 'info' : 'default' }, () => o.label),
        ),
      ),
  },
  { title: t('stats.pg.txPkts'), key: 'tx', align: 'right', width: 120, render: (r) => n(r.tx_pkts) },
  { title: t('stats.pg.rxPkts'), key: 'rx', align: 'right', width: 120, render: (r) => n(r.rx_pkts) },
  { title: 'TX−RX', key: 'diff', align: 'right', width: 150, render: diff },
  { title: 'TX pps', key: 'txpps', align: 'right', width: 100, render: (r) => (r.tx_pps == null ? '—' : formatPps(r.tx_pps)) },
  {
    title: 'Latency (μs)',
    key: 'latency',
    align: 'center',
    children: [
      { title: t('stats.pg.avg'), key: 'avg', align: 'right', width: 70, render: (r) => us(lat(r, 'average')) },
      { title: t('stats.pg.min'), key: 'min', align: 'right', width: 70, render: (r) => us(lat(r, 'total_min')) },
      { title: t('stats.pg.max'), key: 'max', align: 'right', width: 70, render: (r) => us(lat(r, 'total_max')) },
      { title: t('stats.pg.lastMax'), key: 'last', align: 'right', width: 80, render: (r) => us(lat(r, 'last_max')) },
      { title: 'Jitter', key: 'jit', align: 'right', width: 70, render: (r) => us(lat(r, 'jitter')) },
    ],
  },
  {
    title: t('stats.pg.seqCheck'),
    key: 'seq',
    align: 'center',
    children: [
      { title: t('stats.pg.dropped'), key: 'drop', align: 'right', width: 80, render: (r) => n(lat(r, 'dropped')) },
      { title: t('stats.pg.outOfOrder'), key: 'ooo', align: 'right', width: 70, render: (r) => n(lat(r, 'out_of_order')) },
      { title: t('stats.pg.dup'), key: 'dup', align: 'right', width: 70, render: (r) => n(lat(r, 'dup')) },
    ],
  },
])

const g = computed(() => props.latest?.pg_global ?? {})
const globalErrors = computed(() =>
  [
    [t('stats.pg.rxErr'), g.value.rx_err],
    [t('stats.pg.txErr'), g.value.tx_err],
    [t('stats.pg.oldFlow'), g.value.old_flow],
    [t('stats.pg.badHdr'), g.value.bad_hdr],
  ].filter(([, v]) => v),
)

async function clear() {
  try {
    await api.clearStats(props.hostId)
    message.success(t('stats.clearedWithPg'))
  } catch (e) {
    message.error((e as Error).message)
  }
}
</script>

<template>
  <NSpace vertical :size="12">
    <NSpace align="center" justify="space-between">
      <NSpace align="center" :size="6">
        <NSwitch v-model:value="onlyChecked" size="small" />
        <NText depth="2">{{ t('stats.pg.onlyChecked') }}</NText>
      </NSpace>
      <NButton size="small" @click="clear">{{ t('stats.clear') }}</NButton>
    </NSpace>
    <NText depth="3" style="font-size: 12px">
      {{ t('stats.pg.help1') }}{{ t('stats.pg.help2') }}
    </NText>
    <NText v-for="[label, v] in globalErrors" :key="String(label)" type="warning" style="font-size: 12px">
      {{ label }}: {{ v }}
    </NText>
    <NEmpty v-if="!rows.length" :description="t('stats.pg.empty')" />
    <NDataTable
      :scrollbar-props="{ trigger: 'none' }"
      v-else
      :columns="columns"
      :data="rows"
      :row-key="(r: Row) => r.pg"
      size="small"
      :scroll-x="1350"
      :max-height="'max(240px, calc(100vh - 400px))'"
    />
  </NSpace>
</template>

<style scoped>
:deep(.expand) {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 24px;
  font-size: 12px;
}
:deep(.bar-row) {
  display: grid;
  grid-template-columns: 90px 1fr 100px;
  align-items: center;
  gap: 8px;
}
:deep(.bar) {
  height: 10px;
  border-radius: 2px;
  background: #2080f0;
  min-width: 1px;
}
:deep(.bar-label),
:deep(.bar-count) {
  font-variant-numeric: tabular-nums;
}
:deep(.bar-count) {
  text-align: right;
}
</style>
