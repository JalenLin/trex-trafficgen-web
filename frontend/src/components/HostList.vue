<script setup lang="ts">
import { NBadge, NText, NThing, NTooltip } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { HostSummary } from '../api'
import { useHostsStore } from '../stores/hosts'

/** compact: the collapsed sidebar, a narrow strip of status dots and short names. */
defineProps<{ compact?: boolean }>()

const store = useHostsStore()
const { t } = useI18n()

// "itxpc (v3.08)" -> "itxpc"; long names are cut, the tooltip has the rest.
const short = (h: HostSummary) => {
  const word = h.name.split(/[(（]/)[0].trim() || h.id
  return word.length > 6 ? word.slice(0, 5) + '…' : word
}
const dotType = (h: HostSummary) => (h.connected ? 'success' : 'error')
const dotColor = (h: HostSummary) => (h.connected || h.last_error ? undefined : 'rgba(128, 128, 128, 0.5)')
function pick(id: string) {
  store.selectedId = id
  store.view = 'host'
}
const state = (h: HostSummary) =>
  t(h.connected ? 'layout.connected' : h.last_error ? 'layout.connectFailed' : 'layout.notConnected')
</script>

<template>
  <div v-if="compact" class="compact">
    <NTooltip v-if="store.hosts.length" placement="right">
      <template #trigger>
        <div class="citem" :class="{ active: store.view === 'overview' }" @click="store.view = 'overview'">
          <span class="grid-icon">▦</span>
          <span class="cname">{{ t('overview.navShort') }}</span>
        </div>
      </template>
      {{ t('overview.nav') }}
    </NTooltip>
    <NTooltip v-for="h in store.hosts" :key="h.id" placement="right">
      <template #trigger>
        <div class="citem" :class="{ active: store.view === 'host' && h.id === store.selectedId }" @click="pick(h.id)">
          <NBadge dot :type="dotType(h)" :color="dotColor(h)" :processing="h.connected" />
          <span class="cname">{{ short(h) }}</span>
        </div>
      </template>
      {{ h.name }}<br />{{ h.server }} · {{ state(h) }}
    </NTooltip>
  </div>

  <div v-else class="list">
    <div v-if="store.hosts.length" class="item overview" :class="{ active: store.view === 'overview' }" @click="store.view = 'overview'">
      <span class="grid-icon">▦</span> {{ t('overview.nav') }}
    </div>
    <NText depth="3" class="title">{{ t('layout.hosts') }}</NText>
    <div
      v-for="h in store.hosts"
      :key="h.id"
      class="item"
      :class="{ active: store.view === 'host' && h.id === store.selectedId }"
      @click="pick(h.id)"
    >
      <NThing>
        <template #avatar>
          <NBadge dot :type="dotType(h)" :color="dotColor(h)" :processing="h.connected" />
        </template>
        <template #header>{{ h.name }}</template>
        <template #description>
          <NText depth="3" class="server">{{ h.server }}</NText>
        </template>
      </NThing>
    </div>
  </div>
</template>

<style scoped>
.title {
  display: block;
  font-size: 12px;
  padding: 4px 8px 8px;
}
.item {
  padding: 8px;
  border-radius: 4px;
  cursor: pointer;
}
.item:hover,
.citem:hover {
  background: var(--n-color-hover, rgba(128, 128, 128, 0.08));
}
.item.active,
.citem.active {
  background: rgba(24, 160, 88, 0.12);
}
.overview {
  margin-bottom: 4px;
  font-size: 14px;
}
.grid-icon {
  opacity: 0.7;
}
.server {
  font-size: 12px;
  font-family: monospace;
}
.compact {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 4px;
}
.citem {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 2px;
  border-radius: 4px;
  cursor: pointer;
}
.cname {
  font-size: 11px;
  line-height: 1.2;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
}
</style>
