# 建置方式

[English](building.en.md) | **繁體中文**

這份文件說明怎麼從原始碼建立開發環境、建置前端、打包離線安裝包，以及新增功能的流程。部署到 TRex 主機見 [deployment.md](deployment.md)，操作方式見 [user-guide.md](user-guide.md)。

---

## 1. 需要的工具

| 工具 | 版本 | 用途 |
|---|---|---|
| Python | 3.10 以上，開發機用 3.12 | 後端 |
| Node.js + npm | 22 以上 | 建置前端；TRex 主機上不需要 |
| TRex | 選用 | 連真的 TRex 時才需要，沒有時可以用 mock 主機 |

後端執行時只依賴 FastAPI、uvicorn、PyYAML。TRex 的 Python client 和它內附的 Scapy、ZMQ 不用安裝，worker 會直接 import 設定檔 `client_path` 指向的那一份。

---

## 2. 開發環境

```bash
# 後端
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[mock]'   # [mock]：mock 主機用 pip 的 Scapy 組封包

# 前端
cd ../frontend
npm install

# 設定檔
cd ..
cp config.example.yaml config.yaml   # 預設有一台 mock 主機，不需要 TRex
```

`config.yaml` 和 `data/` 不進版本控制（見 `.gitignore`），每台機器各自保留。

### 開發模式

開兩個終端機：

```bash
backend/.venv/bin/python -m trex_gui -c config.yaml   # 後端 http://127.0.0.1:8080
cd frontend && npm run dev                            # 前端 http://127.0.0.1:5173
```

開 http://127.0.0.1:5173 。Vite 會把 `/api`（含 WebSocket）轉到後端，前端改了會自動重新載入；後端改了要重啟。後端不在 8080 時，用環境變數指定：

```bash
TREX_GUI_BACKEND=http://127.0.0.1:8096 npm run dev
```

### Mock 主機

mock 主機（`mock: true`）模擬一台 TRex，介面和真的 worker 相同，不需要 TRex 也能開發和展示：

- **port**：數量由 `mock_ports` 決定。port 0/1 是 L2 對接，模擬「被其他人占用、正在送流」；其餘 port 是 L3，gateway 會回應 ARP。
- **流量與統計**：送出的流量經過一台假的被測設備，線速 85% 以下不遺失，超過的部分會遺失。統計依時間累積。
- **其他功能**：namespace 節點、擷取、RFC 2544 都可以操作。

要測多台主機時，在設定檔裡多加幾台 mock 主機即可，每台的 MAC 不同。

```yaml
hosts:
  - {id: lab-a, name: Lab A, mock: true, mock_ports: 2}
  - {id: big, name: Big Box, mock: true, mock_ports: 16}
```

### 連真的 TRex 開發

在 `config.yaml` 加一台主機，`client_path` 指向**與 server 同版本**的 `automation/trex_control_plane/interactive`。開發機和 TRex 不在同一台時，把該目錄和 `external_libs` 一起複製過來，保持相對位置。後端要能連到 TRex 主機的 TCP 4501 / 4500。

---

## 3. 建置

### 前端

```bash
cd frontend
npm run build                     # 型別檢查（vue-tsc）+ 建置到 frontend/dist/
npx tsx scripts/check-i18n.ts     # 檢查所有介面文字的語法、繁中與英文的 key 是否一致
```

- `npm run build` 的型別檢查會擋下「英文少了某個 key」。
- `check-i18n.ts` 另外會擋下訊息語法錯誤，例如文字裡直接寫了 `{`、`@`、`|`。這類錯誤型別檢查抓不到，只會在執行時出錯。

後端預設從 `frontend/dist/` 提供網頁，所以建置完重新整理瀏覽器就是新版，不需要重啟後端。

### 後端

後端是純 Python，不需要建置。`pip install -e` 是可編輯安裝，改了程式碼重啟就生效。

---

## 4. 打包離線安裝包

TRex 主機常常沒有 pip、沒有網路，所以在開發機打包、拿到 TRex 主機離線安裝：

```bash
deploy/make-bundle.sh 3.12            # 參數：TRex 主機的 python3 版本，預設 3.12
deploy/make-bundle.sh 3.10 x86_64     # 第二個參數是 CPU 架構，預設 x86_64
```

產物是 `dist/trex-gui-<版本>-py<python版本>-<架構>.tar.gz`，版本號取自 `backend/pyproject.toml`。

腳本會做這些事：
1. 建置前端（`npm run build`）。
2. 下載對應 Python 版本與架構的相依 wheel，部分套件是編譯過的，所以 Python 版本必須和 TRex 主機一致。這一步需要網路。
3. 把後端程式、前端 `dist/`、`config.example.yaml`、安裝腳本、systemd unit 範本、`docs/` 打包在一起。

安裝方式見 [deployment.md](deployment.md) 第 3 節。

### 更新已安裝的主機

改版時用新的安裝包重新執行 `./install.sh` 即可，`config.yaml` 和 `data/` 會保留。

開發中想快速更新一台已經裝好的主機，可以直接同步檔案：

```bash
rsync -a --delete --exclude __pycache__ backend/trex_gui/ <帳號>@<主機>:trex-gui/backend/trex_gui/
rsync -a --delete frontend/dist/ <帳號>@<主機>:trex-gui/frontend/dist/
ssh <帳號>@<主機> 'systemctl --user restart trex-gui'
```

只改前端時不需要重啟服務。這個方式不會更新 Python 相依套件，`pyproject.toml` 的 dependencies 有變時請改用安裝包。

---

## 5. 程式結構

```
backend/trex_gui/
  __main__.py     啟動入口（python -m trex_gui -c config.yaml）
  config.py       設定檔格式與預設值
  affinity.py     啟動時套用 cpu_affinity
  app.py          REST 與 WebSocket API
  hosts.py        每台主機的 worker 子程序、連線狀態、共用的統計輪詢、事件紀錄
  worker.py       在子程序裡包裝 TRex client 的 adapter（op_* 方法）
  mock.py         假的 TRex 主機，介面和 worker.TRexAdapter 相同
  packets.py      協定目錄、封包組裝與解析、欄位變化編譯、header 檢查（只在 worker 裡執行）
  store.py        stream 定義、共用範本、port 設定檔的保存
  profiles.py / profileops.py
                  TRex Python profile 的列表與執行
  pcaps.py / pcapops.py
                  PCAP 檔案庫、重播、擷取
  rfc2544.py      RFC 2544 測試流程與結果保存
frontend/src/
  api.ts          所有 API 的型別與呼叫
  stores/         Pinia：主機與 port 狀態、streams、範本、設定檔
  composables/    共用的統計串流、port 配對、畫面尺寸
  components/     畫面元件；編輯器在 editor/，監控在 monitor/，總覽在 overview/，RFC 2544 在 rfc2544/
  locales/        介面文字，每個檔案裡繁中（zh）和英文（en）並列
  theme.ts        淺色 / 深色主題
deploy/           離線安裝包的打包腳本、安裝腳本、systemd unit 範本
bench/            GUI 對打流效能影響的測試腳本與數據
docs/             部署、使用、建置文件
```

### 為什麼 worker 是子程序

每個 TRex 版本隨附的 client 只能搭配同版本的 server，而且會帶自己的 Scapy、ZMQ、PyYAML。同一個 Python 程序無法同時載入兩個版本，所以每台主機開一個子程序（`spawn`），只在子程序裡 import 該主機的 client。主程序不 import 任何 TRex 或 Scapy 的東西。這也是 `__main__.py` 頂層只 import `argparse` 的原因。

---

## 6. 新增功能的流程

以「新增一個對 port 的操作」為例：

1. **`worker.py`**：在 `TRexAdapter` 加 `op_<名稱>(self, ...)`，在這裡呼叫 TRex client。回傳值必須能轉成 JSON。
2. **`mock.py`**：在 `MockAdapter` 加同名方法，模擬合理的行為，讓沒有 TRex 時也能操作。
3. **`app.py`**：加路由。會改變狀態的操作用 `act(request, host_id, "<事件代碼>", "<名稱>", ...)` 呼叫 worker，它會把操作、來源 IP 和結果記進事件紀錄（事件代碼的文字在 `locales/monitor.ts` 的 `events`）；唯讀的查詢直接用 `session.call("<名稱>", ...)`。
4. **`frontend/src/api.ts`**：加型別和呼叫函式。
5. **元件**：在 `components/` 裡使用。
6. **`frontend/src/locales/`**：所有顯示文字都放這裡，`zh` 和 `en` 兩邊都要加。英文少了 key 時，型別檢查會失敗。
7. **檢查**：執行 `npm run build` 和 `npx tsx scripts/check-i18n.ts`，然後用 mock 主機操作一次。動到 TRex 行為的功能，請在真的 TRex 上再測一次，mock 測不出 TRex client 的實際回傳格式。

設計時的規則：
- **會對 TRex 多發請求的功能，預設關閉**，做成選項讓使用者自己開啟，並加上警語，因為每個請求都由 TRex 的 master 執行緒處理。不會多發請求的功能才預設顯示。
- **後端產生的警告訊息**（例如 header 檢查）送出代碼和參數，由前端依語言組成句子，不要在後端寫死中文或英文。
- **暫時改變 port 狀態的操作**（例如擷取時進入 service mode），做完要恢復成原本的狀態，不要一律關掉。

---

## 7. 測試

目前沒有自動化測試套件，驗證方式是：

- **型別檢查與介面文字**：`npm run build`、`npx tsx scripts/check-i18n.ts`。
- **mock 主機**：所有畫面和流程都能在 mock 主機上操作。
- **真的 TRex**：兩個 port 對接成 loopback（直接對接，或在交換器上放進同一個獨立 VLAN），用 GUI 的 API 送流並比對統計。
- **效能影響**：`bench/` 裡的腳本，見 [bench/README.md](../bench/README.md)。
