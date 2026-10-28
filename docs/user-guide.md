# 使用說明

[English](user-guide.en.md) | **繁體中文**

這份文件說明怎麼用 TRex GUI 打流、看統計和做測試。安裝與部署見 [deployment.md](deployment.md)，從原始碼建置見 [building.md](building.md)。

---

## 1. 基本概念

- **主機**：一台 TRex server。GUI 可以同時連好幾台，主機清單寫在後端的 `config.yaml`，畫面左側選擇。
- **取得（acquire）port**：TRex 的 port 同一時間只能有一個擁有者。要送流、改設定、擷取之前，必須先取得 port。所有 GUI 使用者共用設定檔裡的同一個 TRex username，所以 GUI 使用者之間沒有區隔；被 TRex console 或其他工具占用的 port 會顯示對方的名字。
- **Stream**：一種封包加上傳送方式（速率、連續或 burst）。GUI 把 stream 定義存在後端，按「開始」時才送到 TRex。
- **勾選 vs 選中**：左側 port 清單的**勾選框**決定工具列的批次操作（取得、開始、停止……）作用在哪些 port；**點選某一列**決定 Streams、Port 設定等分頁顯示哪個 port。
- **L2 / L3 模式**：L3 模式填本機 IP 和 gateway，TRex 用 ARP 解析出目的 MAC，**ARP 沒解析成功就不能送流**。L2 模式直接指定目的 MAC，例如兩個 port 直接對接時填對方 port 的 MAC。

---

## 2. 畫面配置

| 區塊 | 內容 |
|---|---|
| 頂端 | 「總覽與對應圖」、語言（繁中 / English）、外觀（淺色 / 深色 / 跟隨系統）。語言和外觀記在瀏覽器裡 |
| 左側 | TRex 主機清單（連線 / 中斷連線）、選中主機的 port 清單（link、速度、狀態、擁有者） |
| 主機頁上方 | 工具列：取得、強制取得、釋放、開始、停止、暫停、繼續、重設、速率倍數、送流時間；右上角是 session 匯出 / 匯入 |
| 主機頁分頁 | Streams、統計、監控、Profile、RFC 2544、PCAP、pg / Latency、Port 設定、Port 詳細 |

---

## 3. 第一次送流

1. 左側選主機，按「**連線**」。
2. 勾選要用的 port，按工具列「**取得**」。
   - port 被別人占用時，「強制取得」會中斷對方的測試，送出前會再確認一次。
3. 到「**Port 設定**」分頁確認模式：
   - L3：填本機 IPv4 和 gateway，畫面顯示「已解析」才能送流。
   - L2：填目的 MAC。
4. 點選一個 port，到「**Streams**」分頁按「＋ 新增 stream」，在編輯器裡設定封包和速率後儲存（見第 4 節）。
5. 回到工具列按「**開始**」。
   - **速率倍數**：空白是 1 倍，也可以寫 `2`（2 倍）、`50%`（線速一半）、`10kpps`、`1gbps`。
   - **送流時間**：填了就在幾秒後自動停止，空白代表一直送到按停止。
6. 到「**統計**」或「**監控**」分頁看速率。
7. 用完按「**停止**」，再按「**釋放**」。釋放時 GUI 會一併清掉它送到 TRex 上的 streams；GUI 裡存的 stream 定義不會刪除，下次取得後可以直接再送。

送流中的 port 改了 streams，要重新按「開始」才會生效。按「開始」時 port 若正在送流，會先確認再停止並重新開始。

「**重設**」會停止送流、清掉 TRex 上的 streams、清除這些 port 的統計並關閉 service mode，port 仍然保留在你手上。

---

## 4. Stream 編輯器

### 封包
- **協定層**：由上往下逐層加入。可以選的協定就是該版 TRex 內附 Scapy 的全部 layer，TRex v3.08 約 2600 個；常用的協定會排在前面。
- **欄位**：沒填的欄位交給 Scapy 自動計算，例如長度、checksum、上一層的 type 或 proto。
- **預覽**：右側即時顯示 hex 與解析結果。點 hex 裡的某個 byte 或解析樹的某個欄位，會跳到該欄位的編輯框。
- **不合理的 header 只警告、不阻擋**，方便刻意送錯誤封包做負面測試。例如層與層接不上、手動填的欄位和下一層矛盾、手動覆寫 len 或 chksum。
- **Frame 大小**：可以固定，也可以遞增、遞減或隨機變化。改變長度時，IP、IPv6、UDP 的長度欄位和 checksum 會自動修正。
- **Payload 填充**：在 Frame 大小下方，可選補 0、固定位元組、遞增 / 遞減位元組、隨機（固定種子）、重複文字、重複 hex。

### 欄位變化（field engine）
讓欄位逐封包變化：遞增、遞減或隨機，可以設定範圍和步進，也支援 VLAN ID、MPLS label 這類 bit 欄位。checksum 會自動重算。

TRex 會把一個 stream 分給多個核心送出，所以線路上的值不會嚴格照順序，但範圍內每個值送出的次數相同。例如 5 個值、送 100 個封包，每個值剛好 20 次。可變長度也是如此。

### 傳送
- **模式**：連續、單次 burst、多次 burst。
- **速率**：pps、bps（L1 或 L2）、線速百分比。
- **Flow 統計**：選「封包統計」或「Latency」並指定 pg_id，結果顯示在「pg / Latency」分頁。latency 的 pg_id 必須唯一，複製 stream 到其他 port 時 GUI 會自動換號。

### 送出封包
編輯器底部的「**送出封包…**」可以把目前編輯中的封包直接送出 N 次，並設定封包之間的間隔，不必先儲存。適合快速確認對端收不收得到。

### 範本
- **個人範本**：存在瀏覽器，只有自己看得到，可以匯出 / 匯入 JSON 帶到別台電腦。
- **共用範本**：存在後端，所有人、所有主機共用。
- **內建範本**：例如 IMIX（64 / 594 / 1518 bytes，比例 7:4:1）。

Streams 分頁的「**複製到其他 port…**」可以把整組 streams 複製到多個 port。

---

## 5. 送流中的控制

- **整個 port**：用工具列的暫停、繼續、調整速率。
- **單一 stream**：送流中，Streams 分頁的操作欄會出現「暫停」、「繼續」、「調速」按鈕，可以個別控制某一個 stream。
  - TRex 把這組功能標為暫時性。個別調速之後，若再用工具列調整整個 port 的速率，兩邊記錄的速率會不一致；需要準確速率時，請停止後重新開始。

---

## 6. 統計與監控

| 分頁 | 內容 |
|---|---|
| 統計 | 各 port 的 TX/RX 速率（pps、L1/L2 bps、使用率）、封包數、bytes、錯誤；可切換「Port 為欄 / 列」，可只看勾選的 port。「清除統計」會把計數歸零 |
| pg / Latency | 每個 pg_id 的 TX/RX、各 port 封包數、latency 平均 / 最小 / 最大 / jitter、序號檢查（丟失、亂序、重複）、latency 分布 |
| 監控 | 速率圖表（合計或各 port、bps/pps、1/5/15 分鐘，可切換成表格；點圖例可隱藏線條）和事件紀錄（GUI 操作含來源 IP、TRex 事件） |
| Port 詳細 | 每個 port 的 driver、速度、link、模式、目的、promiscuous、flow control |
| 總覽與對應圖 | 所有主機並排的總量與各 port 速率、跨主機 port 配對、port 對應圖（見第 9 節） |

**監控的成本**：每次查詢都由 TRex 的 master 執行緒處理。速率圖表和事件紀錄只用 GUI 本來就在收的資料，所以預設顯示。「**進階監控**」（每個核心的 CPU 與 mbuf、網卡 xstats）會多發請求給 TRex，所以預設關閉，開啟前請先看畫面上的警語。實測數據見 [bench/README.md](../bench/README.md)。

送流中按「清除統計」時，TX 和 RX 的歸零時間點不同步，會有少量誤差。要比對有沒有遺失，請在停止送流時清除。

---

## 7. Port 設定

- **L2 / L3**、VLAN（最多兩層 QinQ）、IPv6、promiscuous、multicast、flow control、link up/down。網卡不支援的項目不會顯示。
  - IPv6 需要 TRex 使用 `stack: linux_based`，預設的 legacy stack 會回「IPv6 is not supported with current stack」。
  - 有些網卡會接受 flow control 設定卻沒有真的套用（實測 X557 / ixgbe），這時畫面會提示「網卡沒有套用 flow control 設定」。
  - 使用 `stack: linux_based` 時，TRex 的 port 只在 service mode 才會回應 ARP；兩個 TRex port 互為 gateway 時，當作 gateway 的那個 port 要先開 service mode。
- **批次套用**：VLAN、IPv6 開關、promiscuous、multicast、flow control 可以一次套到其他勾選的 port。MAC、IP、gateway 每個 port 不同，所以不會批次套用。
- **Ping**：從 port 送 ping，確認路徑通不通。
- **設定檔**：把多個 port 的 L2/L3 設定整組存起來（存在後端、依主機分開），套用前會列出每個 port 會怎麼變。
  - TRex 重啟後 port 設定會回到 `trex_cfg.yaml` 的預設值。GUI 偵測到之後會提示是否重新套用上次的設定檔，不會自動套用。
  - 設定被 GUI 以外的方式改掉時（例如 TRex console），GUI 也會提示。
- **Namespace 節點**（頁面最下方）：在 port 後面模擬主機，可以設定 MAC、IPv4 + gateway、VLAN、IPv6、MTU。
  - TRex 的 `trex_cfg.yaml` 必須設定 `stack: linux_based`，沒有時畫面會說明怎麼改。
  - 節點只有在 port 處於 service mode 時才會回應 ARP。
  - 「過濾式 service mode」需要 TRex 以 `--software` 啟動。
  - 已知問題：實測節點會回應 ARP，但 ping 不通，原因還沒查出來。

---

## 8. PCAP 與 Python profile

### PCAP
- **檔案庫**：上傳 pcap / pcapng（pcapng 自動轉成 pcap，只支援 Ethernet），可以下載、改名、刪除。檔案庫存在後端、所有人共用。
- **重播**：可以照原本的封包間隔並加速，或用固定間隔；可以設定次數和時間上限，並選擇 MAC 用 pcap 裡的還是 port 的。重播是逐封包照時間送出，適合低到中速。
- **預覽 / 轉成 stream**：勾選封包轉成 stream，會拆成協定欄位，長度和 checksum 自動重算。要高速大量送時，用這個方式。
- **擷取**：可以擷取 TX、RX，或兩者都擷取，並設定上限與 BPF 過濾，停止後存進檔案庫。遠端主機也能擷取，封包會傳回執行 GUI 的那台。
  - 擷取的封包要經過 CPU，適合除錯，不適合線速錄製。
  - 要擷取 stream 送出或收到的流量，請勾選「Service mode」。勾選後，擷取期間 TX 和 RX port 都會進入 service mode，結束後恢復原本的模式。

### Python profile
「Profile」分頁列出伺服器上的兩個資料夾：TRex 自帶的範例（`<trex>/stl`）和共用資料夾（`data/profiles`）。profile 的參數會自動變成表單，選好 port、倍數和時間後按「開始」。

- profile 會取代該 port 在 TRex 上的 streams，但 Streams 分頁存的 streams 不受影響，之後按工具列「開始」會改回送那些 streams。
- profile 是 Python 程式，會在 GUI 後端執行。所以從網頁上傳預設關閉，請管理員用 SSH 把檔案放進 `data/profiles`。

---

## 9. 多主機：總覽、配對與對應圖

「**總覽與對應圖**」頁把所有主機並排顯示。這頁只用各主機原本的統計串流，不會多發請求。

- **跨主機 port 配對**：指定兩個實體上接在一起（或中間經過被測設備）的 port，就會比對「A 送出 vs B 收到」，顯示差值與遺失率。
  - 送流中的方向會標示為「送流中」，因為還在路上的封包會被算成差值。
  - 「清除相關主機的統計」可以一次清除兩端主機。
- **Port 對應圖**：依每個 port 的 L2 目的 MAC、L3 gateway 和跨主機配對，畫出 port 之間以及往外的連接。只有一台主機時也會顯示。
  - 主機很多時，圖會比頁面寬，可以在圖內左右捲動；「以表格顯示」可以改用表格看同樣的內容。

---

## 10. RFC 2544

「RFC 2544」分頁依 RFC 2544 量測被測設備（DUT）或回路的效能。

1. **測試設定**
   - 選 port 配對（TX → RX，可勾選雙向）。
   - 選封包大小，預設 64 / 128 / 256 / 512 / 1024 / 1280 / 1518，也可以自訂 64–9216。
   - 勾選測試項目：
     - **吞吐量**：二分搜尋遺失不超過可接受值的最高速率。
     - **延遲**：在吞吐量的速率下量測延遲。
     - **封包遺失率**：從最高速率逐步降低，記錄每個速率的遺失率。
     - **背對背**：找出不遺失的最長連續封包數。
   - 設定每次試驗時間、解析度、最高速率、可接受遺失。畫面會預估總時間；全部項目都跑可能需要數小時。
2. **執行狀態**：顯示目前的試驗與進度，可以中途停止。測試期間，用到的 port 不能被其他操作拿去送流。
3. **結果**：每種封包大小的吞吐量（線速 % / Mpps / Gbps）、延遲、遺失率曲線、背對背長度，可以匯出 JSON / CSV。
4. **歷史紀錄**：每次測試都存在後端，可以回頭查看或刪除。

注意事項：
- **遺失的計算**用網卡硬體的 port 計數器，所以測試期間這些 port 上不要有其他流量。
- **吞吐量依「實際送出」的速率判定**。TRex 本身送不到要求的速率時，結果會標示「受限於 TRex」，代表瓶頸在測試設備，不在 DUT。
- **loopback 測試**（兩個 TRex port 直接對接）時，結果包含 TRex 接收端本身的極限。例如實驗室主機雙向 64B 只量到約 53%，原因是 TRex 每個 port 超過約 27 Mpps 就收不完；512B 和 1518B 都是 100%。

---

## 11. Session 匯出 / 匯入

主機頁右上角的「**匯出 session**」會把整台主機各 port 的 streams、port 設定和 port 設定檔存成一個 JSON 檔。

「**匯入 session…**」可以把每個 port 對應到不同的 port 或另一台主機，並選擇要匯入哪些內容：
- 取代 streams。
- 套用 port 設定。只會套用到已取得的 port；匯到不同號碼的 port 時預設不勾，以免帶入別的 port 的 IP。
- 加入 port 設定檔。同名的會略過。

---

## 12. 資料存在哪裡

| 資料 | 位置 | 誰看得到 |
|---|---|---|
| Stream 定義 | 後端 `data/<主機>/port-<n>.json` | 所有人 |
| 共用範本 | 後端 `data/templates.json` | 所有人、所有主機 |
| PCAP 檔案庫 | 後端 `data/pcaps/` | 所有人 |
| Port 設定檔 | 後端 `data/<主機>/port-profiles.json` | 所有人 |
| RFC 2544 結果 | 後端 `data/<主機>/rfc2544/` | 所有人 |
| 共用 Python profile | 後端 `data/profiles/` | 所有人 |
| 個人範本、語言、外觀、勾選、分頁、排版、未儲存的草稿 | 瀏覽器 localStorage | 只有自己，清掉瀏覽器資料就會重置 |
| 事件紀錄 | 後端記憶體（最近幾百筆） | 所有人，後端重啟會清空 |
| 速率圖表的歷史 | 瀏覽器分頁記憶體 | 只有自己，重新整理就會清空 |

`data/` 的位置可以用 `config.yaml` 的 `server.data_dir` 修改，預設是設定檔旁邊的 `data/`。備份時備份這個資料夾即可。

---

## 13. 常見問題

| 現象 | 原因與處理 |
|---|---|
| 按「開始」沒反應或顯示 ARP 未解析 | L3 模式的 gateway 沒有回應 ARP。確認接線與 gateway，或在 Port 設定按「重新解析」；直接對接時改用 L2 模式 |
| 按鈕是灰的 | 還沒取得 port，或 port 正在送流（L2/L3 設定要停止後才能改） |
| 擷取不到 stream 的封包 | 擷取時要勾選「Service mode」 |
| 統計的 RX 比 TX 少一點 | 送流中清除統計造成的誤差，或封包還在路上。請停止送流後再比對 |
| pg / Latency 沒資料 | stream 的「傳送」設定裡沒有開啟封包統計或 Latency |
| pg / Latency 只有 TX，RX 一直是 0，但 port 的 RX 計數正常 | 部分網卡上 TRex 不計算 flow 統計與 latency 的接收（實測 e300 的 X557 / ixgbe，用 TRex 自己的 client 也一樣）。請改用 port 計數比對 |
| 畫面顯示未連線 | TRex 沒在執行，或 GUI 後端連不到 TCP 4501 / 4500。畫面上會顯示原因 |
| Namespace 顯示需要 `stack: linux_based` | 需要修改 TRex 的 `trex_cfg.yaml` 並重啟 TRex，這會影響所有使用者，請先和管理員確認 |

**目前沒有登入機制**，任何連得到 GUI 的人都能控制打流，請只在隔離的實驗室網段開放（見 [deployment.md](deployment.md) 第 5 節）。
