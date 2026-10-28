<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NCollapse, NCollapseItem, NRadioButton, NRadioGroup, NSpace, NSwitch, NText } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { LogEvent, MonitorExtra, MonitorSettings } from '../../api'
import { HISTORY_SECONDS, type RateSample } from '../../composables/useStatsStream'
import { useHostsStore } from '../../stores/hosts'
import { persisted } from '../../utils/prefs'
import EventLog from './EventLog.vue'
import ExtraMonitor from './ExtraMonitor.vue'
import RateChart from './RateChart.vue'

const props = defineProps<{
  hostId: string
  history: RateSample[]
  events: LogEvent[]
  settings: MonitorSettings | null
  extra: MonitorExtra | null
}>()
const { t } = useI18n()
const hosts = useHostsStore()

const EVENT_LOG_SIZE = 500 // backend hosts.EVENT_LOG_SIZE

const metric = persisted<'bps' | 'pps'>('monitor.metric', 'bps')
const scope = persisted<'total' | 'tx' | 'rx'>('monitor.scope', 'total')
const windowMin = persisted('monitor.windowMin', 5)
const showTable = persisted('monitor.table', false)
const open = persisted<string[]>('monitor.sections', ['chart', 'events'])

const allPorts = computed(() => (hosts.ports[props.hostId] ?? []).map((p) => p.id))
const chartPorts = computed(() => {
  const ticked = hosts.checked[props.hostId] ?? []
  return ticked.length ? [...ticked].sort((a, b) => a - b) : allPorts.value
})
const capped = computed(() => scope.value !== 'total' && chartPorts.value.length > 8)
</script>

<template>
  <NSpace vertical :size="10">
    <NText depth="3" style="font-size: 12px">{{ t('monitor.noLoadNote') }}</NText>
    <NCollapse v-model:expanded-names="open">
      <NCollapseItem :title="t('monitor.chart.title')" name="chart">
        <NCard size="small" :bordered="false" content-style="padding: 0">
          <div class="controls">
            <NRadioGroup v-model:value="scope" size="small">
              <NRadioButton value="total">{{ t('monitor.chart.total') }}</NRadioButton>
              <NRadioButton value="tx">{{ t('monitor.chart.perPortTx') }}</NRadioButton>
              <NRadioButton value="rx">{{ t('monitor.chart.perPortRx') }}</NRadioButton>
            </NRadioGroup>
            <NRadioGroup v-model:value="metric" size="small">
              <NRadioButton value="bps">bps</NRadioButton>
              <NRadioButton value="pps">pps</NRadioButton>
            </NRadioGroup>
            <NRadioGroup v-model:value="windowMin" size="small">
              <NRadioButton v-for="n in [1, 5, 15]" :key="n" :value="n">{{ t('monitor.chart.minutes', { n }) }}</NRadioButton>
            </NRadioGroup>
            <label class="table-toggle">
              <NSwitch v-model:value="showTable" size="small" />
              <span>{{ t('monitor.chart.table') }}</span>
            </label>
          </div>
          <RateChart
            :history="history"
            :port-ids="chartPorts"
            :metric="metric"
            :scope="scope"
            :window-sec="windowMin * 60"
            :show-table="showTable"
          />
          <NText v-if="capped" depth="3" class="note">{{ t('monitor.chart.capped', { max: 8, n: chartPorts.length }) }}</NText>
          <NText depth="3" class="note">
            {{ t('monitor.chart.keptInBrowser', { n: HISTORY_SECONDS / 60 }) }}
            <template v-if="!(hosts.checked[hostId] ?? []).length">{{ t('monitor.chart.noPorts') }}</template>
          </NText>
        </NCard>
      </NCollapseItem>
      <NCollapseItem :title="t('monitor.events.title')" name="events">
        <EventLog :events="events" :log-size="EVENT_LOG_SIZE" />
      </NCollapseItem>
      <NCollapseItem :title="t('monitor.extra.title')" name="extra">
        <ExtraMonitor :host-id="hostId" :settings="settings" :extra="extra" :events="events" :port-count="allPorts.length" />
      </NCollapseItem>
    </NCollapse>
  </NSpace>
</template>

<style scoped>
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  margin-bottom: 8px;
}
.table-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
}
.note {
  display: block;
  font-size: 12px;
  margin-top: 4px;
}
</style>
