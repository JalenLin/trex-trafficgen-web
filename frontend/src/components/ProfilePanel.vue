<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NAlert, NButton, NEmpty, NForm, NFormItem, NInput, NInputNumber, NPopconfirm, NSelect, NSpace, NSpin, NSwitch, NTag, NText,
  useMessage,
} from 'naive-ui'
import { api, type ProfileFile, type ProfileInfo, type ProfileRun } from '../api'
import { useI18n } from 'vue-i18n'
import { NARROW, viewportWidth } from '../composables/useViewport'
import { useHostsStore } from '../stores/hosts'
import { persisted } from '../utils/prefs'

const props = defineProps<{ hostId: string }>()

const hosts = useHostsStore()
const message = useMessage()
const { t } = useI18n()

const sourceLabel = (f: ProfileFile) => t(f.source === 'shared' ? 'pyprofile.sourceShared' : 'pyprofile.sourceTrex', { folder: f.folder })

const files = ref<ProfileFile[]>([])
const uploadAllowed = ref(false)
const runs = ref<Record<string, ProfileRun>>({})
const filter = ref('')
const loadingList = ref(false)

async function refresh() {
  loadingList.value = true
  try {
    const r = await api.profiles(props.hostId)
    files.value = r.profiles
    uploadAllowed.value = r.upload_allowed
    runs.value = await api.profileRuns(props.hostId)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loadingList.value = false
  }
}
watch(() => props.hostId, refresh, { immediate: true })

const shown = computed(() => {
  const q = filter.value.trim().toLowerCase()
  return q ? files.value.filter((f) => f.name.toLowerCase().includes(q)) : files.value
})

// --- chosen profile and its parameters ---
const chosenId = persisted<string | null>(`profile.chosen`, null)
const chosen = computed(() => files.value.find((f) => f.id === chosenId.value) ?? null)
const info = ref<ProfileInfo | null>(null)
const infoError = ref<string | null>(null)
const loadingInfo = ref(false)
// Remembered per browser and profile: the parameter values last used.
const allValues = persisted<Record<string, Record<string, unknown>>>('profile.values', {})
watch(chosenId, (id) => id && !allValues.value[id] && (allValues.value[id] = {}), { immediate: true })
const values = computed(() => (chosenId.value ? allValues.value[chosenId.value] ?? {} : {}))

watch(
  chosenId,
  async (id) => {
    info.value = null
    infoError.value = null
    if (!id) return
    loadingInfo.value = true
    try {
      info.value = await api.profileInfo(props.hostId, id)
    } catch (e) {
      infoError.value = (e as Error).message
    } finally {
      loadingInfo.value = false
    }
  },
  { immediate: true },
)

// --- run ---
const mult = persisted('profile.mult', '1')
const duration = persisted<number | null>('profile.duration', null)
const targets = computed(() => {
  const ports = hosts.ports[props.hostId] ?? []
  const ticked = hosts.checked[props.hostId] ?? []
  const ids = ticked.length ? ticked : hosts.focused[props.hostId] != null ? [hosts.focused[props.hostId]!] : []
  return ports.filter((p) => ids.includes(p.id) && p.acquired)
})
const running = computed(() => targets.value.filter((p) => p.status !== 'IDLE').map((p) => p.id))
const busy = ref(false)

async function start(force = false) {
  if (!chosen.value) return
  busy.value = true
  try {
    const r = await api.startProfile(props.hostId, {
      id: chosen.value.id,
      ports: targets.value.map((p) => p.id),
      values: values.value,
      mult: mult.value.trim() || '1',
      duration: duration.value && duration.value > 0 ? duration.value : -1,
      force,
    })
    hosts.ports[props.hostId] = r.ports
    const counts = Object.entries(r.streams)
      .map(([p, n]) => t('pyprofile.portStreams', { port: p, n }, n))
      .join(t('pyprofile.listSep'))
    message.success(t('pyprofile.started', { name: chosen.value.name, counts }))
    runs.value = await api.profileRuns(props.hostId)
  } catch (e) {
    message.error((e as Error).message, { duration: 10000 })
  } finally {
    busy.value = false
  }
}

const runsText = computed(() =>
  Object.entries(runs.value).map(([p, r]) =>
    r.streams != null
      ? t('pyprofile.runEntryStreams', { port: p, name: r.id.split(':')[1], n: r.streams }, r.streams)
      : t('pyprofile.runEntry', { port: p, name: r.id.split(':')[1] }),
  ),
)

// --- upload (only when the server allows it) ---
const fileInput = ref<HTMLInputElement | null>(null)
async function onFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    await api.uploadProfile(file)
    message.success(t('pyprofile.uploaded', { name: file.name }))
    await refresh()
  } catch (e) {
    message.error((e as Error).message)
  }
}
async function remove(f: ProfileFile) {
  try {
    await api.deleteProfile(f.name)
    if (chosenId.value === f.id) chosenId.value = null
    await refresh()
  } catch (e) {
    message.error((e as Error).message)
  }
}
</script>

<template>
  <div class="profiles">
    <div class="list">
      <NSpace align="center" justify="space-between" style="margin-bottom: 6px">
        <NText strong>{{ t('pyprofile.title') }}</NText>
        <NButton size="tiny" quaternary :loading="loadingList" @click="refresh">{{ t('common.refresh') }}</NButton>
      </NSpace>
      <NInput v-model:value="filter" size="small" :placeholder="t('pyprofile.searchPlaceholder')" clearable style="margin-bottom: 6px" />
      <div class="items">
        <div
          v-for="f in shown"
          :key="f.id"
          class="item"
          :class="{ active: f.id === chosenId }"
          :title="`${sourceLabel(f)}\n${f.modified} · ${f.size} bytes`"
          @click="chosenId = f.id"
        >
          <span class="fname">{{ f.name }}</span>
          <NTag size="tiny" :bordered="false" :type="f.source === 'shared' ? 'info' : 'default'">
            {{ f.source === 'shared' ? t('common.shared') : t('pyprofile.tagTrex') }}
          </NTag>
        </div>
        <NEmpty v-if="!shown.length" size="small" :description="t('pyprofile.empty')" />
      </div>
      <NText depth="3" class="note">
        {{ t('pyprofile.listNote') }}
      </NText>
      <template v-if="uploadAllowed">
        <NButton size="small" style="margin-top: 6px" @click="fileInput?.click()">{{ t('pyprofile.uploadButton') }}</NButton>
        <input ref="fileInput" type="file" accept=".py" hidden @change="onFile" />
      </template>
    </div>

    <div class="detail">
      <NEmpty v-if="!chosen" :description="t('pyprofile.pickOne')" />
      <template v-else>
        <NSpace align="center" justify="space-between">
          <NSpace align="center">
            <NText strong style="font-size: 16px">{{ chosen.name }}</NText>
            <NText depth="3" style="font-size: 12px">{{ sourceLabel(chosen) }}</NText>
          </NSpace>
          <NPopconfirm v-if="chosen.source === 'shared' && uploadAllowed" @positive-click="remove(chosen)">
            <template #trigger><NButton size="tiny" quaternary type="error">{{ t('common.delete') }}</NButton></template>
            {{ t('pyprofile.confirmDelete', { name: chosen.name }) }}
          </NPopconfirm>
        </NSpace>

        <NSpin :show="loadingInfo">
          <NAlert v-if="infoError" type="error" :title="t('pyprofile.loadError')" class="block">
            <pre class="err">{{ infoError }}</pre>
          </NAlert>
          <template v-else-if="info">
            <pre v-if="info.doc" class="doc">{{ info.doc }}</pre>
            <NText strong class="block">{{ t('pyprofile.params') }}</NText>
            <NText v-if="!info.options.length" depth="3" class="block">{{ t('pyprofile.noParams') }}</NText>
            <NForm v-else :label-placement="viewportWidth < NARROW ? 'top' : 'left'" label-width="120" size="small">
              <NFormItem v-for="o in info.options" :key="o.name" :label="o.flag">
                <NSpace vertical :size="2" style="width: 100%">
                  <NSwitch
                    v-if="o.kind === 'bool'"
                    :value="(values[o.name] ?? o.default) === true"
                    @update:value="(v: boolean) => (values[o.name] = v)"
                  />
                  <NSelect
                    v-else-if="o.kind === 'choice'"
                    :value="(values[o.name] as string | undefined) ?? (o.default == null ? null : String(o.default))"
                    :options="(o.choices ?? []).map((c) => ({ label: c, value: c }))"
                    clearable
                    :placeholder="t('common.default')"
                    style="max-width: 260px"
                    @update:value="(v: string | null) => (values[o.name] = v ?? '')"
                  />
                  <NInput
                    v-else
                    :value="(values[o.name] as string | undefined) ?? ''"
                    :placeholder="o.default == null ? t('common.default') : t('common.defaultValue', { value: o.default })"
                    clearable
                    style="max-width: 260px"
                    @update:value="(v: string) => (values[o.name] = v)"
                  />
                  <NText v-if="o.help" depth="3" style="font-size: 12px">{{ o.help }}</NText>
                </NSpace>
              </NFormItem>
            </NForm>

            <NText strong class="block">{{ t('pyprofile.traffic') }}</NText>
            <NForm :label-placement="viewportWidth < NARROW ? 'top' : 'left'" label-width="120" size="small">
              <NFormItem :label="t('common.port')">
                <NText v-if="targets.length">{{ t('pyprofile.targetPorts', { ports: targets.map((p) => p.id).join(', ') }) }}</NText>
                <NText v-else type="warning">{{ t('pyprofile.pickPortsFirst') }}</NText>
              </NFormItem>
              <NFormItem :label="t('pyprofile.mult')">
                <NInput v-model:value="mult" :placeholder="t('pyprofile.multPlaceholder')" style="max-width: 200px" />
              </NFormItem>
              <NFormItem :label="t('pyprofile.duration')">
                <NInputNumber v-model:value="duration" :min="0" clearable :placeholder="t('pyprofile.durationPlaceholder')" style="max-width: 200px">
                  <template #suffix>{{ t('common.seconds') }}</template>
                </NInputNumber>
              </NFormItem>
              <NFormItem label=" ">
                <NPopconfirm v-if="running.length" @positive-click="start(true)">
                  <template #trigger>
                    <NButton type="primary" :disabled="!targets.length" :loading="busy">{{ t('pyprofile.start') }}</NButton>
                  </template>
                  {{ t('pyprofile.confirmForce', { ports: running.join(', ') }) }}
                </NPopconfirm>
                <NButton v-else type="primary" :disabled="!targets.length" :loading="busy" @click="start()">{{ t('pyprofile.start') }}</NButton>
              </NFormItem>
            </NForm>
            <NText depth="3" style="font-size: 12px">
              {{ t('pyprofile.trafficNote') }}
            </NText>
          </template>
        </NSpin>
      </template>

      <NAlert v-if="runsText.length" type="info" :show-icon="false" class="block">
        {{ t('pyprofile.running', { list: runsText.join(t('pyprofile.runSep')) }) }}
      </NAlert>
    </div>
  </div>
</template>

<style scoped>
.profiles {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
}
@media (max-width: 860px) {
  .profiles {
    grid-template-columns: minmax(0, 1fr);
  }
}
.items {
  max-height: 50vh;
  overflow: auto;
  border: 1px solid rgba(128, 128, 128, 0.2);
  border-radius: 4px;
}
.item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 13px;
}
.item:hover {
  background: rgba(128, 128, 128, 0.08);
}
.item.active {
  background: rgba(24, 160, 88, 0.14);
}
.fname {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.note {
  display: block;
  font-size: 12px;
  margin-top: 6px;
}
.block {
  display: block;
  margin: 12px 0 6px;
}
.doc,
.err {
  white-space: pre-wrap;
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
  background: rgba(128, 128, 128, 0.06);
  padding: 8px;
  border-radius: 4px;
  margin: 8px 0 0;
}
</style>
