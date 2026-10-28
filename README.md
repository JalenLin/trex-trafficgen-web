# TRex GUI

[English](README.en.md) | **繁體中文**

Cisco TRex（stateless 模式）的 Web 介面，用來取代已無法連上新版 TRex 的 [trex-stateless-gui](https://github.com/cisco-system-traffic-generator/trex-stateless-gui)。

## 文件

| 文件 | 內容 |
|---|---|
| [使用說明](docs/user-guide.md) | 介面操作：送流、stream 編輯器、統計與監控、port 設定、PCAP、多主機總覽、RFC 2544、session 匯出入 |
| [建置方式](docs/building.md) | 開發環境、建置前端、打包離線安裝包、程式結構、新增功能的流程 |
| [部署說明](docs/deployment.md) | 安裝到 TRex 主機、CPU 綁定、開放連線、日常操作、疑難排解 |
| [效能測試](bench/README.md) | GUI 與各種監控對打流的影響實測 |

## 架構

```
瀏覽器 (Vue 3 + Naive UI)
   │  HTTP / WebSocket
後端 (FastAPI)  ── 每台 TRex 主機一個 worker 子程序
   │                └ import 該 TRex 版本隨附的官方 Python client
TRex server (ZMQ 4501 RPC / 4500 async)
```

- **不自己實作 TRex 協定**：每個 TRex 版本都隨附官方 client，worker 直接 import 那一份，所以 server 升級後協定一定對得上。舊 GUI 就是因為手刻 JSON-RPC，API 從 4.x 改到 5.x 後才完全連不上。
- **每台主機一個子程序**：同一個 Python 程序沒辦法同時載入不同版本的 client，分開程序就能同時連不同版本的 TRex。
- **統計共用輪詢**：每台主機的統計只會被輪詢一次，再分送給所有開著的瀏覽器，因為每次 RPC 都會打到 TRex 的 master thread。port 的狀態和擁有者也跟著統計一起推送，資料來自 TRex client 的非同步事件，不會多打 RPC。
- **協定清單不寫死**：TRex 的封包產生器直接吃 Scapy 封包，所以「TRex 支援的 header」就是該版 TRex 內附 Scapy 的所有 layer（core 加 contrib）。worker 從那份 Scapy 讀出每個協定的欄位定義，前端自動產生編輯表單。TRex v3.08 約 2600 個協定。
- **Stream 定義由 GUI 保存**：TRex 只存編譯後的 stream，沒辦法還原成可編輯的分層欄位，所以 GUI 自己用 JSON 保存（`data/<主機>/port-<n>.json`），按「開始」時才送到 TRex。範本存在 `data/templates.json`，pcap 存在 `data/pcaps/`，port 設定檔存在 `data/<主機>/port-profiles.json`。
- **什麼存在哪裡**：需要共用、不能遺失的（stream、共用範本）存在後端；個人範本也存在瀏覽器；個人習慣（勾選、排版、最近用過的值、未儲存的草稿）存在瀏覽器 localStorage，清掉瀏覽器資料就會重置，不影響別人。
- **Header 檢查依 Scapy 的綁定表**：判斷「B 能不能接在 A 後面」用的是 Scapy 自動填 type/proto 的同一份資料（`bind_layers`），所以對所有協定都有效，不用逐一寫規則。
- **Python profile 在後端執行**：TRex 的 `.py` profile 是程式，不是資料，載入時 worker 會執行它，再把產生的 streams 送到 TRex。GUI 只列出伺服器上的兩個資料夾：TRex 自帶的 `<trex>/stl`（由 `client_path` 推算，`client_path` 指向 TRex 安裝目錄時才找得到）和 `data/profiles`。profile 的參數（argparse 或 `get_streams` 的關鍵字參數）會自動變成表單。
- **監控不能本末倒置**：每個 RPC 都由 TRex 的 master 執行緒處理。已實測過各種監控的成本（[bench/README.md](bench/README.md)）：不會多打 RPC 的速率圖表和事件紀錄預設顯示；每核心 CPU/mbuf 與 xstats 會多打 RPC，所以預設關閉，由使用者在「監控」分頁開啟，並附上實測數據的警語。`server.stats_interval` 最小 0.5 秒。
- **多國語系**：介面有繁體中文和 English，右上角切換，選擇記在瀏覽器裡；第一次開啟時依瀏覽器語言決定。文字都在 `frontend/src/locales/<區域>.ts`，同一個檔案裡並列兩種語言，英文缺 key 時型別檢查就會失敗。後端的檢查警告送出代碼與參數，由前端依語言組成句子；TRex 本身回傳的錯誤與事件維持原文（英文）。
- **後端位置可選**：可以裝在每台 TRex 主機上，讓使用者用瀏覽器直接連；也可以裝在另一台機器。裝在 TRex 主機上時**必須**用 `server.cpu_affinity` 把後端綁在 TRex 不打流的 CPU，否則會影響打流的 latency。詳見 [部署說明](docs/deployment.md)。

## 快速開始

```bash
# 後端
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[mock]'   # [mock]：mock 主機用 pip 的 Scapy 組封包

# 前端
cd ../frontend
npm install
npm run build

# 設定並啟動
cd ..
cp config.example.yaml config.yaml   # 預設有一台 mock 主機，不用 TRex 也能試
backend/.venv/bin/python -m trex_gui -c config.yaml
```

開啟 http://127.0.0.1:8080 。

## 部署到 TRex 主機

用離線安裝包安裝，不需要 pip、網路或 sudo，安裝腳本會自動設定 CPU 綁定：

```bash
deploy/make-bundle.sh 3.12      # 在開發機打包，參數是 TRex 主機的 python3 版本
# 把 dist/ 底下的 tar.gz 複製到 TRex 主機，解開後執行 ./install.sh
```

完整步驟、怎麼選 CPU、怎麼驗證，見 [docs/deployment.md](docs/deployment.md)。

## 連真的 TRex

在 `config.yaml` 加一台主機，`client_path` 指向**與 server 同版本**的 client：

```yaml
hosts:
  - id: lab-a
    name: Lab A
    server: 192.0.2.10
    client_path: /opt/trex/v3.06/automation/trex_control_plane/interactive
```

- **後端跟 TRex 在不同台機器時**：把 TRex 安裝目錄下的 `automation/trex_control_plane/interactive` 和 `external_libs` 一起複製過來，保持相對位置（`external_libs` 在 `interactive` 往上三層），或用 `ext_libs_path` 另外指定。
- **TRex 升級時**：重新複製一次，或直接改路徑。
- **防火牆**：後端機器要能連到 TRex 主機的 TCP 4501 和 4500。

## 開發

```bash
backend/.venv/bin/python -m trex_gui -c config.yaml   # 後端 :8080
cd frontend && npm run dev                            # 前端 :5173，/api 會轉到後端
```

程式結構、建置、打包和新增功能的流程見 [建置方式](docs/building.md)。

## 安全性

目前**沒有登入機制**，所有使用者共用同一個 TRex username（設定檔的 `username`）。因為 Python profile 會在後端執行，從網頁上傳 profile 預設關閉（`server.allow_profile_upload`），請管理員用 SSH 把檔案放進 `data/profiles`。預設只綁定 `127.0.0.1`。在隔離的實驗室網段可以改成 `0.0.0.0` 直接開放（TRex 自己的 RPC port 本來就沒有驗證）；網段不夠隔離時請用 SSH tunnel。詳見 [部署說明](docs/deployment.md) 第 5 節。

## 狀態

- [x] 多主機、連線與中斷
- [x] Port 列表、取得與釋放（含強制取得）
- [x] 即時統計（WebSocket）、清除統計
- [x] 部署到 TRex 主機：CPU 綁定、離線安裝包、systemd 服務
- [x] Stream 編輯器：TRex 支援的所有協定、欄位表單、hex 與解析預覽
- [x] 欄位變化：遞增、遞減、隨機，支援 bit 欄位（VLAN ID、MPLS label 等），自動修正 checksum
- [x] 傳送模式：連續、單次 burst、多次 burst；速率 pps、bps、線速百分比；flow 統計與 latency 的 pg_id 設定
- [x] 多 port：勾選批次取得、開始、停止、暫停、繼續、調整速率；stream 複製到多個 port；統計可切換 port 為列
- [x] pg_id / latency 統計：每個 pg 的 TX/RX、各 port 封包數、latency 平均/最小/最大/jitter、序號檢查、latency 分布
- [x] Port 設定：L2（目的 MAC）/ L3（IPv4 + gateway，ARP 解析）、VLAN / QinQ、IPv6、promiscuous、multicast、ping
- [x] 釋放 port 時，一併清掉 GUI 送到 TRex 上的 streams
- [x] 不合理 header 檢查（只警告、不阻擋，方便刻意送錯誤封包做負面測試）：層與層接不上、手動欄位和下一層矛盾、手動覆寫 len/chksum、frame 大小、flow 統計與 latency 的 TRex 限制
- [x] Stream 範本庫，分兩種：個人範本（存在瀏覽器，只有自己看得到，可匯出/匯入 JSON 帶到別台電腦）和共用範本（存在後端，所有人、所有 TRex 主機共用）；兩邊可以互相複製
- [x] 記住使用習慣（瀏覽器 localStorage，各人分開）：上次的主機、勾選和選中的 port、分頁、統計排版、速率倍數紀錄、最近用過的協定、ping 目標、未儲存的編輯草稿
- [x] Port 設定批次套用：VLAN、IPv6 開關、promiscuous、multicast、flow control 可一次套到多個勾選的 port
- [x] Link up/down、flow control（網卡支援時才顯示）
- [x] Port 設定檔：整組保存多個 port 的 L2/L3 設定（存在後端、依 TRex 主機分開），套用前先列出每個 port 會怎麼變
- [x] 偵測 TRex 重啟或 port 設定被 GUI 以外的方式改掉，提示是否重新套用上次的設定檔（不會自動套用）
- [x] TRex 斷線或 worker 程序結束時，畫面顯示為未連線並說明原因
- [x] PCAP：檔案庫（上傳 pcap/pcapng、下載、改名）、重播（原始間隔加速 / 固定間隔、次數、時間上限、MAC 來源）、預覽與轉成 stream（完整還原原封包）、擷取 TX/RX 存進檔案庫
- [x] 可變封包長度：固定、遞增、遞減、隨機，IP / IPv6 / UDP 長度欄位與 checksum 自動修正；內建 IMIX（64/594/1518，7:4:1）範本
- [x] 送流時間（送幾秒後自動停止）、重設（停止、清掉 TRex 上的 streams 與 port 統計、關閉 service mode，port 仍保留在手上）
- [x] TRex Python profile：列出 TRex 自帶範例與共用資料夾、參數表單、依 port 載入並送流（倍數、時間）
- [x] 監控分頁：速率圖表（TX/RX 合計或各 port、bps/pps、1/5/15 分鐘、可切換表格）與事件紀錄（GUI 操作含來源 IP、TRex 事件），兩者都不增加 TRex 負擔
- [x] 進階監控（預設關閉、附警語）：每個資料平面核心的使用率、mbuf 用量、網卡 xstats（含每秒變化）
- [x] 多國語系：繁體中文、English
- [x] 外觀：淺色 / 深色 / 跟隨系統（右上角切換，記在瀏覽器）
- [x] 多主機總覽：所有主機並排（總量、各 port 速率、速率圖），以及跨主機 port 配對（A 送出 vs B 收到、差值、遺失率，送流中標示為「送流中」）
- [x] 擷取封包可用於遠端主機（封包經 RPC 傳回，存進執行 GUI 那台的檔案庫）；勾選 service mode 時 TX 與 RX port 都會進入 service mode，才擷取得到 stream 送出的流量
- [x] 單一 stream 控制：送流中可個別暫停、繼續、調整速率（TRex 標為暫時性功能，畫面上有說明）
- [x] Payload 填充樣式：補 0、固定位元組、遞增/遞減、隨機（固定種子）、重複文字、重複 hex
- [x] 單封包送出：在 stream 編輯器直接把目前的封包送出 N 次（不需先儲存）
- [x] Port 對應圖：依 L2 目的 MAC、L3 gateway 與跨主機配對畫出 port 之間與對外的連接
- [x] Session 匯出/匯入：整台主機各 port 的 streams、port 設定與 port 設定檔，一個 JSON 檔；匯入可改對應到其他 port 或其他主機
- [x] Namespace 節點：在 port 後面模擬主機（需要 TRex 設定 `stack: linux_based`，沒有時畫面會說明）
- [x] RFC 2544：吞吐量、latency、frame loss、back-to-back，結果圖表、歷史紀錄、匯出 JSON/CSV；吞吐量以實際送出的負載判定，TRex 本身送不到要求速率時會標示
- [ ] 使用者登入（暫不做）

## 授權

Copyright 2026 Jalen Lin。以 [Apache License 2.0](LICENSE) 授權發布。

本專案與 Cisco 無關，TRex 是 Cisco 的開源專案。執行時使用的 TRex Python client 和它內附的 Scapy 不包含在本專案或離線安裝包裡，各自依其授權使用。
