<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NCard, NEmpty, NInput, NModal, NPopconfirm, NSpace, NTabPane, NTabs, NText, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { StreamTemplate } from '../../api'
import { useTemplatesStore, type TemplateScope } from '../../stores/templates'
import { layersSummary } from '../../utils/streams'

defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const { t } = useI18n()
const templates = useTemplatesStore()
const message = useMessage()
const renaming = ref<Record<string, string>>({})
const fileInput = ref<HTMLInputElement | null>(null)

async function act(done: string, action: () => Promise<unknown>) {
  try {
    await action()
    if (done) message.success(done)
  } catch (e) {
    message.error((e as Error).message)
  }
}

const key = (scope: TemplateScope, tpl: StreamTemplate) => `${scope}:${tpl.id}`

function exportFile() {
  const url = URL.createObjectURL(templates.exportPersonal())
  const a = document.createElement('a')
  a.href = url
  a.download = `trex-gui-templates-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

async function importFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  await act('', async () => {
    const n = await templates.importPersonal(file)
    message.success(t('streams.templates.imported', { n }))
  })
  ;(ev.target as HTMLInputElement).value = ''
}
</script>

<template>
  <NModal :show="show" @update:show="(v: boolean) => emit('update:show', v)">
    <NCard style="width: min(820px, 94vw)" :title="t('streams.templates.managerTitle')" size="small" :bordered="false">
      <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="importFile" />
      <NTabs type="line" size="small" @update:value="(v: string) => v === 'shared' && templates.loadShared()">
        <template v-for="scope in (['personal', 'shared'] as TemplateScope[])" :key="scope">
          <NTabPane
            :name="scope"
            :tab="t('streams.templates.tab', { scope: t(scope === 'personal' ? 'common.personal' : 'common.shared'), n: (scope === 'personal' ? templates.personal : templates.shared).length })"
          >
            <NSpace v-if="scope === 'personal'" align="center" justify="space-between" style="margin-bottom: 8px">
              <NText depth="3" style="font-size: 12px">{{ t('streams.templates.personalNote') }}</NText>
              <NSpace :size="6">
                <NButton size="small" :disabled="!templates.personal.length" @click="exportFile">{{ t('streams.templates.exportFile') }}</NButton>
                <NButton size="small" @click="fileInput?.click()">{{ t('streams.templates.importFile') }}</NButton>
              </NSpace>
            </NSpace>
            <NText v-else depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
              {{ t('streams.templates.sharedNote') }}
            </NText>

            <NEmpty
              v-if="!(scope === 'personal' ? templates.personal : templates.shared).length"
              :description="t('streams.templates.empty')"
            />
            <div v-for="tpl in scope === 'personal' ? templates.personal : templates.shared" :key="tpl.id" class="tpl">
              <NInput
                :value="renaming[key(scope, tpl)] ?? tpl.name"
                size="small"
                @update:value="(v: string) => (renaming[key(scope, tpl)] = v)"
              />
              <NText depth="3" class="dim">{{ layersSummary(tpl.stream) }}</NText>
              <NText depth="3" class="dim">{{ new Date(tpl.saved_at).toLocaleDateString() }}</NText>
              <NSpace :size="2" :wrap="false">
                <NButton
                  size="tiny"
                  :disabled="!renaming[key(scope, tpl)]?.trim() || renaming[key(scope, tpl)] === tpl.name"
                  @click="act(t('streams.templates.renamed'), async () => { await templates.rename(scope, tpl.id!, renaming[key(scope, tpl)].trim()); delete renaming[key(scope, tpl)] })"
                  >{{ t('common.rename') }}</NButton
                >
                <NButton
                  v-if="scope === 'personal'"
                  size="tiny"
                  quaternary
                  @click="act(t('streams.templates.sharedDone', { name: tpl.name }), () => templates.copyTo('shared', tpl))"
                  >{{ t('streams.templates.shareToShared') }}</NButton
                >
                <NButton
                  v-else
                  size="tiny"
                  quaternary
                  @click="act(t('streams.templates.copiedToPersonal', { name: tpl.name }), () => templates.copyTo('personal', tpl))"
                  >{{ t('streams.templates.copyToPersonal') }}</NButton
                >
                <NPopconfirm @positive-click="act(t('streams.templates.deleted'), () => templates.remove(scope, tpl.id!))">
                  <template #trigger><NButton size="tiny" type="error" quaternary>{{ t('common.delete') }}</NButton></template>
                  {{ t(scope === 'shared' ? 'streams.templates.confirmDeleteShared' : 'streams.templates.confirmDelete', { name: tpl.name }) }}
                </NPopconfirm>
              </NSpace>
            </div>
          </NTabPane>
        </template>
      </NTabs>
    </NCard>
  </NModal>
</template>

<style scoped>
.tpl {
  display: grid;
  grid-template-columns: minmax(110px, 200px) minmax(0, 1fr) 80px auto;
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
