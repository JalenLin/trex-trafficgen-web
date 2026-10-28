<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NCheckbox, NInput, NSelect, NText, NTooltip } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { DescLayer, FieldSchema, FieldValue, ProtocolSchema } from '../../api'

const props = defineProps<{
  schema: ProtocolSchema
  modelValue: Record<string, FieldValue>
  /** This layer in the latest preview; its values show as placeholders. */
  built?: DescLayer
  /** Outermost Ethernet: TRex fills unset src/dst with the port's MACs. */
  portMacs?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [Record<string, FieldValue>]
  hover: [field: string | null]
}>()

const { t } = useI18n()

// --- jump here from the packet preview ---
const root = ref<HTMLElement | null>(null)
const flashing = ref<string | null>(null)
let flashTimer: ReturnType<typeof setTimeout> | undefined

/** Scroll to a field, flash it and put the cursor in its input. */
function focusField(name: string) {
  const row = root.value?.querySelector<HTMLElement>(`.row[data-field="${CSS.escape(name)}"]`)
  if (!row) return false
  row.scrollIntoView({ block: 'center', behavior: 'smooth' })
  row.querySelector<HTMLInputElement>('input')?.focus({ preventScroll: true })
  flashing.value = name
  clearTimeout(flashTimer)
  flashTimer = setTimeout(() => (flashing.value = null), 1600)
  return true
}
defineExpose({ focusField })

const builtRepr = computed(() => Object.fromEntries((props.built?.fields ?? []).map((f) => [f.name, f.repr])))

function set(name: string, value: FieldValue | null) {
  const next = { ...props.modelValue }
  if (value === null || value === '') delete next[name]
  else next[name] = value
  emit('update:modelValue', next)
}

const textOf = (v: FieldValue | undefined): string => {
  if (v === undefined) return ''
  if (typeof v === 'object') return 'hex' in v ? v.hex : v.py
  return String(v)
}
const isHex = (name: string) => {
  const v = props.modelValue[name]
  return typeof v === 'object' && v !== null && 'hex' in v
}

function onText(f: FieldSchema, text: string) {
  if (!text) return set(f.name, null)
  if (f.kind === 'packet' || f.kind === 'list') return set(f.name, { py: text })
  if (f.kind === 'bytes' && isHex(f.name)) return set(f.name, { hex: text })
  set(f.name, text)
}

function toggleHex(f: FieldSchema, on: boolean) {
  const text = textOf(props.modelValue[f.name])
  set(f.name, text ? (on ? { hex: text } : text) : on ? { hex: '' } : null)
}

const enumOptions = (f: FieldSchema) =>
  (f.enum ?? []).map((e) => ({ label: `${e.label} (${e.value})`, value: String(e.value) }))

function placeholder(f: FieldSchema): string {
  if (props.portMacs && (f.name === 'src' || f.name === 'dst')) return t('streams.fields.autoPortMac')
  const shown = builtRepr.value[f.name]
  if (shown !== undefined && shown !== '') return t('streams.fields.autoValue', { value: shown })
  return f.default ? t('common.defaultValue', { value: f.default }) : t('common.auto')
}

function hint(f: FieldSchema): string {
  const parts: string[] = [f.kind]
  if (f.bits) parts.push(`${f.bits} bits`)
  if (f.conditional) parts.push(t('streams.fields.conditional'))
  return parts.join(' · ')
}
</script>

<template>
  <div ref="root" class="fields">
    <div v-if="!schema.fields.length" class="empty"><NText depth="3">{{ t('streams.fields.noFields') }}</NText></div>
    <div
      v-for="f in schema.fields"
      :key="f.name"
      class="row"
      :class="{ flash: flashing === f.name }"
      :data-field="f.name"
      @mouseenter="emit('hover', f.name)"
      @mouseleave="emit('hover', null)"
    >
      <NTooltip placement="left">
        <template #trigger>
          <span class="name" :class="{ set: f.name in modelValue }">{{ f.name }}</span>
        </template>
        {{ f.type }} · {{ hint(f) }}
        <template v-if="f.flags"><br />{{ t('streams.fields.flagsHint', { flags: f.flags.join(' '), example: f.flags.slice(0, 2).join('') }) }}</template>
        <template v-if="f.kind === 'packet' || f.kind === 'list'"><br />{{ t('streams.fields.pyLiteral') }}</template>
      </NTooltip>

      <NSelect
        v-if="f.kind === 'enum'"
        :value="textOf(modelValue[f.name]) || null"
        :options="enumOptions(f)"
        :placeholder="placeholder(f)"
        size="small"
        filterable
        tag
        clearable
        @update:value="(v: string | null) => set(f.name, v)"
      />
      <NInput
        v-else
        :value="textOf(modelValue[f.name])"
        :placeholder="placeholder(f)"
        size="small"
        clearable
        @update:value="(v: string) => onText(f, v)"
      />

      <NCheckbox
        v-if="f.kind === 'bytes'"
        size="small"
        :checked="isHex(f.name)"
        @update:checked="(on: boolean) => toggleHex(f, on)"
        >hex</NCheckbox
      >
      <NButton v-else-if="f.name in modelValue" size="tiny" quaternary @click="set(f.name, null)">{{ t('common.reset') }}</NButton>
      <span v-else />
    </div>
  </div>
</template>

<style scoped>
.row {
  display: grid;
  grid-template-columns: minmax(80px, 130px) minmax(0, 1fr) 52px;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
}
.name {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.75;
}
.name.set {
  opacity: 1;
  font-weight: 600;
}
.empty {
  padding: 12px 0;
}
.row.flash {
  animation: flash 1.6s ease-out;
  border-radius: 4px;
}
@keyframes flash {
  0%,
  40% {
    background: rgba(240, 160, 32, 0.35);
  }
  100% {
    background: transparent;
  }
}
</style>
