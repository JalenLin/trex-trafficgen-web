<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NModal, NSpace, NTag, NText, useMessage } from 'naive-ui'
import type { PortProfile } from '../../api'
import { useHostsStore } from '../../stores/hosts'
import { useProfilesStore } from '../../stores/profiles'
import { describeConfig, diffConfig } from '../../utils/portcfg'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ show: boolean; hostId: string; profile: Pick<PortProfile, 'id' | 'name' | 'ports'> | null }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const hosts = useHostsStore()
const profiles = useProfilesStore()
const message = useMessage()
const { t } = useI18n()
const busy = ref(false)
const warnings = ref<string[]>([])

type Status = 'missing' | 'same' | 'not-mine' | 'busy' | 'ready'
const rows = computed(() =>
  Object.entries(props.profile?.ports ?? {}).map(([pid, want]) => {
    const port = (hosts.ports[props.hostId] ?? []).find((p) => String(p.id) === pid)
    if (!port?.layer) return { pid, status: 'missing' as Status, lines: [], cfg: {} }
    const cfg = diffConfig(port.layer, want)
    const lines = describeConfig(port.layer, cfg)
    const status: Status = !lines.length ? 'same' : !port.acquired ? 'not-mine' : port.status !== 'IDLE' ? 'busy' : 'ready'
    return { pid, status, lines, cfg, owner: port.owner }
  }),
)
const ready = computed(() => rows.value.filter((r) => r.status === 'ready'))
// Ports nobody holds can be taken here; ports owned by others need a deliberate force-acquire.
const freeToTake = computed(() => rows.value.filter((r) => r.status === 'not-mine' && !r.owner).map((r) => Number(r.pid)))

const STATUS_TYPE: Record<Status, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  missing: 'error',
  same: 'success',
  'not-mine': 'warning',
  busy: 'warning',
  ready: 'info',
}
const statusText = (r: { status: Status; owner?: string | null }) =>
  r.status === 'not-mine'
    ? r.owner
      ? t('portprofiles.status.notMineOwned', { owner: r.owner })
      : t('portprofiles.status.notMine')
    : t(`portprofiles.status.${r.status}`)

async function acquire() {
  busy.value = true
  try {
    await hosts.acquire(props.hostId, freeToTake.value)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

async function apply() {
  if (!props.profile) return
  busy.value = true
  warnings.value = []
  const failed: string[] = []
  // Snapshot: `ready` is a diff against the ports, and empties as they get applied.
  const targets = ready.value
  try {
    for (const r of targets) {
      try {
        warnings.value.push(...(await hosts.configurePort(props.hostId, Number(r.pid), r.cfg)))
      } catch (e) {
        failed.push(t('ports.portFailed', { id: r.pid, error: (e as Error).message }))
      }
    }
    const host = hosts.hosts.find((h) => h.id === props.hostId)
    await profiles.recordApplied(props.hostId, props.profile, host?.server_started ?? null)
    if (failed.length) message.error(t('ports.partialFailed', { list: failed.join(t('ports.failedSep')) }), { duration: 8000 })
    else
      message.success(
        t(targets.length ? 'portprofiles.applied' : 'portprofiles.recorded', { name: props.profile.name }),
      )
    if (!failed.length && !warnings.value.length) emit('update:show', false)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <NModal :show="show" @update:show="(v: boolean) => emit('update:show', v)">
    <NCard v-if="profile" style="width: min(720px, 94vw)" :title="t('portprofiles.dialogTitle', { name: profile.name })" size="small" :bordered="false">
      <NSpace vertical>
        <div v-for="r in rows" :key="r.pid" class="row">
          <NText strong>Port {{ r.pid }}</NText>
          <NTag size="small" :bordered="false" :type="STATUS_TYPE[r.status]">
            {{ statusText(r) }}
          </NTag>
          <div class="lines">
            <div v-for="l in r.lines" :key="l">{{ l }}</div>
          </div>
        </div>
        <NAlert v-for="w in warnings" :key="w" type="warning" :show-icon="false">{{ w }}</NAlert>
        <NText v-if="rows.some((r) => r.status === 'busy')" depth="3" style="font-size: 12px">
          {{ t('portprofiles.busyHint') }}
        </NText>
      </NSpace>
      <template #footer>
        <NSpace justify="end">
          <NButton v-if="freeToTake.length" :loading="busy" @click="acquire">{{ t('portprofiles.acquireFirst', { ports: freeToTake.join(', ') }) }}</NButton>
          <NButton @click="emit('update:show', false)">{{ t('common.cancel') }}</NButton>
          <!-- All-same still records the profile as applied, so later drift is noticed. -->
          <NButton
            type="primary"
            :disabled="!ready.length && !rows.some((r) => r.status === 'same')"
            :loading="busy"
            @click="apply"
          >
            {{
              ready.length
                ? t('portprofiles.applyToN', { n: ready.length }, ready.length)
                : rows.some((r) => r.status === 'same')
                  ? t('portprofiles.allSame')
                  : t('portprofiles.nothingToApply')
            }}
          </NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>

<style scoped>
.row {
  display: grid;
  grid-template-columns: 70px auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  font-size: 13px;
}
.lines {
  font-size: 12px;
}
</style>
