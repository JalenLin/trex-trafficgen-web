<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NButton, NEmpty, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NSelect, NText, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { LANGS, setLang, type Lang } from '../i18n'
import { themePref, type ThemePref } from '../theme'
import { NARROW, viewportWidth } from '../composables/useViewport'
import { useHostsStore } from '../stores/hosts'
import { persisted } from '../utils/prefs'
import HostList from './HostList.vue'
import HostPanel from './HostPanel.vue'
import OverviewPanel from './overview/OverviewPanel.vue'

const store = useHostsStore()
const message = useMessage()
const { t, locale } = useI18n()
const themeOptions = computed(() =>
  (['system', 'light', 'dark'] as const).map((v) => ({ value: v, label: t(`layout.theme.${v}`) })),
)

// Remembered per browser once toggled; until then, collapsed when there is only
// one host (nothing to switch between) and open when there are several.
const collapsedPref = persisted<boolean | null>('sider.collapsed', null)
// Narrow screens need the room: closed by default there, whatever was remembered
// for wide screens; the hamburger opens it for the moment (not remembered).
const narrow = computed(() => viewportWidth.value < NARROW)
const narrowOpen = ref(false)
const collapsed = computed({
  get: () => (narrow.value ? !narrowOpen.value : collapsedPref.value ?? store.hosts.length <= 1),
  set: (v: boolean) => (narrow.value ? (narrowOpen.value = !v) : (collapsedPref.value = v)),
})

onMounted(async () => {
  try {
    await store.load()
  } catch (e) {
    message.error(t('layout.backendUnreachable', { error: (e as Error).message }))
  }
})
</script>

<template>
  <NLayout class="root">
    <NLayoutHeader bordered class="header">
      <NButton
        quaternary
        size="small"
        class="burger"
        :title="collapsed ? t('layout.expandHosts') : t('layout.collapseHosts')"
        @click="collapsed = !collapsed"
      >
        ☰
      </NButton>
      <NText strong>TRex GUI</NText>
      <NSelect
        class="theme"
        size="small"
        :value="themePref"
        :options="themeOptions"
        :consistent-menu-width="false"
        :aria-label="t('layout.theme.label')"
        @update:value="(v: ThemePref) => (themePref = v)"
      />
      <NSelect
        class="lang"
        size="small"
        :value="locale"
        :options="LANGS"
        :consistent-menu-width="false"
        :aria-label="t('common.language')"
        @update:value="(v: Lang) => setLang(v)"
      />
    </NLayoutHeader>
    <NLayout has-sider class="body">
      <NLayoutSider
        bordered
        collapse-mode="width"
        :collapsed="collapsed"
        :width="240"
        :collapsed-width="64"
        :content-style="collapsed ? 'padding: 4px;' : 'padding: 8px;'"
      >
        <HostList :compact="collapsed" />
      </NLayoutSider>
      <NLayoutContent :content-style="narrow ? 'padding: 10px;' : 'padding: 16px;'">
        <OverviewPanel v-if="store.view === 'overview' && store.hosts.length" />
        <HostPanel v-else-if="store.selected" :key="store.selected.id" :host="store.selected" />
        <NEmpty v-else :description="t('layout.noHost')" class="empty" />
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>

<style scoped>
.root {
  height: 100vh;
}
.header {
  height: 48px;
  padding: 0 16px 0 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.theme {
  margin-left: auto;
  width: 120px;
}
.lang {
  width: 120px;
}
@media (max-width: 480px) {
  .theme,
  .lang {
    width: 96px;
  }
}
.burger {
  font-size: 18px;
  width: 40px;
}
.body {
  height: calc(100vh - 48px);
}
.empty {
  margin-top: 120px;
}
</style>
