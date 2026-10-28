<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NAlert, NButton, NCard, NCheckbox, NForm, NFormItem, NInputNumber, NModal, NPopconfirm, NRadio, NRadioGroup, NSpace, NText,
  useMessage,
} from 'naive-ui'
import { api, MAX_PUSH_COUNT, type PcapMeta } from '../../api'
import { useI18n } from 'vue-i18n'
import { NARROW, viewportWidth } from '../../composables/useViewport'
import { useHostsStore } from '../../stores/hosts'
import { formatPps } from '../../utils/format'
import { persisted } from '../../utils/prefs'

const props = defineProps<{ show: boolean; hostId: string; pcap: PcapMeta | null }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const hosts = useHostsStore()
const message = useMessage()
const { t } = useI18n()
const busy = ref(false)

// Remembered per browser: the replay settings last used.
const opts = persisted('pcap.push', {
  timing: 'original' as 'original' | 'fixed',
  speedup: 1,
  ipg_usec: 100,
  min_ipg_usec: null as number | null,
  count: 1,
  forever: false,
  duration: null as number | null,
  src_mac_pcap: false,
  dst_mac_pcap: false,
})

// Targets: the ticked ports that are mine, else the focused one if it is.
const targets = computed(() => {
  const ports = hosts.ports[props.hostId] ?? []
  const ticked = hosts.checked[props.hostId] ?? []
  const ids = ticked.length ? ticked : hosts.focused[props.hostId] != null ? [hosts.focused[props.hostId]!] : []
  return ports.filter((p) => ids.includes(p.id))
})
const mine = computed(() => targets.value.filter((p) => p.acquired))
const running = computed(() => mine.value.filter((p) => p.status !== 'IDLE').map((p) => p.id))
const notMine = computed(() => targets.value.filter((p) => !p.acquired).map((p) => p.id))

const estimate = computed(() => {
  const m = props.pcap
  if (!m) return ''
  const o = opts.value
  const pass = o.timing === 'fixed' ? (m.packets * (o.ipg_usec || 0)) / 1e6 : m.duration_s / Math.max(o.speedup || 1, 1e-9)
  const pps = pass > 0 ? m.packets / pass : 0
  return t('pcap.push.estimate', {
    packets: m.packets.toLocaleString(),
    time: pass < 1 ? `${(pass * 1000).toFixed(1)} ms` : `${pass.toFixed(2)} s`,
    rate: formatPps(pps),
  })
})

watch(
  () => props.show,
  (open) => open && targets.value.length === 0 && message.warning(t('pcap.push.pickPortsFirst')),
)

async function push(force = false) {
  if (!props.pcap) return
  const o = opts.value
  busy.value = true
  try {
    const list = await api.pushPcap(props.hostId, props.pcap.id, {
      ports: mine.value.map((p) => p.id),
      ipg_usec: o.timing === 'fixed' ? o.ipg_usec : null,
      speedup: o.timing === 'original' ? o.speedup : 1,
      min_ipg_usec: o.timing === 'original' ? o.min_ipg_usec : null,
      count: o.forever ? MAX_PUSH_COUNT : o.count,
      duration: o.duration && o.duration > 0 ? o.duration : -1,
      src_mac_pcap: o.src_mac_pcap,
      dst_mac_pcap: o.dst_mac_pcap,
      force,
    })
    hosts.ports[props.hostId] = list
    message.success(t('pcap.push.started', { ports: mine.value.map((p) => p.id).join(', '), name: props.pcap.name }))
    emit('update:show', false)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <NModal :show="show" @update:show="(v: boolean) => emit('update:show', v)">
    <NCard v-if="pcap" style="width: min(640px, 94vw)" :title="t('pcap.push.title', { name: pcap.name })" size="small" :bordered="false">
      <NForm :label-placement="viewportWidth < NARROW ? 'top' : 'left'" label-width="110" size="small">
        <NFormItem :label="t('common.port')">
          <NText v-if="mine.length">{{ t('pcap.push.portList', { ports: mine.map((p) => p.id).join(', ') }) }}</NText>
          <NText v-else type="warning">{{ t('pcap.push.noneAcquired') }}</NText>
          <NText v-if="notMine.length" depth="3" style="margin-left: 8px; font-size: 12px">
            {{ t('pcap.push.skipped', { ports: notMine.join(', ') }) }}
          </NText>
        </NFormItem>
        <NFormItem :label="t('pcap.push.timing')">
          <NRadioGroup v-model:value="opts.timing">
            <NSpace vertical :size="6">
              <NSpace align="center">
                <NRadio value="original">{{ t('pcap.push.timingOriginal') }}</NRadio>
                <NInputNumber v-model:value="opts.speedup" :min="0.001" :step="1" size="small" style="width: 110px" :disabled="opts.timing !== 'original'" />
                <NText depth="3">{{ t('pcap.push.times') }}</NText>
              </NSpace>
              <NSpace align="center">
                <NRadio value="fixed">{{ t('pcap.push.timingFixed') }}</NRadio>
                <NInputNumber v-model:value="opts.ipg_usec" :min="0" size="small" style="width: 110px" :disabled="opts.timing !== 'fixed'" />
                <NText depth="3">μs</NText>
              </NSpace>
            </NSpace>
          </NRadioGroup>
        </NFormItem>
        <NFormItem v-if="opts.timing === 'original'" :label="t('pcap.push.minGap')">
          <NSpace align="center">
            <NInputNumber v-model:value="opts.min_ipg_usec" :min="0" size="small" style="width: 110px" clearable :placeholder="t('pcap.push.unlimited')" />
            <NText depth="3" style="font-size: 12px">{{ t('pcap.push.minGapNote') }}</NText>
          </NSpace>
        </NFormItem>
        <NFormItem :label="t('pcap.push.count')">
          <NSpace align="center">
            <NInputNumber v-model:value="opts.count" :min="1" size="small" style="width: 110px" :disabled="opts.forever" />
            <NCheckbox v-model:checked="opts.forever">{{ t('pcap.push.forever') }}</NCheckbox>
          </NSpace>
        </NFormItem>
        <NFormItem :label="t('pcap.push.durationLimit')">
          <NSpace align="center">
            <NInputNumber v-model:value="opts.duration" :min="0" size="small" style="width: 110px" clearable :placeholder="t('pcap.push.unlimited')" />
            <NText depth="3">{{ t('common.seconds') }}</NText>
          </NSpace>
        </NFormItem>
        <NFormItem label="MAC">
          <NSpace vertical :size="2">
            <NCheckbox v-model:checked="opts.src_mac_pcap">{{ t('pcap.push.srcMac') }}</NCheckbox>
            <NCheckbox v-model:checked="opts.dst_mac_pcap">{{ t('pcap.push.dstMac') }}</NCheckbox>
            <NText depth="3" style="font-size: 12px">{{ t('pcap.push.macNote') }}</NText>
          </NSpace>
        </NFormItem>
      </NForm>
      <NAlert type="info" :show-icon="false">
        {{ t('pcap.push.replayNote', { estimate }) }}
      </NAlert>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="emit('update:show', false)">{{ t('common.cancel') }}</NButton>
          <NPopconfirm v-if="running.length" @positive-click="push(true)">
            <template #trigger>
              <NButton type="primary" :disabled="!mine.length" :loading="busy">{{ t('pcap.push.start') }}</NButton>
            </template>
            {{ t('pcap.push.confirmForce', { ports: running.join(', ') }) }}
          </NPopconfirm>
          <NButton v-else type="primary" :disabled="!mine.length" :loading="busy" @click="push()">{{ t('pcap.push.start') }}</NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>
