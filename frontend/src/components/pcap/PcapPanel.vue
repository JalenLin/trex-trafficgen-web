<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  NAlert, NButton, NCheckbox, NCheckboxGroup, NDataTable, NDivider, NInput, NInputNumber, NPopconfirm, NProgress,
  NRadioButton, NRadioGroup, NSpace, NTag, NText, useMessage, type DataTableColumns,
} from 'naive-ui'
import { api, uploadPcap, type CaptureStatus, type PcapMeta } from '../../api'
import { useI18n } from 'vue-i18n'
import { useHostsStore } from '../../stores/hosts'
import { formatBytes } from '../../utils/format'
import { persisted } from '../../utils/prefs'
import PcapPreviewDialog from './PcapPreviewDialog.vue'
import PushDialog from './PushDialog.vue'

const props = defineProps<{ hostId: string }>()

const hosts = useHostsStore()
const message = useMessage()
const { t } = useI18n()

// --- library ---
const pcaps = ref<PcapMeta[]>([])
const loading = ref(false)
async function refresh() {
  loading.value = true
  try {
    pcaps.value = await api.listPcaps()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

const fileInput = ref<HTMLInputElement | null>(null)
const progress = ref<number | null>(null)
async function onFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  progress.value = 0
  try {
    const meta = await uploadPcap(file, (f) => (progress.value = Math.round(f * 100)))
    message.success(t('pcap.uploaded', { name: meta.name, packets: meta.packets.toLocaleString() }, meta.packets))
    await refresh()
  } catch (e) {
    message.error(t('pcap.uploadFailed', { error: (e as Error).message }), { duration: 8000 })
  } finally {
    progress.value = null
  }
}

const previewOf = ref<PcapMeta | null>(null)
const previewOpen = ref(false)
const pushOf = ref<PcapMeta | null>(null)
const pushOpen = ref(false)

const renaming = ref<Record<string, string>>({})
async function act(done: string, action: () => Promise<unknown>) {
  try {
    await action()
    if (done) message.success(done)
    await refresh()
  } catch (e) {
    message.error((e as Error).message)
  }
}

const columns = computed<DataTableColumns<PcapMeta>>(() => [
  {
    title: t('common.name'),
    key: 'name',
    minWidth: 170,
    render: (m) =>
      h(NInput, {
        size: 'small',
        value: renaming.value[m.id] ?? m.name,
        'onUpdate:value': (v: string) => (renaming.value[m.id] = v),
        onBlur: () => {
          const v = renaming.value[m.id]?.trim()
          delete renaming.value[m.id]
          if (v && v !== m.name) act(t('pcap.renamed'), () => api.renamePcap(m.id, v))
        },
      }),
  },
  {
    title: t('pcap.col.source'),
    key: 'source',
    width: 70,
    render: (m) => h(NTag, { size: 'small', bordered: false, type: m.source === 'capture' ? 'info' : 'default' }, () => (m.source === 'capture' ? t('pcap.sourceCapture') : t('pcap.sourceUpload'))),
  },
  { title: t('pcap.col.packets'), key: 'packets', width: 90, align: 'right', render: (m) => m.packets.toLocaleString() },
  { title: t('pcap.col.duration'), key: 'duration_s', width: 90, align: 'right', render: (m) => `${m.duration_s.toFixed(3)} s` },
  { title: t('pcap.col.size'), key: 'size', width: 90, align: 'right', render: (m) => formatBytes(m.size) },
  { title: t('pcap.col.created'), key: 'created_at', width: 140, render: (m) => m.created_at.replace('T', ' ').slice(0, 16) },
  {
    title: '',
    key: 'actions',
    width: 270,
    fixed: 'right',
    render: (m) =>
      h(NSpace, { size: 2, wrap: false }, () => [
        h(NButton, { size: 'tiny', type: 'primary', onClick: () => ((pushOf.value = m), (pushOpen.value = true)) }, () => t('pcap.replayButton')),
        h(NButton, { size: 'tiny', onClick: () => ((previewOf.value = m), (previewOpen.value = true)) }, () => t('pcap.previewButton')),
        h('a', { href: api.pcapDownloadUrl(m.id), download: '' }, h(NButton, { size: 'tiny', quaternary: true }, () => t('common.download'))),
        h(NPopconfirm, { onPositiveClick: () => act(t('pcap.deleted'), () => api.deletePcap(m.id)) }, {
          trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, () => t('common.delete')),
          default: () => t('pcap.confirmDelete', { name: m.name }),
        }),
      ]),
  },
])

// --- capture ---
const ports = computed(() => (hosts.ports[props.hostId] ?? []).filter((p) => p.acquired))
const cap = persisted('pcap.capture', { tx: [] as number[], rx: [] as number[], limit: 1000, mode: 'fixed', bpf: '', service: true })
const captures = ref<CaptureStatus[]>([])
const capName = ref<Record<number, string>>({})
const capBusy = ref(false)
let poll: ReturnType<typeof setInterval> | undefined

async function loadCaptures() {
  try {
    captures.value = await api.captures(props.hostId)
  } catch {
    /* host disconnected: the panel says so elsewhere */
  }
}
// Local time, e.g. capture-20261028-152301
const defaultName = () => {
  const d = new Date()
  const two = (n: number) => String(n).padStart(2, '0')
  return `capture-${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}-${two(d.getHours())}${two(d.getMinutes())}${two(d.getSeconds())}`
}

async function startCapture() {
  capBusy.value = true
  try {
    const r = await api.startCapture(props.hostId, {
      tx_ports: cap.value.tx, rx_ports: cap.value.rx, limit: cap.value.limit, mode: cap.value.mode, bpf_filter: cap.value.bpf, service: cap.value.service,
    })
    capName.value[r.id] = defaultName()
    message.success(t('pcap.captureStarted'))
    await loadCaptures()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    capBusy.value = false
  }
}

async function stopCapture(c: CaptureStatus, save: boolean) {
  capBusy.value = true
  try {
    const meta = await api.stopCapture(props.hostId, c.id, save, capName.value[c.id] || defaultName())
    if (meta) message.success(t('pcap.savedAs', { name: meta.name, packets: meta.packets.toLocaleString() }, meta.packets))
    await Promise.all([loadCaptures(), refresh()])
  } catch (e) {
    message.error((e as Error).message)
    await loadCaptures()
  } finally {
    capBusy.value = false
  }
}

onMounted(() => {
  refresh()
  loadCaptures()
  poll = setInterval(() => captures.value.length && loadCaptures(), 1000)
})
onBeforeUnmount(() => clearInterval(poll))
watch(() => props.hostId, () => loadCaptures())
</script>

<template>
  <NSpace vertical :size="12">
    <NSpace align="center" justify="space-between">
      <NText strong>{{ t('pcap.library') }}</NText>
      <NSpace align="center">
        <NProgress v-if="progress !== null" type="line" :percentage="progress" style="width: 160px" />
        <NButton size="small" type="primary" :disabled="progress !== null" @click="fileInput?.click()">{{ t('pcap.uploadButton') }}</NButton>
        <NButton size="small" quaternary :loading="loading" @click="refresh">{{ t('common.refresh') }}</NButton>
        <input ref="fileInput" type="file" accept=".pcap,.pcapng,.cap" hidden @change="onFile" />
      </NSpace>
    </NSpace>
    <NText depth="3" style="font-size: 12px">
      {{ t('pcap.libraryNote') }}
    </NText>
    <NDataTable
      :scrollbar-props="{ trigger: 'none' }"
      :columns="columns"
      :data="pcaps"
      :row-key="(m: PcapMeta) => m.id"
      :loading="loading"
      size="small"
      :scroll-x="920"
    />

    <NDivider style="margin: 4px 0" />
    <NText strong>{{ t('pcap.capture') }}</NText>
    <NText depth="3" style="font-size: 12px">{{ t('pcap.captureNote') }}</NText>
    <NAlert v-if="!ports.length" type="info" :show-icon="false">{{ t('pcap.acquireFirst') }}</NAlert>
    <template v-else>
      <div class="capform">
        <NText>{{ t('pcap.txLabel') }}</NText>
        <NCheckboxGroup v-model:value="cap.tx">
          <NSpace :size="8"><NCheckbox v-for="p in ports" :key="p.id" :value="p.id" :label="t('common.portN', { n: p.id })" /></NSpace>
        </NCheckboxGroup>
        <NText>{{ t('pcap.rxLabel') }}</NText>
        <NCheckboxGroup v-model:value="cap.rx">
          <NSpace :size="8"><NCheckbox v-for="p in ports" :key="p.id" :value="p.id" :label="t('common.portN', { n: p.id })" /></NSpace>
        </NCheckboxGroup>
        <NText>{{ t('pcap.limit') }}</NText>
        <NSpace align="center">
          <NInputNumber v-model:value="cap.limit" :min="1" :max="100000" size="small" style="width: 120px" />
          <NText depth="3">{{ t('pcap.limitSuffix') }}</NText>
          <NRadioGroup v-model:value="cap.mode" size="small">
            <NRadioButton value="fixed">{{ t('pcap.modeFixed') }}</NRadioButton>
            <NRadioButton value="cyclic">{{ t('pcap.modeCyclic') }}</NRadioButton>
          </NRadioGroup>
        </NSpace>
        <NText>{{ t('pcap.filter') }}</NText>
        <NInput v-model:value="cap.bpf" size="small" :placeholder="t('pcap.filterPlaceholder')" style="max-width: 420px" />
        <NText>{{ t('pcap.serviceMode') }}</NText>
        <NSpace vertical :size="2">
          <NCheckbox v-model:checked="cap.service">{{ t('pcap.serviceCheckbox') }}</NCheckbox>
          <NText depth="3" style="font-size: 12px">{{ t('pcap.serviceNote') }}</NText>
        </NSpace>
      </div>
      <NButton type="primary" size="small" style="width: fit-content" :disabled="!cap.tx.length && !cap.rx.length" :loading="capBusy" @click="startCapture">
        {{ t('pcap.startCapture') }}
      </NButton>
    </template>

    <div v-for="c in captures" :key="c.id" class="capture">
      <NTag size="small" :bordered="false" type="info">#{{ c.id }} {{ c.state }}</NTag>
      <NText>{{ t('pcap.captureCount', { count: c.count.toLocaleString(), limit: c.limit.toLocaleString() }) }}</NText>
      <NInput
        :value="capName[c.id] ?? ''"
        size="small"
        :placeholder="t('pcap.saveNamePlaceholder')"
        style="width: 220px; max-width: 100%"
        @update:value="(v: string) => (capName[c.id] = v)"
      />
      <NButton size="small" type="primary" :loading="capBusy" @click="stopCapture(c, true)">{{ t('pcap.stopAndSave') }}</NButton>
      <NPopconfirm @positive-click="stopCapture(c, false)">
        <template #trigger><NButton size="small" quaternary type="error">{{ t('pcap.discard') }}</NButton></template>
        {{ t('pcap.confirmDiscard') }}
      </NPopconfirm>
    </div>

    <PcapPreviewDialog v-model:show="previewOpen" :host-id="hostId" :pcap="previewOf" />
    <PushDialog v-model:show="pushOpen" :host-id="hostId" :pcap="pushOf" />
  </NSpace>
</template>

<style scoped>
.capform {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 10px 12px;
  align-items: center;
  font-size: 13px;
}
@media (max-width: 760px) {
  .capform {
    grid-template-columns: minmax(0, 1fr);
    gap: 4px;
  }
}
.capture {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(32, 128, 240, 0.08);
}
</style>
