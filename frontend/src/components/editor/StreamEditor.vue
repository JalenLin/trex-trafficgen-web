<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import {
  NAlert, NButton, NCard, NForm, NFormItem, NInput, NInputNumber, NModal, NPopover, NRadioButton, NRadioGroup, NSelect, NSpace,
  NSwitch, NTabPane, NTabs, NText, useMessage, type SelectGroupOption, type SelectOption,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  api, type DescField, type LintItem, type PacketDescription, type PayloadType, type ProtocolSchema, type StreamSpec, type VmRow,
} from '../../api'
import { codedText } from '../../i18n'
import { useHostsStore } from '../../stores/hosts'
import { useStreamsStore } from '../../stores/streams'
import { loadPref, persisted, pushRecent, savePref } from '../../utils/prefs'
import { clone } from '../../utils/streams'
import SaveTemplateDialog from '../templates/SaveTemplateDialog.vue'
import HexView from './HexView.vue'
import LayerFields from './LayerFields.vue'

const props = defineProps<{
  show: boolean
  hostId: string
  port: number
  stream: StreamSpec | null
  /** Other streams on the same port, for "next stream". */
  siblings: StreamSpec[]
}>()
const emit = defineEmits<{ 'update:show': [boolean]; save: [StreamSpec] }>()

const streams = useStreamsStore()
const hosts = useHostsStore()
const message = useMessage()
const { t } = useI18n()

const draft = ref<StreamSpec | null>(null)
const tab = ref('packet')
const selected = ref(0)
const schemas = reactive<Record<string, ProtocolSchema>>({})
const preview = ref<PacketDescription | null>(null)
const previewError = ref<string | null>(null)
const saveError = ref<string | null>(null)
const saving = ref(false)
const hoverField = ref<{ layer: number; field: string } | null>(null)
const addChoice = ref<string | null>(null)
const catalogOptions = ref<SelectGroupOption[]>([])

/**
 * Fill in keys the editor relies on. Streams saved by this GUI always have them,
 * but imported templates or hand-edited JSON may not (e.g. a layer without
 * "fields"), and a missing one would blank the whole field form.
 */
function normalize(s: StreamSpec): StreamSpec {
  s.packet ??= { layers: [] }
  s.packet.layers ??= []
  for (const l of s.packet.layers) l.fields ??= {}
  s.vm ??= []
  s.mode ??= { type: 'continuous' }
  s.rate ??= { unit: 'pps', value: 1000 }
  s.flow_stats ??= { type: 'none' }
  s.enabled ??= true
  return s
}

// --- unsaved drafts ----------------------------------------------------------
// Edits are mirrored to localStorage, so a closed tab or crash doesn't lose them.
// Saving or cancelling clears the draft.

interface Draft {
  at: string
  stream: StreamSpec
}
const draftKey = computed(() => `draft:${props.hostId}:${props.port}:${props.stream?.id ?? 'new'}`)
const pendingDraft = ref<Draft | null>(null)
let draftTimer: ReturnType<typeof setTimeout> | undefined
// The stream as opened (after normalize); a draft is only worth keeping if it differs.
let baseline = ''

watch(
  () => (props.show && draft.value ? JSON.stringify(draft.value) : ''),
  (json) => {
    clearTimeout(draftTimer)
    if (!json || pendingDraft.value) return
    // Only keep a draft that actually differs from what is saved.
    if (json === baseline) return savePref(draftKey.value, undefined)
    draftTimer = setTimeout(() => savePref(draftKey.value, { at: new Date().toISOString(), stream: JSON.parse(json) }), 400)
  },
)

function dropDraft() {
  clearTimeout(draftTimer)
  savePref(draftKey.value, undefined)
}

async function restoreDraft() {
  if (!pendingDraft.value) return
  draft.value = normalize(clone(pendingDraft.value.stream))
  pendingDraft.value = null
  await Promise.all(draft.value.packet.layers.map((l) => loadSchema(l.proto)))
}

function discardDraft() {
  pendingDraft.value = null
  dropDraft()
}

function close() {
  dropDraft()
  emit('update:show', false)
}

watch(
  () => props.show,
  async (open) => {
    if (!open || !props.stream) return
    draft.value = normalize(clone(props.stream))
    baseline = JSON.stringify(draft.value)
    tab.value = 'packet'
    selected.value = 0
    saveError.value = null
    preview.value = null
    const saved = loadPref<Draft | null>(draftKey.value, null)
    pendingDraft.value = saved && JSON.stringify(normalize(clone(saved.stream))) !== baseline ? saved : null
    await Promise.all(draft.value.packet.layers.map((l) => loadSchema(l.proto)))
    await buildCatalogOptions()
  },
  { immediate: true },
)

async function loadSchema(proto: string) {
  if (!schemas[proto]) schemas[proto] = await streams.schema(props.hostId, proto)
}

// --- protocol picker ------------------------------------------------------

async function buildCatalogOptions() {
  const cat = await streams.catalog(props.hostId)
  const byId = new Map(cat.protocols.map((p) => [p.id, p]))
  const opt = (id: string): SelectOption => {
    const p = byId.get(id)
    return { label: p ? `${p.name} — ${p.desc}` : id, value: id }
  }
  catalogOptions.value = [
    { type: 'group', label: t('streams.editor.commonProtocols'), key: 'common', children: cat.common.map(opt) },
    {
      type: 'group',
      label: t('streams.editor.allProtocols', { n: cat.protocols.length, version: cat.scapy_version }),
      key: 'all',
      children: cat.protocols.map((p) => ({ label: `${p.name} — ${p.desc}  [${p.module}]`, value: p.id })),
    },
  ]
}

const suggestions = computed<SelectGroupOption | null>(() => {
  const layers = draft.value?.packet.layers ?? []
  const last = layers[selected.value] ?? layers[layers.length - 1]
  const next = last ? schemas[last.proto]?.next ?? [] : []
  if (!next.length) return null
  return { type: 'group', label: t('streams.editor.suggestedAfter', { proto: last.proto }), key: 'next', children: next.map((id) => ({ label: id, value: id })) }
})
// Remembered per browser: protocols this user added recently.
const recentProtocols = persisted<string[]>('recentProtocols', [])
const recentGroup = computed<SelectGroupOption | null>(() =>
  recentProtocols.value.length
    ? { type: 'group', label: t('streams.editor.recent'), key: 'recent', children: recentProtocols.value.map((id) => ({ label: id, value: id })) }
    : null,
)
const pickerOptions = computed(() =>
  [suggestions.value, recentGroup.value, ...catalogOptions.value].filter((g): g is SelectGroupOption => g !== null),
)

async function addLayer(proto: string | null) {
  if (!proto || !draft.value) return
  await loadSchema(proto)
  const at = Math.min(selected.value + 1, draft.value.packet.layers.length)
  draft.value.packet.layers.splice(at, 0, { proto, fields: {} })
  shiftVm(at, +1)
  selected.value = at
  addChoice.value = null
  pushRecent(recentProtocols, proto, 12)
}

function removeLayer(i: number) {
  if (!draft.value) return
  draft.value.packet.layers.splice(i, 1)
  draft.value.vm = draft.value.vm.filter((r) => r.layer !== i)
  shiftVm(i, -1)
  selected.value = Math.max(0, Math.min(selected.value, draft.value.packet.layers.length - 1))
}

function moveLayer(i: number, d: -1 | 1) {
  const layers = draft.value?.packet.layers
  if (!layers || i + d < 0 || i + d >= layers.length) return
  ;[layers[i], layers[i + d]] = [layers[i + d], layers[i]]
  for (const r of draft.value!.vm) {
    if (r.layer === i) r.layer = i + d
    else if (r.layer === i + d) r.layer = i
  }
  selected.value = i + d
}

// Field-engine rows point at layers by index; keep them aimed at the same layer.
function shiftVm(from: number, by: number) {
  for (const r of draft.value?.vm ?? []) if (r.layer >= from && !(by < 0 && r.layer === from)) r.layer += by
}

// --- frame size -------------------------------------------------------------

const sizeModes = computed(() => (['fixed', 'inc', 'dec', 'random'] as const).map((value) => ({ label: t(`streams.op.${value}`), value })))
const vmOps = computed(() => (['inc', 'dec', 'random'] as const).map((value) => ({ label: t(`streams.op.${value}`), value })))
const sizeMode = computed({
  get: () => draft.value?.packet.size?.mode ?? 'fixed',
  set: (mode: 'fixed' | 'inc' | 'dec' | 'random') => {
    if (!draft.value) return
    const cur = draft.value.packet.size
    draft.value.packet.size =
      mode === 'fixed'
        ? { mode }
        : { mode, min: cur?.min ?? draft.value.packet.frame_size ?? 64, max: cur?.max ?? 1518, step: cur?.step ?? 1 }
  },
})
const size = computed(() => draft.value?.packet.size)

/** Varying sizes preview at the largest size, which is how the packet is built. */
// --- payload fill ---
const PAYLOAD_TYPES = ['zeros', 'byte', 'inc', 'dec', 'random', 'text', 'hex'] as const
const payloadTypes = computed(() => PAYLOAD_TYPES.map((v) => ({ label: t(`streams.payloadType.${v}`), value: v })))
const payloadType = computed(() => draft.value?.packet.payload?.type ?? 'zeros')
function setPayloadType(v: PayloadType) {
  if (!draft.value) return
  draft.value.packet.payload = v === 'zeros' ? undefined : { type: v, value: draft.value.packet.payload?.value ?? '' }
}
const payloadValue = computed({
  get: () => draft.value?.packet.payload?.value ?? '',
  set: (v: string) => {
    if (draft.value?.packet.payload) draft.value.packet.payload.value = v
  },
})

// --- send the packet being edited, once (push_packets) ---
const pushCount = persisted('editor.pushCount', 1)
const pushGap = persisted('editor.pushGap', 0)
const pushing = ref(false)
const portMine = computed(() => (hosts.ports[props.hostId] ?? []).some((p) => p.id === props.port && p.acquired))
async function pushNow() {
  if (!draft.value) return
  pushing.value = true
  try {
    const r = await api.pushPacket(props.hostId, props.port, previewPacket(draft.value), pushCount.value || 1, pushGap.value || 0)
    message.success(t('streams.editor.pushed', { n: r.sent, port: props.port, bytes: r.bytes }))
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    pushing.value = false
  }
}

function previewPacket(s: StreamSpec) {
  const sz = s.packet.size
  return sz && sz.mode !== 'fixed' ? { ...s.packet, frame_size: sz.max } : s.packet
}

// --- live preview -----------------------------------------------------------

let timer: ReturnType<typeof setTimeout> | undefined
let seq = 0
watch(
  () => (draft.value ? JSON.stringify({ packet: previewPacket(draft.value), fs: draft.value.flow_stats }) : ''),
  (key) => {
    clearTimeout(timer)
    if (!key) return
    timer = setTimeout(async () => {
      const mine = ++seq
      const { packet, fs } = JSON.parse(key)
      try {
        const d = await api.buildPacket(props.hostId, packet, fs)
        if (mine === seq) {
          preview.value = d
          previewError.value = null
        }
      } catch (e) {
        if (mine === seq) previewError.value = (e as Error).message
      }
    }, 250)
  },
)

const highlight = computed<[number, number] | null>(() => {
  const h = hoverField.value
  const layer = h && preview.value?.layers[h.layer]
  const f = layer && layer.fields.find((x) => x.name === h.field)
  if (!f) return h && layer ? [layer.offset, layer.offset + layer.length] : null
  return [Math.floor(f.bit_offset / 8), Math.ceil((f.bit_offset + Math.max(f.bits, 1)) / 8)]
})

// --- sanity warnings ----------------------------------------------------------

// --- jump from the preview (hex byte or decoded field) to the field's editor ---
const fieldsRef = ref<InstanceType<typeof LayerFields> | null>(null)

/** The field a byte belongs to: innermost layer first, as the hex view colours it. */
function fieldAt(byte: number): { layer: number; field: string } | null {
  const layers = preview.value?.layers ?? []
  for (let i = layers.length - 1; i >= 0; i--) {
    const l = layers[i]
    if (byte < l.offset || byte >= l.offset + l.length) continue
    if (l.padding) return null
    const f = l.fields.find((x) => x.bit_offset < (byte + 1) * 8 && x.bit_offset + Math.max(x.bits, 1) > byte * 8)
    return { layer: i, field: f?.name ?? '' }
  }
  return null
}

async function editField(layer: number, field: string) {
  if (!draft.value?.packet.layers[layer]) return // padding the GUI added, not a user layer
  selected.value = layer
  await nextTick()
  if (field) fieldsRef.value?.focusField(field)
}

function pickByte(byte: number) {
  const at = fieldAt(byte)
  if (at) editField(at.layer, at.field)
}

const warnings = computed(() => preview.value?.warnings ?? [])
const warningCount = computed(() => warnings.value.filter((w) => w.level === 'warning').length)
const showAllWarnings = ref(false)

function jumpTo(w: LintItem) {
  tab.value = 'packet'
  if (w.layer === null) return
  selected.value = w.layer
  hoverField.value = { layer: w.layer, field: w.field ?? '' }
  setTimeout(() => {
    if (hoverField.value?.layer === w.layer) hoverField.value = null
  }, 2500)
}

// --- field engine -----------------------------------------------------------

const layerOptions = computed(() =>
  (draft.value?.packet.layers ?? []).map((l, i) => ({ label: `${i + 1}. ${l.proto}`, value: i })),
)
const writable = (layer: number): DescField[] => preview.value?.layers[layer]?.fields.filter((f) => f.writable) ?? []

function addVmRow() {
  draft.value?.vm.push({ layer: selected.value, field: '', op: 'inc', start: '', end: '', step: 1 })
}

function pickVmField(row: VmRow, name: string) {
  row.field = name
  // Start from the field's current value in the packet.
  const f = writable(row.layer).find((x) => x.name === name)
  if (f && !row.start) row.start = f.kind === 'int' || f.kind === 'enum' || f.kind === 'flags' ? String(parseInt(f.repr) || 0) : f.repr
}

// --- transmit ---------------------------------------------------------------

const nextOptions = computed(() =>
  props.siblings.filter((s) => s.id && s.id !== draft.value?.id).map((s) => ({ label: s.name || s.id!, value: s.id! })),
)

watch(
  () => draft.value?.flow_stats.type,
  async (type) => {
    if (!draft.value || type === 'none' || draft.value.flow_stats.pg_id != null) return
    draft.value.flow_stats.pg_id = await streams.nextPgId(props.hostId, [props.port])
  },
)

// --- templates ----------------------------------------------------------------

const templateOpen = ref(false)

// --- save -------------------------------------------------------------------

async function save() {
  if (!draft.value) return
  saving.value = true
  saveError.value = null
  try {
    const check = await api.checkStream(props.hostId, draft.value)
    // Saved with the stream so the list can flag it without re-checking.
    emit('save', { ...draft.value, lint: check.warnings.length ? check.warnings : undefined })
    close()
  } catch (e) {
    saveError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <NModal :show="show" :mask-closable="false" @update:show="(v: boolean) => emit('update:show', v)">
    <NCard v-if="draft" style="width: min(1280px, 96vw)" :bordered="false" size="small" role="dialog">
      <template #header>
        <NSpace align="center">
          <NText>{{ t('streams.editor.title', { port }) }}</NText>
          <NInput v-model:value="draft.name" size="small" :placeholder="t('common.name')" style="width: 240px; max-width: 50vw" />
          <NSwitch v-model:value="draft.enabled" size="small" />
          <NText depth="3">{{ draft.enabled ? t('common.enabled') : t('common.disabled') }}</NText>
        </NSpace>
      </template>

      <NAlert v-if="pendingDraft" type="info" :show-icon="false" class="err">
        <NSpace align="center" justify="space-between">
          <span>{{ t('streams.editor.pendingDraft', { at: new Date(pendingDraft.at).toLocaleString() }) }}</span>
          <NSpace>
            <NButton size="small" type="primary" @click="restoreDraft">{{ t('streams.editor.restore') }}</NButton>
            <NButton size="small" @click="discardDraft">{{ t('streams.editor.discard') }}</NButton>
          </NSpace>
        </NSpace>
      </NAlert>
      <NTabs v-model:value="tab" type="line" size="small">
        <!-- Packet -------------------------------------------------------- -->
        <NTabPane name="packet" :tab="t('streams.editor.tabPacket')">
          <div class="packet">
            <div class="stack">
              <NText depth="3" class="label">{{ t('streams.editor.stack') }}</NText>
              <div
                v-for="(l, i) in draft.packet.layers"
                :key="i"
                class="layer"
                :class="{ active: i === selected }"
                @click="selected = i"
              >
                <span class="idx">{{ i + 1 }}</span>
                <span class="proto">{{ l.proto }}</span>
                <span class="ops" @click.stop>
                  <NButton size="tiny" quaternary :disabled="i === 0" @click="moveLayer(i, -1)">↑</NButton>
                  <NButton size="tiny" quaternary :disabled="i === draft.packet.layers.length - 1" @click="moveLayer(i, 1)">↓</NButton>
                  <NButton size="tiny" quaternary @click="removeLayer(i)">✕</NButton>
                </span>
              </div>
              <NSelect
                v-model:value="addChoice"
                :options="pickerOptions"
                size="small"
                filterable
                :placeholder="t('streams.editor.addProtocol')"
                class="picker"
                @update:value="addLayer"
              />
              <NText depth="3" class="label">{{ t('streams.editor.frameSize') }}</NText>
              <NSelect v-model:value="sizeMode" :options="sizeModes" size="small" style="margin-bottom: 6px" />
              <NInputNumber
                v-if="sizeMode === 'fixed'"
                v-model:value="draft.packet.frame_size"
                size="small"
                :min="1"
                clearable
                :placeholder="t('streams.editor.noPadding')"
              />
              <template v-else-if="size">
                <div class="sizes">
                  <NInputNumber v-model:value="size.min" size="small" :min="1" :placeholder="t('streams.editor.min')" />
                  <NText depth="3">～</NText>
                  <NInputNumber v-model:value="size.max" size="small" :min="1" :max="9216" :placeholder="t('streams.editor.max')" />
                </div>
                <NInputNumber
                  v-if="sizeMode !== 'random'"
                  v-model:value="size.step"
                  size="small"
                  :min="1"
                  style="margin-top: 6px"
                >
                  <template #prefix>{{ t('streams.editor.stepPrefix') }}</template>
                  <template #suffix>bytes</template>
                </NInputNumber>
                <NText depth="3" class="size-hint">
                  {{ t('streams.editor.sizeHint') }}
                </NText>
              </template>
              <NText depth="3" class="label payload-label">{{ t('streams.editor.payload') }}</NText>
              <NSelect :value="payloadType" :options="payloadTypes" size="small" @update:value="setPayloadType" />
              <NInput
                v-if="payloadType !== 'zeros'"
                v-model:value="payloadValue"
                size="small"
                style="margin-top: 6px"
                :placeholder="t(`streams.editor.payloadPlaceholder.${payloadType}`)"
              />
              <NText depth="3" class="size-hint">{{ t('streams.editor.payloadHint') }}</NText>
            </div>

            <div class="fields">
              <template v-if="draft.packet.layers[selected] && schemas[draft.packet.layers[selected].proto]">
                <NText depth="3" class="label">
                  {{
                    t('streams.editor.fieldsHeading', {
                      name: schemas[draft.packet.layers[selected].proto].name,
                      desc: schemas[draft.packet.layers[selected].proto].desc,
                    })
                  }}
                </NText>
                <LayerFields
                  ref="fieldsRef"
                  v-model="draft.packet.layers[selected].fields"
                  :schema="schemas[draft.packet.layers[selected].proto]"
                  :built="preview?.layers[selected]"
                  :port-macs="selected === 0 && draft.packet.layers[0].proto === 'Ether'"
                  @hover="(f) => (hoverField = f ? { layer: selected, field: f } : null)"
                />
              </template>
              <NText v-else depth="3">{{ t('streams.editor.pickLayer') }}</NText>
            </div>

            <div class="preview">
              <NText v-if="draft.packet.layers[0]?.proto === 'Ether'" depth="3" class="label">
                {{ t('streams.editor.etherMacNote') }}
              </NText>
              <NText depth="3" class="label">
                {{ t('streams.editor.preview') }}
                <template v-if="preview">{{ t('streams.editor.previewLength', { n: preview.frame_length }) }}</template>
              </NText>
              <NAlert v-if="previewError" type="error" :show-icon="false" class="err">{{ previewError }}</NAlert>
              <template v-if="preview">
                <HexView
                  :hex="preview.hex"
                  :layers="preview.layers"
                  :highlight="highlight"
                  :hint="t('streams.editor.clickToEdit')"
                  class="hexview"
                  @pick="pickByte"
                  @hover-byte="(b) => (hoverField = b === null ? null : fieldAt(b))"
                />
                <div class="decode">
                  <div v-for="(l, i) in preview.layers" :key="i" class="dlayer">
                    <div
                      class="dhead"
                      :class="{ pad: l.padding }"
                      @mouseenter="hoverField = { layer: i, field: '' }"
                      @mouseleave="hoverField = null"
                      @click="!l.padding && (selected = i)"
                    >
                      {{ l.padding ? t('streams.editor.padding') : l.name }} <span class="dim">@{{ l.offset }} · {{ l.length }}B</span>
                    </div>
                    <div
                      v-for="f in l.padding ? [] : l.fields"
                      :key="f.name"
                      class="dfield"
                      :title="t('streams.editor.clickToEdit')"
                      @mouseenter="hoverField = { layer: i, field: f.name }"
                      @mouseleave="hoverField = null"
                      @click="editField(i, f.name)"
                    >
                      <span class="dim">{{ f.name }}</span> {{ f.repr }}
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </NTabPane>

        <!-- Field engine -------------------------------------------------- -->
        <NTabPane name="vm" :tab="draft.vm.length ? t('streams.editor.tabVmCount', { n: draft.vm.length }) : t('streams.editor.tabVm')">
          <NSpace vertical>
            <NText depth="3">{{ t('streams.editor.vmIntro') }}</NText>
            <div v-for="(row, n) in draft.vm" :key="n" class="vmrow">
              <NSelect v-model:value="row.layer" :options="layerOptions" size="small" @update:value="row.field = ''" />
              <NSelect
                :value="row.field || null"
                :options="writable(row.layer).map((f) => ({ label: `${f.name} (${f.bits} bits)`, value: f.name }))"
                size="small"
                :placeholder="t('streams.editor.vmField')"
                filterable
                @update:value="(v: string) => pickVmField(row, v)"
              />
              <NSelect
                v-model:value="row.op"
                size="small"
                :options="vmOps"
              />
              <NInput v-model:value="row.start" size="small" :placeholder="t('streams.editor.vmStart')" />
              <NInput v-model:value="row.end" size="small" :placeholder="t('streams.editor.vmEnd')" />
              <NInputNumber v-model:value="row.step" size="small" :min="1" :placeholder="t('streams.editor.vmStep')" :disabled="row.op === 'random'" />
              <NButton size="small" quaternary @click="draft.vm.splice(n, 1)">✕</NButton>
            </div>
            <NButton size="small" dashed @click="addVmRow">{{ t('streams.editor.addVm') }}</NButton>
          </NSpace>
        </NTabPane>

        <!-- Transmit ------------------------------------------------------ -->
        <NTabPane name="tx" :tab="t('streams.editor.tabTx')">
          <NForm label-placement="left" label-width="120" size="small" style="max-width: 640px">
            <NFormItem :label="t('streams.editor.mode')">
              <NRadioGroup v-model:value="draft.mode.type">
                <NRadioButton value="continuous">{{ t('streams.editor.continuous') }}</NRadioButton>
                <NRadioButton value="single_burst">{{ t('streams.editor.singleBurst') }}</NRadioButton>
                <NRadioButton value="multi_burst">{{ t('streams.editor.multiBurst') }}</NRadioButton>
              </NRadioGroup>
            </NFormItem>
            <NFormItem v-if="draft.mode.type === 'single_burst'" :label="t('streams.editor.totalPkts')">
              <NInputNumber v-model:value="draft.mode.total_pkts" :min="1" :default-value="1" />
            </NFormItem>
            <template v-if="draft.mode.type === 'multi_burst'">
              <NFormItem :label="t('streams.editor.pktsPerBurst')"><NInputNumber v-model:value="draft.mode.pkts_per_burst" :min="1" /></NFormItem>
              <NFormItem :label="t('streams.editor.burstCount')"><NInputNumber v-model:value="draft.mode.count" :min="1" /></NFormItem>
              <NFormItem :label="t('streams.editor.ibg')"><NInputNumber v-model:value="draft.mode.ibg_usec" :min="0" /></NFormItem>
            </template>
            <NFormItem :label="t('streams.editor.rate')">
              <NSpace>
                <NInputNumber v-model:value="draft.rate.value" :min="0" style="width: 180px" />
                <NSelect
                  v-model:value="draft.rate.unit"
                  style="width: 160px"
                  :options="[
                    { label: t('streams.editor.rateLinePct'), value: 'percentage' },
                    { label: 'pps', value: 'pps' },
                    { label: 'bps (L1)', value: 'bps_L1' },
                    { label: 'bps (L2)', value: 'bps_L2' },
                  ]"
                />
              </NSpace>
            </NFormItem>
            <NFormItem :label="t('streams.editor.isg')">
              <NInputNumber v-model:value="draft.isg_usec" :min="0" placeholder="0" />
            </NFormItem>
            <NFormItem :label="t('streams.editor.flowStats')">
              <NSpace align="center">
                <NRadioGroup v-model:value="draft.flow_stats.type">
                  <NRadioButton value="none">{{ t('common.none') }}</NRadioButton>
                  <NRadioButton value="stats">{{ t('streams.editor.stats') }}</NRadioButton>
                  <NRadioButton value="latency">Latency</NRadioButton>
                </NRadioGroup>
                <NInputNumber
                  v-if="draft.flow_stats.type !== 'none'"
                  v-model:value="draft.flow_stats.pg_id"
                  :min="0"
                  placeholder="pg_id"
                  style="width: 120px"
                />
              </NSpace>
            </NFormItem>
            <NFormItem :label="t('streams.editor.selfStart')">
              <NSwitch v-model:value="draft.self_start" />
              <NText depth="3" style="margin-left: 8px">{{ t('streams.editor.selfStartHint') }}</NText>
            </NFormItem>
            <NFormItem :label="t('streams.editor.next')">
              <NSelect
                v-model:value="draft.next"
                :options="nextOptions"
                clearable
                :disabled="draft.mode.type === 'continuous'"
                :placeholder="draft.mode.type === 'continuous' ? t('streams.editor.nextContinuous') : t('common.none')"
              />
            </NFormItem>
          </NForm>
        </NTabPane>
      </NTabs>

      <template #footer>
        <div v-if="warnings.length" class="lint">
          <NText :type="warningCount ? 'warning' : 'default'" depth="2" class="lint-title">
            {{ warningCount ? t('streams.editor.lintWarnings', warningCount) : t('streams.editor.lintInfos') }}{{ t('streams.editor.lintSaveAnyway') }}
          </NText>
          <div
            v-for="(w, i) in showAllWarnings ? warnings : warnings.slice(0, 3)"
            :key="i"
            class="lint-item"
            :class="[w.level, { link: w.layer !== null }]"
            @click="jumpTo(w)"
          >
            <span class="lint-tag">{{ w.level === 'warning' ? t('common.warning') : t('streams.lintInfo') }}</span>
            <span v-if="w.layer !== null" class="lint-where">{{ t('streams.editor.lintLayer', { n: w.layer + 1 }) }}</span>
            {{ codedText(w) }}
          </div>
          <NButton v-if="warnings.length > 3" size="tiny" text @click="showAllWarnings = !showAllWarnings">
            {{ showAllWarnings ? t('streams.editor.showLess') : t('streams.editor.showAll', { n: warnings.length }) }}
          </NButton>
        </div>
        <NAlert v-if="saveError" type="error" :title="t('streams.editor.cannotSave')" class="err">{{ saveError }}</NAlert>
        <NSpace justify="end">
          <!-- :to="false" keeps it inside the modal, whose focus trap would otherwise block its inputs -->
          <NPopover trigger="click" placement="top-start" :width="320" :to="false">
            <template #trigger>
              <NButton :title="t('streams.editor.pushTitle')">{{ t('streams.editor.push') }}</NButton>
            </template>
            <NSpace vertical :size="8">
              <NText depth="3" style="font-size: 12px">{{ t('streams.editor.pushHint', { port }) }}</NText>
              <NSpace :size="8" :wrap="false">
                <NInputNumber v-model:value="pushCount" size="small" :min="1" :max="1000" style="width: 130px">
                  <template #prefix>{{ t('streams.editor.pushCount') }}</template>
                </NInputNumber>
                <NInputNumber v-model:value="pushGap" size="small" :min="0" style="width: 150px">
                  <template #prefix>{{ t('streams.editor.pushGap') }}</template>
                  <template #suffix>µs</template>
                </NInputNumber>
              </NSpace>
              <NText v-if="!portMine" type="warning" style="font-size: 12px">{{ t('streams.editor.pushNeedPort', { port }) }}</NText>
              <NButton type="primary" size="small" :disabled="!portMine" :loading="pushing" @click="pushNow">
                {{ t('streams.editor.pushSend') }}
              </NButton>
            </NSpace>
          </NPopover>
          <NButton @click="templateOpen = true">{{ t('streams.editor.saveAsTemplate') }}</NButton>
          <NButton @click="close">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="saving" @click="save">{{ t('streams.editor.checkAndSave') }}</NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
  <SaveTemplateDialog v-model:show="templateOpen" :stream="draft" />
</template>

<style scoped>
.packet {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) minmax(0, 1.2fr);
  gap: 16px;
  min-height: 520px;
}
/* Medium: stack + fields side by side, preview underneath. */
@media (max-width: 1200px) {
  .packet {
    grid-template-columns: 200px minmax(0, 1fr);
    min-height: 0;
  }
  .preview {
    grid-column: 1 / -1;
    max-height: none;
  }
  .fields {
    max-height: 50vh;
  }
}
/* Narrow: one column. */
@media (max-width: 760px) {
  .packet {
    grid-template-columns: minmax(0, 1fr);
  }
}
.label {
  display: block;
  font-size: 12px;
  margin: 4px 0 6px;
}
.layer {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}
.layer:hover {
  background: rgba(128, 128, 128, 0.08);
}
.layer.active {
  background: rgba(24, 160, 88, 0.14);
}
.idx {
  opacity: 0.5;
  font-size: 12px;
}
.proto {
  overflow: hidden;
  text-overflow: ellipsis;
}
.picker {
  margin: 8px 0 16px;
}
.sizes {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 4px;
  align-items: center;
}
.payload-label {
  margin-top: 14px;
}
.size-hint {
  display: block;
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.5;
}
.fields {
  max-height: 62vh;
  overflow: auto;
  padding-right: 4px;
}
.preview {
  max-height: 62vh;
  overflow: auto;
}
.hexview {
  margin-bottom: 12px;
  overflow-x: auto;
}
.decode {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  margin-bottom: 12px;
}
.dhead {
  font-weight: 600;
  margin-top: 4px;
  cursor: pointer;
}
.dhead.pad {
  font-weight: 400;
  opacity: 0.6;
}
.dfield {
  padding-left: 14px;
  cursor: pointer;
}
.dfield:hover,
.dhead:hover {
  background: rgba(240, 160, 32, 0.15);
}
.dim {
  opacity: 0.55;
}
.vmrow {
  display: grid;
  grid-template-columns: 150px 200px 100px minmax(0, 1fr) minmax(0, 1fr) 110px 40px;
  gap: 8px;
}
/* Wrap the row into two lines instead of squeezing seven controls. */
/* (layer, field, op) / (start, end, step) / remove */
@media (max-width: 1000px) {
  .vmrow {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    padding-bottom: 8px;
    border-bottom: 1px dashed rgba(128, 128, 128, 0.25);
  }
}
.err {
  margin-bottom: 8px;
}
.lint {
  margin-bottom: 10px;
  font-size: 13px;
}
.lint-title {
  display: block;
  margin-bottom: 4px;
}
.lint-item {
  padding: 3px 8px;
  border-radius: 4px;
  margin-bottom: 2px;
}
.lint-item.warning {
  background: rgba(240, 160, 32, 0.12);
}
.lint-item.info {
  background: rgba(128, 128, 128, 0.08);
}
.lint-item.link {
  cursor: pointer;
}
.lint-item.link:hover {
  outline: 1px solid rgba(240, 160, 32, 0.6);
}
.lint-tag {
  font-weight: 600;
  margin-right: 6px;
}
.lint-where {
  opacity: 0.6;
  margin-right: 6px;
}
</style>
