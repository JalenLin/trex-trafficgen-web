<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAutoComplete, NButton, NButtonGroup, NDivider, NInputNumber, NPopconfirm, NSpace, NText, NTooltip, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useHostsStore, type TrafficAction } from '../stores/hosts'
import { persisted, pushRecent } from '../utils/prefs'

const props = defineProps<{ hostId: string }>()

const store = useHostsStore()
const message = useMessage()
const { t } = useI18n()
const busy = ref(false)
// Remembered per browser: the last multiplier and recently used ones.
const mult = persisted('traffic.mult', '')
const multHistory = persisted<string[]>('traffic.multHistory', [])
const multOptions = computed(() => multHistory.value.map((v) => ({ label: v, value: v })))
const rememberMult = () => mult.value.trim() && pushRecent(multHistory, mult.value.trim(), 8)

const ports = computed(() => store.ports[props.hostId] ?? [])
const checkedIds = computed(() => store.checked[props.hostId] ?? [])
const checked = computed(() => ports.value.filter((p) => checkedIds.value.includes(p.id)))

const ownedByOthers = computed(() => checked.value.filter((p) => p.owner && !p.acquired).map((p) => p.id))
const notMine = computed(() => checked.value.filter((p) => !p.acquired).map((p) => p.id))
const mine = computed(() => checked.value.filter((p) => p.acquired))
const running = computed(() => mine.value.filter((p) => p.status !== 'IDLE').map((p) => p.id))
const ids = (list: { id: number }[]) => list.map((p) => p.id)

async function run(label: string, action: () => Promise<void>) {
  busy.value = true
  try {
    await action()
  } catch (e) {
    message.error(t('toolbar.failed', { action: label, error: (e as Error).message }))
  } finally {
    busy.value = false
  }
}

const acquire = (force: boolean) => run(t('toolbar.acquire'), () => store.acquire(props.hostId, checkedIds.value, force))
const release = () => run(t('toolbar.release'), () => store.release(props.hostId, ids(mine.value)))
// Remembered per browser: seconds to transmit after Start (empty = until Stop).
const duration = persisted<number | null>('traffic.duration', null)

const traffic = (action: TrafficAction, force = false) =>
  run(t(`toolbar.${action}`), async () => {
    await store.traffic(props.hostId, action, ids(mine.value), { mult: mult.value.trim() || '1', force, duration: duration.value })
    if (action === 'start') rememberMult()
  })
const updateRate = () =>
  run(t('toolbar.updateRate'), async () => {
    await store.updateRate(props.hostId, running.value, mult.value.trim())
    rememberMult()
  })
</script>

<template>
  <NSpace align="center" :size="8" class="toolbar">
    <NText depth="2" class="count">{{ t('toolbar.checkedCount', { n: checkedIds.length }) }}</NText>

    <NButtonGroup size="small">
      <NButton :disabled="!notMine.length" :loading="busy" @click="acquire(false)">{{ t('toolbar.acquire') }}</NButton>
      <NPopconfirm v-if="ownedByOthers.length" @positive-click="acquire(true)">
        <template #trigger>
          <NButton type="warning" :loading="busy">{{ t('toolbar.forceAcquire') }}</NButton>
        </template>
        {{ t('toolbar.forceConfirm', { ports: ownedByOthers.join(', ') }) }}
      </NPopconfirm>
      <NButton :disabled="!mine.length" :loading="busy" @click="release">{{ t('toolbar.release') }}</NButton>
    </NButtonGroup>

    <NDivider vertical />

    <NButtonGroup size="small">
      <NPopconfirm v-if="running.length" @positive-click="traffic('start', true)">
        <template #trigger>
          <NButton type="primary" :loading="busy">▶ {{ t('toolbar.start') }}</NButton>
        </template>
        {{ t('toolbar.restartConfirm', { ports: running.join(', ') }) }}
      </NPopconfirm>
      <NButton v-else type="primary" :disabled="!mine.length" :loading="busy" @click="traffic('start')">▶ {{ t('toolbar.start') }}</NButton>
      <NButton :disabled="!running.length" :loading="busy" @click="traffic('stop')">■ {{ t('toolbar.stop') }}</NButton>
      <NButton :disabled="!running.length" :loading="busy" @click="traffic('pause')">{{ t('toolbar.pause') }}</NButton>
      <NButton :disabled="!running.length" :loading="busy" @click="traffic('resume')">{{ t('toolbar.resume') }}</NButton>
    </NButtonGroup>

    <NInputNumber
      v-model:value="duration"
      size="small"
      :min="0"
      clearable
      :placeholder="t('toolbar.noTimeLimit')"
      style="width: 150px"
      :title="t('toolbar.durationTitle')"
    >
      <template #suffix>{{ t('common.seconds') }}</template>
    </NInputNumber>

    <NPopconfirm @positive-click="traffic('reset')">
      <template #trigger>
        <NButton size="small" quaternary :disabled="!mine.length" :loading="busy">{{ t('toolbar.reset') }}</NButton>
      </template>
      {{ t('toolbar.resetConfirm1', { ports: ids(mine).join(', ') }) }}<br />{{ t('toolbar.resetConfirm2') }}
    </NPopconfirm>

    <NDivider vertical />

    <NTooltip>
      <template #trigger>
        <NAutoComplete
          v-model:value="mult"
          :options="multOptions"
          :get-show="() => true"
          size="small"
          :placeholder="t('toolbar.multPlaceholder')"
          style="width: 170px"
          clearable
        />
      </template>
      {{ t('toolbar.multHelp1') }}<br />
      {{ t('toolbar.multHelpFormat') }}<code>2</code>{{ t('toolbar.multHelp2x') }}{{ t('toolbar.sep') }}<code>50%</code>{{ t('toolbar.multHelpPct')
      }}{{ t('toolbar.sep') }}<code>10kpps</code>{{ t('toolbar.sep') }}<code>5gbps</code>
    </NTooltip>
    <NButton size="small" :disabled="!running.length || !mult.trim()" :loading="busy" @click="updateRate">{{ t('toolbar.apply') }}</NButton>

    <NText v-if="checkedIds.length && !mine.length" depth="3" class="hint">{{ t('toolbar.acquireFirst') }}</NText>
  </NSpace>
</template>

<style scoped>
.toolbar {
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(128, 128, 128, 0.06);
}
.count {
  min-width: 110px;
}
.hint {
  font-size: 12px;
}
</style>
