<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NModal, NSpace, NText, useMessage, type DataTableColumns } from 'naive-ui'
import { api, type PcapMeta, type PcapPacket } from '../../api'
import { useI18n } from 'vue-i18n'
import { codedText } from '../../i18n'
import { useHostsStore } from '../../stores/hosts'
import { useStreamsStore } from '../../stores/streams'
import { clone } from '../../utils/streams'

const props = defineProps<{ show: boolean; hostId: string; pcap: PcapMeta | null }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const hosts = useHostsStore()
const streams = useStreamsStore()
const message = useMessage()
const { t } = useI18n()

const PAGE = 200
const rows = ref<PcapPacket[]>([])
const checked = ref<number[]>([])
const loading = ref(false)
const notes = ref<string[]>([])

const port = computed(() => hosts.focused[props.hostId] ?? null)
const more = computed(() => !!props.pcap && rows.value.length < props.pcap.packets)

async function load(reset = false) {
  if (!props.pcap) return
  loading.value = true
  try {
    const page = await api.pcapPackets(props.hostId, props.pcap.id, reset ? 0 : rows.value.length, PAGE)
    rows.value = reset ? page : [...rows.value, ...page]
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.show, props.pcap?.id],
  () => {
    if (!props.show) return
    rows.value = []
    checked.value = []
    notes.value = []
    load(true)
  },
)

async function addToPort() {
  if (!props.pcap || port.value === null || !checked.value.length) return
  loading.value = true
  try {
    const imported = await api.pcapToStreams(props.hostId, props.pcap.id, [...checked.value].sort((a, b) => a - b))
    notes.value = imported
      .filter((s) => s.import_note)
      .map((s) => t('pcap.preview.streamNote', { name: s.name, note: codedText({ code: s.import_note_code ?? undefined, message: s.import_note! }) }))
    const fresh = imported.map(({ import_note: _note, import_note_code: _code, ...s }) => s)
    const existing = clone(await streams.ensure(props.hostId, port.value))
    await streams.save(props.hostId, port.value, [...existing, ...fresh])
    message.success(t('pcap.preview.added', { n: fresh.length, port: port.value }, fresh.length))
    checked.value = []
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

const columns = computed<DataTableColumns<PcapPacket>>(() => [
  { type: 'selection' },
  { title: '#', key: 'index', width: 70, render: (r) => r.index + 1 },
  { title: t('pcap.preview.colTime'), key: 'ts', width: 100, align: 'right', render: (r) => r.ts.toFixed(6) },
  { title: t('pcap.preview.colLength'), key: 'length', width: 70, align: 'right' },
  { title: t('pcap.preview.colSummary'), key: 'summary', ellipsis: { tooltip: true } },
])
</script>

<template>
  <NModal :show="show" @update:show="(v: boolean) => emit('update:show', v)">
    <NCard v-if="pcap" style="width: min(1000px, 94vw)" :title="t('pcap.preview.title', { name: pcap.name })" size="small" :bordered="false">
      <NSpace vertical>
        <NText depth="3" style="font-size: 12px">
          {{ t('pcap.preview.note', { port: port ?? '—' }) }}
        </NText>
        <NDataTable
          v-model:checked-row-keys="checked"
          :scrollbar-props="{ trigger: 'none' }"
          :columns="columns"
          :data="rows"
          :row-key="(r: PcapPacket) => r.index"
          :loading="loading"
          size="small"
          :max-height="'max(240px, calc(100vh - 360px))'"
          :scroll-x="700"
          virtual-scroll
        />
        <NSpace justify="space-between" align="center">
          <NText depth="3">{{ t('pcap.preview.shown', { shown: rows.length.toLocaleString(), total: pcap.packets.toLocaleString() }) }}</NText>
          <NButton v-if="more" size="small" :loading="loading" @click="load()">{{ t('pcap.preview.loadMore', { n: PAGE }) }}</NButton>
        </NSpace>
        <NAlert v-for="n in notes" :key="n" type="info" :show-icon="false">{{ n }}</NAlert>
      </NSpace>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="emit('update:show', false)">{{ t('common.close') }}</NButton>
          <NButton type="primary" :disabled="!checked.length || port === null" :loading="loading" @click="addToPort">
            {{ t('pcap.preview.addButton', { n: checked.length, port: port ?? '—' }, checked.length) }}
          </NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>
