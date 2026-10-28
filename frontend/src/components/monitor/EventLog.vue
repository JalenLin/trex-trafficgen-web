<script setup lang="ts">
import { computed, h } from 'vue'
import { NDataTable, NRadioButton, NRadioGroup, NSpace, NTag, NText, type DataTableColumns } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { LogEvent } from '../../api'
import { persisted } from '../../utils/prefs'

const props = defineProps<{ events: LogEvent[]; logSize: number }>()
const { t, te } = useI18n()

const filter = persisted<'all' | 'gui' | 'trex' | 'warning'>('monitor.eventFilter', 'all')

const shown = computed(() =>
  props.events
    .filter((e) => filter.value === 'all' || (filter.value === 'warning' ? e.level === 'warning' : e.source === filter.value))
    .slice()
    .reverse(),
)

function portsText(ports: unknown): string {
  return Array.isArray(ports) && ports.length ? t('monitor.events.ports', { ports: ports.join(', ') }) : ''
}

function text(e: LogEvent): string {
  if (e.source === 'trex') return e.message
  const p = e.params ?? {}
  const key =
    e.code === 'clearStats' && !(p.ports as unknown[] | undefined)?.length
      ? 'clearStatsAll'
      : e.code === 'rfcEnd'
        ? `rfcEnd${String(p.state).charAt(0).toUpperCase()}${String(p.state).slice(1)}`
        : e.code
  const what = p.what === 'cpu' ? t('monitor.extra.cpu') : p.what === 'xstats' ? t('monitor.extra.xstats') : ''
  const body = te(`monitor.events.${key}`)
    ? t(`monitor.events.${key}`, {
        ...p,
        ports: portsText(p.ports),
        name: e.code === 'captureStop' ? (p.name ? ` → ${p.name}` : '') : p.name,
        what,
        mode: p.mode ? t(`ns.service.${p.mode}`) : '',
      })
    : e.code
  return p.error && e.code !== 'rfcEnd' ? `${body} — ${t('monitor.events.failed', { error: p.error })}` : body
}

const clock = (ts: number) => new Date(ts * 1000).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })

const columns = computed<DataTableColumns<LogEvent>>(() => [
  { title: t('monitor.events.time'), key: 'ts', width: 170, render: (e) => clock(e.ts) },
  {
    title: t('monitor.events.source'),
    key: 'source',
    width: 80,
    render: (e) =>
      h(NTag, { size: 'small', bordered: false, type: e.source === 'gui' ? 'info' : 'default' }, () =>
        e.source === 'gui' ? t('monitor.events.sourceGui') : t('monitor.events.sourceTrex'),
      ),
  },
  { title: t('monitor.events.from'), key: 'client', width: 120, render: (e) => e.client ?? '' },
  {
    title: t('monitor.events.text'),
    key: 'text',
    minWidth: 240,
    render: (e) => h(NText, { type: e.level === 'warning' ? 'warning' : undefined }, () => (e.level === 'warning' ? `⚠ ${text(e)}` : text(e))),
  },
])
</script>

<template>
  <NSpace vertical :size="8">
    <NRadioGroup v-model:value="filter" size="small">
      <NRadioButton value="all">{{ t('monitor.events.filterAll') }}</NRadioButton>
      <NRadioButton value="gui">{{ t('monitor.events.filterGui') }}</NRadioButton>
      <NRadioButton value="trex">{{ t('monitor.events.filterTrex') }}</NRadioButton>
      <NRadioButton value="warning">{{ t('monitor.events.filterWarn') }}</NRadioButton>
    </NRadioGroup>
    <NDataTable
      size="small"
      :columns="columns"
      :data="shown"
      :row-key="(e: LogEvent) => e.seq"
      :max-height="320"
      :scroll-x="600"
      virtual-scroll
    >
      <template #empty>{{ t('monitor.events.empty') }}</template>
    </NDataTable>
    <NText depth="3" style="font-size: 12px">{{ t('monitor.events.keptOnServer', { n: logSize }) }}</NText>
  </NSpace>
</template>
