<script setup lang="ts">
// Test settings (remembered per browser), the warning block and Start.
import { computed } from 'vue'
import {
  NAlert, NButton, NCheckbox, NCheckboxGroup, NForm, NFormItem, NInputNumber, NSelect, NSpace, NSwitch, NText,
  type SelectOption,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { Rfc2544Config, Rfc2544Test } from '../../api'
import { NARROW, viewportWidth } from '../../composables/useViewport'
import { useHostsStore } from '../../stores/hosts'
import { persisted } from '../../utils/prefs'
import { DEFAULT_SIZES, MAX_SIZE, MIN_SIZE, TESTS, defaultConfig, directions, duration, estimate } from './util'

const props = defineProps<{ hostId: string; busy: boolean; testRunning: boolean }>()
const emit = defineEmits<{ start: [cfg: Rfc2544Config]; error: [text: string] }>()
const { t } = useI18n()
const hosts = useHostsStore()

const cfg = persisted<Rfc2544Config>('rfc2544.config', defaultConfig())
// Older saved settings may lack fields added later.
cfg.value = { ...defaultConfig(), ...cfg.value }

const ports = computed(() => hosts.ports[props.hostId] ?? [])
const portOptions = computed<SelectOption[]>(() =>
  ports.value.map((p) => {
    const speed = p.speed_gbps ? `${p.speed_gbps}G` : t('rfc2544.form.speedUnknown')
    return {
      value: p.id,
      label: t(p.acquired ? 'rfc2544.form.portOption' : 'rfc2544.form.portOptionNotAcquired', { id: p.id, speed }),
    }
  }),
)

// --- pairs ---
function addPair() {
  const used = new Set(cfg.value.pairs.flatMap((p) => [p.tx, p.rx]))
  const free = ports.value.map((p) => p.id).filter((id) => !used.has(id))
  const all = ports.value.map((p) => p.id)
  const tx = free[0] ?? all[0] ?? 0
  const rx = free[1] ?? all.find((id) => id !== tx) ?? tx + 1
  cfg.value.pairs.push({ tx, rx })
}
const removePair = (i: number) => cfg.value.pairs.splice(i, 1)

// --- frame sizes ---
const sizeOptions = computed<SelectOption[]>(() =>
  [...new Set([...DEFAULT_SIZES, ...cfg.value.frame_sizes])].sort((a, b) => a - b).map((n) => ({ label: String(n), value: n })),
)
const onCreateSize = (label: string): SelectOption => ({ label: label.trim(), value: label.trim() })
function setSizes(values: (string | number)[]) {
  const out: number[] = []
  for (const v of values) {
    const n = Number(v)
    if (!Number.isInteger(n) || n < MIN_SIZE || n > MAX_SIZE) emit('error', t('rfc2544.form.badSize', { value: v }))
    else if (!out.includes(n)) out.push(n)
  }
  cfg.value.frame_sizes = out.sort((a, b) => a - b)
}

// --- numbers (NInputNumber gives null while the field is empty; keep the last value) ---
type NumKey = 'trial_s' | 'resolution_pct' | 'max_rate_pct' | 'loss_tolerance_pct' | 'frame_loss_step_pct' | 'b2b_max_s'
const setNum = (key: NumKey) => (v: number | null) => {
  if (v != null && Number.isFinite(v)) cfg.value[key] = v
}
const has = (test: Rfc2544Test) => cfg.value.tests.includes(test)

// --- estimate ---
const est = computed(() => estimate(cfg.value))
const estText = computed(() => {
  const e = est.value
  const tmin = duration(t, e.tmin)
  const tmax = duration(t, e.tmax)
  return e.min === e.max ? t('rfc2544.estimate.textSame', { max: e.max, tmax }) : t('rfc2544.estimate.text', { min: e.min, max: e.max, tmin, tmax })
})

// --- what stops Start ---
const usedPorts = computed(() => [...new Set(cfg.value.pairs.flatMap((p) => [p.tx, p.rx]))].sort((a, b) => a - b))
const blockers = computed(() => {
  const out: string[] = []
  const c = cfg.value
  if (props.testRunning) out.push(t('rfc2544.block.running'))
  if (!c.pairs.length) out.push(t('rfc2544.block.noPairs'))
  if (c.pairs.some((p) => p.tx === p.rx)) out.push(t('rfc2544.block.samePort'))
  const known = new Set(ports.value.map((p) => p.id))
  const unknown = usedPorts.value.filter((id) => !known.has(id))
  if (unknown.length) out.push(t('rfc2544.block.unknownPort', { ports: unknown.join(', ') }))
  const txs = directions(c.pairs, c.bidirectional).map(([tx]) => tx)
  const dup = [...new Set(txs.filter((tx, i) => txs.indexOf(tx) !== i))]
  if (dup.length) out.push(t('rfc2544.block.dupTx', { ports: dup.join(', ') }))
  if (!c.frame_sizes.length) out.push(t('rfc2544.block.noSizes'))
  if (!c.tests.length) out.push(t('rfc2544.block.noTests'))
  return out
})
const notAcquired = computed(() => {
  const byId = new Map(ports.value.map((p) => [p.id, p]))
  return usedPorts.value.filter((id) => byId.has(id) && !byId.get(id)!.acquired)
})
const transmitting = computed(() => {
  if (props.testRunning) return [] // that's the test's own traffic
  const byId = new Map(ports.value.map((p) => [p.id, p]))
  return usedPorts.value.filter((id) => byId.get(id)?.acquired && byId.get(id)!.status !== 'IDLE')
})
const canStart = computed(() => !blockers.value.length && !notAcquired.value.length)

function start() {
  if (!canStart.value) return
  const c = cfg.value
  emit('start', {
    ...c,
    pairs: c.pairs.map((p) => ({ tx: p.tx, rx: p.rx })),
    // tests in the backend's order, whatever order they were ticked in
    tests: TESTS.filter((x) => c.tests.includes(x)),
  })
}
function resetAll() {
  const keepPairs = cfg.value.pairs
  cfg.value = { ...defaultConfig(), pairs: keepPairs }
}

const labelTop = computed(() => viewportWidth.value < NARROW)
</script>

<template>
  <div class="rfc-form">
    <NText depth="3" class="intro">{{ t('rfc2544.intro') }}</NText>
    <NForm :label-placement="labelTop ? 'top' : 'left'" label-width="130" size="small" :show-feedback="false">
      <div class="grid">
        <div class="col">
          <NFormItem :label="t('rfc2544.form.pairs')">
            <div class="field">
              <div v-for="(p, i) in cfg.pairs" :key="i" class="pair-row">
                <label class="end">
                  <span class="dir">{{ t('rfc2544.form.tx') }}</span>
                  <NSelect v-model:value="p.tx" :options="portOptions" class="port-select" :consistent-menu-width="false" />
                </label>
                <span class="arrow" aria-hidden="true">→</span>
                <label class="end">
                  <span class="dir">{{ t('rfc2544.form.rx') }}</span>
                  <NSelect v-model:value="p.rx" :options="portOptions" class="port-select" :consistent-menu-width="false" />
                </label>
                <NButton size="small" quaternary type="error" @click="removePair(i)">{{ t('common.remove') }}</NButton>
              </div>
              <NText v-if="!cfg.pairs.length" depth="3" class="help">{{ t('rfc2544.form.noPairs') }}</NText>
              <div>
                <NButton size="small" dashed @click="addPair">{{ t('rfc2544.form.addPair') }}</NButton>
              </div>
              <NText depth="3" class="help">{{ t('rfc2544.form.pairsHelp') }}</NText>
            </div>
          </NFormItem>
          <NFormItem :label="t('rfc2544.form.bidirectional')">
            <div class="field">
              <NSwitch v-model:value="cfg.bidirectional" />
              <NText depth="3" class="help">{{ t('rfc2544.form.bidirectionalHelp') }}</NText>
            </div>
          </NFormItem>
          <NFormItem :label="t('rfc2544.form.frameSizes')">
            <div class="field">
              <NSelect
                :value="cfg.frame_sizes"
                :options="sizeOptions"
                multiple
                filterable
                tag
                :on-create="onCreateSize"
                :placeholder="t('rfc2544.form.frameSizesPlaceholder')"
                @update:value="setSizes"
              />
              <NSpace align="center" :size="8">
                <NText depth="3" class="help">{{ t('rfc2544.form.frameSizesHelp') }}</NText>
                <NButton size="tiny" quaternary @click="cfg.frame_sizes = [...DEFAULT_SIZES]">{{ t('rfc2544.form.resetSizes') }}</NButton>
              </NSpace>
            </div>
          </NFormItem>
          <NFormItem :label="t('rfc2544.form.tests')">
            <NCheckboxGroup v-model:value="cfg.tests">
              <div class="tests">
                <div v-for="x in TESTS" :key="x" class="test">
                  <NCheckbox :value="x" :label="t(`rfc2544.tests.${x}`)" />
                  <NText depth="3" class="help test-help">{{ t(`rfc2544.testHelp.${x}`) }}</NText>
                </div>
              </div>
            </NCheckboxGroup>
          </NFormItem>
        </div>

        <div class="col">
          <NFormItem :label="t('rfc2544.form.trialS')">
            <NInputNumber :value="cfg.trial_s" :min="1" :max="600" :step="1" class="num" @update:value="setNum('trial_s')($event)">
              <template #suffix>{{ t('common.seconds') }}</template>
            </NInputNumber>
          </NFormItem>
          <NFormItem :label="t('rfc2544.form.maxRate')">
            <div class="field">
              <NInputNumber :value="cfg.max_rate_pct" :min="1" :max="100" :step="1" class="num" @update:value="setNum('max_rate_pct')($event)">
                <template #suffix>{{ t('rfc2544.form.pctOfLine') }}</template>
              </NInputNumber>
              <NText depth="3" class="help">{{ t('rfc2544.form.maxRateHelp') }}</NText>
            </div>
          </NFormItem>
          <NFormItem :label="t('rfc2544.form.lossTolerance')">
            <div class="field">
              <NInputNumber
                :value="cfg.loss_tolerance_pct"
                :min="0"
                :max="99.99"
                :step="0.001"
                class="num"
                @update:value="setNum('loss_tolerance_pct')($event)"
              >
                <template #suffix>%</template>
              </NInputNumber>
              <NText depth="3" class="help">{{ t('rfc2544.form.lossToleranceHelp') }}</NText>
            </div>
          </NFormItem>
          <NFormItem v-if="has('throughput')" :label="t('rfc2544.form.resolution')">
            <div class="field">
              <NInputNumber
                :value="cfg.resolution_pct"
                :min="0.01"
                :max="50"
                :step="0.1"
                class="num"
                @update:value="setNum('resolution_pct')($event)"
              >
                <template #suffix>%</template>
              </NInputNumber>
              <NText depth="3" class="help">{{ t('rfc2544.form.resolutionHelp') }}</NText>
            </div>
          </NFormItem>
          <NFormItem v-if="has('frame_loss')" :label="t('rfc2544.form.frameLossStep')">
            <NInputNumber
              :value="cfg.frame_loss_step_pct"
              :min="1"
              :max="50"
              :step="1"
              class="num"
              @update:value="setNum('frame_loss_step_pct')($event)"
            >
              <template #suffix>%</template>
            </NInputNumber>
          </NFormItem>
          <NFormItem v-if="has('back_to_back')" :label="t('rfc2544.form.b2bMax')">
            <div class="field">
              <NInputNumber :value="cfg.b2b_max_s" :min="0.01" :max="10" :step="0.5" class="num" @update:value="setNum('b2b_max_s')($event)">
                <template #suffix>{{ t('common.seconds') }}</template>
              </NInputNumber>
              <NText depth="3" class="help">{{ t('rfc2544.form.b2bMaxHelp') }}</NText>
            </div>
          </NFormItem>
          <NFormItem :label="t('rfc2544.estimate.title')">
            <div class="field">
              <NText>{{ estText }}</NText>
              <NText depth="3" class="help">{{ t('rfc2544.estimate.note') }}</NText>
            </div>
          </NFormItem>
          <NFormItem label=" ">
            <NButton size="tiny" quaternary @click="resetAll">{{ t('rfc2544.form.resetAll') }}</NButton>
          </NFormItem>
        </div>
      </div>
    </NForm>

    <NAlert type="warning" :title="t('rfc2544.warn.title')" class="warn">
      <ul>
        <li>{{ t('rfc2544.warn.replace') }}</li>
        <li>{{ t('rfc2544.warn.refuse') }}</li>
        <li>{{ t('rfc2544.warn.pgids') }}</li>
        <li>{{ t('rfc2544.warn.loopbackNote') }}</li>
        <li>{{ t('rfc2544.warn.path') }}</li>
      </ul>
    </NAlert>

    <div class="start-row">
      <NButton type="primary" :disabled="!canStart" :loading="busy" @click="start">
        {{ busy ? t('rfc2544.form.starting') : t('rfc2544.form.start') }}
      </NButton>
      <div class="reasons">
        <NText v-for="b in blockers" :key="b" type="error" class="reason">{{ b }}</NText>
        <NText v-if="notAcquired.length" type="error" class="reason">{{ t('rfc2544.block.acquire', { ports: notAcquired.join(', ') }) }}</NText>
        <NText v-if="transmitting.length" type="warning" class="reason">
          {{ t('rfc2544.block.transmitting', { ports: transmitting.join(', ') }) }}
        </NText>
      </div>
    </div>
  </div>
</template>

<style scoped>
.intro {
  display: block;
  font-size: 12px;
  margin-bottom: 10px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr));
  gap: 0 24px;
}
.col :deep(.n-form-item) {
  margin-bottom: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  min-width: 0;
}
.help {
  font-size: 12px;
}
.pair-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.end {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.dir {
  font-size: 12px;
  font-weight: 600;
  opacity: 0.7;
}
.arrow {
  opacity: 0.6;
}
.port-select {
  width: 150px;
  max-width: 100%;
}
.tests {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.test-help {
  display: block;
  padding-left: 24px;
}
.num {
  width: 200px;
  max-width: 100%;
}
.warn {
  margin: 8px 0 12px;
}
.warn ul {
  margin: 0;
  padding-left: 18px;
}
.warn li + li {
  margin-top: 2px;
}
.start-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 8px 14px;
}
.reasons {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1 1 240px;
}
.reason {
  font-size: 13px;
}
</style>
