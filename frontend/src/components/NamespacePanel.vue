<script setup lang="ts">
// Emulated hosts behind a port (TRex namespaces). Needs `stack: linux_based` in the
// server's trex_cfg.yaml; without it TRex refuses and this shows why.
import { computed, h, ref, watch } from 'vue'
import {
  NAlert, NButton, NDataTable, NForm, NFormItem, NInput, NInputNumber, NPopconfirm, NRadioButton, NRadioGroup, NSpace, NSwitch,
  NText, useMessage, type DataTableColumns,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { api, type NsNode, type ServiceMode } from '../api'
import { useHostsStore } from '../stores/hosts'

const props = defineProps<{ hostId: string; port: number }>()
const { t } = useI18n()
const store = useHostsStore()
const message = useMessage()

const nodes = ref<NsNode[]>([])
const unsupported = ref(false)
const loadError = ref<string | null>(null)
const loading = ref(false)
const busy = ref(false)
const portInfo = computed(() => (store.ports[props.hostId] ?? []).find((p) => p.id === props.port) ?? null)
const mine = computed(() => !!portInfo.value?.acquired)

// Nodes only answer (ARP, ping) while the port is in service mode.
const service = computed<ServiceMode>(() => portInfo.value?.layer?.service ?? 'off')
async function setService(mode: ServiceMode) {
  busy.value = true
  try {
    store.ports[props.hostId] = await api.setServiceMode(props.hostId, props.port, mode)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    nodes.value = await api.nsNodes(props.hostId, props.port)
    unsupported.value = false
  } catch (e) {
    const msg = (e as Error).message
    unsupported.value = /linux_based/i.test(msg)
    loadError.value = unsupported.value ? null : msg
    nodes.value = []
  } finally {
    loading.value = false
  }
}
watch(() => [props.hostId, props.port], load, { immediate: true })

// --- add form ---
const randomMac = () =>
  // locally administered unicast: 02:xx:xx:xx:xx:xx
  ['02', ...Array.from({ length: 5 }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, '0'))].join(':')
const mac = ref(randomMac())
const ipv4 = ref('')
const dg = ref('')
const vlans = ref('')
const ipv6 = ref(false)
const mtu = ref<number | null>(null)
const vlanList = computed(() =>
  vlans.value
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(Number),
)
const vlanError = computed(() =>
  vlanList.value.some((v) => !Number.isInteger(v) || v < 1 || v > 4094) || vlanList.value.length > 2 ? t('ns.vlanError') : null,
)
const macOk = computed(() => /^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i.test(mac.value.trim()))
const needDg = computed(() => !!ipv4.value.trim() && !dg.value.trim())

async function add() {
  busy.value = true
  try {
    nodes.value = await api.nsAdd(props.hostId, props.port, {
      mac: mac.value.trim(),
      ipv4: ipv4.value.trim() || null,
      dg: dg.value.trim() || null,
      ipv6: ipv6.value,
      vlans: vlanList.value,
      mtu: mtu.value,
    })
    message.success(t('ns.added', { mac: mac.value.trim() }))
    mac.value = randomMac()
    ipv4.value = ''
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    busy.value = false
  }
}
async function remove(macs: string[]) {
  busy.value = true
  try {
    nodes.value = await api.nsRemove(props.hostId, props.port, macs)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

const macOf = (n: NsNode) => n.ether?.src ?? ''
const columns = computed<DataTableColumns<NsNode>>(() => [
  { title: 'MAC', key: 'mac', minWidth: 150, render: (n) => macOf(n) },
  {
    title: 'IPv4',
    key: 'ipv4',
    minWidth: 140,
    render: (n) => n.ipv4?.src || '—',
  },
  { title: t('ns.gateway'), key: 'dg', minWidth: 120, render: (n) => n.ipv4?.dst || '—' },
  { title: 'VLAN', key: 'vlan', width: 90, render: (n) => (n.vlan?.tags?.length ? n.vlan.tags.join(' / ') : '—') },
  { title: 'IPv6', key: 'ipv6', width: 70, render: (n) => (n.ipv6?.enabled ? n.ipv6.src || '✓' : '—') },
  {
    title: '',
    key: 'rm',
    width: 80,
    render: (n) =>
      h(NPopconfirm, { onPositiveClick: () => remove([macOf(n)]) }, {
        trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error', disabled: !mine.value }, () => t('common.remove')),
        default: () => t('ns.confirmRemove', { mac: macOf(n) }),
      }),
  },
])
</script>

<template>
  <NSpace vertical :size="8">
    <NSpace align="center" justify="space-between">
      <NText strong>{{ t('ns.title') }}</NText>
      <NButton size="tiny" quaternary :loading="loading" @click="load">{{ t('common.refresh') }}</NButton>
    </NSpace>
    <NText depth="3" style="font-size: 12px">{{ t('ns.intro') }}</NText>

    <NAlert v-if="unsupported" type="info" :title="t('ns.unsupportedTitle')">
      {{ t('ns.unsupported') }}
      <pre class="cfg">- port_limit: 2
  version: 2
  stack: linux_based
  ...</pre>
    </NAlert>
    <NAlert v-else-if="loadError" type="error" :show-icon="false">{{ loadError }}</NAlert>

    <template v-else>
      <NSpace align="center" :size="8">
        <NText style="font-size: 13px">{{ t('ns.service.label') }}</NText>
        <NRadioGroup :value="service" size="small" :disabled="!mine || busy" @update:value="setService">
          <NRadioButton value="off">{{ t('ns.service.off') }}</NRadioButton>
          <NRadioButton value="filtered">{{ t('ns.service.filtered') }}</NRadioButton>
          <NRadioButton value="on">{{ t('ns.service.on') }}</NRadioButton>
        </NRadioGroup>
      </NSpace>
      <NText depth="3" style="font-size: 12px">{{ t('ns.service.help') }}</NText>
      <NAlert v-if="nodes.length && service === 'off'" type="warning" :show-icon="false">{{ t('ns.service.offWarn') }}</NAlert>
      <NDataTable size="small" :columns="columns" :data="nodes" :row-key="macOf" :loading="loading" :scroll-x="640">
        <template #empty>{{ t('ns.empty') }}</template>
      </NDataTable>
      <NPopconfirm v-if="nodes.length > 1" @positive-click="remove(nodes.map(macOf))">
        <template #trigger>
          <NButton size="tiny" quaternary type="error" :disabled="!mine" style="align-self: flex-start">{{ t('ns.removeAll') }}</NButton>
        </template>
        {{ t('ns.confirmRemoveAll', { n: nodes.length }) }}
      </NPopconfirm>

      <NText strong style="font-size: 13px">{{ t('ns.addTitle') }}</NText>
      <NForm label-placement="left" label-width="auto" size="small" class="form">
        <NFormItem label="MAC" :feedback="mac && !macOk ? t('ns.macError') : ''" :validation-status="mac && !macOk ? 'error' : undefined">
          <NSpace :size="6" :wrap="false">
            <NInput v-model:value="mac" style="width: 180px" />
            <NButton size="small" quaternary @click="mac = randomMac()">{{ t('ns.randomMac') }}</NButton>
          </NSpace>
        </NFormItem>
        <NFormItem label="IPv4">
          <NInput v-model:value="ipv4" :placeholder="t('ns.ipv4Placeholder')" style="width: 160px" />
        </NFormItem>
        <NFormItem :label="t('ns.gateway')" :feedback="needDg ? t('ns.needDg') : ''" :validation-status="needDg ? 'error' : undefined">
          <NInput v-model:value="dg" :placeholder="t('ns.dgPlaceholder')" style="width: 160px" />
        </NFormItem>
        <NFormItem label="VLAN" :feedback="vlanError ?? ''" :validation-status="vlanError ? 'error' : undefined">
          <NInput v-model:value="vlans" :placeholder="t('ns.vlanPlaceholder')" style="width: 160px" />
        </NFormItem>
        <NFormItem label="IPv6">
          <NSwitch v-model:value="ipv6" />
          <NText depth="3" style="font-size: 12px; margin-left: 8px">{{ t('ns.ipv6Hint') }}</NText>
        </NFormItem>
        <NFormItem label="MTU">
          <NInputNumber v-model:value="mtu" :min="64" :max="9216" clearable :placeholder="t('ns.optional')" style="width: 120px" />
        </NFormItem>
        <NFormItem label=" ">
          <NButton type="primary" :disabled="!mine || !macOk || !!vlanError || needDg" :loading="busy" @click="add">{{ t('ns.add') }}</NButton>
          <NText v-if="!mine" type="warning" style="font-size: 12px; margin-left: 8px">{{ t('ns.needPort', { port }) }}</NText>
        </NFormItem>
      </NForm>
    </template>
  </NSpace>
</template>

<style scoped>
.cfg {
  margin: 6px 0 0;
  padding: 6px 8px;
  font-size: 12px;
  background: rgba(128, 128, 128, 0.08);
  border-radius: 4px;
  white-space: pre;
  overflow-x: auto;
}
.form {
  max-width: 560px;
}
</style>
