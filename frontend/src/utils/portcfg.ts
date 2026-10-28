// Comparing a port's live L2/L3 state with wanted settings, shared by the port
// settings form, profile apply and the "settings drifted" check.
import type { PortConfig, PortLayer, PortSettings } from '../api'
import { t } from '../i18n'

const FLOW_CTRL_KEYS = ['off', 'tx', 'rx', 'both'] as const

/** Flow control mode labels, index = TRex flow_ctrl value. Call at render time. */
export const flowCtrlLabels = () => FLOW_CTRL_KEYS.map((k) => t(`ports.flowCtrl.${k}`))
export const flowCtrlLabel = (v: number) => (FLOW_CTRL_KEYS[v] ? t(`ports.flowCtrl.${FLOW_CTRL_KEYS[v]}`) : String(v))

export function settingsOf(l: PortLayer): PortSettings {
  return {
    mode: l.mode,
    ...(l.mode === 'L2' ? { dst_mac: l.dst_mac } : { ipv4_src: l.ipv4_src ?? '', ipv4_dst: l.ipv4_dst ?? '' }),
    vlan: [...l.vlan],
    ipv6: l.ipv6,
    ipv6_src: l.ipv6 ? l.ipv6_src : null,
    promiscuous: l.promiscuous,
    multicast: l.multicast,
    ...(l.flow_ctrl !== null ? { flow_ctrl: l.flow_ctrl } : {}),
  }
}

/** Only the parts of `want` that differ from the port now. */
export function diffConfig(cur: PortLayer, want: PortSettings): PortConfig {
  const out: PortConfig = {}
  if (want.vlan.join(',') !== cur.vlan.join(',')) out.vlan = want.vlan
  if (want.mode === 'L2' && (cur.mode !== 'L2' || (want.dst_mac ?? '').toLowerCase() !== cur.dst_mac.toLowerCase()))
    out.l2 = { dst_mac: want.dst_mac ?? '' }
  if (want.mode === 'L3' && (cur.mode !== 'L3' || want.ipv4_src !== cur.ipv4_src || want.ipv4_dst !== cur.ipv4_dst))
    out.l3 = { src: want.ipv4_src ?? '', dst: want.ipv4_dst ?? '' }
  // An empty wanted IPv6 address means "automatic"; don't compare it with the one TRex picked.
  if (want.ipv6 !== cur.ipv6 || (want.ipv6 && want.ipv6_src && want.ipv6_src !== cur.ipv6_src))
    out.ipv6 = { enabled: want.ipv6, src: want.ipv6_src || null }
  if (want.promiscuous !== cur.promiscuous) out.promiscuous = want.promiscuous
  if (want.multicast !== cur.multicast) out.multicast = want.multicast
  if (want.flow_ctrl != null && cur.flow_ctrl != null && want.flow_ctrl !== cur.flow_ctrl) out.flow_ctrl = want.flow_ctrl
  return out
}

const vlanText = (v: number[]) => (v.length ? v.join(' / ') : t('common.none'))
const modeText = (l: { mode: string; dst_mac?: string | null; ipv4_src?: string | null; ipv4_dst?: string | null }) =>
  l.mode === 'L2'
    ? t('ports.modeL2Text', { mac: l.dst_mac })
    : t('ports.modeL3Text', { src: l.ipv4_src, dst: l.ipv4_dst })
const onOff = (b: boolean) => (b ? t('common.on') : t('common.off'))
const change = (name: string, from: string, to: string) => t('ports.change', { name, from, to })
const updown = (b: boolean) => (b ? 'UP' : 'DOWN')

/** Human-readable "before → after" lines for a change set. */
export function describeConfig(cur: PortLayer, cfg: PortConfig): string[] {
  const lines: string[] = []
  const mode = t('ports.mode')
  if (cfg.l2) lines.push(change(mode, modeText(cur), modeText({ mode: 'L2', dst_mac: cfg.l2.dst_mac })))
  if (cfg.l3) lines.push(change(mode, modeText(cur), modeText({ mode: 'L3', ipv4_src: cfg.l3.src, ipv4_dst: cfg.l3.dst })))
  if (cfg.vlan) lines.push(change('VLAN', vlanText(cur.vlan), vlanText(cfg.vlan)))
  if (cfg.ipv6) {
    const to = onOff(cfg.ipv6.enabled)
    lines.push(change('IPv6', onOff(cur.ipv6), cfg.ipv6.enabled && cfg.ipv6.src ? t('ports.withAddr', { value: to, addr: cfg.ipv6.src }) : to))
  }
  if (cfg.promiscuous !== undefined) lines.push(change(t('ports.promiscuous'), onOff(cur.promiscuous), onOff(cfg.promiscuous)))
  if (cfg.multicast !== undefined) lines.push(change(t('ports.multicast'), onOff(cur.multicast), onOff(cfg.multicast)))
  if (cfg.link_up !== undefined) lines.push(change(t('ports.link'), updown(cur.link_up), updown(cfg.link_up)))
  if (cfg.flow_ctrl !== undefined)
    lines.push(change(t('ports.flowControl'), flowCtrlLabel(cur.flow_ctrl ?? 0), flowCtrlLabel(cfg.flow_ctrl)))
  return lines
}

export const summarize = (s: PortSettings) =>
  [modeText(s), s.vlan.length ? `VLAN ${vlanText(s.vlan)}` : '', s.ipv6 ? 'IPv6' : '', s.promiscuous ? 'Promisc' : '']
    .filter(Boolean)
    .join(t('ports.clauseSep'))
