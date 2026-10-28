<script setup lang="ts">
// Export / import a whole host session: every port's streams and L2/L3 settings,
// plus the host's saved port profiles, as one JSON file.
import { computed, h, ref, watch } from 'vue'
import {
  NAlert, NButton, NCard, NCheckbox, NDataTable, NModal, NSelect, NSpace, NText, useMessage, type DataTableColumns,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { HostSummary, PortProfile, PortSettings, StreamSpec } from '../api'
import { useHostsStore } from '../stores/hosts'
import { useProfilesStore } from '../stores/profiles'
import { useStreamsStore } from '../stores/streams'
import { describeConfig, diffConfig, settingsOf, summarize } from '../utils/portcfg'

const FORMAT = 'trex-gui-session'

interface SessionPort {
  id: number
  mac: string
  speed_gbps: number
  settings: PortSettings
  streams: StreamSpec[]
}
interface SessionFile {
  format: typeof FORMAT
  version: 1
  exported_at: string
  host: { id: string; name: string; server: string; version: string }
  ports: SessionPort[]
  port_profiles: PortProfile[]
}

const props = defineProps<{ host: HostSummary }>()
const { t } = useI18n()
const hosts = useHostsStore()
const streams = useStreamsStore()
const profiles = useProfilesStore()
const message = useMessage()

const ports = computed(() => hosts.ports[props.host.id] ?? [])

// --- export ---
const exporting = ref(false)
async function exportSession() {
  exporting.value = true
  try {
    const out: SessionFile = {
      format: FORMAT,
      version: 1,
      exported_at: new Date().toISOString(),
      host: { id: props.host.id, name: props.host.name, server: props.host.server, version: props.host.server_version?.version ?? '' },
      ports: [],
      port_profiles: (await profiles.load(props.host.id)).profiles,
    }
    for (const p of ports.value) {
      out.ports.push({
        id: p.id,
        mac: p.layer?.src_mac ?? '',
        speed_gbps: p.speed_gbps,
        settings: p.layer ? settingsOf(p.layer) : ({ mode: 'L2', vlan: [] } as unknown as PortSettings),
        streams: (await streams.ensure(props.host.id, p.id)).map(({ lint: _lint, ...s }) => s as StreamSpec),
      })
    }
    const stamp = out.exported_at.slice(0, 16).replace(/[-:T]/g, '')
    const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `trex-gui-session-${props.host.id}-${stamp}.json`
    a.click()
    URL.revokeObjectURL(a.href)
    message.success(t('session.exported', { n: out.ports.length }))
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    exporting.value = false
  }
}

// --- import ---
const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<SessionFile | null>(null)
const open = ref(false)
const targets = ref<Record<number, number | null>>({})
const doStreams = ref(true)
const doSettings = ref(true)
const doProfiles = ref(true)
const applying = ref(false)
const report = ref<{ port: string; lines: string[]; error?: boolean }[]>([])

function parse(text: string): SessionFile {
  const data = JSON.parse(text)
  if (data?.format !== FORMAT || !Array.isArray(data.ports)) throw new Error(t('session.notSession'))
  return data as SessionFile
}
async function onFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  try {
    file.value = parse(await f.text())
  } catch (e) {
    message.error(e instanceof SyntaxError ? t('session.notJson') : (e as Error).message)
    return
  }
  // Same port number when this host has it; otherwise left unmapped.
  targets.value = Object.fromEntries(file.value.ports.map((p) => [p.id, ports.value.some((q) => q.id === p.id) ? p.id : null]))
  doSettings.value = true
  report.value = []
  open.value = true
}

const targetOptions = computed(() => [
  { label: t('session.skip'), value: -1 },
  ...ports.value.map((p) => ({ label: t('common.portN', { n: p.id }) + (p.acquired ? '' : ` (${t('session.notMine')})`), value: p.id })),
])
const mapped = computed(() =>
  (file.value?.ports ?? []).filter((p) => targets.value[p.id] != null && targets.value[p.id]! >= 0),
)
const dupTargets = computed(() => {
  const seen = mapped.value.map((p) => targets.value[p.id])
  return seen.some((v, i) => seen.indexOf(v) !== i)
})
// Another port's addresses rarely belong on a different port: once a port is mapped
// elsewhere, untick "apply port settings" (the user can tick it again).
watch(
  () => mapped.value.some((p) => targets.value[p.id] !== p.id),
  (moved) => moved && (doSettings.value = false),
)
const notMine = computed(() =>
  doSettings.value ? mapped.value.filter((p) => !ports.value.find((q) => q.id === targets.value[p.id])?.acquired).map((p) => targets.value[p.id]) : [],
)

const columns = computed<DataTableColumns<SessionPort>>(() => [
  { title: t('session.fromPort'), key: 'id', width: 90, render: (p) => t('common.portN', { n: p.id }) },
  {
    title: t('session.toPort'),
    key: 'to',
    width: 170,
    render: (p) =>
      h(NSelect, {
        size: 'small',
        value: targets.value[p.id] ?? -1,
        options: targetOptions.value,
        'onUpdate:value': (v: number) => (targets.value[p.id] = v),
      }),
  },
  { title: t('session.streams'), key: 'streams', width: 90, render: (p) => String(p.streams.length) },
  { title: t('session.settings'), key: 'settings', minWidth: 220, render: (p) => summarize(p.settings) },
])

async function apply() {
  if (!file.value) return
  applying.value = true
  report.value = []
  const id = props.host.id
  try {
    for (const p of mapped.value) {
      const to = targets.value[p.id]!
      const lines: string[] = []
      let error = false
      try {
        if (doStreams.value) {
          await streams.save(id, to, p.streams)
          lines.push(t('session.streamsReplaced', { n: p.streams.length }))
        }
        if (doSettings.value) {
          const cur = ports.value.find((q) => q.id === to)
          if (!cur?.acquired || !cur.layer) {
            lines.push(t('session.settingsSkipped'))
          } else {
            const cfg = diffConfig(cur.layer, p.settings)
            if (!Object.keys(cfg).length) {
              lines.push(t('session.settingsSame'))
            } else {
              const before = describeConfig(cur.layer, cfg)
              const warnings = await hosts.configurePort(id, to, cfg)
              lines.push(...before, ...warnings)
              await profiles.forgetPorts(id, [to]).catch(() => undefined)
            }
          }
        }
      } catch (e) {
        lines.push((e as Error).message)
        error = true
      }
      report.value.push({ port: t('session.mapLine', { from: p.id, to }), lines, error })
    }
    if (doProfiles.value && file.value.port_profiles?.length) {
      const have = new Set((await profiles.load(id)).profiles.map((p) => p.name))
      const fresh = file.value.port_profiles.filter((p) => !have.has(p.name))
      for (const p of fresh) await profiles.add(id, p.name, p.ports)
      report.value.push({
        port: t('session.profiles'),
        lines: [t('session.profilesAdded', { n: fresh.length, skipped: file.value.port_profiles.length - fresh.length })],
      })
    }
    message.success(t('session.imported'))
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <NSpace :size="6">
    <NButton size="small" :loading="exporting" :disabled="!ports.length" @click="exportSession">{{ t('session.export') }}</NButton>
    <NButton size="small" :disabled="!ports.length" @click="fileInput?.click()">{{ t('session.import') }}</NButton>
    <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="onFile" />
  </NSpace>

  <NModal v-model:show="open">
    <NCard style="width: min(760px, 96vw)" :title="t('session.importTitle')" size="small" :bordered="false" closable @close="open = false">
      <NSpace v-if="file" vertical :size="10">
        <NText depth="3" style="font-size: 12px">
          {{ t('session.fileInfo', { host: file.host.name, server: file.host.server, at: new Date(file.exported_at).toLocaleString(), n: file.ports.length }) }}
        </NText>
        <NDataTable size="small" :columns="columns" :data="file.ports" :row-key="(p: SessionPort) => p.id" :max-height="300" :scroll-x="580" />
        <NSpace vertical :size="4">
          <NCheckbox v-model:checked="doStreams">{{ t('session.optStreams') }}</NCheckbox>
          <NCheckbox v-model:checked="doSettings">{{ t('session.optSettings') }}</NCheckbox>
          <NCheckbox v-model:checked="doProfiles" :disabled="!file.port_profiles?.length">
            {{ t('session.optProfiles', { n: file.port_profiles?.length ?? 0 }) }}
          </NCheckbox>
        </NSpace>
        <NAlert v-if="dupTargets" type="error" :show-icon="false">{{ t('session.dupTargets') }}</NAlert>
        <NAlert v-if="notMine.length" type="warning" :show-icon="false">{{ t('session.notMineNote', { ports: notMine.join(', ') }) }}</NAlert>
        <NAlert v-if="report.length" type="info" :title="t('session.result')">
          <div v-for="(r, i) in report" :key="i" class="rep">
            <b>{{ r.port }}</b>
            <div v-for="(l, j) in r.lines" :key="j" :class="{ bad: r.error }">· {{ l }}</div>
          </div>
        </NAlert>
        <NSpace justify="end">
          <NButton @click="open = false">{{ t('common.close') }}</NButton>
          <NButton
            type="primary"
            :loading="applying"
            :disabled="!mapped.length || dupTargets || (!doStreams && !doSettings && !doProfiles)"
            @click="apply"
          >
            {{ t('session.apply', { n: mapped.length }) }}
          </NButton>
        </NSpace>
      </NSpace>
    </NCard>
  </NModal>
</template>

<style scoped>
.rep {
  margin-bottom: 6px;
  font-size: 13px;
}
.bad {
  color: #d03050;
}
</style>
