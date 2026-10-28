<script setup lang="ts">
import { computed, h } from 'vue'
import {
  NAlert, NButton, NDataTable, NRadioButton, NRadioGroup, NSpace, NStatistic, NSwitch, NText, useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { api, type PortStats, type StatsMessage } from '../api'
import { useI18n } from 'vue-i18n'
import { useHostsStore } from '../stores/hosts'
import { formatBps, formatBytes, formatCount, formatPercent, formatPps } from '../utils/format'
import { persisted } from '../utils/prefs'

const props = defineProps<{
  hostId: string
  latest: Extract<StatsMessage, { type: 'stats' }> | null
  error: string | null
  socketOpen: boolean
}>()

const store = useHostsStore()
const message = useMessage()
const { t } = useI18n()

const METRIC_DEFS: { key: keyof PortStats; short: string; fmt: (v: number) => string }[] = [
  { key: 'tx_pps', short: 'TX pps', fmt: formatPps },
  { key: 'rx_pps', short: 'RX pps', fmt: formatPps },
  { key: 'tx_bps_L1', short: 'TX L1', fmt: formatBps },
  { key: 'rx_bps_L1', short: 'RX L1', fmt: formatBps },
  { key: 'tx_bps', short: 'TX L2', fmt: formatBps },
  { key: 'rx_bps', short: 'RX L2', fmt: formatBps },
  { key: 'tx_util', short: 'TX %', fmt: formatPercent },
  { key: 'rx_util', short: 'RX %', fmt: formatPercent },
  { key: 'opackets', short: '', fmt: formatCount },
  { key: 'ipackets', short: '', fmt: formatCount },
  { key: 'obytes', short: 'TX Bytes', fmt: formatBytes },
  { key: 'ibytes', short: 'RX Bytes', fmt: formatBytes },
  { key: 'oerrors', short: '', fmt: formatCount },
  { key: 'ierrors', short: '', fmt: formatCount },
]
// Labels follow the UI language; short names that are plain units stay as they are.
const METRICS = computed(() =>
  METRIC_DEFS.map((m) => ({ ...m, label: t(`stats.metric.${m.key}`), short: m.short || t(`stats.short.${m.key}`) })),
)

const onlyChecked = persisted('stats.onlyChecked', true)
const allPortIds = computed(() => Object.keys(props.latest?.ports ?? {}).map(Number))
const checked = computed(() => store.checked[props.hostId] ?? [])
const portIds = computed(() =>
  onlyChecked.value && checked.value.length ? allPortIds.value.filter((p) => checked.value.includes(p)) : allPortIds.value,
)
// With many ports, one row per port reads better than one column per port.
const layout = persisted<'auto' | 'columns' | 'rows'>('stats.layout', 'auto')
const portsAsRows = computed(() => (layout.value === 'auto' ? portIds.value.length > 4 : layout.value === 'rows'))

type Row = { key: string } & Record<string, string>

const rows = computed<Row[]>(() => {
  const ports = props.latest?.ports ?? {}
  if (portsAsRows.value) {
    return portIds.value.map((pid) => {
      const row: Row = { key: String(pid), port: t('common.portN', { n: pid }) }
      for (const m of METRICS.value) row[m.key] = m.fmt(ports[pid]?.[m.key] ?? 0)
      return row
    })
  }
  return METRICS.value.map((m) => {
    const row: Row = { key: m.key, label: m.label }
    for (const pid of portIds.value) row[pid] = m.fmt(ports[pid]?.[m.key] ?? 0)
    return row
  })
})

const columns = computed<DataTableColumns<Row>>(() =>
  portsAsRows.value
    ? [
        { title: 'Port', key: 'port', width: 80, fixed: 'left' },
        ...METRICS.value.map((m) => ({ title: m.short, key: m.key, align: 'right' as const, minWidth: 110 })),
      ]
    : [
        { title: '', key: 'label', width: 140, fixed: 'left', render: (r) => h(NText, { depth: 2 }, () => r.label) },
        ...portIds.value.map((pid) => ({ title: t('common.portN', { n: pid }), key: String(pid), align: 'right' as const, minWidth: 120 })),
      ],
)
const scrollX = computed(() => (portsAsRows.value ? 80 + METRICS.value.length * 110 : 140 + portIds.value.length * 120))

const g = computed(() => props.latest?.global ?? {})

async function clearStats() {
  try {
    await api.clearStats(props.hostId)
    message.success(t('stats.cleared'))
  } catch (e) {
    message.error((e as Error).message)
  }
}
</script>

<template>
  <NSpace vertical :size="12">
    <NSpace justify="space-between" align="center">
      <NSpace :size="32">
        <NStatistic :label="t('stats.totalTx')" :value="formatBps(g.tx_bps ?? 0)" />
        <NStatistic :label="t('stats.totalRx')" :value="formatBps(g.rx_bps ?? 0)" />
        <NStatistic :label="t('stats.totalTxPps')" :value="formatPps(g.tx_pps ?? 0)" />
        <NStatistic label="TRex CPU" :value="formatPercent(g.cpu_util ?? 0)" />
      </NSpace>
      <NButton @click="clearStats">{{ t('stats.clear') }}</NButton>
    </NSpace>
    <NSpace align="center" :size="16">
      <NSpace align="center" :size="6">
        <NSwitch v-model:value="onlyChecked" size="small" :disabled="!checked.length" />
        <NText depth="2">{{ t('stats.onlyChecked', { n: checked.length || t('stats.noneCheckedAll') }) }}</NText>
      </NSpace>
      <NRadioGroup v-model:value="layout" size="small">
        <NRadioButton value="auto">{{ t('stats.layoutAuto') }}</NRadioButton>
        <NRadioButton value="columns">{{ t('stats.layoutColumns') }}</NRadioButton>
        <NRadioButton value="rows">{{ t('stats.layoutRows') }}</NRadioButton>
      </NRadioGroup>
    </NSpace>
    <NAlert v-if="error" type="warning" :title="t('stats.updateFailed')">{{ error }}</NAlert>
    <NAlert v-else-if="!socketOpen" type="info">{{ t('stats.connecting') }}</NAlert>
    <NDataTable
      :scrollbar-props="{ trigger: 'none' }"
      :columns="columns"
      :data="rows"
      :row-key="(r: Row) => r.key"
      size="small"
      :scroll-x="scrollX"
      :max-height="'max(240px, calc(100vh - 420px))'"
    />
  </NSpace>
</template>
