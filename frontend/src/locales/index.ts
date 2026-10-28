// One module per area of the UI; each holds both languages side by side so a
// missing English string is a type error, not a blank label.
// Keys are used as t('<module>.<key>'), e.g. t('streams.addStream').
//
// vue-i18n message syntax: {name} interpolates; a literal { } @ $ or | must be
// written as {'{'} {'}'} {'@'} {'$'} {'|'} (| separates plural forms).
import common from './common'
import layout from './layout'
import lint from './lint'
import monitor from './monitor'
import ns from './ns'
import overview from './overview'
import pcap from './pcap'
import portmap from './portmap'
import portprofiles from './portprofiles'
import ports from './ports'
import pyprofile from './pyprofile'
import rfc2544 from './rfc2544'
import session from './session'
import stats from './stats'
import streams from './streams'
import toolbar from './toolbar'

const modules = {
  common, layout, lint, monitor, ns, overview, pcap, portmap, portprofiles, ports, pyprofile, rfc2544, session, stats, streams, toolbar,
}

export type Lang = 'zh-TW' | 'en'

type Messages = { [K in keyof typeof modules]: (typeof modules)[K]['zh'] }

function pick(lang: 'zh' | 'en'): Messages {
  return Object.fromEntries(Object.entries(modules).map(([k, m]) => [k, m[lang]])) as Messages
}

export const messages: Record<Lang, Messages> = { 'zh-TW': pick('zh'), en: pick('en') }
