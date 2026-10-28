<script setup lang="ts">
// Ports wired together across hosts (directly or through a DUT): what one side
// sent against what the other received, both directions.
import { computed, h, ref } from 'vue'
import { NAlert, NButton, NDataTable, NPopconfirm, NSelect, NSpace, NText, useMessage, type DataTableColumns } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { api, type HostSummary, type StatsMessage } from '../../api'
import { useHostsStore } from '../../stores/hosts'
import { formatCount, formatPps } from '../../utils/format'
import { portPairs, type PairEnd } from '../../composables/usePortPairs'

type Stats = Extract<StatsMessage, { type: 'stats' }>
type End = PairEnd

const props = defineProps<{ hosts: HostSummary[]; latest: Record<string, Stats | null> }>()
const { t } = useI18n()
const store = useHostsStore()
const message = useMessage()

const pairs = portPairs

// --- add form ---
const aHost = ref<string | null>(null)
const aPort = ref<number | null>(null)
const bHost = ref<string | null>(null)
const bPort = ref<number | null>(null)
const hostOptions = computed(() => props.hosts.filter((h) => h.connected).map((h) => ({ label: h.name, value: h.id })))
const portOptions = (host: string | null) => (host ? (store.ports[host] ?? []).map((p) => ({ label: t('common.portN', { n: p.id }), value: p.id })) : [])
const same = computed(() => aHost.value === bHost.value && aPort.value === bPort.value)
const canAdd = computed(() => aHost.value && bHost.value && aPort.value != null && bPort.value != null && !same.value)

function add() {
  if (!canAdd.value) return
  pairs.value = [...pairs.value, { a: { host: aHost.value!, port: aPort.value! }, b: { host: bHost.value!, port: bPort.value! } }]
}
function remove(i: number) {
  pairs.value = pairs.value.filter((_, j) => j !== i)
}

// --- comparison rows: two per pair (A→B, B→A) ---
const hostName = (id: string) => props.hosts.find((h) => h.id === id)?.name.split(/[(（]/)[0].trim() ?? id
const endLabel = (e: End) => `${hostName(e.host)} · ${t('common.portN', { n: e.port })}`

interface Row {
  key: string
  pair: number
  first: boolean
  dir: string
  sent: number | null
  received: number | null
  txRate: number | null
  rxRate: number | null
  /** The sending port is still transmitting: the counts are moving, loss isn't final. */
  running: boolean
}
const rows = computed<Row[]>(() =>
  pairs.value.flatMap((p, i) =>
    [
      [p.a, p.b],
      [p.b, p.a],
    ].map(([from, to], k) => {
      const tx = props.latest[from.host]?.ports[from.port]
      const rx = props.latest[to.host]?.ports[to.port]
      return {
        key: `${i}-${k}`,
        pair: i,
        first: k === 0,
        dir: `${endLabel(from)} → ${endLabel(to)}`,
        sent: tx ? tx.opackets : null,
        received: rx ? rx.ipackets : null,
        txRate: tx ? tx.tx_pps : null,
        rxRate: rx ? rx.rx_pps : null,
        running: (store.ports[from.host] ?? []).find((p) => p.id === from.port)?.status === 'TRANSMITTING',
      }
    }),
  ),
)

const dash = () => t('overview.pairs.noData')
const columns = computed<DataTableColumns<Row>>(() => [
  { title: t('overview.pairs.direction'), key: 'dir', minWidth: 230 },
  { title: t('overview.pairs.sent'), key: 'sent', align: 'right', render: (r) => (r.sent == null ? dash() : formatCount(r.sent)) },
  { title: t('overview.pairs.received'), key: 'received', align: 'right', render: (r) => (r.received == null ? dash() : formatCount(r.received)) },
  {
    title: t('overview.pairs.diff'),
    key: 'diff',
    align: 'right',
    render: (r) => (r.sent == null || r.received == null ? dash() : formatCount(r.sent - r.received)),
  },
  {
    title: t('overview.pairs.loss'),
    key: 'loss',
    align: 'right',
    render: (r) => {
      if (r.sent == null || r.received == null || !r.sent) return dash()
      // Two hosts are sampled at slightly different moments: mid-run figures can even go negative.
      if (r.running) return h('span', { style: 'opacity: 0.6' }, t('overview.pairs.running'))
      const pct = ((r.sent - r.received) / r.sent) * 100
      return `${pct.toFixed(Math.abs(pct) < 0.01 && pct ? 4 : 3)} %`
    },
  },
  { title: t('overview.pairs.txRate'), key: 'txr', align: 'right', render: (r) => (r.txRate == null ? dash() : formatPps(r.txRate)) },
  { title: t('overview.pairs.rxRate'), key: 'rxr', align: 'right', render: (r) => (r.rxRate == null ? dash() : formatPps(r.rxRate)) },
  {
    title: '',
    key: 'remove',
    width: 70,
    render: (r) => (r.first ? (h(NButton, { size: 'tiny', quaternary: true, onClick: () => remove(r.pair) }, () => t('overview.pairs.remove'))) : null),
  },
])

// --- clear every host used by a pair ---
const involved = computed(() => [...new Set(pairs.value.flatMap((p) => [p.a.host, p.b.host]))])
const involvedNames = computed(() => involved.value.map(hostName).join(', '))
async function clearAll() {
  try {
    await Promise.all(involved.value.map((id) => api.clearStats(id)))
    message.success(t('overview.pairs.cleared', { hosts: involvedNames.value }))
  } catch (e) {
    message.error((e as Error).message)
  }
}
</script>

<template>
  <NSpace vertical :size="10">
    <NText depth="3" style="font-size: 12px">{{ t('overview.pairs.help') }}</NText>
    <div class="form">
      <span class="end-label">{{ t('overview.pairs.a') }}</span>
      <NSelect v-model:value="aHost" :options="hostOptions" :placeholder="t('overview.pairs.host')" size="small" class="host" @update:value="aPort = null" />
      <NSelect v-model:value="aPort" :options="portOptions(aHost)" :placeholder="t('overview.pairs.port')" size="small" class="port" />
      <span class="arrow">↔</span>
      <span class="end-label">{{ t('overview.pairs.b') }}</span>
      <NSelect v-model:value="bHost" :options="hostOptions" :placeholder="t('overview.pairs.host')" size="small" class="host" @update:value="bPort = null" />
      <NSelect v-model:value="bPort" :options="portOptions(bHost)" :placeholder="t('overview.pairs.port')" size="small" class="port" />
      <NButton size="small" type="primary" :disabled="!canAdd" @click="add">{{ t('overview.pairs.add') }}</NButton>
    </div>
    <NAlert v-if="same && aHost && aPort != null" type="warning" :show-icon="false">{{ t('overview.pairs.sameEnd') }}</NAlert>

    <NText v-if="!pairs.length" depth="3">{{ t('overview.pairs.empty') }}</NText>
    <template v-else>
      <NDataTable size="small" :columns="columns" :data="rows" :row-key="(r: Row) => r.key" :scroll-x="900" />
      <NSpace align="center">
        <NPopconfirm @positive-click="clearAll">
          <template #trigger>
            <NButton size="small">{{ t('overview.pairs.clear') }}</NButton>
          </template>
          {{ t('overview.pairs.clearConfirm', { hosts: involvedNames }) }}
        </NPopconfirm>
        <NText depth="3" style="font-size: 12px">{{ t('overview.pairs.clearNote') }}</NText>
      </NSpace>
    </template>
  </NSpace>
</template>

<style scoped>
.form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
}
.end-label {
  font-size: 13px;
  opacity: 0.75;
}
.host {
  width: 170px;
}
.port {
  width: 110px;
}
.arrow {
  margin: 0 4px;
  opacity: 0.6;
}
</style>
