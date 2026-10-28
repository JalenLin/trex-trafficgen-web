<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NSpace, NTabPane, NTabs, NTag, NText, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { HostSummary } from '../api'
import { useStatsStream } from '../composables/useStatsStream'
import { useHostsStore } from '../stores/hosts'
import { persisted } from '../utils/prefs'
import MonitorPanel from './monitor/MonitorPanel.vue'
import PcapPanel from './pcap/PcapPanel.vue'
import PgStatsPanel from './PgStatsPanel.vue'
import PortDriftBanner from './profiles/PortDriftBanner.vue'
import ProfilePanel from './ProfilePanel.vue'
import Rfc2544Panel from './rfc2544/Rfc2544Panel.vue'
import SessionIO from './SessionIO.vue'
import PortConfigPanel from './PortConfigPanel.vue'
import PortList from './PortList.vue'
import PortsTable from './PortsTable.vue'
import StatsTable from './StatsTable.vue'
import StreamsPanel from './StreamsPanel.vue'
import TrafficToolbar from './TrafficToolbar.vue'

const props = defineProps<{ host: HostSummary }>()

const store = useHostsStore()
const message = useMessage()
const { t } = useI18n()
const busy = ref(false)
const tab = persisted('hostTab', 'streams')

const version = computed(() => props.host.server_version?.version ?? '')
// One stats stream per host view, shared by the port list and the stats tab.
const { latest, error, socketOpen, disconnected, history, events, monitor, extra } = useStatsStream(computed(() => (props.host.connected ? props.host.id : null)))

// TRex went away (restart, crash): pull the host state so the page shows it as
// disconnected, with the reason, instead of a silently frozen view.
watch(disconnected, (gone) => gone && store.load().catch(() => undefined))

watch(latest, (m) => m && store.mergePortStates(props.host.id, m.port_states))

// The backend may already be connected (another browser, or a page reload).
watch(
  () => props.host.connected,
  (connected) => {
    if (connected && !store.ports[props.host.id]) store.refreshPorts(props.host.id).catch((e) => message.error(e.message))
  },
  { immediate: true },
)

async function toggleConnection() {
  busy.value = true
  try {
    if (props.host.connected) await store.disconnect(props.host.id)
    else await store.connect(props.host.id)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="panel">
    <NSpace align="center" justify="space-between">
      <NSpace align="center">
        <NText strong style="font-size: 18px">{{ host.name }}</NText>
        <NText depth="3" code>{{ host.server }}</NText>
        <NTag v-if="host.connected" type="success" size="small" round>{{ t('layout.connected') }}{{ version ? ` · ${version}` : '' }}</NTag>
        <NTag v-else size="small" round>{{ t('layout.notConnected') }}</NTag>
        <NTag v-if="host.mock" type="warning" size="small" round>Mock</NTag>
      </NSpace>
      <NSpace :size="8">
        <SessionIO v-if="host.connected" :host="host" />
        <NButton :type="host.connected ? 'default' : 'primary'" :loading="busy" @click="toggleConnection">
          {{ host.connected ? t('layout.disconnect') : t('layout.connect') }}
        </NButton>
      </NSpace>
    </NSpace>

    <NAlert v-if="host.last_error && !host.connected" type="error" :title="t('layout.connectFailed')">
      {{ host.last_error }}
    </NAlert>

    <template v-if="host.connected">
      <PortDriftBanner :host="host" />
      <TrafficToolbar :host-id="host.id" />
      <div class="split">
        <div class="ports">
          <PortList :host-id="host.id" :stats="latest?.ports ?? null" />
        </div>
        <NTabs v-model:value="tab" type="line" class="tabs">
          <NTabPane name="streams" tab="Streams">
            <StreamsPanel :host-id="host.id" />
          </NTabPane>
          <NTabPane name="stats" :tab="t('layout.tabStats')" display-directive="show:lazy">
            <StatsTable :host-id="host.id" :latest="latest" :error="error" :socket-open="socketOpen" />
          </NTabPane>
          <NTabPane name="monitor" :tab="t('monitor.tab')" display-directive="show:lazy">
            <MonitorPanel :host-id="host.id" :history="history" :events="events" :settings="monitor" :extra="extra" />
          </NTabPane>
          <NTabPane name="profile" tab="Profile" display-directive="show:lazy">
            <ProfilePanel :host-id="host.id" />
          </NTabPane>
          <NTabPane name="rfc2544" tab="RFC 2544" display-directive="show:lazy">
            <Rfc2544Panel :host-id="host.id" />
          </NTabPane>
          <NTabPane name="pcap" tab="PCAP" display-directive="show:lazy">
            <PcapPanel :host-id="host.id" />
          </NTabPane>
          <NTabPane name="pg" tab="pg / Latency" display-directive="show:lazy">
            <PgStatsPanel :host-id="host.id" :latest="latest" />
          </NTabPane>
          <NTabPane name="config" :tab="t('layout.tabPortConfig')" display-directive="show:lazy">
            <PortConfigPanel :host-id="host.id" />
          </NTabPane>
          <NTabPane name="ports" :tab="t('layout.tabPortDetails')" display-directive="show:lazy">
            <PortsTable :host-id="host.id" />
          </NTabPane>
        </NTabs>
      </div>
    </template>
  </div>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}
.split {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 16px;
  flex: 1;
  min-height: 0;
}
.ports {
  border-right: 1px solid rgba(128, 128, 128, 0.2);
  padding-right: 8px;
  min-height: 0;
  max-height: calc(100vh - 220px);
}
@media (max-width: 1100px) {
  .split {
    grid-template-columns: 230px minmax(0, 1fr);
    gap: 10px;
  }
}
/* Too narrow for side by side: port list on top, scrolling within a short box. */
@media (max-width: 860px) {
  .split {
    grid-template-columns: minmax(0, 1fr);
  }
  .ports {
    border-right: none;
    border-bottom: 1px solid rgba(128, 128, 128, 0.2);
    padding: 0 0 8px;
    /* a fixed height: the list scrolls inside it (max-height alone collapses it) */
    height: 220px;
    max-height: none;
  }
}
.tabs {
  min-width: 0;
}
</style>
