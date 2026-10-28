<script setup lang="ts">
// RFC 2544 tab: settings + Start, the running/last job, results, and saved runs.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NButton, NCollapse, NCollapseItem, NSpace, NTag, NText, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { api, type Rfc2544Config, type Rfc2544Job, type Rfc2544Summary } from '../../api'
import { persisted } from '../../utils/prefs'
import Rfc2544Form from './Rfc2544Form.vue'
import Rfc2544History from './Rfc2544History.vue'
import Rfc2544Results from './Rfc2544Results.vue'
import Rfc2544Run from './Rfc2544Run.vue'
import { clockSpan, dateTime } from './util'

const props = defineProps<{ hostId: string }>()
const { t } = useI18n()
const message = useMessage()

const open = persisted<string[]>('rfc2544.sections', ['config', 'run', 'results', 'history'])
function expand(...names: string[]) {
  open.value = [...new Set([...open.value, ...names])]
}

// --- current job of this backend session (polled while it runs) ---
const viewed = ref<Rfc2544Job | null>(null) // a history item opened with View
const current = ref<Rfc2544Job | null>(null)
const now = ref(Date.now() / 1000)
const running = computed(() => current.value?.state === 'running')
let timer: number | undefined
let pollFailed = false
let alive = true

function stopPolling() {
  if (timer !== undefined) window.clearTimeout(timer)
  timer = undefined
}
function schedule() {
  stopPolling()
  if (alive && running.value) timer = window.setTimeout(poll, 1000)
}
function apply(job: Rfc2544Job | null) {
  const ended = running.value && job?.id === current.value?.id && job?.state !== 'running'
  current.value = job
  now.value = Date.now() / 1000
  if (ended) loadHistory()
}
async function poll() {
  timer = undefined
  const host = props.hostId
  try {
    const job = await api.rfcCurrent(host)
    if (host !== props.hostId) return
    apply(job)
    pollFailed = false
  } catch (e) {
    if (!pollFailed) message.error((e as Error).message)
    pollFailed = true
  }
  schedule()
}

// --- history ---
const history = ref<Rfc2544Summary[]>([])
const loadingHistory = ref(false)
async function loadHistory() {
  loadingHistory.value = true
  try {
    history.value = await api.rfcHistory(props.hostId)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loadingHistory.value = false
  }
}

watch(
  () => props.hostId,
  () => {
    stopPolling()
    current.value = null
    viewed.value = null
    history.value = []
    poll()
    loadHistory()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  alive = false
  stopPolling()
})

// --- start / stop ---
const busy = ref(false)
async function start(cfg: Rfc2544Config) {
  busy.value = true
  try {
    apply(await api.rfcStart(props.hostId, cfg))
    viewed.value = null
    expand('run', 'results')
    schedule()
  } catch (e) {
    message.error((e as Error).message, { duration: 10000 })
  } finally {
    busy.value = false
  }
}
const stopping = ref(false)
async function stop() {
  stopping.value = true
  try {
    apply(await api.rfcStop(props.hostId))
    message.info(t('rfc2544.run.stopped'))
    schedule()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    stopping.value = false
  }
}

// --- results: a history item when one is opened, else the current job ---
const shown = computed(() => viewed.value ?? current.value)
const resultsBox = ref<HTMLElement | null>(null)
async function view(id: string) {
  try {
    viewed.value = await api.rfcResult(props.hostId, id)
    expand('results')
    await nextTick()
    resultsBox.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (e) {
    message.error((e as Error).message)
  }
}
async function remove(id: string) {
  try {
    await api.rfcDelete(props.hostId, id)
    if (viewed.value?.id === id) viewed.value = null
    message.success(t('rfc2544.history.deleted'))
  } catch (e) {
    message.error((e as Error).message)
  }
  await loadHistory()
}
</script>

<template>
  <div class="rfc-panel">
    <NCollapse v-model:expanded-names="open">
      <NCollapseItem :title="t('rfc2544.sections.config')" name="config">
        <Rfc2544Form :host-id="hostId" :busy="busy" :test-running="running" @start="start" @error="(m) => message.warning(m)" />
      </NCollapseItem>

      <NCollapseItem v-if="current" :title="t('rfc2544.sections.run')" name="run">
        <template #header-extra>
          <NSpace :size="6" align="center" :wrap="false">
            <NTag v-if="running" type="info" size="small" :bordered="false">{{ t('rfc2544.state.running') }}</NTag>
            <NText v-if="running" depth="3" class="mono">{{ clockSpan(now - current.started) }}</NText>
          </NSpace>
        </template>
        <Rfc2544Run :job="current" :now="now" :stopping="stopping" @stop="stop" />
      </NCollapseItem>

      <NCollapseItem v-if="shown" :title="t('rfc2544.sections.results')" name="results">
        <template #header-extra>
          <NText depth="3" class="extra">{{ dateTime(shown.started) }}</NText>
        </template>
        <div ref="resultsBox" class="results-box">
          <div v-if="viewed" class="viewing">
            <NTag size="small" type="success" :bordered="false">{{ t('rfc2544.results.viewingHistory') }}</NTag>
            <NButton size="tiny" quaternary @click="viewed = null">
              {{ current ? t('rfc2544.results.showCurrent') : t('rfc2544.results.close') }}
            </NButton>
          </div>
          <Rfc2544Results :job="shown" />
        </div>
      </NCollapseItem>

      <NCollapseItem :title="t('rfc2544.sections.history')" name="history">
        <template #header-extra>
          <NButton size="tiny" quaternary :loading="loadingHistory" @click.stop="loadHistory">{{ t('common.refresh') }}</NButton>
        </template>
        <Rfc2544History
          :items="history"
          :loading="loadingHistory"
          :viewing-id="viewed?.id ?? null"
          @view="view"
          @delete="remove"
        />
      </NCollapseItem>
    </NCollapse>
    <NText v-if="!current && !history.length && !loadingHistory" depth="3" class="hint">{{ t('rfc2544.run.noJob') }}</NText>
  </div>
</template>

<style scoped>
.rfc-panel {
  min-width: 0;
}
.mono {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}
.extra {
  font-size: 12px;
}
.results-box {
  scroll-margin-top: 8px;
  min-width: 0;
}
.viewing {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.hint {
  display: block;
  font-size: 12px;
  margin-top: 8px;
}
</style>
