// Cross-host port pairs ("these two ports are wired together"), remembered per
// browser. One module-level ref, so the pairs table and the port map see the
// same list and update together.
import { persisted } from '../utils/prefs'

export interface PairEnd {
  host: string
  port: number
}
export interface PortPair {
  a: PairEnd
  b: PairEnd
}

const isEnd = (e: unknown): e is PairEnd => typeof (e as PairEnd)?.host === 'string' && Number.isFinite((e as PairEnd)?.port)

export const portPairs = persisted<PortPair[]>('overview.pairs', [])
// Hand-edited or older storage: keep only well-formed entries.
if (!Array.isArray(portPairs.value)) portPairs.value = []
portPairs.value = portPairs.value.filter((p) => isEnd(p?.a) && isEnd(p?.b))
