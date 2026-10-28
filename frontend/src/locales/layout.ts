// App shell: header, host list, host panel.
const zh = {
  backendUnreachable: '無法連到後端：{error}',
  expandHosts: '展開主機列表',
  collapseHosts: '收合主機列表',
  noHost: '在 config.yaml 設定 TRex 主機後，從左側選擇',
  hosts: 'TRex 主機',
  connected: '已連線',
  connectFailed: '連線失敗',
  notConnected: '未連線',
  connect: '連線',
  disconnect: '中斷連線',
  tabStats: '統計',
  tabPortConfig: 'Port 設定',
  tabPortDetails: 'Port 詳細',
  theme: {
    label: '外觀',
    system: '跟隨系統',
    light: '淺色',
    dark: '深色',
  },
}

const en: typeof zh = {
  backendUnreachable: 'Cannot reach the backend: {error}',
  expandHosts: 'Show host list',
  collapseHosts: 'Hide host list',
  noHost: 'Add TRex hosts in config.yaml, then pick one on the left',
  hosts: 'TRex hosts',
  connected: 'Connected',
  connectFailed: 'Connection failed',
  notConnected: 'Not connected',
  connect: 'Connect',
  disconnect: 'Disconnect',
  tabStats: 'Stats',
  tabPortConfig: 'Port settings',
  tabPortDetails: 'Port details',
  theme: {
    label: 'Appearance',
    system: 'System',
    light: 'Light',
    dark: 'Dark',
  },
}

export default { zh, en }
