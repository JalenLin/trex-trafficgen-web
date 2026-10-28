<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NSpace } from 'naive-ui'
import type { HostSummary } from '../../api'
import { useHostsStore } from '../../stores/hosts'
import { useProfilesStore } from '../../stores/profiles'
import { diffConfig } from '../../utils/portcfg'
import { loadPref, savePref } from '../../utils/prefs'
import ApplyProfileDialog from './ApplyProfileDialog.vue'
import { useI18n } from 'vue-i18n'

// Warns when ports no longer match the last applied profile: TRex restarted
// (back to trex_cfg.yaml) or someone changed them outside this GUI. Changes made
// in this GUI's port settings drop the port from the comparison instead.

const props = defineProps<{ host: HostSummary }>()

const hosts = useHostsStore()
const profiles = useProfilesStore()
const { t } = useI18n()

watch(
  () => [props.host.id, props.host.connected, props.host.server_started],
  () => props.host.connected && profiles.load(props.host.id).catch(() => undefined),
  { immediate: true },
)

const last = computed(() => profiles.docs[props.host.id]?.last_applied ?? null)
const drifted = computed(() => {
  const la = last.value
  if (!la) return []
  const ports = hosts.ports[props.host.id] ?? []
  return Object.entries(la.ports)
    .filter(([pid, want]) => {
      const layer = ports.find((p) => String(p.id) === pid)?.layer
      return layer && Object.keys(diffConfig(layer, want)).length > 0
    })
    .map(([pid]) => pid)
})
const restarted = computed(
  () => !!last.value?.server_started && !!props.host.server_started && last.value.server_started !== props.host.server_started,
)

// "Ignore" is per browser and per situation: a new restart or new drift shows again.
const situation = computed(() => `${last.value?.at}|${props.host.server_started}|${drifted.value.join(',')}`)
const dismissed = ref(loadPref<Record<string, string>>('driftDismissed', {}))
const visible = computed(() => drifted.value.length > 0 && dismissed.value[props.host.id] !== situation.value)
function ignore() {
  dismissed.value = { ...dismissed.value, [props.host.id]: situation.value }
  savePref('driftDismissed', dismissed.value)
}

const applyOpen = ref(false)
</script>

<template>
  <NAlert v-if="visible && last" type="warning" :title="restarted ? t('portprofiles.restartedTitle') : t('portprofiles.driftTitle')">
    <NSpace vertical :size="6">
      <span v-if="restarted">
        {{ t('portprofiles.restartedBody', { time: host.server_started, ports: drifted.join(', '), name: last.name }) }}
      </span>
      <span v-else>
        {{ t('portprofiles.driftBody', { ports: drifted.join(', '), name: last.name }) }}
      </span>
      <NSpace>
        <NButton size="small" type="primary" @click="applyOpen = true">{{ t('portprofiles.reapply', { name: last.name }) }}</NButton>
        <NButton size="small" @click="ignore">{{ t('portprofiles.ignore') }}</NButton>
      </NSpace>
    </NSpace>
    <ApplyProfileDialog v-model:show="applyOpen" :host-id="host.id" :profile="{ id: last.profile_id, name: last.name, ports: last.ports }" />
  </NAlert>
</template>
