import type { StreamSpec } from '../api'
import { t } from '../i18n'
import { formatBps, formatPps } from './format'

export const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T

export const layersSummary = (s: StreamSpec) => s.packet.layers.map((l) => l.proto.split('.').pop()).join(' / ')

export function sizeSummary(s: StreamSpec): string {
  const sz = s.packet.size
  if (sz && sz.mode !== 'fixed') return t('streams.summary.sizeRange', { min: sz.min, max: sz.max, mode: t(`streams.op.${sz.mode}`) })
  return s.packet.frame_size ? `${s.packet.frame_size}B` : '—'
}

export function modeSummary(s: StreamSpec): string {
  const m = s.mode
  if (m.type === 'single_burst') return t('streams.summary.singleBurst', { n: m.total_pkts ?? 1 })
  if (m.type === 'multi_burst') return t('streams.summary.multiBurst', { count: m.count ?? 1, n: m.pkts_per_burst ?? 1 })
  return t('streams.summary.continuous')
}

export function rateSummary(s: StreamSpec): string {
  const { unit, value } = s.rate
  if (unit === 'pps') return formatPps(value)
  if (unit === 'percentage') return t('streams.summary.lineRate', { value })
  return `${formatBps(value)} (${unit === 'bps_L1' ? 'L1' : 'L2'})`
}

export function flowStatsSummary(s: StreamSpec): string {
  if (s.flow_stats.type === 'stats') return t('streams.summary.stats', { id: s.flow_stats.pg_id })
  if (s.flow_stats.type === 'latency') return `Latency #${s.flow_stats.pg_id}`
  return ''
}
