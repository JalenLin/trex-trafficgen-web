<script setup lang="ts">
// Opt-in monitoring. Everything here costs RPC time on the TRex master thread, so
// it is off until a user turns it on, with the measured cost spelled out first.
import { computed, ref, watch } from 'vue'
import { NAlert, NCheckbox, NDataTable, NEmpty, NInput, NSelect, NSpace, NSwitch, NText, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { api, type LogEvent, type MonitorExtra, type MonitorSettings } from '../../api'
import { formatCount } from '../../utils/format'
import { persisted } from '../../utils/prefs'

const props = defineProps<{
  hostId: string
  settings: MonitorSettings | null
  extra: MonitorExtra | null
  events: LogEvent[]
  portCount: number
}>()
const { t } = useI18n()
const message = useMessage()
const saving = ref(false)

// Local copy: the server's settings arrive with the next stats tick, and two quick
// clicks must not send the second change on top of the stale first one.
const local = ref<MonitorSettings | null>(null)
let pending = 0
watch(
  () => props.settings,
  (s) => {
    if (!pending) local.value = s ? { ...s } : null
  },
  { immediate: true, deep: true },
)
const on = computed(() => !!local.value && (local.value.cpu || local.value.xstats))
const intervals = computed(() => [1, 2, 5, 10].map((n) => ({ label: t('monitor.extra.everyN', { n }), value: n })))

/** Who switched it on: the latest monitorOn entry in the event log. */
const turnedOnBy = computed(() => {
  const e = [...props.events].reverse().find((x) => x.source === 'gui' && x.code === 'monitorOn')
  return e ? `${e.client ?? '?'} · ${new Date(e.ts * 1000).toLocaleString()}` : null
})

async function change(patch: Partial<MonitorSettings>) {
  if (!local.value) return
  local.value = { ...local.value, ...patch }
  pending++
  saving.value = true
  try {
    const saved = await api.setMonitor(props.hostId, local.value)
    if (pending === 1) local.value = saved
  } catch (e) {
    message.error((e as Error).message)
    if (pending === 1) local.value = props.settings ? { ...props.settings } : null
  } finally {
    pending--
    saving.value = pending > 0
  }
}

// --- per-core utilization ---
const cores = computed(() =>
  (props.extra?.cpu ?? []).map((c, i) => {
    const ports = c.ports.filter((p) => p >= 0)
    return { n: i + 1, ports, history: c.history, now: c.history[0] ?? 0 }
  }),
)
const mbufRows = computed(() =>
  Object.entries(props.extra?.mbuf ?? {}).flatMap(([sock, pools]) =>
    Object.entries(pools)
      .sort(([a], [b]) => parseFloat(a) * (a.includes('k') ? 1024 : 1) - parseFloat(b) * (b.includes('k') ? 1024 : 1))
      .map(([size, v]) => ({ key: `${sock}/${size}`, socket: sock.replace('cpu-', ''), size, ...v })),
  ),
)
const mbufColumns = computed(() => [
  { title: t('monitor.extra.socket'), key: 'socket', width: 90 },
  { title: t('monitor.extra.size'), key: 'size', width: 70 },
  { title: t('monitor.extra.used'), key: 'used', align: 'right' as const, render: (r: { used: number; total: number }) => `${formatCount(r.used)} (${((r.used / r.total) * 100).toFixed(1)} %)` },
  { title: t('monitor.extra.total'), key: 'total', align: 'right' as const, render: (r: { total: number }) => formatCount(r.total) },
])

// --- xstats: counters per port, with the change per second since the previous fetch ---
const xFilter = persisted('monitor.xstatsFilter', '')
const hideZero = persisted('monitor.xstatsHideZero', true)
const prevX = ref<{ ts: number; data: Record<string, Record<string, number>> } | null>(null)
const lastX = ref<{ ts: number; data: Record<string, Record<string, number>> } | null>(null)
watch(
  () => props.extra,
  (x) => {
    if (!x?.xstats) return
    prevX.value = lastX.value
    lastX.value = { ts: x.ts, data: x.xstats }
  },
)
const xPorts = computed(() => Object.keys(lastX.value?.data ?? {}))
const xRows = computed(() => {
  const cur = lastX.value
  if (!cur) return []
  const prev = prevX.value
  const dt = prev ? cur.ts - prev.ts : 0
  const names = new Set(Object.values(cur.data).flatMap((d) => Object.keys(d)))
  const q = xFilter.value.trim().toLowerCase()
  return [...names]
    .filter((n) => !q || n.toLowerCase().includes(q))
    .map((name) => {
      const row: Record<string, string | number> = { name }
      let any = false
      for (const p of xPorts.value) {
        const v = cur.data[p]?.[name] ?? 0
        if (v) any = true
        const d = prev && dt > 0 ? (v - (prev.data[p]?.[name] ?? v)) / dt : null
        row[p] = formatCount(v) + (d ? `  (${d > 0 ? '+' : ''}${formatCount(d)}/s)` : '')
      }
      return { row, any }
    })
    .filter((r) => r.any || !hideZero.value)
    .map((r) => r.row)
})
const xColumns = computed(() => [
  { title: t('monitor.extra.counter'), key: 'name', width: 220, fixed: 'left' as const },
  ...xPorts.value.map((p) => ({ title: t('common.portN', { n: p }), key: p, align: 'right' as const, minWidth: 160 })),
])
</script>

<template>
  <NSpace vertical :size="10">
    <NAlert type="warning" :title="t('monitor.extra.warnTitle')">
      <ul class="warn">
        <li>{{ t('monitor.extra.warn1') }}</li>
        <li>{{ t('monitor.extra.warn2') }}</li>
        <li>{{ t('monitor.extra.warn3') }}</li>
      </ul>
    </NAlert>

    <div v-if="local" class="controls">
      <label class="opt">
        <NSwitch :value="local.cpu" @update:value="(v: boolean) => change({ cpu: v })" />
        <span>{{ t('monitor.extra.cpu') }}</span>
        <NText depth="3" class="cost">{{ t('monitor.extra.cpuCost') }}</NText>
      </label>
      <label class="opt">
        <NSwitch :value="local.xstats" @update:value="(v: boolean) => change({ xstats: v })" />
        <span>{{ t('monitor.extra.xstats') }}</span>
        <NText depth="3" class="cost">{{ t('monitor.extra.xstatsCost', { n: portCount }) }}</NText>
      </label>
      <label class="opt">
        <span>{{ t('monitor.extra.interval') }}</span>
        <NSelect
          :value="local.interval"
          :options="intervals"
          size="small"
          style="width: 120px"
          @update:value="(v: number) => change({ interval: v })"
        />
      </label>
    </div>
    <NText depth="3" class="cost">{{ on ? t('monitor.extra.sharedNote', { who: turnedOnBy ?? '?' }) : t('monitor.extra.offNote') }}</NText>

    <NAlert v-if="extra?.error" type="error" :show-icon="false">{{ t('monitor.extra.fetchError', { error: extra.error }) }}</NAlert>

    <template v-if="local?.cpu">
      <NText strong>{{ t('monitor.extra.cpuTitle') }}</NText>
      <NEmpty v-if="!cores.length" size="small" :description="t('monitor.extra.waiting')" />
      <div v-else class="cores">
        <div v-for="c in cores" :key="c.n" class="core">
          <span class="core-name">{{ t('monitor.extra.core', { n: c.n }) }}</span>
          <span class="core-ports">{{ c.ports.length ? t('monitor.extra.corePorts', { ports: c.ports.join(', ') }) : t('monitor.extra.coreIdle') }}</span>
          <span class="core-bar" :title="t('monitor.extra.last20')">
            <span
              v-for="(v, i) in [...c.history].reverse()"
              :key="i"
              class="cell"
              :style="{ height: `${Math.max(2, v)}%` }"
              :title="`${v} %`"
            />
          </span>
          <span class="core-now">{{ c.now }} %</span>
        </div>
      </div>
      <NText depth="3" class="cost">{{ t('monitor.extra.last20') }}</NText>
      <NText strong>{{ t('monitor.extra.mbufTitle') }}</NText>
      <NDataTable size="small" :columns="mbufColumns" :data="mbufRows" :row-key="(r: { key: string }) => r.key" :max-height="240" />
    </template>

    <template v-if="local?.xstats">
      <NSpace align="center" justify="space-between">
        <NText strong>{{ t('monitor.extra.xstatsTitle') }}</NText>
        <NText v-if="lastX" depth="3" class="cost">
          {{ t('monitor.extra.updated', { time: new Date(lastX.ts * 1000).toLocaleTimeString() }) }}
        </NText>
      </NSpace>
      <NSpace align="center">
        <NInput v-model:value="xFilter" size="small" clearable :placeholder="t('monitor.extra.xstatsFilter')" style="width: 220px" />
        <NCheckbox v-model:checked="hideZero">{{ t('monitor.extra.hideZero') }}</NCheckbox>
      </NSpace>
      <NEmpty v-if="!lastX" size="small" :description="t('monitor.extra.waiting')" />
      <NDataTable
        v-else
        size="small"
        :columns="xColumns"
        :data="xRows"
        :row-key="(r: Record<string, unknown>) => String(r.name)"
        :max-height="360"
        :scroll-x="220 + xPorts.length * 160"
        virtual-scroll
      />
    </template>
  </NSpace>
</template>

<style scoped>
.warn {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 24px;
  align-items: center;
}
.opt {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.cost {
  font-size: 12px;
}
.cores {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 6px 16px;
}
.core {
  display: grid;
  grid-template-columns: 52px 1fr 90px 44px;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.core-ports {
  color: rgba(128, 128, 128, 0.9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.core-bar {
  display: flex;
  align-items: flex-end;
  gap: 1px;
  height: 18px;
  background: rgba(128, 128, 128, 0.08);
  border-radius: 2px;
}
.cell {
  flex: 1;
  background: #2a78d6;
  border-radius: 1px 1px 0 0;
}
:global(html.dark .core-bar .cell) {
  background: #3987e5;
}
.core-now {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
