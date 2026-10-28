<script setup lang="ts">
import { computed } from 'vue'
import { darkTheme, NConfigProvider, NDialogProvider, NGlobalStyle, NMessageProvider, zhTW, dateZhTW, enUS, dateEnUS } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import MainLayout from './components/MainLayout.vue'
import { isDark } from './theme'

const theme = computed(() => (isDark.value ? darkTheme : null))
const { locale } = useI18n()
const naiveLocale = computed(() => (locale.value === 'zh-TW' ? zhTW : enUS))
const naiveDate = computed(() => (locale.value === 'zh-TW' ? dateZhTW : dateEnUS))
</script>

<template>
  <NConfigProvider :theme="theme" :locale="naiveLocale" :date-locale="naiveDate">
    <NGlobalStyle />
    <NMessageProvider>
      <NDialogProvider>
        <MainLayout />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
