<script setup lang="ts">
import { reactive } from 'vue'
import { NCard, NText } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { StatsMessage } from '../../api'
import { useHostsStore } from '../../stores/hosts'
import HostCard from './HostCard.vue'
import PortMap from './PortMap.vue'
import PortPairs from './PortPairs.vue'

const { t } = useI18n()
const store = useHostsStore()
// Latest sample per host, filled by the cards (each owns its host's stats stream).
const latest = reactive<Record<string, Extract<StatsMessage, { type: 'stats' }> | null>>({})
</script>

<template>
  <div class="overview">
    <NText strong style="font-size: 18px">{{ t('overview.nav') }}</NText>
    <NText depth="3" style="font-size: 12px">{{ t('overview.intro') }}</NText>
    <div class="cards">
      <HostCard v-for="h in store.hosts" :key="h.id" :host="h" @latest="(m) => (latest[h.id] = m)" />
    </div>
    <NCard size="small" :title="t('portmap.title')">
      <PortMap :hosts="store.hosts" />
    </NCard>
    <NCard size="small" :title="t('overview.pairs.title')">
      <PortPairs :hosts="store.hosts" :latest="latest" />
    </NCard>
  </div>
</template>

<style scoped>
.overview {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 12px;
}
@media (max-width: 860px) {
  .cards {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
