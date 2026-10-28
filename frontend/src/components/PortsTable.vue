<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { NButton, NDataTable, NSpace, NTag, useMessage, type DataTableColumns } from 'naive-ui'
import type { PortInfo } from '../api'
import { useHostsStore } from '../stores/hosts'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ hostId: string }>()

const store = useHostsStore()
const message = useMessage()
const { t } = useI18n()
const loading = ref(false)

const ports = computed(() => store.ports[props.hostId] ?? [])
// Read-only overview. Ticking ports for bulk actions happens in the port list on
// the left; a row click here focuses the port, like clicking it in that list.
const focused = computed(() => store.focused[props.hostId])
const rowProps = (p: PortInfo) => ({
  style: 'cursor: pointer',
  onClick: () => (store.focused[props.hostId] = p.id),
})
const rowClass = (p: PortInfo) => (p.id === focused.value ? 'focused' : '')

async function refresh() {
  loading.value = true
  try {
    await store.refreshPorts(props.hostId)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

const statusType = (s: string) => (s === 'TRANSMITTING' ? 'success' : s === 'PAUSE' ? 'warning' : 'default')

const columns = computed<DataTableColumns<PortInfo>>(() => [
  { title: t('common.port'), key: 'id', width: 64 },
  {
    title: t('ports.col.link'),
    key: 'link',
    width: 80,
    render: (p) => h(NTag, { size: 'small', type: p.link === 'UP' ? 'success' : 'error', bordered: false }, () => p.link),
  },
  { title: t('ports.col.speed'), key: 'speed_gbps', width: 90, render: (p) => `${p.speed_gbps} Gb/s` },
  {
    title: t('ports.col.status'),
    key: 'status',
    width: 130,
    render: (p) => h(NTag, { size: 'small', type: statusType(p.status), bordered: false }, () => p.status),
  },
  {
    title: t('ports.col.owner'),
    key: 'owner',
    width: 140,
    render: (p) =>
      p.acquired
        ? h(NTag, { size: 'small', type: 'info' }, () => t('ports.ownerMe', { owner: p.owner }))
        : p.owner || h('span', { style: 'opacity: .5' }, '—'),
  },
  { title: t('ports.col.mode'), key: 'mode', width: 60, render: (p) => p.layer?.mode ?? '' },
  {
    title: t('ports.col.dest'),
    key: 'dest',
    width: 330,
    render: (p) => {
      const l = p.layer
      if (!l) return ''
      if (l.mode === 'L2') return l.dst_mac
      const arp = l.arp === 'resolved' ? 'success' : 'error'
      return h(NSpace, { size: 4, align: 'center' }, () => [
        `${l.ipv4_src} → ${l.ipv4_dst}`,
        h(NTag, { size: 'tiny', type: arp, bordered: false }, () => (l.arp === 'resolved' ? t('ports.resolved') : t('ports.unresolved'))),
      ])
    },
  },
  { title: t('ports.col.driver'), key: 'driver', width: 110 },
  { title: t('ports.col.description'), key: 'description', ellipsis: { tooltip: true } },
  { title: 'MAC', key: 'hw_mac', width: 160 },
  { title: 'VLAN', key: 'vlan', width: 90, render: (p) => (p.layer?.vlan.length ? p.layer.vlan.join(' / ') : '—') },
  { title: t('ports.col.promisc'), key: 'prom', width: 80, render: (p) => (p.layer?.promiscuous ? t('common.on') : t('common.off')) },
  {
    title: t('ports.col.flowCtrl'),
    key: 'fc',
    width: 90,
    render: (p) => (p.layer?.flow_ctrl == null ? t('ports.unsupported') : [t('common.off'), 'TX', 'RX', 'TX+RX'][p.layer.flow_ctrl]),
  },
])
</script>

<template>
  <NSpace vertical>
    <NButton size="small" quaternary :loading="loading" @click="refresh">{{ t('common.refresh') }}</NButton>
    <NDataTable
      :scrollbar-props="{ trigger: 'none' }"
      :row-props="rowProps"
      :row-class-name="rowClass"
      :columns="columns"
      :scroll-x="1500"
      :data="ports"
      :row-key="(p: PortInfo) => p.id"
      size="small"
      :max-height="'max(240px, calc(100vh - 340px))'"
    />
  </NSpace>
</template>

<style scoped>
:deep(.focused td) {
  background: rgba(24, 160, 88, 0.12) !important;
}
</style>
