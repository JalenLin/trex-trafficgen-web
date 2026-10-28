<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NCheckbox, NScrollbar, NSpace, NTag, NText } from 'naive-ui'
import type { PortStats } from '../api'
import { useHostsStore } from '../stores/hosts'
import { formatBps } from '../utils/format'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ hostId: string; stats: Record<string, PortStats> | null }>()

const store = useHostsStore()
const { t } = useI18n()

const ports = computed(() => store.ports[props.hostId] ?? [])
const checked = computed({
  get: () => store.checked[props.hostId] ?? [],
  set: (v: number[]) => (store.checked[props.hostId] = [...v].sort((a, b) => a - b)),
})
const focused = computed(() => store.focused[props.hostId])

const allChecked = computed(() => ports.value.length > 0 && checked.value.length === ports.value.length)
const someChecked = computed(() => checked.value.length > 0 && !allChecked.value)

function toggle(pid: number, on: boolean) {
  checked.value = on ? [...checked.value, pid] : checked.value.filter((p) => p !== pid)
}
const selectAll = (on: boolean) => (checked.value = on ? ports.value.map((p) => p.id) : [])
const selectMine = () => (checked.value = ports.value.filter((p) => p.acquired).map((p) => p.id))

const STATUS = computed<Record<string, { label: string; type: 'success' | 'warning' | 'default' }>>(() => ({
  TRANSMITTING: { label: t('ports.status.transmitting'), type: 'success' },
  PAUSE: { label: t('ports.status.paused'), type: 'warning' },
  IDLE: { label: t('ports.status.idle'), type: 'default' },
}))
</script>

<template>
  <div class="port-list">
    <div class="head">
      <NCheckbox :checked="allChecked" :indeterminate="someChecked" @update:checked="selectAll">
        <NText depth="2">{{ t('ports.checkedCount', { n: checked.length, total: ports.length }) }}</NText>
      </NCheckbox>
      <NSpace :size="4">
        <NButton size="tiny" quaternary @click="selectMine">{{ t('common.mine') }}</NButton>
        <NButton size="tiny" quaternary @click="selectAll(false)">{{ t('common.clear') }}</NButton>
      </NSpace>
    </div>
    <NScrollbar class="scroll">
      <div
        v-for="p in ports"
        :key="p.id"
        class="row"
        :class="{ focused: p.id === focused }"
        @click="store.focused[hostId] = p.id"
      >
        <NCheckbox :checked="checked.includes(p.id)" @click.stop @update:checked="(v: boolean) => toggle(p.id, v)" />
        <span class="link" :class="p.link === 'UP' ? 'up' : 'down'" :title="t('ports.linkState', { state: p.link })" />
        <span class="name">Port {{ p.id }}</span>
        <NTag size="tiny" :type="STATUS[p.status]?.type ?? 'default'" :bordered="false">
          {{ STATUS[p.status]?.label ?? p.status }}
        </NTag>
        <span class="owner" :title="p.owner ? t('ports.ownerTitle', { owner: p.owner }) : t('ports.noOwner')">
          <NTag v-if="p.acquired" size="tiny" type="info" :bordered="false">{{ t('ports.me') }}</NTag>
          <NText v-else-if="p.owner" depth="3">{{ p.owner }}</NText>
        </span>
        <!-- An unresolved port cannot transmit, so its rate slot shows why instead. -->
        <NTag
          v-if="p.layer?.arp === 'unresolved'"
          size="tiny"
          type="error"
          :bordered="false"
          :title="t('ports.arpUnresolvedTitle', { ip: p.layer.ipv4_dst })"
          >{{ t('ports.arpUnresolvedTag') }}</NTag
        >
        <NText v-else class="rate" depth="3">{{ stats?.[p.id] ? formatBps(stats[p.id].tx_bps_L1) : '' }}</NText>
      </div>
    </NScrollbar>
  </div>
</template>

<style scoped>
.port-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px 8px;
}
.scroll {
  flex: 1;
  min-height: 0;
}
.row {
  display: grid;
  grid-template-columns: 20px 10px 56px 50px 1fr auto;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}
/* In the 230px list the owner needs the room; rates are on the stats tab.
   (An "ARP 未解析" tag in that slot stays.) */
@media (max-width: 1100px) {
  .row {
    grid-template-columns: 20px 10px 52px 46px minmax(0, 1fr) auto;
    gap: 4px;
  }
  .rate {
    display: none;
  }
}
.row:hover {
  background: rgba(128, 128, 128, 0.08);
}
.row.focused {
  background: rgba(24, 160, 88, 0.14);
}
.link {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.link.up {
  background: #18a058;
}
.link.down {
  background: #d03050;
}
.owner {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.rate {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: right;
}
</style>
