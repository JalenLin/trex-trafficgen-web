# 測試

[English](README.en.md) | **繁體中文**

| 目錄 | 內容 | 對象 |
|---|---|---|
| `backend/` | 後端 API 測試（pytest），涵蓋所有 API | mock 主機，或真的 TRex |
| `e2e/` | 瀏覽器端對端測試（Playwright），逐一操作每個畫面，中英文都檢查 | mock 主機 |

前端的型別檢查與介面文字檢查見 [docs/building.md](../docs/building.md) 第 3 節。

**GitHub Actions**：`.github/workflows/test.yml` 在每次 push 和 PR 時跑 mock 的後端測試、前端建置與介面文字檢查、瀏覽器測試；失敗時會上傳截圖和後端 log。實機測試需要接好 loopback，請照下面的步驟手動跑。

## 後端 API 測試

```bash
backend/.venv/bin/pip install -e 'backend[mock,test]'   # 第一次
backend/.venv/bin/python -m pytest tests/backend
```

不加任何設定時，測試會自己啟動一個 mock 後端（隨機 port、全新的資料夾），約 2.5 分鐘。

### 對真的 TRex 跑

需要一台已經在執行的 GUI 後端，以及兩個接成 loopback 的 port（直接對接，或在交換器上放進只有這兩個 port 的 VLAN）。測試期間這兩個 port 不能有其他人使用。

```bash
TREX_GUI_URL=http://<GUI 主機>:8080 TREX_GUI_HOST=local TREX_GUI_PAIR=0,1 \
    backend/.venv/bin/python -m pytest tests/backend
```

| 環境變數 | 用途 |
|---|---|
| `TREX_GUI_URL` | 要測試的 GUI 後端；不設定時用 mock |
| `TREX_GUI_HOST` | 設定檔裡的主機 id，預設 `local`（mock 為 `demo`） |
| `TREX_GUI_PAIR` | loopback 的兩個 port，預設 `0,1`（mock 為 `2,3`） |
| `TREX_GUI_PEER` | 第二台主機的 id，用來跑 `test_cross_host.py`。兩台的 p0、p1 要分別對接 |
| `TREX_GUI_PING` | `<port>:<本機 IP>:<gateway>:<目標>`，ping 一台真的主機（TRex 的 port 不回應 ping） |

- **開始前**：測試會強制取得這兩個 port。
- **結束時**：會把 port 設定還原成開始前的狀態並釋放 port。
- **兩種 stack**：namespace 和 IPv6 的測試需要 TRex 使用 `stack: linux_based`，沒有時會略過或改為檢查錯誤訊息。

## 瀏覽器端對端測試

```bash
cd tests/e2e
npm ci                           # 第一次
npx playwright-core install chromium   # 第一次，下載對應版本的瀏覽器
node run.mjs                     # 全部，約 3 分鐘
node run.mjs streams pcap        # 只跑名稱符合的群組（群組 01 一定會跑）
```

- **後端與資料**：會自己在 port 8098 啟動 mock 後端，資料夾每次都是全新的。
- **前端建置**：`frontend/src` 比 `frontend/dist` 新時，會先重新建置前端。
- **瀏覽器與 Python**：預設用 `npx playwright-core install chromium` 安裝的 Chromium，和 `backend/.venv` 裡的 Python；可以用 `CHROME`、`E2E_PYTHON` 改用其他的。
- **截圖**：存在 `$E2E_OUT/e2e-shots`。
- **前後相依**：各群組共用同一個頁面並依序執行，後面的群組會用到前面取得的 port，所以單獨跑某個群組時結果僅供參考。
- **失敗條件**：任何頁面錯誤或主控台錯誤都算失敗。
