<script setup lang="ts">
// Saved runs of this host, newest first: View / Delete.
import { computed, h } from 'vue'
import { NButton, NDataTable, NPopconfirm, NSpace, NTag, type DataTableColumns } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { Rfc2544Summary } from '../../api'
import { dateTime, dirLabel, directions, testName, type Translate } from './util'

defineProps<{ items: Rfc2544Summary[]; loading: boolean; viewingId: string | null }>()
const emit = defineEmits<{ view: [id: string]; delete: [id: string] }>()
const { t: i18nT } = useI18n()
const t: Translate = (k, p) => (p ? i18nT(k, p) : i18nT(k))

const stateType = (s: string) => (s === 'done' ? 'success' : s === 'error' ? 'error' : s === 'stopped' ? 'warning' : 'info')

const columns = computed<DataTableColumns<Rfc2544Summary>>(() => [
  { title: t('rfc2544.history.time'), key: 'started', width: 170, render: (x) => dateTime(x.started) },
  {
    title: t('rfc2544.history.tests'),
    key: 'tests',
    minWidth: 150,
    render: (x) => (x.tests ?? []).map((v) => testName(t, v)).join(t('rfc2544.log.listSep')),
  },
  { title: t('rfc2544.history.sizes'), key: 'sizes', minWidth: 120, render: (x) => (x.frame_sizes ?? []).join(', ') },
  {
    title: t('rfc2544.history.ports'),
    key: 'pairs',
    width: 120,
    render: (x) => directions(x.pairs ?? [], !!x.bidirectional).map(([a, b]) => dirLabel(a, b)).join(', '),
  },
  {
    title: t('rfc2544.history.state'),
    key: 'state',
    width: 90,
    render: (x) => h(NTag, { size: 'small', bordered: false, type: stateType(x.state) }, () => t(`rfc2544.state.${x.state}`)),
  },
  { title: t('rfc2544.history.who'), key: 'client', width: 120, render: (x) => x.client ?? '' },
  {
    title: t('rfc2544.history.actions'),
    key: 'actions',
    width: 140,
    render: (x) =>
      h(NSpace, { size: 4, wrap: false }, () => [
        h(NButton, { size: 'tiny', secondary: true, type: 'primary', onClick: () => emit('view', x.id) }, () => t('rfc2544.history.view')),
        h(
          NPopconfirm,
          { onPositiveClick: () => emit('delete', x.id) },
          {
            trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, () => t('common.delete')),
            default: () => t('rfc2544.history.confirmDelete'),
          },
        ),
      ]),
  },
])
</script>

<template>
  <NDataTable
    size="small"
    :columns="columns"
    :data="items"
    :loading="loading"
    :row-key="(x: Rfc2544Summary) => x.id"
    :row-class-name="(x: Rfc2544Summary) => (x.id === viewingId ? 'viewing' : '')"
    :scroll-x="900"
    :max-height="360"
  >
    <template #empty>{{ t('rfc2544.history.empty') }}</template>
  </NDataTable>
</template>

<style scoped>
:deep(.viewing td) {
  background: rgba(24, 160, 88, 0.1) !important;
}
</style>
