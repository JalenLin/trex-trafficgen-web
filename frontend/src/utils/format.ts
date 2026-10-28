const SI = ['', 'K', 'M', 'G', 'T']

function si(value: number, unit: string, digits = 2): string {
  let v = Math.abs(value)
  let i = 0
  while (v >= 1000 && i < SI.length - 1) {
    v /= 1000
    i++
  }
  return `${(Math.sign(value) * v).toFixed(i === 0 ? 0 : digits)} ${SI[i]}${unit}`
}

export const formatBps = (v: number) => si(v, 'bps')
export const formatPps = (v: number) => si(v, 'pps')
export const formatBytes = (v: number) => si(v, 'B')
export const formatCount = (v: number) => Math.round(v).toLocaleString()
export const formatPercent = (v: number) => `${v.toFixed(1)} %`
