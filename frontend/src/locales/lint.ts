// Backend check warnings, by code (backend/trex_gui/packets.py `_w(...)`), plus pcap import notes.
const zh = {
  afterRaw: '{prev} 是原始資料，後面的 {next} 只會被當成資料的一部分',
  unusualNext: '{next} 通常不會接在 {prev} 後面，Scapy 無法自動填入下一層的類型',
  unusualNextHint: '{next} 通常不會接在 {prev} 後面，Scapy 無法自動填入下一層的類型（目前 {hint}）',
  dispatchField: '{name} 手動填了 {value}，但下一層是 {next}，標準值是 {std}',
  dispatchPort: '{name} 手動填了 {value}，但下一層是 {next}，標準值是 {std}；接收端可能不會把它當成 {next} 解析',
  autoField: '{name} 是自動計算的欄位，手動填寫會產生不合法的封包（刻意的負面測試可忽略）',
  sizeGrid: '依間隔實際會送 {count} 種長度：{first}、{second} … {last} bytes',
  contentOverSize: '封包內容已有 {content} bytes（含 FCS），比設定的 frame 大小 {size} 還大，設定被忽略',
  belowMinFrame: '封包最小 {size} bytes（含 FCS），低於乙太網路最小的 {min} bytes，可能被補齊或丟棄',
  jumbo: '封包最大 {size} bytes 超過標準乙太網路的 {max} bytes，路徑上的設備都要支援 jumbo frame',
  innerUdpChecksum:
    '長度變動時只會修正最外層的 UDP checksum；內層（隧道裡）的 UDP checksum 會不正確，接收端會檢查的話，可以把內層 UDP 的 chksum 填 0（IPv4 允許不帶 checksum）',
  latencyNeedsIp: 'Latency 需要 IPv4 或 IPv6（只能先經過 Ethernet、VLAN、MPLS），否則開始送流時 TRex 會拒絕',
  flowNeedsIp: '封包統計需要 IPv4 或 IPv6（只能先經過 Ethernet、VLAN、MPLS），否則開始送流時 TRex 會拒絕',
  latencyNicSupport: 'Latency 遇到 {tags} 時需要網卡支援，不支援時開始送流會失敗',
  flowNicSupport: '封包統計遇到 {tags} 時需要網卡支援，不支援時開始送流會失敗',
  latencyMinVarying: 'Latency 搭配變動長度時，最小 frame 至少要 {min} bytes，否則開始送流時 TRex 會拒絕',
  latencyPayload:
    'Latency 需要 {after} 之後至少 {need_payload} bytes 資料，目前只有 {payload} bytes；frame 大小至少要 {need} bytes，否則開始送流時 TRex 會拒絕',
  pcapKeptAuto: '長度或 checksum 欄位保留了 pcap 裡的原值（重新計算會和原封包不同）',
  pcapRawOnly: '無法拆成協定欄位，以原始 bytes 匯入',
}

const en: typeof zh = {
  afterRaw: '{prev} is raw data; {next} after it is just more data',
  unusualNext: "{next} doesn't normally follow {prev}; Scapy can't fill in the next-layer type",
  unusualNextHint: "{next} doesn't normally follow {prev}; Scapy can't fill in the next-layer type (now {hint})",
  dispatchField: '{name} is set to {value} but the next layer is {next}; the standard value is {std}',
  dispatchPort:
    "{name} is set to {value} but the next layer is {next}; the standard value is {std}. The receiver may not parse it as {next}",
  autoField: '{name} is computed automatically; a manual value makes an invalid packet (fine for deliberate negative tests)',
  sizeGrid: 'With this step {count} sizes are sent: {first}, {second} … {last} bytes',
  contentOverSize: 'The packet content is already {content} bytes (with FCS), more than the frame size {size}; the setting is ignored',
  belowMinFrame: "Smallest frame is {size} bytes (with FCS), below Ethernet's minimum of {min}; it may be padded or dropped",
  jumbo: "Largest frame is {size} bytes, over standard Ethernet's {max}; every device on the path must support jumbo frames",
  innerUdpChecksum:
    'With a varying size only the outermost UDP checksum is fixed; inner (tunnelled) UDP checksums will be wrong. If the receiver checks them, set the inner UDP chksum to 0 (allowed over IPv4)',
  latencyNeedsIp: 'Latency needs IPv4 or IPv6 (with only Ethernet, VLAN or MPLS before it), or TRex rejects the start',
  flowNeedsIp: 'Flow stats need IPv4 or IPv6 (with only Ethernet, VLAN or MPLS before it), or TRex rejects the start',
  latencyNicSupport: 'Latency through {tags} needs NIC support; without it starting traffic fails',
  flowNicSupport: 'Flow stats through {tags} need NIC support; without it starting traffic fails',
  latencyMinVarying: 'Latency with a varying size needs a minimum frame of at least {min} bytes, or TRex rejects the start',
  latencyPayload:
    'Latency needs at least {need_payload} bytes of data after {after}, there are {payload}; the frame must be at least {need} bytes, or TRex rejects the start',
  pcapKeptAuto: 'Length/checksum fields keep the values from the pcap (recomputing them would differ from the capture)',
  pcapRawOnly: 'Could not split into protocol fields; imported as raw bytes',
}

export default { zh, en }
