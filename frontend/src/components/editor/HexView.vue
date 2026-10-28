<script setup lang="ts">
import { computed } from 'vue'
import type { DescLayer } from '../../api'

const props = defineProps<{
  hex: string
  layers: DescLayer[]
  /** Byte range [start, end) to highlight, e.g. the hovered field. */
  highlight: [number, number] | null
  /** Tooltip on the bytes, e.g. "click to edit this field". */
  hint?: string
}>()
const emit = defineEmits<{
  /** A byte was clicked (not a text selection): the editor jumps to its field. */
  pick: [byte: number]
  hoverByte: [byte: number | null]
}>()

// One listener for all bytes: each byte span carries its index in data-i.
const byteOf = (ev: Event): number | null => {
  const i = (ev.target as HTMLElement).dataset?.i
  return i === undefined ? null : Number(i)
}
function onClick(ev: MouseEvent) {
  const b = byteOf(ev)
  // Dragging to copy bytes must not jump away.
  if (b !== null && !window.getSelection()?.toString()) emit('pick', b)
}

const bytes = computed(() => props.hex.match(/../g) ?? [])
const layerOf = computed(() => {
  const out = new Array<number>(bytes.value.length).fill(-1)
  props.layers.forEach((l, i) => {
    for (let b = l.offset; b < l.offset + l.length && b < out.length; b++) out[b] = i
  })
  return out
})
const rows = computed(() => {
  const out: number[] = []
  for (let i = 0; i < bytes.value.length; i += 16) out.push(i)
  return out
})

const ascii = (b: string) => {
  const c = parseInt(b, 16)
  return c >= 32 && c < 127 ? String.fromCharCode(c) : '.'
}
const lit = (i: number) => props.highlight !== null && i >= props.highlight[0] && i < props.highlight[1]
</script>

<template>
  <div class="hex" :title="hint" @click="onClick" @mouseover="emit('hoverByte', byteOf($event))" @mouseleave="emit('hoverByte', null)">
    <div v-for="start in rows" :key="start" class="line">
      <span class="off">{{ start.toString(16).padStart(4, '0') }}</span>
      <span class="bytes">
        <span
          v-for="i in Math.min(16, bytes.length - start)"
          :key="i"
          :data-i="start + i - 1"
          :class="['b', `l${layerOf[start + i - 1] % 6}`, { lit: lit(start + i - 1), gap: i === 8 }]"
          >{{ bytes[start + i - 1] }}</span
        >
      </span>
      <span class="ascii">
        <span
          v-for="i in Math.min(16, bytes.length - start)"
          :key="i"
          :data-i="start + i - 1"
          :class="['a', `l${layerOf[start + i - 1] % 6}`, { lit: lit(start + i - 1) }]"
          >{{ ascii(bytes[start + i - 1]) }}</span
        >
      </span>
    </div>
  </div>
</template>

<style scoped>
.hex {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre;
}
.off {
  opacity: 0.5;
  margin-right: 12px;
}
.b {
  padding: 0 3px;
}
.b,
.a {
  cursor: pointer;
}
.b.gap {
  margin-right: 8px;
}
.ascii {
  margin-left: 12px;
}
.lit {
  outline: 1.5px solid #f0a020;
  background: rgba(240, 160, 32, 0.35) !important;
}
/* Alternating layer tints */
.l0 { background: rgba(32, 128, 240, 0.12); }
.l1 { background: rgba(24, 160, 88, 0.12); }
.l2 { background: rgba(208, 48, 80, 0.10); }
.l3 { background: rgba(144, 96, 224, 0.12); }
.l4 { background: rgba(240, 160, 32, 0.12); }
.l5 { background: rgba(0, 170, 170, 0.12); }
</style>
