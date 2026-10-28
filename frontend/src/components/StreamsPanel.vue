<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import {
  NAlert, NButton, NCheckbox, NCheckboxGroup, NDataTable, NEmpty, NInput, NModal, NCard, NPopconfirm, NPopover, NRadioButton,
  NRadioGroup, NSpace, NSwitch, NTag, NText, NTooltip, NDropdown, useMessage, type DataTableColumns, type DropdownOption,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { api, type ProfileRun, type StreamSpec, type StreamStates, type StreamTemplate } from '../api'
import { codedText } from '../i18n'
import { useHostsStore } from '../stores/hosts'
import { newStream, useStreamsStore } from '../stores/streams'
import { useTemplatesStore } from '../stores/templates'
import { persisted } from '../utils/prefs'
import { clone, flowStatsSummary, layersSummary, modeSummary, rateSummary, sizeSummary } from '../utils/streams'
import StreamEditor from './editor/StreamEditor.vue'
import SaveTemplateDialog from './templates/SaveTemplateDialog.vue'
import TemplateManager from './templates/TemplateManager.vue'

const props = defineProps<{ hostId: string }>()

const hosts = useHostsStore()
const store = useStreamsStore()
const templates = useTemplatesStore()
const message = useMessage()
const { t } = useI18n()

const port = computed(() => hosts.focused[props.hostId] ?? null)

// A Python profile started from the Profile tab replaces this port's streams on TRex.
const runs = ref<Record<string, ProfileRun>>({})
watch(
  () => [props.hostId, port.value, hosts.ports[props.hostId]],
  async () => {
    try {
      runs.value = await api.profileRuns(props.hostId)
    } catch {
      runs.value = {}
    }
  },
  { immediate: true },
)
const profileRun = computed(() => (port.value === null ? null : runs.value[port.value] ?? null))
const list = computed(() => (port.value === null ? [] : store.get(props.hostId, port.value) ?? []))

// --- per-stream control while the port transmits ---
const portInfo = computed(() => (hosts.ports[props.hostId] ?? []).find((p) => p.id === port.value) ?? null)
const states = ref<StreamStates | null>(null)
watch(
  () => [props.hostId, port.value, portInfo.value?.status, portInfo.value?.acquired],
  async () => {
    const p = portInfo.value
    if (port.value === null || !p || p.status === 'IDLE' || !p.acquired) {
      states.value = null
      return
    }
    try {
      states.value = await api.streamStates(props.hostId, port.value)
    } catch {
      states.value = null
    }
  },
  { immediate: true },
)
const live = computed(() => !!states.value?.running && !profileRun.value)
const onTrex = (s: StreamSpec) => !!s.id && !!states.value?.on_trex.includes(s.id)
const isPaused = (s: StreamSpec) => !!s.id && !!states.value?.paused.includes(s.id)
const rateInput = ref('')
async function control(s: StreamSpec, action: 'pause' | 'resume' | 'update', mult?: string) {
  if (port.value === null || !s.id) return
  try {
    states.value = await api.streamControl(props.hostId, port.value, [s.id], action, mult)
  } catch (e) {
    message.error((e as Error).message)
  }
}
const loading = ref(false)

watch(
  port,
  async (p) => {
    if (p === null) return
    loading.value = true
    try {
      await store.load(props.hostId, p)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

async function save(streams: StreamSpec[], p = port.value) {
  if (p === null) return
  try {
    await store.save(props.hostId, p, streams)
  } catch (e) {
    message.error(t('streams.saveFailed', { error: (e as Error).message }))
  }
}

// --- editing ---
const editorOpen = ref(false)
const editing = ref<StreamSpec | null>(null)
const editingIndex = ref(-1)

function openEditor(i: number, start?: StreamSpec) {
  editingIndex.value = i
  editing.value = i >= 0 ? list.value[i] : start ?? newStream(t('streams.defaultStreamName', { n: list.value.length + 1 }))
  editorOpen.value = true
}

// --- templates (personal in this browser, shared on the backend) ---
templates.ensure().catch(() => undefined)

const templateMenu = computed<DropdownOption[]>(() => {
  const group = (scope: 'personal' | 'shared', label: string, list: StreamTemplate[]) =>
    list.length ? [{ type: 'group', label, key: scope, children: list.map((tpl) => ({ label: tpl.name, key: `${scope}:${tpl.id}` })) }] : []
  const groups = [...group('personal', t('streams.personalTemplates'), templates.personal), ...group('shared', t('streams.sharedTemplates'), templates.shared)]
  return [
    { type: 'group', label: t('streams.builtin'), key: 'builtin', children: [{ label: t('streams.imix'), key: 'builtin:imix' }] },
    ...(groups.length ? groups : [{ label: t('streams.noOwnTemplates'), key: 'none', disabled: true }]),
    { type: 'divider', key: 'd' },
    { label: t('streams.manageTemplates'), key: 'manage' },
  ]
})

// Simple IMIX: 64/594/1518-byte frames (60/590/1514 + FCS) at 7:4:1 by packet count.
// The pps values only set the ratio; scale them with the toolbar multiplier (e.g. "100%").
function addImix() {
  const sizes: [number, number][] = [[64, 7000], [594, 4000], [1518, 1000]]
  const next = clone(list.value)
  for (const [frame, pps] of sizes) {
    const s = newStream(`IMIX ${frame}B`)
    s.packet.frame_size = frame
    s.rate = { unit: 'pps', value: pps }
    next.push(s)
  }
  save(next)
  message.success(t('streams.imixAdded'))
}

async function fromTemplate(key: string) {
  if (key === 'manage') return (manageOpen.value = true)
  if (key === 'builtin:imix') return addImix()
  const [scope, id] = key.split(':')
  const tpl = (scope === 'personal' ? templates.personal : templates.shared).find((x) => x.id === id)
  if (!tpl || port.value === null) return
  const s = clone(tpl.stream)
  s.name = tpl.name
  if (s.flow_stats.type === 'latency') s.flow_stats.pg_id = await store.nextPgId(props.hostId, [port.value])
  openEditor(-1, s) // review before it is added
}

const saveTplOpen = ref(false)
const saveTplStream = ref<StreamSpec | null>(null)
function askTemplate(i: number) {
  saveTplStream.value = list.value[i]
  saveTplOpen.value = true
}
const manageOpen = ref(false)

// --- list edits ---

function onSaved(s: StreamSpec) {
  const next = clone(list.value)
  if (editingIndex.value >= 0) next[editingIndex.value] = s
  else next.push(s)
  save(next)
}

function duplicate(i: number) {
  const copy = clone(list.value[i])
  delete copy.id
  copy.name = t('streams.copyName', { name: copy.name })
  if (copy.flow_stats.type === 'latency') copy.flow_stats = { type: 'none' } // latency pg_ids must be unique
  const next = clone(list.value)
  next.splice(i + 1, 0, copy)
  save(next)
}

function remove(i: number) {
  const next = clone(list.value)
  next.splice(i, 1)
  save(next)
}

function move(i: number, d: -1 | 1) {
  const next = clone(list.value)
  ;[next[i], next[i + d]] = [next[i + d], next[i]]
  save(next)
}

function toggle(i: number, on: boolean) {
  const next = clone(list.value)
  next[i].enabled = on
  save(next)
}

// --- copy to other ports ---
const copyOpen = ref(false)
const copyTargets = ref<number[]>([])
const copyMode = persisted<'append' | 'replace'>('copyMode', 'append')
const copying = ref(false)
const otherPorts = computed(() => (hosts.ports[props.hostId] ?? []).filter((p) => p.id !== port.value))

function openCopy() {
  copyTargets.value = (hosts.checked[props.hostId] ?? []).filter((p) => p !== port.value)
  copyOpen.value = true
}

async function doCopy() {
  copying.value = true
  try {
    let pg = await store.nextPgId(props.hostId, [port.value!, ...copyTargets.value])
    for (const target of copyTargets.value) {
      const copies = clone(list.value).map((s) => {
        delete s.id
        if (s.flow_stats.type === 'latency') s.flow_stats.pg_id = pg++
        return s
      })
      // "next" refers to stream ids, which change in the copy; drop the links.
      copies.forEach((s) => (s.next = null))
      const existing = copyMode.value === 'append' ? clone(await store.ensure(props.hostId, target)) : []
      await store.save(props.hostId, target, [...existing, ...copies])
    }
    message.success(t('streams.copied', { streams: list.value.length, ports: copyTargets.value.length }))
    copyOpen.value = false
  } catch (e) {
    message.error(t('streams.copyFailed', { error: (e as Error).message }))
  } finally {
    copying.value = false
  }
}

const columns = computed<DataTableColumns<StreamSpec>>(() => [
  {
    title: t('common.enabled'),
    key: 'enabled',
    width: 60,
    render: (s, i) => h(NSwitch, { size: 'small', value: s.enabled, 'onUpdate:value': (v: boolean) => toggle(i, v) }),
  },
  { title: t('common.name'), key: 'name', minWidth: 120, ellipsis: { tooltip: true } },
  {
    title: '',
    key: 'lint',
    width: 50,
    render: (s) => {
      if (!s.lint?.length) return null
      const warn = s.lint.filter((w) => w.level === 'warning').length
      return h(NTooltip, { style: 'max-width: 480px' }, {
        trigger: () =>
          h(NTag, { size: 'small', bordered: false, type: warn ? 'warning' : 'default' }, () => (warn ? `⚠ ${warn}` : 'ℹ')),
        default: () => s.lint!.map((w) => h('div', null, t('streams.lintLine', { level: w.level === 'warning' ? t('common.warning') : t('streams.lintInfo'), message: codedText(w) }))),
      })
    },
  },
  { title: t('streams.col.packet'), key: 'layers', minWidth: 160, ellipsis: { tooltip: true }, render: layersSummary },
  { title: t('streams.col.size'), key: 'size', width: 130, render: sizeSummary },
  { title: t('streams.col.mode'), key: 'mode', width: 130, render: modeSummary },
  { title: t('streams.col.rate'), key: 'rate', width: 130, render: rateSummary },
  { title: t('streams.col.vm'), key: 'vm', width: 80, render: (s) => (s.vm.length ? t('streams.vmCount', s.vm.length) : '') },
  { title: t('streams.col.flowStats'), key: 'fs', width: 110, render: flowStatsSummary },
  ...(live.value
    ? [
        {
          title: t('streams.live.col'),
          key: 'live',
          width: 90,
          render: (s: StreamSpec) =>
            onTrex(s)
              ? h(NTag, { size: 'small', bordered: false, type: isPaused(s) ? 'warning' : 'success' }, () =>
                  isPaused(s) ? t('streams.live.paused') : t('streams.live.sending'),
                )
              : h(NText, { depth: 3, style: 'font-size: 12px' }, () => t('streams.live.notOnTrex')),
        },
      ]
    : []),
  {
    title: '',
    key: 'actions',
    width: live.value ? 400 : 270,
    fixed: 'right',
    render: (s, i) =>
      h(NSpace, { size: 2 }, () => [
        ...(live.value && onTrex(s)
          ? [
              h(
                NButton,
                { size: 'tiny', type: 'warning', secondary: true, onClick: () => control(s, isPaused(s) ? 'resume' : 'pause') },
                () => (isPaused(s) ? t('streams.live.resume') : t('streams.live.pause')),
              ),
              h(NPopover, { trigger: 'click', placement: 'bottom', onUpdateShow: (v: boolean) => v && (rateInput.value = '') }, {
                trigger: () => h(NButton, { size: 'tiny', type: 'warning', secondary: true }, () => t('streams.live.rate')),
                default: () =>
                  h(NSpace, { vertical: true, size: 6, style: 'width: 240px' }, () => [
                    h(NText, { depth: 3, style: 'font-size: 12px' }, () => t('streams.live.rateHelp')),
                    h(NSpace, { size: 6, wrap: false }, () => [
                      h(NInput, {
                        size: 'small',
                        value: rateInput.value,
                        placeholder: t('streams.live.ratePlaceholder'),
                        'onUpdate:value': (v: string) => (rateInput.value = v),
                      }),
                      h(
                        NButton,
                        { size: 'small', type: 'primary', disabled: !rateInput.value.trim(), onClick: () => control(s, 'update', rateInput.value.trim()) },
                        () => t('streams.live.apply'),
                      ),
                    ]),
                  ]),
              }),
            ]
          : []),
        h(NButton, { size: 'tiny', onClick: () => openEditor(i) }, () => t('common.edit')),
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => duplicate(i) }, () => t('common.copy')),
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => askTemplate(i) }, () => t('streams.saveTemplate')),
        h(NButton, { size: 'tiny', quaternary: true, disabled: i === 0, onClick: () => move(i, -1) }, () => '↑'),
        h(NButton, { size: 'tiny', quaternary: true, disabled: i === list.value.length - 1, onClick: () => move(i, 1) }, () => '↓'),
        h(NPopconfirm, { onPositiveClick: () => remove(i) }, {
          trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, () => t('common.delete')),
          default: () => t('streams.confirmDeleteStream'),
        }),
      ]),
  },
])
</script>

<template>
  <NEmpty v-if="port === null" :description="t('streams.pickPort')" />
  <NSpace v-else vertical>
    <NSpace align="center" justify="space-between">
      <NText strong>{{ t('streams.portStreams', { port }) }}</NText>
      <NSpace>
        <NButton size="small" type="primary" @click="openEditor(-1)">{{ t('streams.addStream') }}</NButton>
        <NDropdown :options="templateMenu" trigger="click" @select="fromTemplate">
          <NButton size="small" @click="templates.loadShared().catch(() => undefined)">{{ t('streams.addFromTemplate') }}</NButton>
        </NDropdown>
        <NButton size="small" :disabled="!list.length" @click="openCopy">{{ t('streams.copyToPorts') }}</NButton>
      </NSpace>
    </NSpace>
    <NText depth="3" style="font-size: 12px">
      {{ t('streams.saveNote') }}
    </NText>
    <NText v-if="live" depth="3" style="font-size: 12px">{{ t('streams.live.note') }}</NText>
    <NAlert v-if="profileRun" type="info" :show-icon="false">
      {{ t('streams.profileActive', { port, name: profileRun.id.split(':')[1] }) }}
    </NAlert>
    <NDataTable
      :scrollbar-props="{ trigger: 'none' }"
      :columns="columns"
      :data="list"
      :row-key="(s: StreamSpec) => s.id ?? s.name"
      :loading="loading"
      size="small"
      :scroll-x="live ? 1400 : 1180"
    />

    <StreamEditor
      v-model:show="editorOpen"
      :host-id="hostId"
      :port="port"
      :stream="editing"
      :siblings="list"
      @save="onSaved"
    />

    <SaveTemplateDialog v-model:show="saveTplOpen" :stream="saveTplStream" />
    <TemplateManager v-model:show="manageOpen" />

    <NModal v-model:show="copyOpen">
      <NCard style="width: min(560px, 94vw)" :title="t('streams.copyTitle')" size="small" :bordered="false">
        <NSpace vertical>
          <NText depth="3">{{ t('streams.copyIntro', { port, n: list.length }) }}</NText>
          <NCheckboxGroup v-model:value="copyTargets">
            <div class="targets">
              <NCheckbox v-for="p in otherPorts" :key="p.id" :value="p.id" :label="t('common.portN', { n: p.id })" />
            </div>
          </NCheckboxGroup>
          <NSpace>
            <NButton size="tiny" quaternary @click="copyTargets = otherPorts.map((p) => p.id)">{{ t('streams.selectAll') }}</NButton>
            <NButton size="tiny" quaternary @click="copyTargets = []">{{ t('common.clear') }}</NButton>
          </NSpace>
          <NRadioGroup v-model:value="copyMode" size="small">
            <NRadioButton value="append">{{ t('streams.copyAppend') }}</NRadioButton>
            <NRadioButton value="replace">{{ t('streams.copyReplace') }}</NRadioButton>
          </NRadioGroup>
          <NText depth="3" style="font-size: 12px">
            {{ t('streams.copyNote') }}
          </NText>
        </NSpace>
        <template #footer>
          <NSpace justify="end">
            <NButton @click="copyOpen = false">{{ t('common.cancel') }}</NButton>
            <NButton type="primary" :disabled="!copyTargets.length" :loading="copying" @click="doCopy">{{ t('common.copy') }}</NButton>
          </NSpace>
        </template>
      </NCard>
    </NModal>
  </NSpace>
</template>

<style scoped>
.targets {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
  gap: 6px;
}
</style>
