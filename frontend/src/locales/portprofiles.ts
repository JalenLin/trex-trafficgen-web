// zh-TW is the source; en must have exactly the same keys (checked by `typeof zh`).
// "Port profile" = a saved set of L2/L3 port settings (not the Python profile).
const zh = {
  // PortProfiles
  title: '設定檔',
  intro:
    '整組保存 port 的 L2/L3 設定（不含 link），存在後端、這台 TRex 專用，所有人共用。TRex 重啟後設定會回到 trex_cfg.yaml 的預設值，可以用這裡重新套用。',
  optionLabel: '{name}（Port {ports}）',
  choose: '選擇設定檔',
  applyEllipsis: '套用…',
  saveFrom: '把 Port {ports} 存成設定檔…',
  manage: '管理…',
  saveTitle: '存成設定檔',
  namePlaceholder: '例如：R4 測試、Loopback',
  saveHint: '存的是這些 port 現在的設定。要存其他 port，先在左邊勾選。',
  saved: '已存成設定檔「{name}」',
  manageTitle: 'Port 設定檔',
  empty: '還沒有設定檔',
  portSummary: 'P{id}：{summary}',
  summarySep: '；',
  renamed: '已改名',
  deleted: '已刪除',
  confirmDelete: '刪除設定檔「{name}」？所有人都會看不到。',

  // ApplyProfileDialog
  dialogTitle: '套用設定檔「{name}」',
  status: {
    missing: '這台沒有此 port',
    same: '已經相同',
    notMine: '未取得',
    notMineOwned: '未取得（{owner} 使用中）',
    busy: '送流中',
    ready: '會套用',
  },
  busyHint: '送流中的 port 要先停止才能改 L2/L3 設定，會略過。',
  acquireFirst: '先取得 Port {ports}',
  applyToN: '套用到 {n} 個 port',
  allSame: '設定都相同，記錄為目前的設定檔',
  nothingToApply: '沒有可以套用的 port',
  applied: '已套用設定檔「{name}」',
  recorded: '已記錄「{name}」為目前的設定檔',

  // PortDriftBanner
  restartedTitle: 'TRex 重新啟動過，port 設定已回到預設值',
  driftTitle: 'Port 設定和上次套用的設定檔不同',
  restartedBody:
    'TRex 在 {time} 重新啟動，Port {ports} 的設定回到 trex_cfg.yaml 的預設值，和上次套用的設定檔「{name}」不同。',
  driftBody: 'Port {ports} 的設定和上次套用的設定檔「{name}」不同，可能被其他人或其他工具（例如 TRex console）改過。',
  reapply: '重新套用「{name}」…',
  ignore: '忽略',
}

const en: typeof zh = {
  title: 'Port profiles',
  intro:
    "Saves a whole set of ports' L2/L3 settings (link state excluded) on the backend, for this TRex only and shared with everyone. After a TRex restart, ports go back to the defaults in trex_cfg.yaml; re-apply a profile from here.",
  optionLabel: '{name} (Port {ports})',
  choose: 'Choose a port profile',
  applyEllipsis: 'Apply…',
  saveFrom: 'Save port {ports} as a port profile…',
  manage: 'Manage…',
  saveTitle: 'Save as port profile',
  namePlaceholder: 'e.g. R4 test, Loopback',
  saveHint: "Saves these ports' current settings. To save other ports, select them on the left first.",
  saved: 'Saved as port profile "{name}"',
  manageTitle: 'Port profiles',
  empty: 'No port profiles yet',
  portSummary: 'P{id}: {summary}',
  summarySep: '; ',
  renamed: 'Renamed',
  deleted: 'Deleted',
  confirmDelete: 'Delete port profile "{name}"? It will be gone for everyone.',

  dialogTitle: 'Apply port profile "{name}"',
  status: {
    missing: 'No such port on this host',
    same: 'Already matches',
    notMine: 'Not acquired',
    notMineOwned: 'Not acquired (in use by {owner})',
    busy: 'Transmitting',
    ready: 'Will apply',
  },
  busyHint: 'Transmitting ports must be stopped before their L2/L3 settings can change; they will be skipped.',
  acquireFirst: 'Acquire port {ports} first',
  applyToN: 'Apply to {n} port | Apply to {n} ports',
  allSame: 'All settings match; record as the current port profile',
  nothingToApply: 'No ports to apply to',
  applied: 'Applied port profile "{name}"',
  recorded: 'Recorded "{name}" as the current port profile',

  restartedTitle: 'TRex restarted; port settings are back to defaults',
  driftTitle: 'Port settings differ from the last applied port profile',
  restartedBody:
    'TRex restarted at {time}. Port {ports} went back to the defaults in trex_cfg.yaml and no longer match the last applied port profile "{name}".',
  driftBody:
    'Port {ports} settings differ from the last applied port profile "{name}"; someone else or another tool (e.g. the TRex console) may have changed them.',
  reapply: 'Re-apply "{name}"…',
  ignore: 'Ignore',
}

export default { zh, en }
