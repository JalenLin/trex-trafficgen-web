<script setup lang="ts">
import { ref, watch } from 'vue'
import { NButton, NCard, NInput, NModal, NRadio, NRadioGroup, NSpace, NText, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { StreamSpec } from '../../api'
import { useTemplatesStore, type TemplateScope } from '../../stores/templates'
import { persisted } from '../../utils/prefs'

const props = defineProps<{ show: boolean; stream: StreamSpec | null }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const { t } = useI18n()
const templates = useTemplatesStore()
const message = useMessage()
const name = ref('')
// Remembered per browser: where this user usually saves.
const scope = persisted<TemplateScope>('templates.scope', 'personal')
const saving = ref(false)

watch(
  () => props.show,
  (open) => open && (name.value = props.stream?.name ?? ''),
)

async function save() {
  if (!props.stream || !name.value.trim()) return
  saving.value = true
  try {
    await templates.add(scope.value, name.value.trim(), props.stream)
    message.success(t(scope.value === 'personal' ? 'streams.templates.savedPersonal' : 'streams.templates.savedShared', { name: name.value.trim() }))
    emit('update:show', false)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <NModal :show="show" @update:show="(v: boolean) => emit('update:show', v)">
    <NCard style="width: min(460px, 94vw)" :title="t('streams.templates.saveTitle')" size="small" :bordered="false">
      <NSpace vertical>
        <NInput v-model:value="name" :placeholder="t('streams.templates.namePlaceholder')" @keyup.enter="save" />
        <NRadioGroup v-model:value="scope">
          <NSpace vertical :size="4">
            <NRadio value="personal">
              {{ t('streams.personalTemplates') }} <NText depth="3" style="font-size: 12px">{{ t('streams.templates.personalHint') }}</NText>
            </NRadio>
            <NRadio value="shared">
              {{ t('streams.sharedTemplates') }} <NText depth="3" style="font-size: 12px">{{ t('streams.templates.sharedHint') }}</NText>
            </NRadio>
          </NSpace>
        </NRadioGroup>
      </NSpace>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="emit('update:show', false)">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :disabled="!name.trim()" :loading="saving" @click="save">{{ t('common.save') }}</NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>
