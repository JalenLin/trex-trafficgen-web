<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  NAlert, NButton, NCheckbox, NDataTable, NDivider, NEmpty, NForm, NFormItem, NInput, NInputNumber, NPopconfirm, NRadio,
  NRadioGroup, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { api, type PingRecord, type PortConfig, type PortSettings } from '../api'
import { useHostsStore } from '../stores/hosts'
import { useProfilesStore } from '../stores/profiles'
import { diffConfig, flowCtrlLabels } from '../utils/portcfg'
import { NARROW, viewportWidth } from '../composables/useViewport'
import { persisted } from '../utils/prefs'
import NamespacePanel from './NamespacePanel.vue'
import PortProfiles from './profiles/PortProfiles.vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ hostId: string }>()

const store = useHostsStore()
const profiles = useProfilesStore()
const message = useMessage()
const { t } = useI18n()

const portId = computed(() => store.focused[props.hostId] ?? null)
const port = computed(() => (store.ports[props.hostId] ?? []).find((p) => p.id === portId.value) ?? null)
const layer = computed(() => port.value?.layer ?? null)

const blocked = computed(() => {
  if (!port.value) return null
  if (!port.value.acquired) return t('ports.blockedNotAcquired')
  if (port.value.status !== 'IDLE') return t('ports.blockedBusy')
  return null
})

const draft = reactive({
  mode: 'L3' as 'L2' | 'L3',
  dst_mac: '',
  ipv4_src: '',
  ipv4_dst: '',
  vlan: '',
  ipv6: false,
  ipv6_src: '',
  promiscuous: false,
  multicast: false,
  link_up: true,
  flow_ctrl: 0,
})

function reset() {
  const l = layer.value
  if (!l) return
  Object.assign(draft, {
    mode: l.mode,
    dst_mac: l.mode === 'L2' ? l.dst_mac : '',
    ipv4_src: l.ipv4_src ?? '',
    ipv4_dst: l.ipv4_dst ?? '',
    vlan: l.vlan.join(', '),
    ipv6: l.ipv6,
    ipv6_src: l.ipv6_src ?? '',
    promiscuous: l.promiscuous,
    multicast: l.multicast,
    link_up: l.link_up,
    flow_ctrl: l.flow_ctrl ?? 0,
  })
}
watch(portId, () => {
  reset()
  pings.value = []
}, { immediate: true })

function parseVlan(text: string): number[] | null {
  const parts = text.split(/[\s,/]+/).filter(Boolean)
  const tags = parts.map(Number)
  if (tags.length > 2 || tags.some((n) => !Number.isInteger(n) || n < 1 || n > 4094)) return null
  return tags
}
const vlanTags = computed(() => parseVlan(draft.vlan))
const vlanError = computed(() =>
  vlanTags.value === null ? t('ports.vlanError') : null,
)

/** Only the sections that differ from the port's current settings. */
const changes = computed<PortConfig>(() => {
  const l = layer.value
  if (!l || !vlanTags.value) return {}
  const want: PortSettings = {
    mode: draft.mode,
    dst_mac: draft.dst_mac.trim(),
    ipv4_src: draft.ipv4_src.trim(),
    ipv4_dst: draft.ipv4_dst.trim(),
    vlan: vlanTags.value,
    ipv6: draft.ipv6,
    ipv6_src: draft.ipv6_src.trim() || null,
    promiscuous: draft.promiscuous,
    multicast: draft.multicast,
    flow_ctrl: l.flow_ctrl === null ? null : draft.flow_ctrl,
  }
  const out = diffConfig(l, want)
  if (l.link_supported && draft.link_up !== l.link_up) out.link_up = draft.link_up
  return out
})
const dirty = computed(() => Object.keys(changes.value).length > 0)

const busy = ref(false)
const warnings = ref<string[]>([])

// --- apply to other ticked ports ---
// Only settings that make sense on many ports at once; addresses stay per port.
const alsoOthers = persisted('portConfig.alsoOthers', false)
const others = computed(() => {
  const ticked = new Set(store.checked[props.hostId] ?? [])
  return (store.ports[props.hostId] ?? []).filter((p) => p.id !== portId.value && ticked.has(p.id))
})
const otherReady = computed(() => others.value.filter((p) => p.acquired && p.status === 'IDLE'))
const shared = computed<PortConfig>(() => {
  const c = changes.value
  const out: PortConfig = {}
  if (c.vlan) out.vlan = c.vlan
  if (c.ipv6) out.ipv6 = { enabled: c.ipv6.enabled } // each port keeps its own address
  if (c.promiscuous !== undefined) out.promiscuous = c.promiscuous
  if (c.multicast !== undefined) out.multicast = c.multicast
  if (c.flow_ctrl !== undefined) out.flow_ctrl = c.flow_ctrl // skipped on ports without flow control
  return out
})
const sharedLabel = computed(() =>
  [shared.value.vlan && 'VLAN', shared.value.ipv6 && 'IPv6', shared.value.promiscuous !== undefined && t('ports.promiscuous'),
    shared.value.multicast !== undefined && t('ports.multicast'), shared.value.flow_ctrl !== undefined && t('ports.flowControl')]
    .filter(Boolean)
    .join(t('ports.listSep')),
)

async function apply() {
  if (portId.value === null || vlanError.value) return
  busy.value = true
  warnings.value = []
  const failed: string[] = []
  // Snapshot first: once this port is updated, `changes` (a diff against it) is empty.
  const mine = changes.value
  const toOthers = alsoOthers.value && Object.keys(shared.value).length ? { ...shared.value } : null
  const targets = toOthers ? otherReady.value.map((p) => p.id) : []
  try {
    warnings.value = await store.configurePort(props.hostId, portId.value, mine)
    for (const id of targets) {
      const cfg = { ...toOthers! }
      if (store.ports[props.hostId]?.find((p) => p.id === id)?.layer?.flow_ctrl === null) delete cfg.flow_ctrl
      if (!Object.keys(cfg).length) continue
      try {
        warnings.value.push(...(await store.configurePort(props.hostId, id, cfg)))
      } catch (e) {
        failed.push(t('ports.portFailed', { id, error: (e as Error).message }))
      }
    }
    // Ports changed by hand no longer follow the last applied profile.
    profiles.forgetPorts(props.hostId, [portId.value, ...targets]).catch(() => undefined)
    const count = 1 + targets.length - failed.length
    if (failed.length) message.error(t('ports.partialFailed', { list: failed.join(t('ports.failedSep')) }), { duration: 8000 })
    else if (!warnings.value.length)
      message.success(count > 1 ? t('ports.appliedCount', { n: count }) : t('ports.appliedOne', { id: portId.value }))
    reset()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

async function resolve() {
  if (portId.value === null) return
  busy.value = true
  try {
    warnings.value = await store.resolve(props.hostId, [portId.value])
    if (!warnings.value.length) message.success(t('ports.arpResolveOk'))
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

// --- ping ---
// Remembered per browser and port.
const pingTargets = persisted<Record<string, string>>('pingTargets', {})
const pingTarget = computed({
  get: () => pingTargets.value[`${props.hostId}:${portId.value}`] ?? '',
  set: (v: string) => (pingTargets.value[`${props.hostId}:${portId.value}`] = v),
})
const pingCount = persisted('pingCount', 3)
const pings = ref<PingRecord[]>([])
const pinging = ref(false)
async function ping() {
  if (portId.value === null) return
  pinging.value = true
  try {
    pings.value = await api.ping(props.hostId, portId.value, pingTarget.value.trim() || layer.value?.ipv4_dst || '', pingCount.value)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    pinging.value = false
  }
}
const pingSummary = computed(() => {
  const ok = pings.value.filter((r) => r.state === 'ok')
  if (!pings.value.length) return ''
  const rtts = ok.map((r) => r.rtt_ms ?? 0)
  const counts = { ok: ok.length, total: pings.value.length }
  return rtts.length
    ? t('ports.pingSummaryRtt', { ...counts, min: Math.min(...rtts).toFixed(3), max: Math.max(...rtts).toFixed(3) })
    : t('ports.pingSummary', counts)
})

const arpTag = computed(() => {
  const a = layer.value?.arp
  if (a === 'resolved') return { type: 'success' as const, text: t('ports.arpResolved', { mac: layer.value?.dst_mac }) }
  if (a === 'unresolved') return { type: 'error' as const, text: t('ports.arpUnresolved') }
  return null
})
</script>

<template>
  <NEmpty v-if="!port || !layer" :description="t('ports.pickPort')" />
  <NSpace v-else vertical :size="12" style="max-width: 820px">
    <PortProfiles :host-id="hostId" />
    <NSpace align="center">
      <NText strong>{{ t('ports.title', { id: port.id }) }}</NText>
      <NTag size="small" :bordered="false">{{ layer.mode }}</NTag>
      <NText depth="3" code>{{ layer.src_mac }}</NText>
    </NSpace>
    <NAlert v-if="blocked" type="info" :show-icon="false">{{ blocked }}</NAlert>
    <NAlert v-for="w in warnings" :key="w" type="warning" :show-icon="false">{{ w }}</NAlert>

    <NForm
      :label-placement="viewportWidth < NARROW ? 'top' : 'left'"
      label-width="130"
      size="small"
      :disabled="!!blocked"
      class="form"
    >
      <NFormItem :label="t('ports.mode')">
        <NRadioGroup v-model:value="draft.mode">
          <NSpace :size="16">
            <NRadio value="L3">{{ t('ports.modeL3') }}</NRadio>
            <NRadio value="L2">{{ t('ports.modeL2') }}</NRadio>
          </NSpace>
        </NRadioGroup>
      </NFormItem>
      <template v-if="draft.mode === 'L2'">
        <NFormItem :label="t('ports.dstMac')">
          <NInput v-model:value="draft.dst_mac" :placeholder="t('ports.example', { value: '00:11:22:33:44:55' })" style="width: 260px; max-width: 100%" />
        </NFormItem>
        <NText depth="3" :style="`font-size: 12px; display: block; margin: -8px 0 12px ${viewportWidth < NARROW ? 0 : 130}px`">
          {{ t('ports.dstMacHint') }}
        </NText>
      </template>
      <template v-else>
        <NFormItem :label="t('ports.localIpv4')">
          <NInput v-model:value="draft.ipv4_src" :placeholder="t('ports.example', { value: '10.0.0.2' })" style="width: 200px; max-width: 100%" />
        </NFormItem>
        <NFormItem :label="t('ports.gatewayIpv4')">
          <NSpace align="center">
            <NInput v-model:value="draft.ipv4_dst" :placeholder="t('ports.example', { value: '10.0.0.1' })" style="width: 200px; max-width: 100%" />
            <NTag v-if="arpTag" size="small" :type="arpTag.type" :bordered="false">{{ arpTag.text }}</NTag>
            <NButton v-if="layer.mode === 'L3'" size="tiny" :loading="busy" :disabled="!!blocked" @click="resolve">{{ t('ports.reResolve') }}</NButton>
          </NSpace>
        </NFormItem>
        <NText depth="3" :style="`font-size: 12px; display: block; margin: -8px 0 12px ${viewportWidth < NARROW ? 0 : 130}px`">
          {{ t('ports.gatewayHint') }}
        </NText>
      </template>
      <NFormItem label="VLAN" :validation-status="vlanError ? 'error' : undefined" :feedback="vlanError ?? undefined">
        <NInput v-model:value="draft.vlan" :placeholder="t('ports.vlanPlaceholder')" style="width: 260px; max-width: 100%" />
      </NFormItem>
      <NFormItem label="IPv6">
        <NSpace align="center">
          <NSwitch v-model:value="draft.ipv6" />
          <NInput
            v-if="draft.ipv6"
            v-model:value="draft.ipv6_src"
            :placeholder="t('ports.ipv6Placeholder')"
            style="width: 300px; max-width: 100%"
          />
        </NSpace>
      </NFormItem>
      <NFormItem :label="t('ports.promiscuous')">
        <NSwitch v-model:value="draft.promiscuous" />
        <NText depth="3" style="margin-left: 8px; font-size: 12px">{{ t('ports.promiscHint') }}</NText>
      </NFormItem>
      <NFormItem :label="t('ports.multicast')">
        <NSwitch v-model:value="draft.multicast" />
      </NFormItem>
      <NFormItem :label="t('ports.flowControl')">
        <NSelect
          v-if="layer.flow_ctrl !== null"
          v-model:value="draft.flow_ctrl"
          :options="flowCtrlLabels().map((label, value) => ({ label, value }))"
          style="width: 260px; max-width: 100%"
        />
        <NText v-else depth="3" style="font-size: 12px">{{ t('ports.flowCtrlUnsupported') }}</NText>
      </NFormItem>
      <NFormItem :label="t('ports.link')">
        <NSpace v-if="layer.link_supported" align="center">
          <NSwitch v-model:value="draft.link_up" />
          <NText>{{ draft.link_up ? 'UP' : 'DOWN' }}</NText>
          <NText v-if="layer.link_up && !draft.link_up" type="warning" style="font-size: 12px">
            {{ t('ports.linkDownWarn') }}
          </NText>
        </NSpace>
        <NText v-else depth="3" style="font-size: 12px">{{ t('ports.linkUnsupported') }}</NText>
      </NFormItem>
      <NFormItem v-if="others.length" label=" ">
        <NSpace vertical :size="2">
          <NCheckbox v-model:checked="alsoOthers">
            {{ t('ports.alsoOthers', { ports: otherReady.map((p) => p.id).join(', ') || t('common.none') }) }}
          </NCheckbox>
          <NText depth="3" style="font-size: 12px">
            {{ t('ports.alsoOthersScope', { thisTime: sharedLabel ? t('ports.alsoOthersThisTime', { list: sharedLabel }) : '' }) }}
            <template v-if="others.length > otherReady.length">
              {{ t('ports.othersSkipped', { ports: others.filter((p) => !otherReady.includes(p)).map((p) => p.id).join(', ') }) }}
            </template>
          </NText>
        </NSpace>
      </NFormItem>
      <NFormItem label=" ">
        <NSpace>
          <NPopconfirm v-if="changes.link_up === false" @positive-click="apply">
            <template #trigger>
              <NButton type="primary" :disabled="!!vlanError || !!blocked" :loading="busy">{{ t('common.apply') }}</NButton>
            </template>
            {{ t('ports.confirmLinkDown', { id: portId }) }}
          </NPopconfirm>
          <NButton v-else type="primary" :disabled="!dirty || !!vlanError || !!blocked" :loading="busy" @click="apply">{{ t('common.apply') }}</NButton>
          <NButton :disabled="!dirty" @click="reset">{{ t('ports.revert') }}</NButton>
        </NSpace>
      </NFormItem>
    </NForm>

    <NDivider style="margin: 4px 0" />
    <NText strong>Ping</NText>
    <NSpace align="center">
      <NInput
        v-model:value="pingTarget"
        :placeholder="layer.ipv4_dst ? t('ports.pingDefaultGateway', { ip: layer.ipv4_dst }) : t('ports.pingDstIp')"
        style="width: 240px; max-width: 100%"
        size="small"
        :disabled="!!blocked"
      />
      <NInputNumber v-model:value="pingCount" :min="1" :max="20" size="small" style="width: 100px; max-width: 100%" :disabled="!!blocked" />
      <NButton size="small" :loading="pinging" :disabled="!!blocked" @click="ping">Ping</NButton>
      <NText v-if="pingSummary" depth="2">{{ pingSummary }}</NText>
    </NSpace>
    <NDataTable
      :scrollbar-props="{ trigger: 'none' }"
      v-if="pings.length"
      size="small"
      :data="pings.map((r, i) => ({ ...r, i: i + 1 }))"
      :columns="[
        { title: '#', key: 'i', width: 50 },
        { title: t('ports.col.result'), key: 'state', width: 100 },
        { title: t('ports.col.responder'), key: 'responder' },
        { title: 'RTT (ms)', key: 'rtt_ms', render: (r: PingRecord) => (r.rtt_ms == null ? '—' : r.rtt_ms.toFixed(3)) },
        { title: 'TTL', key: 'ttl', render: (r: PingRecord) => r.ttl ?? '—' },
      ]"
      style="max-width: 600px"
    />

    <NDivider style="margin: 4px 0" />
    <NamespacePanel :host-id="hostId" :port="port.id" />
  </NSpace>
</template>
