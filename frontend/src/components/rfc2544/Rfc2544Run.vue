<script setup lang="ts">
// Status of the current (or last) job of this backend session: progress, Stop, log.
import { computed } from 'vue'
import { NAlert, NButton, NPopconfirm, NTag, NText } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { Rfc2544Job } from '../../api'
import { clock, clockSpan, dateTime, logText, num, testName, type Translate } from './util'

const props = defineProps<{ job: Rfc2544Job; now: number; stopping: boolean }>()
const emit = defineEmits<{ stop: [] }>()
const { t: i18nT } = useI18n()
const t: Translate = (k, p) => (p ? i18nT(k, p) : i18nT(k))

const running = computed(() => props.job.state === 'running')
const elapsed = computed(() => clockSpan((props.job.finished ?? props.now) - props.job.started))
const prog = computed(() => props.job.progress ?? {})
const stateType = (s: string) => (s === 'done' ? 'success' : s === 'error' ? 'error' : s === 'stopped' ? 'warning' : 'info')

const items = computed(() => {
  const p = prog.value
  const out: { label: string; value: string }[] = []
  if (running.value) {
    out.push({ label: t('rfc2544.run.currentTest'), value: p.test ? testName(t, p.test) : t('rfc2544.run.waiting') })
    if (p.size != null) out.push({ label: t('rfc2544.run.frameSize'), value: `${p.size} B` })
    if (p.test === 'back_to_back' && p.burst != null) out.push({ label: t('rfc2544.run.burst'), value: t('rfc2544.run.burstFrames', { n: p.burst.toLocaleString() }) })
    else if (p.rate_pct != null) out.push({ label: t('rfc2544.run.rate'), value: t('rfc2544.run.ratePct', { pct: num(p.rate_pct, 3) }) })
  }
  out.push({ label: t('rfc2544.run.trials'), value: String(props.job.trials ?? 0) })
  out.push({ label: t('rfc2544.run.elapsed'), value: elapsed.value })
  out.push({ label: t('rfc2544.run.started'), value: dateTime(props.job.started) })
  if (props.job.client) out.push({ label: t('rfc2544.run.by'), value: props.job.client })
  return out
})

const log = computed(() => (props.job.log ?? []).slice().reverse())
</script>

<template>
  <div class="rfc-run">
    <div class="status-line">
      <NTag :type="stateType(job.state)" :bordered="false" size="small">{{ t(`rfc2544.state.${job.state}`) }}</NTag>
      <NPopconfirm v-if="running" @positive-click="emit('stop')">
        <template #trigger>
          <NButton size="small" type="error" :loading="stopping">{{ t('rfc2544.run.stop') }}</NButton>
        </template>
        {{ t('rfc2544.run.confirmStop') }}
      </NPopconfirm>
    </div>
    <div class="facts">
      <div v-for="it in items" :key="it.label" class="fact">
        <NText depth="3" class="fact-label">{{ it.label }}</NText>
        <span class="fact-value">{{ it.value }}</span>
      </div>
    </div>
    <NAlert v-if="job.state === 'error' && job.error" type="error" :show-icon="false" class="err">{{ job.error }}</NAlert>

    <NText strong class="log-title">{{ t('rfc2544.run.log') }}</NText>
    <div class="log" role="log">
      <div v-for="(e, i) in log" :key="`${e.ts}-${i}`" class="log-row" :class="e.code">
        <span class="log-time">{{ clock(e.ts) }}</span>
        <span class="log-text">{{ logText(t, e) }}</span>
      </div>
      <NText v-if="!log.length" depth="3" class="log-empty">{{ t('rfc2544.run.logEmpty') }}</NText>
    </div>
  </div>
</template>

<style scoped>
.status-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.facts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px 16px;
}
.fact {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.fact-label {
  font-size: 12px;
}
.fact-value {
  font-size: 15px;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.err {
  margin-top: 10px;
}
.log-title {
  display: block;
  margin: 14px 0 6px;
}
.log {
  max-height: 260px;
  overflow: auto;
  border: 1px solid rgba(128, 128, 128, 0.2);
  border-radius: 4px;
  font-size: 12px;
}
.log-row {
  display: flex;
  gap: 10px;
  padding: 3px 8px;
}
.log-row + .log-row {
  border-top: 1px solid rgba(128, 128, 128, 0.1);
}
.log-time {
  flex: none;
  opacity: 0.6;
  font-variant-numeric: tabular-nums;
}
.log-text {
  min-width: 0;
  overflow-wrap: anywhere;
}
.log-row.result .log-text,
.log-row.done .log-text {
  font-weight: 600;
}
.log-row.error .log-text {
  color: #d03050;
}
.log-row.stopped .log-text {
  color: #f0a020;
}
.log-empty {
  display: block;
  padding: 8px;
}
</style>
