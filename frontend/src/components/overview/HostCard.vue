<script setup lang="ts">
// One host in the overview: totals, every port's rates and a small chart. Uses the
// same shared stats stream as the host panel (no extra requests to TRex).
import { computed, h, watch } from 'vue'
import { NButton, NDataTable, NSpace, NTag, NText, useMessage, type DataTableColumns } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { HostSummary, PortInfo, StatsMessage } from '../../api'
import { useStatsStream } from '../../composables/useStatsStream'
import { useHostsStore } from '../../stores/hosts'
import { formatBps, formatPercent, formatPps } from '../../utils/format'
import RateChart from '../monitor/RateChart.vue'

const props = defineProps<{ host: HostSummary }>()
const emit = defineEmits<{ latest: [msg: Extract<StatsMessage, { type: 'stats' }> | null] }>()

const { t } = useI18n()
const store = useHostsStore()
const message = useMessage()

const { latest, history, disconnected } = useStatsStream(computed(() => (props.host.connected ? props.host.id : null)))
watch(latest, (m) => {
  emit('latest', m)
  if (m) store.mergePortStates(props.host.id, m.port_states)
})
watch(disconnected, (gone) => gone && store.load().catch(() => undefined))
watch(
  () => props.host.connected,
  (connected) => {
    if (connected && !store.ports[props.host.id]) store.refreshPorts(props.host.id).catch((e) => message.error(e.message))
    if (!connected) emit('latest', null)
  },
  { immediate: true },
)

async function connect() {
  try {
    await store.connect(props.host.id)
  } catch (e) {
    message.error((e as Error).message)
  }
}
function open() {
  store.selectedId = props.host.id
  store.view = 'host'
}

const ports = computed(() => store.ports[props.host.id] ?? [])
const portIds = computed(() => ports.value.map((p) => p.id))
const g = computed(() => latest.value?.global ?? {})

const STATUS: Record<string, { key: string; type: 'success' | 'warning' | 'default' }> = {
  TRANSMITTING: { key: 'ports.status.transmitting', type: 'success' },
  PAUSE: { key: 'ports.status.paused', type: 'warning' },
  IDLE: { key: 'ports.status.idle', type: 'default' },
}
const rate = (p: PortInfo, k: 'tx_bps' | 'rx_bps' | 'tx_pps' | 'rx_pps') => latest.value?.ports[p.id]?.[k] ?? 0
const columns = computed<DataTableColumns<PortInfo>>(() => [
  { title: t('overview.col.port'), key: 'id', width: 56 },
  {
    title: t('overview.col.status'),
    key: 'status',
    width: 110,
    render: (p) => {
      const s = STATUS[p.status] ?? { key: '', type: 'default' as const }
      return h(NSpace, { size: 4, wrap: false }, () => [
        h(NTag, { size: 'small', bordered: false, type: s.type }, () => (s.key ? t(s.key) : p.status)),
        p.acquired ? h(NTag, { size: 'small', bordered: false, type: 'info' }, () => t('overview.mine')) : null,
      ])
    },
  },
  // bps over pps in one cell, like the totals above: four number columns don't fit a
  // card when three cards share a row.
  ...(['tx', 'rx'] as const).map((dir) => ({
    title: t(`overview.col.${dir}`),
    key: dir,
    align: 'right' as const,
    minWidth: 100,
    render: (p: PortInfo) =>
      h('div', { class: 'num' }, [
        h('div', formatBps(rate(p, `${dir}_bps`))),
        h('div', { class: 'pps' }, formatPps(rate(p, `${dir}_pps`))),
      ]),
  })),
])
</script>

<template>
  <div class="card">
    <NSpace align="center" justify="space-between" :wrap="false">
      <NSpace align="center" :size="8">
        <NText strong style="font-size: 16px">{{ host.name }}</NText>
        <NText depth="3" code>{{ host.server }}</NText>
        <NTag v-if="!host.connected" size="small" round>{{ t('overview.notConnected') }}</NTag>
      </NSpace>
      <NButton v-if="host.connected" size="small" quaternary @click="open">{{ t('overview.open') }} →</NButton>
      <NButton v-else size="small" type="primary" @click="connect">{{ t('overview.connect') }}</NButton>
    </NSpace>

    <template v-if="host.connected">
      <div class="totals">
        <div>
          <NText depth="3" class="k">{{ t('overview.totalTx') }}</NText>
          <div class="v">{{ formatBps(g.tx_bps ?? 0) }}</div>
          <NText depth="3" class="sub">{{ formatPps(g.tx_pps ?? 0) }}</NText>
        </div>
        <div>
          <NText depth="3" class="k">{{ t('overview.totalRx') }}</NText>
          <div class="v">{{ formatBps(g.rx_bps ?? 0) }}</div>
          <NText depth="3" class="sub">{{ formatPps(g.rx_pps ?? 0) }}</NText>
        </div>
        <div>
          <NText depth="3" class="k">{{ t('overview.cpu') }}</NText>
          <div class="v">{{ formatPercent(g.cpu_util ?? 0) }}</div>
        </div>
      </div>
      <NDataTable
        size="small"
        :columns="columns"
        :data="ports"
        :row-key="(p: PortInfo) => p.id"
        :max-height="260"
        :scroll-x="380"
      />
      <RateChart
        :history="history"
        :port-ids="portIds"
        metric="bps"
        scope="total"
        :window-sec="300"
        :show-table="false"
        :height="150"
      />
    </template>
    <NText v-else-if="host.last_error" type="error" style="font-size: 12px">{{ host.last_error }}</NText>
  </div>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid rgba(128, 128, 128, 0.22);
  border-radius: 6px;
}
.totals {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.k,
.sub {
  font-size: 12px;
}
.card :deep(.num) {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.card :deep(.pps) {
  font-size: 12px;
  opacity: 0.6;
}
.v {
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}
</style>
