<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NCard, NEmpty, NInput, NModal, NPopconfirm, NSelect, NSpace, NText, useMessage } from 'naive-ui'
import type { PortProfile, PortSettings } from '../../api'
import { useHostsStore } from '../../stores/hosts'
import { useProfilesStore } from '../../stores/profiles'
import { settingsOf, summarize } from '../../utils/portcfg'
import ApplyProfileDialog from './ApplyProfileDialog.vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ hostId: string }>()

const hosts = useHostsStore()
const profiles = useProfilesStore()
const message = useMessage()
const { t } = useI18n()

watch(() => props.hostId, (id) => profiles.load(id).catch(() => undefined), { immediate: true })
const list = computed(() => profiles.docs[props.hostId]?.profiles ?? [])
const chosen = ref<string | null>(null)
const options = computed(() =>
  list.value.map((p) => ({ label: t('portprofiles.optionLabel', { name: p.name, ports: Object.keys(p.ports).join(', ') }), value: p.id! })),
)
const chosenProfile = computed(() => list.value.find((p) => p.id === chosen.value) ?? null)

const applyOpen = ref(false)

// Save: the ticked ports, or the focused one when nothing is ticked.
const sourcePorts = computed(() => {
  const all = hosts.ports[props.hostId] ?? []
  const ticked = hosts.checked[props.hostId] ?? []
  const ids = ticked.length ? ticked : hosts.focused[props.hostId] != null ? [hosts.focused[props.hostId]!] : []
  return all.filter((p) => ids.includes(p.id) && p.layer)
})
const saveOpen = ref(false)
const saveName = ref('')
async function save() {
  const ports: Record<string, PortSettings> = Object.fromEntries(sourcePorts.value.map((p) => [String(p.id), settingsOf(p.layer!)]))
  try {
    await profiles.add(props.hostId, saveName.value.trim(), ports)
    message.success(t('portprofiles.saved', { name: saveName.value.trim() }))
    saveOpen.value = false
    saveName.value = ''
  } catch (e) {
    message.error((e as Error).message)
  }
}

const manageOpen = ref(false)
const renaming = ref<Record<string, string>>({})
async function act(done: string, action: () => Promise<unknown>) {
  try {
    await action()
    message.success(done)
  } catch (e) {
    message.error((e as Error).message)
  }
}
const portsText = (p: PortProfile) =>
  Object.entries(p.ports)
    .map(([id, s]) => t('portprofiles.portSummary', { id, summary: summarize(s) }))
    .join(t('portprofiles.summarySep'))
</script>

<template>
  <div class="profiles">
    <NText strong>{{ t('portprofiles.title') }}</NText>
    <NText depth="3" style="font-size: 12px">
      {{ t('portprofiles.intro') }}
    </NText>
    <NSpace align="center">
      <NSelect
        v-model:value="chosen"
        :options="options"
        size="small"
        :placeholder="t('portprofiles.choose')"
        style="width: 340px; max-width: 100%"
        clearable
        @focus="profiles.load(hostId).catch(() => undefined)"
      />
      <NButton size="small" type="primary" :disabled="!chosenProfile" @click="applyOpen = true">{{ t('portprofiles.applyEllipsis') }}</NButton>
      <NButton size="small" :disabled="!sourcePorts.length" @click="saveOpen = true">
        {{ t('portprofiles.saveFrom', { ports: sourcePorts.map((p) => p.id).join(', ') || '—' }) }}
      </NButton>
      <NButton size="small" quaternary @click="manageOpen = true">{{ t('portprofiles.manage') }}</NButton>
    </NSpace>

    <ApplyProfileDialog v-model:show="applyOpen" :host-id="hostId" :profile="chosenProfile" />

    <NModal v-model:show="saveOpen">
      <NCard style="width: min(520px, 94vw)" :title="t('portprofiles.saveTitle')" size="small" :bordered="false">
        <NSpace vertical>
          <NInput v-model:value="saveName" :placeholder="t('portprofiles.namePlaceholder')" @keyup.enter="saveName.trim() && save()" />
          <div v-for="p in sourcePorts" :key="p.id" class="preview">
            <NText strong>Port {{ p.id }}</NText>
            <NText depth="2">{{ summarize(settingsOf(p.layer!)) }}</NText>
          </div>
          <NText depth="3" style="font-size: 12px">{{ t('portprofiles.saveHint') }}</NText>
        </NSpace>
        <template #footer>
          <NSpace justify="end">
            <NButton @click="saveOpen = false">{{ t('common.cancel') }}</NButton>
            <NButton type="primary" :disabled="!saveName.trim()" @click="save">{{ t('common.save') }}</NButton>
          </NSpace>
        </template>
      </NCard>
    </NModal>

    <NModal v-model:show="manageOpen">
      <NCard style="width: min(820px, 94vw)" :title="t('portprofiles.manageTitle')" size="small" :bordered="false">
        <NEmpty v-if="!list.length" :description="t('portprofiles.empty')" />
        <div v-for="p in list" :key="p.id" class="manage">
          <NInput :value="renaming[p.id!] ?? p.name" size="small" @update:value="(v: string) => (renaming[p.id!] = v)" />
          <NText depth="3" class="dim" :title="portsText(p)">{{ portsText(p) }}</NText>
          <NSpace :size="2" :wrap="false">
            <NButton
              size="tiny"
              :disabled="!renaming[p.id!]?.trim() || renaming[p.id!] === p.name"
              @click="act(t('portprofiles.renamed'), async () => { await profiles.rename(hostId, p.id!, renaming[p.id!].trim()); delete renaming[p.id!] })"
              >{{ t('common.rename') }}</NButton
            >
            <NPopconfirm @positive-click="act(t('portprofiles.deleted'), () => profiles.remove(hostId, p.id!))">
              <template #trigger><NButton size="tiny" type="error" quaternary>{{ t('common.delete') }}</NButton></template>
              {{ t('portprofiles.confirmDelete', { name: p.name }) }}
            </NPopconfirm>
          </NSpace>
        </div>
      </NCard>
    </NModal>
  </div>
</template>

<style scoped>
.profiles {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 6px;
  background: rgba(128, 128, 128, 0.06);
}
.preview {
  display: grid;
  grid-template-columns: 70px 1fr;
  font-size: 13px;
}
.manage {
  display: grid;
  grid-template-columns: minmax(110px, 200px) minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 4px 0;
}
.dim {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
