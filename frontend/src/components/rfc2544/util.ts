// Shared helpers for the RFC 2544 panel: defaults, time estimate, number and log wording.
import type { Rfc2544Config, Rfc2544Log, Rfc2544Test } from '../../api'

export type Translate = (key: string, params?: Record<string, unknown>) => string

export const TESTS: Rfc2544Test[] = ['throughput', 'latency', 'frame_loss', 'back_to_back']
export const DEFAULT_SIZES = [64, 128, 256, 512, 1024, 1280, 1518]
export const MIN_SIZE = 64
export const MAX_SIZE = 9216

export function defaultConfig(): Rfc2544Config {
  return {
    pairs: [{ tx: 0, rx: 1 }],
    bidirectional: true,
    frame_sizes: [...DEFAULT_SIZES],
    tests: ['throughput', 'latency'],
    trial_s: 10,
    resolution_pct: 0.5,
    max_rate_pct: 100,
    loss_tolerance_pct: 0,
    frame_loss_step_pct: 10,
    b2b_max_s: 2,
  }
}

/** TX → RX directions the backend will measure (rfc2544.Rfc2544Config.directions). */
export function directions(pairs: { tx: number; rx: number }[], bidirectional: boolean): [number, number][] {
  const out: [number, number][] = []
  for (const p of pairs) {
    out.push([p.tx, p.rx])
    if (bidirectional) out.push([p.rx, p.tx])
  }
  return out
}

export const dirLabel = (tx: number, rx: number) => `${tx}→${rx}`

// Backend constants (rfc2544.py): binary search cap, settle time after each trial.
const MAX_BINARY_STEPS = 20
const PER_TRIAL_OVERHEAD_S = 1.5 // settle 1 s + clear/start/read stats

/** Rough best/worst case trial count and duration (seconds) for a config. */
export function estimate(c: Rfc2544Config): { min: number; max: number; tmin: number; tmax: number } {
  const sizes = c.frame_sizes.length
  let min = 0
  let max = 0
  let tmin = 0
  let tmax = 0
  const add = (lo: number, hi: number, secs: number) => {
    min += lo * sizes
    max += hi * sizes
    tmin += lo * sizes * (secs + PER_TRIAL_OVERHEAD_S)
    tmax += hi * sizes * (secs + PER_TRIAL_OVERHEAD_S)
  }
  if (c.tests.includes('throughput')) {
    const steps = c.resolution_pct > 0 ? Math.ceil(Math.log2(Math.max(1, c.max_rate_pct / c.resolution_pct))) : MAX_BINARY_STEPS
    add(1, 1 + Math.min(MAX_BINARY_STEPS, Math.max(0, steps)), c.trial_s)
  }
  if (c.tests.includes('latency')) add(1, 1, c.trial_s)
  if (c.tests.includes('frame_loss')) {
    const n = c.frame_loss_step_pct > 0 ? Math.max(1, Math.ceil(c.max_rate_pct / c.frame_loss_step_pct - 1e-9)) : 1
    add(Math.min(2, n), n, c.trial_s)
  }
  if (c.tests.includes('back_to_back')) add(1, 8, c.b2b_max_s) // within 1 % of the burst: about 7 halvings
  return { min, max, tmin, tmax }
}

export function duration(t: Translate, secs: number): string {
  const s = Math.max(0, Math.round(secs))
  if (s < 60) return t('rfc2544.estimate.s', { s })
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return h ? t('rfc2544.estimate.hm', { h, m }) : t('rfc2544.estimate.m', { m: Math.max(1, m) })
}

/** hh:mm:ss for an elapsed time. */
export function clockSpan(secs: number): string {
  const s = Math.max(0, Math.floor(secs))
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`
}

/** A number with up to `digits` decimals, no trailing zeros; '–' when missing. */
export function num(v: unknown, digits = 2): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '–'
  return String(Number(v.toFixed(digits)))
}

/** Loss % with enough precision to show tiny losses. */
export function lossPct(v: unknown): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '–'
  if (v === 0) return '0'
  return v < 0.001 ? v.toExponential(1) : num(v, v < 1 ? 4 : 2)
}

export const dateTime = (ts: number) =>
  new Date(ts * 1000).toLocaleString([], { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })

export const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function testName(t: Translate, test: unknown): string {
  return TESTS.includes(test as Rfc2544Test) ? t(`rfc2544.tests.${test}`) : String(test)
}

/** Words a log entry from its code and params (backend Rfc2544Job.note). */
export function logText(t: Translate, e: Rfc2544Log): string {
  const p = e.params ?? {}
  const sep = t('rfc2544.log.listSep')
  const list = (v: unknown) => (Array.isArray(v) ? v.join(sep) : '')
  switch (e.code) {
    case 'start':
      return t('rfc2544.log.start', {
        directions: list(p.directions),
        sizes: list(p.sizes),
        tests: Array.isArray(p.tests) ? p.tests.map((x) => testName(t, x)).join(sep) : '',
      })
    case 'trial': {
      const common = {
        test: testName(t, p.test),
        size: p.size,
        loss: p.loss_pct == null ? '–' : `${lossPct(p.loss_pct)} %`,
        verdict: t(p.passed ? 'rfc2544.log.pass' : 'rfc2544.log.fail'),
      }
      return p.burst != null
        ? t('rfc2544.log.trialBurst', { ...common, burst: Number(p.burst).toLocaleString() })
        : t('rfc2544.log.trialRate', { ...common, rate: num(p.rate_pct, 3) })
    }
    case 'result':
      switch (p.test) {
        case 'throughput':
          return (
            t('rfc2544.log.resultThroughput', { size: p.size, rate: num(p.rate_pct, 3), mpps: num(p.mpps, 3) }) +
            (p.tx_limited ? t('rfc2544.log.limited') : '')
          )
        case 'latency':
          return t('rfc2544.log.resultLatency', { size: p.size, avg: num(p.avg_us, 1) })
        case 'frame_loss':
          return t('rfc2544.log.resultFrameLoss', { size: p.size, n: p.points })
        case 'back_to_back':
          return t('rfc2544.log.resultB2b', { size: p.size, frames: Number(p.frames).toLocaleString() })
      }
      return `${testName(t, p.test)} ${p.size ?? ''}`
    case 'done':
      return t('rfc2544.log.done')
    case 'stopped':
      return t('rfc2544.log.stopped')
    case 'error':
      return t('rfc2544.log.error', { error: p.error })
  }
  return String(e.code)
}

/** Save text as a file through a temporary link. */
export function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
