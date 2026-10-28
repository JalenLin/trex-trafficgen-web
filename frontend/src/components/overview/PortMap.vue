<script setup lang="ts">
// Diagram of how ports reach each other and the outside world, inferred only from
// what the store already holds: each port's L2 destination MAC (or, in L3 mode,
// the gateway MAC ARP resolved) matched against every known port's source MAC,
// plus the user's cross-host pairs. No extra requests.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { NButton, NDataTable, type DataTableColumns } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { HostSummary, PortInfo } from '../../api'
import { useHostsStore } from '../../stores/hosts'
import { portPairs as pairs } from '../../composables/usePortPairs'
import { persisted } from '../../utils/prefs'

const props = defineProps<{ hosts: HostSummary[] }>()
const { t } = useI18n()
const store = useHostsStore()

// User pairs come from the shared list the pairs table edits (read-only here).

const showTable = persisted<boolean>('portmap.showTable', false)

// --- container width ---
const root = ref<HTMLDivElement | null>(null)
const width = ref(800)
let ro: ResizeObserver | null = null
onMounted(() => {
  ro = new ResizeObserver(([e]) => (width.value = Math.floor(e.contentRect.width)))
  if (root.value) ro.observe(root.value)
})
onBeforeUnmount(() => ro?.disconnect())

// --- helpers ---
const ZERO_MAC = '00:00:00:00:00:00'
function normMac(v: string | null | undefined): string {
  const m = (v ?? '').trim().toLowerCase().replace(/-/g, ':')
  return /^([0-9a-f]{2}:){5}[0-9a-f]{2}$/.test(m) && m !== ZERO_MAC ? m : ''
}
const shortMac = (m: string) => (m ? `…${m.slice(-8)}` : '–')
function speedLabel(gbps: number): string {
  if (!gbps || gbps <= 0) return ''
  if (gbps < 1) return `${Math.round(gbps * 1000)}M`
  return `${Number.isInteger(gbps) ? gbps : gbps.toFixed(1)}G`
}
/** Rough text width: CJK glyphs are about 1 em, Latin about 0.6 em. */
function textW(s: string, fs: number) {
  let w = 0
  for (const ch of s) w += ch.codePointAt(0)! > 0x2e80 ? fs : fs * 0.6
  return w
}
function fit(s: string, maxPx: number, fs: number) {
  if (textW(s, fs) <= maxPx) return s
  let out = s
  while (out.length > 1 && textW(out + '…', fs) > maxPx) out = out.slice(0, -1)
  return out + '…'
}
const pk = (host: string, port: number) => `${host}#${port}`
const statusLabel = (s: string) => (['TRANSMITTING', 'PAUSE', 'IDLE'].includes(s) ? t(`portmap.status.${s}`) : s)

// --- graph model ---
type ExtKind = 'gw' | 'unresolved' | 'l2dst'
type EdgeKind = 'l2' | 'l2bi' | 'gw' | 'unresolved' | 'l2dst' | 'pair'
interface PortNode {
  key: string
  hostId: string
  hostName: string
  port: PortInfo
  col: number
  row: number
  mac: string
}
interface ExtNode {
  key: string
  kind: ExtKind
  mac: string
  ips: string[]
  ports: string[]
}
interface EdgeModel {
  key: string
  kind: EdgeKind
  from: string
  to: string
  /** Direct port-to-port link found through a resolved L3 gateway MAC. */
  viaArp?: boolean
  mac?: string
}

const columns = computed(() =>
  props.hosts.map((h) => ({ host: h, ports: h.connected ? (store.ports[h.id] ?? []) : [] })),
)

const model = computed(() => {
  const ports: PortNode[] = []
  const byKey = new Map<string, PortNode>()
  const bySrc = new Map<string, PortNode[]>()
  columns.value.forEach((c, col) =>
    c.ports.forEach((p, row) => {
      const n: PortNode = { key: pk(c.host.id, p.id), hostId: c.host.id, hostName: c.host.name, port: p, col, row, mac: normMac(p.layer?.src_mac || p.hw_mac) }
      ports.push(n)
      byKey.set(n.key, n)
      if (n.mac) bySrc.set(n.mac, [...(bySrc.get(n.mac) ?? []), n])
    }),
  )
  // Several ports can share a MAC (e.g. mock hosts); prefer a peer on the same host.
  const peersOf = (n: PortNode, mac: string) => {
    const all = (bySrc.get(mac) ?? []).filter((c) => c.key !== n.key)
    const local = all.filter((c) => c.hostId === n.hostId)
    return local.length ? local : all
  }

  const ext = new Map<string, ExtNode>()
  const edges: EdgeModel[] = []
  const direct = new Map<string, { from: string; to: string; viaArp: boolean; mac: string }>()
  for (const n of ports) {
    const L = n.port.layer
    if (!L) continue
    if (L.mode === 'L3' && L.arp !== 'resolved') {
      const key = `u:${n.key}`
      ext.set(key, { key, kind: 'unresolved', mac: '', ips: L.ipv4_dst ? [L.ipv4_dst] : [], ports: [n.key] })
      edges.push({ key: `${n.key}>${key}`, kind: 'unresolved', from: n.key, to: key })
      continue
    }
    const dst = normMac(L.dst_mac)
    if (!dst) continue
    const peers = peersOf(n, dst)
    if (peers.length) {
      for (const p of peers) direct.set(`${n.key}>${p.key}`, { from: n.key, to: p.key, viaArp: L.mode === 'L3', mac: dst })
      continue
    }
    // One node per external MAC, shared by every port (L2 or L3) that sends to it.
    const key = `x:${dst}`
    let x = ext.get(key)
    if (!x) ext.set(key, (x = { key, kind: 'l2dst', mac: dst, ips: [], ports: [] }))
    if (L.mode === 'L3') {
      x.kind = 'gw'
      if (L.ipv4_dst && !x.ips.includes(L.ipv4_dst)) x.ips.push(L.ipv4_dst)
    }
    x.ports.push(n.key)
    edges.push({ key: `${n.key}>${key}`, kind: L.mode === 'L3' ? 'gw' : 'l2dst', from: n.key, to: key, mac: dst })
  }
  for (const [k, e] of direct) {
    const back = direct.get(`${e.to}>${e.from}`)
    if (!back) edges.push({ key: k, kind: 'l2', from: e.from, to: e.to, viaArp: e.viaArp, mac: e.mac })
    else if (e.from < e.to) edges.push({ key: k, kind: 'l2bi', from: e.from, to: e.to, viaArp: e.viaArp || back.viaArp })
  }
  pairs.value.forEach((p, i) => {
    const a = pk(p.a.host, p.a.port)
    const b = pk(p.b.host, p.b.port)
    if (a !== b && byKey.has(a) && byKey.has(b)) edges.push({ key: `pair${i}`, kind: 'pair', from: a, to: b })
  })
  return { ports, byKey, bySrc, ext: [...ext.values()], edges }
})

// --- layout ---
const PAD_X = 12
const HEAD_H = 46
const BOX_W = 184
const BOX_H = 50
const GAP_Y = 10
const EXT_W = 200
const EXT_H = 46
const MIN_GAP = 80
const MAX_GAP = 260
const LOOP_ROOM = 48
const PAIR_DY = 12 // pair edges attach a little lower so they don't hide an L2 link

interface Box {
  x: number
  y: number
  w: number
  h: number
}
interface EdgeDraw extends EdgeModel {
  d: string
  label?: { x: number; y: number }
}

const layout = computed(() => {
  const m = model.value
  const n = columns.value.length
  const hasExt = m.ext.length > 0
  const gaps = Math.max(0, n - 1) + (hasExt ? 1 : 0)
  const tail = hasExt ? EXT_W : LOOP_ROOM
  const minW = PAD_X * 2 + n * BOX_W + gaps * MIN_GAP + tail
  const W = Math.max(width.value, minW)
  const gap = gaps ? Math.min(MAX_GAP, MIN_GAP + (W - minW) / gaps) : MIN_GAP
  const used = n * BOX_W + gaps * gap + tail
  const left = Math.max(PAD_X, (W - used) / 2)
  const colX = (i: number) => left + i * (BOX_W + gap)
  const rowY = (r: number) => HEAD_H + r * (BOX_H + GAP_Y)

  const boxes = new Map<string, Box>()
  for (const p of m.ports) boxes.set(p.key, { x: colX(p.col), y: rowY(p.row), w: BOX_W, h: BOX_H })

  // External nodes: near the average height of their ports, pushed down to avoid overlap.
  const extX = colX(n)
  const want = m.ext
    .map((e) => {
      const ys = e.ports.map((k) => boxes.get(k)!).map((b) => b.y + b.h / 2)
      return { e, cy: ys.reduce((a, b) => a + b, 0) / Math.max(1, ys.length) }
    })
    .sort((a, b) => a.cy - b.cy)
  let next = HEAD_H
  for (const { e, cy } of want) {
    const y = Math.max(next, cy - EXT_H / 2)
    boxes.set(e.key, { x: extX, y, w: EXT_W, h: EXT_H })
    next = y + EXT_H + GAP_Y
  }

  const maxRows = Math.max(1, ...columns.value.map((c) => c.ports.length))
  const H = Math.max(rowY(maxRows) - GAP_Y, next - GAP_Y) + 10

  const lastCol = n - 1
  const edges: EdgeDraw[] = m.edges.map((e) => {
    const a = boxes.get(e.from)!
    const b = boxes.get(e.to)!
    const dy = e.kind === 'pair' ? PAIR_DY : 0
    const ay = a.y + a.h / 2 + dy
    const by = b.y + b.h / 2 + (m.byKey.has(e.to) ? dy : 0)
    let p0: [number, number], c1: [number, number], c2: [number, number], p3: [number, number]
    if (Math.abs(a.x - b.x) < 1) {
      // Same column: a loop out to the right.
      const col = m.byKey.get(e.from)!.col
      const room = col === lastCol && !hasExt ? LOOP_ROOM - 8 : gap * 0.42
      const bulge = Math.min(room, 22 + Math.abs(by - ay) * 0.12 + (e.kind === 'pair' ? 10 : 0))
      const x = a.x + a.w
      p0 = [x, ay]
      c1 = [x + bulge * 1.33, ay]
      c2 = [x + bulge * 1.33, by]
      p3 = [x, by]
    } else {
      const rightward = b.x > a.x
      const x0 = rightward ? a.x + a.w : a.x
      const x3 = rightward ? b.x : b.x + b.w
      const dx = Math.max(30, Math.abs(x3 - x0) / 2) * (rightward ? 1 : -1)
      p0 = [x0, ay]
      c1 = [x0 + dx, ay]
      c2 = [x3 - dx, by]
      p3 = [x3, by]
    }
    const f = (q: [number, number]) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`
    const d = `M${f(p0)} C${f(c1)} ${f(c2)} ${f(p3)}`
    const mid = (i: 0 | 1) => (p0[i] + 3 * c1[i] + 3 * c2[i] + p3[i]) / 8
    return { ...e, d, label: e.kind === 'pair' ? { x: mid(0), y: mid(1) } : undefined }
  })

  const heads = columns.value.map((c, i) => ({ id: c.host.id, x: colX(i), host: c.host, empty: !c.ports.length }))
  return { W, H, boxes, edges, heads, extX, hasExt }
})

// --- hover / focus / tap ---
const hover = ref<string | null>(null)
const pinned = ref<string | null>(null)
const active = computed(() => hover.value ?? pinned.value)
const litEdges = computed(() => {
  const k = active.value
  return k ? new Set(layout.value.edges.filter((e) => e.from === k || e.to === k).map((e) => e.key)) : null
})
const litNodes = computed(() => {
  const k = active.value
  if (!k) return null
  const s = new Set([k])
  for (const e of layout.value.edges) if (e.from === k || e.to === k) s.add(e.from).add(e.to)
  return s
})
function tap(key: string) {
  pinned.value = pinned.value === key ? null : key
}

// --- edge styling ---
type Tone = 'strong' | 'soft' | 'warn' | 'hi'
const DASH: Partial<Record<EdgeKind, string>> = { pair: '6 4', l2dst: '1 4', unresolved: '1 4' }
function tone(e: EdgeModel): Tone {
  if (litEdges.value?.has(e.key)) return 'hi'
  return e.kind === 'unresolved' ? 'warn' : e.kind === 'gw' || e.kind === 'l2dst' ? 'soft' : 'strong'
}
const uid = `pm${Math.random().toString(36).slice(2, 8)}`
const marker = (e: EdgeModel, end: 'start' | 'end') => {
  if (e.kind === 'pair') return undefined
  if (end === 'start' && e.kind !== 'l2bi') return undefined
  return `url(#${uid}-${tone(e)})`
}
const TONES: Tone[] = ['strong', 'soft', 'warn', 'hi']

// --- labels ---
const hostLabel = (id: string) => props.hosts.find((h) => h.id === id)?.name ?? id
function nodeTitle(e: ExtNode) {
  if (e.kind === 'l2dst') return t('portmap.node.l2dst')
  return e.ips.length ? `${t('portmap.node.gateway')} ${e.ips.join(', ')}` : t('portmap.node.gateway')
}
function endLabel(key: string) {
  const p = model.value.byKey.get(key)
  if (p) return `${hostLabel(p.hostId)} · ${t('common.portN', { n: p.port.id })}`
  const x = model.value.ext.find((e) => e.key === key)
  if (!x) return key
  return x.kind === 'unresolved' ? `${nodeTitle(x)} (${t('portmap.node.unresolved')})` : `${nodeTitle(x)}${x.mac ? ` (${x.mac})` : ''}`
}
function kindLabel(e: EdgeModel) {
  if (e.kind === 'l2' && e.viaArp) return t('portmap.kind.l3direct')
  if (e.kind === 'l2bi' && e.viaArp) return t('portmap.kind.l3directBi')
  return t(`portmap.kind.${e.kind}`)
}

interface PortView extends PortNode {
  box: Box
  title: string
  meta: string
  macText: string
  linkText: string
  down: boolean
  state: 'tx' | 'pause' | 'idle'
}
const portViews = computed<PortView[]>(() =>
  model.value.ports.map((p) => {
    const box = layout.value.boxes.get(p.key)!
    const down = p.port.link !== 'UP'
    const st = p.port.status
    const meta = [speedLabel(p.port.speed_gbps), p.port.layer?.mode].filter(Boolean).join(' · ')
    const linkText = [down ? t('portmap.linkDown') : t('portmap.linkUp'), st === 'TRANSMITTING' || st === 'PAUSE' ? statusLabel(st) : ''].filter(Boolean).join(' · ')
    return {
      ...p,
      box,
      title: t('common.portN', { n: p.port.id }),
      meta,
      macText: shortMac(p.mac),
      linkText,
      down,
      state: st === 'TRANSMITTING' ? 'tx' : st === 'PAUSE' ? 'pause' : 'idle',
    }
  }),
)
const extViews = computed(() =>
  model.value.ext.map((e) => ({
    ...e,
    box: layout.value.boxes.get(e.key)!,
    line1: fit(nodeTitle(e), EXT_W - 24, 12),
    line2: e.kind === 'unresolved' ? t('portmap.node.unresolved') : e.mac,
  })),
)
const heads = computed(() =>
  layout.value.heads.map((h) => ({
    ...h,
    name: fit(h.host.name, BOX_W, 13),
    server: fit(h.host.server, BOX_W, 11),
  })),
)

// --- tooltip ---
const TIP_W = 260
const tip = computed(() => {
  const k = active.value
  if (!k) return null
  const box = layout.value.boxes.get(k)
  if (!box) return null
  const rows: [string, string][] = []
  const notes: string[] = []
  let title: string
  const p = model.value.byKey.get(k)
  if (p) {
    const L = p.port.layer
    title = `${hostLabel(p.hostId)} · ${t('common.portN', { n: p.port.id })}`
    rows.push([t('portmap.tip.status'), statusLabel(p.port.status)])
    rows.push([t('portmap.tip.link'), p.port.link])
    if (p.port.speed_gbps) rows.push([t('portmap.tip.speed'), `${speedLabel(p.port.speed_gbps)}bps`])
    if (L) rows.push([t('portmap.tip.mode'), L.mode])
    rows.push([t('portmap.tip.srcMac'), p.mac || '–'])
    if (L) {
      if (L.mode === 'L3') {
        rows.push([t('portmap.tip.ipv4'), L.ipv4_src ?? '–'])
        rows.push([t('portmap.tip.gateway'), L.ipv4_dst ?? '–'])
        rows.push([t('portmap.tip.arp'), L.arp === 'resolved' ? t('portmap.tip.arpResolved') : t('portmap.tip.arpUnresolved')])
      }
      if (L.mode === 'L2' || L.arp === 'resolved') rows.push([t('portmap.tip.dstMac'), normMac(L.dst_mac) || L.dst_mac || '–'])
      rows.push([t('portmap.tip.vlan'), L.vlan.length ? L.vlan.join(', ') : t('common.none')])
      rows.push([t('portmap.tip.ipv6'), L.ipv6 ? (L.ipv6_src ?? t('common.on')) : t('common.off')])
    }
    const owner = p.port.owner
    rows.push([t('portmap.tip.owner'), !owner ? t('portmap.tip.noOwner') : p.port.acquired ? t('portmap.tip.ownerMe', { owner }) : owner])
    rows.push([t('portmap.tip.driver'), [p.port.description, p.port.driver].filter(Boolean).join(' · ') || '–'])
    const same = p.mac ? (model.value.bySrc.get(p.mac)?.length ?? 0) : 0
    if (same > 1) notes.push(t('portmap.tip.sharedMac', { n: same }))
  } else {
    const x = model.value.ext.find((e) => e.key === k)
    if (!x) return null
    title = x.kind === 'l2dst' ? t('portmap.node.l2dst') : t('portmap.node.gateway')
    if (x.mac) rows.push([t('portmap.tip.mac'), x.mac])
    if (x.ips.length) rows.push([t('portmap.tip.ips'), x.ips.join(', ')])
    if (x.kind === 'unresolved') rows.push([t('portmap.tip.arp'), t('portmap.tip.arpUnresolved')])
    rows.push([t('portmap.tip.ports'), x.ports.map(endLabel).join('\n')])
  }
  const W = layout.value.W
  const right = box.x + box.w + 10 + TIP_W <= W
  const pos = right ? { left: `${box.x + box.w + 10}px` } : box.x - 10 - TIP_W >= 0 ? { left: `${box.x - 10 - TIP_W}px` } : { left: `${Math.max(0, W - TIP_W)}px` }
  return { title, rows, notes, style: { ...pos, top: `${Math.max(0, box.y - 4)}px`, width: `${TIP_W}px` } }
})

// --- empty states ---
const totalPorts = computed(() => model.value.ports.length)
const hint = computed(() => {
  if (!props.hosts.length) return t('portmap.emptyHosts')
  if (!totalPorts.value) return t('portmap.emptyPorts')
  if (!model.value.edges.length) return t('portmap.emptyEdges')
  return null
})

// --- table view ---
interface Row {
  key: string
  from: string
  to: string
  kind: string
  detail: string
}
const tableRows = computed<Row[]>(() =>
  model.value.edges.map((e) => {
    const x = model.value.ext.find((n) => n.key === e.to)
    return {
      key: e.key,
      from: endLabel(e.from),
      to: endLabel(e.to),
      kind: kindLabel(e),
      detail: e.kind === 'pair' ? '' : [e.mac, x?.ips.join(', ')].filter(Boolean).join(' · '),
    }
  }),
)
const tableColumns = computed<DataTableColumns<Row>>(() => [
  { title: t('portmap.col.from'), key: 'from', minWidth: 160 },
  { title: t('portmap.col.to'), key: 'to', minWidth: 160 },
  { title: t('portmap.col.kind'), key: 'kind', minWidth: 120 },
  { title: t('portmap.col.detail'), key: 'detail', minWidth: 140 },
])

const legend = computed(() =>
  (['l2', 'l2bi', 'gw', 'unresolved', 'l2dst', 'pair'] as EdgeKind[]).map((kind) => ({
    kind,
    label: t(`portmap.legend.${kind}`),
    tone: (kind === 'unresolved' ? 'warn' : kind === 'gw' || kind === 'l2dst' ? 'soft' : 'strong') as Tone,
  })),
)
</script>

<template>
  <div ref="root" class="portmap-root">
    <div class="bar">
      <span class="intro">{{ t('portmap.intro') }}</span>
      <NButton v-if="hosts.length" size="tiny" secondary :aria-pressed="showTable" @click="showTable = !showTable">
        {{ showTable ? t('portmap.showDiagram') : t('portmap.showTable') }}
      </NButton>
    </div>

    <div v-if="hint" class="hint">{{ hint }}</div>

    <template v-if="hosts.length && !showTable">
      <div class="legend">
        <span v-for="l in legend" :key="l.kind" class="item">
          <svg width="30" height="10" aria-hidden="true">
            <line
              x1="2"
              y1="5"
              :x2="l.kind === 'pair' ? 28 : 24"
              y2="5"
              :class="`edge tone-${l.tone}`"
              :stroke-dasharray="DASH[l.kind]"
            />
            <path v-if="l.kind !== 'pair'" d="M23,1.5 L29,5 L23,8.5 z" :class="`head tone-${l.tone}`" />
            <path v-if="l.kind === 'l2bi'" d="M7,1.5 L1,5 L7,8.5 z" :class="`head tone-${l.tone}`" />
          </svg>
          {{ l.label }}
        </span>
        <span class="item">
          <span class="stripe-swatch" aria-hidden="true" />
          {{ t('portmap.legend.sending') }}
        </span>
        <span class="legend-hint">{{ t('portmap.hoverHint') }}</span>
      </div>

      <div class="scroller">
        <div class="canvas" :style="{ width: `${layout.W}px`, height: `${layout.H}px` }">
          <svg
            :width="layout.W"
            :height="layout.H"
            role="img"
            :aria-label="t('portmap.ariaLabel', { ports: totalPorts, links: model.edges.length })"
            @click.self="pinned = null"
          >
            <defs>
              <marker
                v-for="tn in TONES"
                :id="`${uid}-${tn}`"
                :key="tn"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="8"
                markerHeight="8"
                markerUnits="userSpaceOnUse"
                orient="auto-start-reverse"
              >
                <path d="M0,1 L9,5 L0,9 z" :class="`head tone-${tn}`" />
              </marker>
            </defs>

            <!-- column headings -->
            <g class="heads">
              <g v-for="h in heads" :key="h.id">
                <text :x="h.x" y="16" class="head-name">
                  <title>{{ h.host.name }}</title>
                  {{ h.name }}
                </text>
                <text :x="h.x" y="32" class="head-sub">{{ h.server }}</text>
                <template v-if="h.empty">
                  <rect :x="h.x + 0.5" :y="HEAD_H + 0.5" :width="BOX_W - 1" :height="BOX_H - 1" rx="6" class="placeholder" />
                  <text :x="h.x + BOX_W / 2" :y="HEAD_H + BOX_H / 2 + 4" text-anchor="middle" class="muted">
                    {{ h.host.connected ? t('portmap.noPorts') : t('portmap.notConnected') }}
                  </text>
                </template>
              </g>
              <text v-if="layout.hasExt" :x="layout.extX" y="16" class="head-name">{{ fit(t('portmap.external'), EXT_W, 13) }}</text>
            </g>

            <!-- edges under the boxes -->
            <g class="edges" :class="{ dim: !!litEdges }">
              <path
                v-for="e in layout.edges"
                :key="e.key"
                :d="e.d"
                :class="['edge', `tone-${tone(e)}`, { lit: litEdges?.has(e.key) }]"
                :stroke-dasharray="DASH[e.kind]"
                :marker-start="marker(e, 'start')"
                :marker-end="marker(e, 'end')"
              />
            </g>

            <!-- ports -->
            <g
              v-for="p in portViews"
              :key="p.key"
              class="node port"
              role="button"
              :class="[`st-${p.state}`, { active: active === p.key, faded: litNodes && !litNodes.has(p.key) }]"
              tabindex="0"
              :aria-label="`${p.hostName} ${p.title} ${p.meta} ${p.linkText}`"
              @pointerenter="hover = p.key"
              @pointerleave="hover = null"
              @focus="hover = p.key"
              @blur="hover = null"
              @click="tap(p.key)"
            >
              <rect :x="p.box.x + 0.5" :y="p.box.y + 0.5" :width="BOX_W - 1" :height="BOX_H - 1" rx="6" class="box" />
              <rect :x="p.box.x + 6" :y="p.box.y + 9" width="3" :height="BOX_H - 18" rx="1.5" class="stripe" />
              <text :x="p.box.x + 16" :y="p.box.y + 20" class="t1">{{ p.title }}</text>
              <g v-if="p.port.acquired">
                <rect :x="p.box.x + 16 + textW(p.title, 12.5) + 6" :y="p.box.y + 9" :width="textW(t('common.mine'), 10) + 10" height="15" rx="7.5" class="pill" />
                <text :x="p.box.x + 16 + textW(p.title, 12.5) + 11" :y="p.box.y + 20" class="pill-text">{{ t('common.mine') }}</text>
              </g>
              <text :x="p.box.x + BOX_W - 10" :y="p.box.y + 20" text-anchor="end" class="t2">{{ p.meta }}</text>
              <text :x="p.box.x + 16" :y="p.box.y + 38" class="mono">{{ p.macText }}</text>
              <text :x="p.box.x + BOX_W - 10" :y="p.box.y + 38" text-anchor="end" :class="p.down ? 'danger' : 't2'">{{ p.linkText }}</text>
            </g>

            <!-- external nodes -->
            <g
              v-for="x in extViews"
              :key="x.key"
              class="node ext"
              role="button"
              :class="[`k-${x.kind}`, { active: active === x.key, faded: litNodes && !litNodes.has(x.key) }]"
              tabindex="0"
              :aria-label="`${x.line1} ${x.line2}`"
              @pointerenter="hover = x.key"
              @pointerleave="hover = null"
              @focus="hover = x.key"
              @blur="hover = null"
              @click="tap(x.key)"
            >
              <rect :x="x.box.x + 0.5" :y="x.box.y + 0.5" :width="EXT_W - 1" :height="EXT_H - 1" rx="12" class="box" />
              <text :x="x.box.x + 12" :y="x.box.y + 19" class="t1">{{ x.line1 }}</text>
              <text :x="x.box.x + 12" :y="x.box.y + 35" :class="x.kind === 'unresolved' ? 'warn' : 'mono'">{{ x.line2 }}</text>
            </g>

            <!-- pair labels on top -->
            <g class="pair-labels">
              <template v-for="e in layout.edges" :key="`l${e.key}`">
                <text
                  v-if="e.label"
                  :x="e.label.x"
                  :y="e.label.y + 4"
                  text-anchor="middle"
                  class="pair-label"
                  :class="{ lit: litEdges?.has(e.key), faded: litEdges && !litEdges.has(e.key) }"
                >
                  {{ t('portmap.pairTag') }}
                </text>
              </template>
            </g>
          </svg>

          <div v-if="tip" class="tooltip" :style="tip.style">
            <div class="tip-title">{{ tip.title }}</div>
            <div v-for="([k, v], i) in tip.rows" :key="i" class="tip-row">
              <span class="tip-k">{{ k }}</span>
              <span class="tip-v">{{ v }}</span>
            </div>
            <div v-for="(nt, i) in tip.notes" :key="`n${i}`" class="tip-note">{{ nt }}</div>
          </div>
        </div>
      </div>
    </template>

    <NDataTable
      v-if="hosts.length && showTable"
      size="small"
      :columns="tableColumns"
      :data="tableRows"
      :row-key="(r: Row) => r.key"
      :max-height="360"
      :scroll-x="600"
    />
  </div>
</template>

<style scoped>
.portmap-root {
  --pm-bg: #ffffff;
  --pm-surface: #ffffff;
  --pm-text: #1f1e1c;
  --pm-text-2: #52514e;
  --pm-muted: #7a7974;
  --pm-border: rgba(128, 128, 128, 0.38);
  --pm-grid: rgba(128, 128, 128, 0.18);
  --pm-edge-strong: #6b6a65;
  --pm-edge-soft: #aeada7;
  --pm-accent: #2a78d6;
  --pm-ok: #1baf7a;
  --pm-pause: #e0a000;
  --pm-warn: #d99a00;
  --pm-warn-text: #8a5a00;
  --pm-danger-text: #b42318;
  --pm-pill: rgba(42, 120, 214, 0.12);
  min-width: 0;
}
:global(html.dark .portmap-root) {
  --pm-bg: #18181c;
  --pm-surface: #222227;
  --pm-text: #e8e7e1;
  --pm-text-2: #c3c2b7;
  --pm-muted: #9a998f;
  --pm-border: rgba(160, 160, 160, 0.32);
  --pm-grid: rgba(160, 160, 160, 0.16);
  --pm-edge-strong: #a3a29a;
  --pm-edge-soft: #64635e;
  --pm-accent: #4d94ea;
  --pm-ok: #199e70;
  --pm-pause: #c98500;
  --pm-warn: #c98500;
  --pm-warn-text: #f0b84a;
  --pm-danger-text: #f97066;
  --pm-pill: rgba(77, 148, 234, 0.2);
}
.bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
.intro {
  font-size: 12px;
  color: var(--pm-muted);
}
.hint {
  font-size: 13px;
  color: var(--pm-text-2);
  padding: 8px 10px;
  margin-bottom: 8px;
  border: 1px dashed var(--pm-border);
  border-radius: 6px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 14px;
  font-size: 12px;
  color: var(--pm-text-2);
  margin-bottom: 6px;
}
.legend .item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.legend svg {
  display: block;
}
.legend-hint {
  color: var(--pm-muted);
  font-size: 11px;
}
.stripe-swatch {
  width: 3px;
  height: 12px;
  border-radius: 1.5px;
  background: var(--pm-ok);
}
.scroller {
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
}
.canvas {
  position: relative;
}
svg {
  display: block;
}

/* text */
.head-name {
  font-size: 13px;
  font-weight: 600;
  fill: var(--pm-text);
}
.head-sub,
.muted {
  font-size: 11px;
  fill: var(--pm-muted);
}
.t1 {
  font-size: 12px;
  font-weight: 600;
  fill: var(--pm-text);
}
.t2 {
  font-size: 11px;
  fill: var(--pm-text-2);
}
.mono {
  font-size: 11px;
  fill: var(--pm-text-2);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.danger {
  font-size: 11px;
  font-weight: 600;
  fill: var(--pm-danger-text);
}
.warn {
  font-size: 11px;
  font-weight: 600;
  fill: var(--pm-warn-text);
}
.pill {
  fill: var(--pm-pill);
}
.pill-text {
  font-size: 10px;
  fill: var(--pm-text);
}

/* structure */
.placeholder {
  fill: none;
  stroke: var(--pm-border);
  stroke-dasharray: 4 4;
}
.node {
  cursor: pointer;
  outline: none;
  transition: opacity 0.12s;
}
.node .box {
  fill: var(--pm-surface);
  stroke: var(--pm-border);
  stroke-width: 1;
}
.port.st-tx .box {
  fill: color-mix(in srgb, var(--pm-ok) 8%, var(--pm-surface));
}
.stripe {
  fill: var(--pm-border);
}
.port.st-tx .stripe {
  fill: var(--pm-ok);
}
.port.st-pause .stripe {
  fill: var(--pm-pause);
}
.ext.k-unresolved .box {
  fill: color-mix(in srgb, var(--pm-warn) 10%, var(--pm-surface));
  stroke: var(--pm-warn);
  stroke-dasharray: 4 3;
}
.ext.k-l2dst .box {
  stroke-dasharray: 2 3;
}
.node.active .box,
.node:focus-visible .box {
  stroke: var(--pm-accent);
  stroke-width: 2;
}
.node.faded {
  opacity: 0.45;
}

/* edges */
.edge {
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  transition: opacity 0.12s;
}
.edge.tone-strong {
  stroke: var(--pm-edge-strong);
}
.edge.tone-soft {
  stroke: var(--pm-edge-soft);
}
.edge.tone-warn {
  stroke: var(--pm-warn);
}
.edge.tone-hi {
  stroke: var(--pm-accent);
}
.head.tone-strong {
  fill: var(--pm-edge-strong);
}
.head.tone-soft {
  fill: var(--pm-edge-soft);
}
.head.tone-warn {
  fill: var(--pm-warn);
}
.head.tone-hi {
  fill: var(--pm-accent);
}
.edges.dim .edge:not(.lit) {
  opacity: 0.18;
}
.pair-label {
  font-size: 10px;
  fill: var(--pm-text-2);
  stroke: var(--pm-bg);
  stroke-width: 4px;
  stroke-linejoin: round;
  paint-order: stroke;
  pointer-events: none;
}
.pair-label.lit {
  fill: var(--pm-text);
  font-weight: 600;
}
.pair-label.faded {
  opacity: 0.3;
}

/* tooltip */
.tooltip {
  position: absolute;
  z-index: 2;
  pointer-events: none;
  background: var(--pm-surface);
  border: 1px solid var(--pm-border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 12px;
  color: var(--pm-text);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.14);
}
.tip-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.tip-row {
  display: flex;
  gap: 8px;
  line-height: 1.5;
}
.tip-k {
  color: var(--pm-muted);
  flex: none;
  width: 92px;
}
.tip-v {
  color: var(--pm-text);
  white-space: pre-line;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
.tip-note {
  margin-top: 4px;
  color: var(--pm-warn-text);
}
</style>
