# 效能測試

[English](README.en.md) | **繁體中文**

這裡的測試回答兩個問題：GUI 後端裝在 TRex 主機上會不會拖慢打流，以及每多一種監控會不會拖慢打流。所有測試都在 p0↔p1 loopback 上跑（實驗室主機的 switch 設定方式見 `docs/deployment.md` 第 8 節），兩個方向都打線速，並各加一條 1000 pps 的 latency stream。

| 腳本 | 用途 |
|---|---|
| `bench.py` | 打一次流並量測：吞吐量、丟包、DP CPU、latency |
| `run_all.sh` | GUI 後端：不執行 / 綁 CPU / 不綁 CPU（2026-10-28，`results-2026-10-28.jsonl`） |
| `monitor_load.py` | 模擬 GUI 的輪詢：綁在 core 0，用自己的唯讀 client 打 RPC |
| `run_monitor.sh` | 監控負載：A/G/M/S 四種情境（`monitor-results.jsonl`、`monitor-rpc.jsonl`） |
| `run_isolate.sh` | 壓力情境下逐一測試各個 RPC（`isolate-results.jsonl`、`isolate-rpc.jsonl`） |
| `analyze.py` / `analyze_rpc.py` | 把 jsonl 整理成下面的表格 |

## 監控負載（2026-10-28，TRex v3.08，Ryzen 7 3800X，ConnectX-4 Lx 25G）

| 情境 | 輪詢內容 |
|---|---|
| A | 不輪詢 |
| G | GUI 目前的輪詢：`get_stats`（含 pg/latency），每秒 1 次 |
| M | G 加上每核心 CPU/mbuf（`get_utilization`）和每個 port 的 xstats，每秒 1 次 |
| S | M 的內容不停頓連續查詢，每秒約 25–27 輪（壓力測試，遠超過實際使用） |

| 封包 | 情境 | 次數 | TX Mpps | latency 丟包 | DP CPU % | latency 平均 μs | latency 最大 μs | jitter μs |
|---|---|---|---|---|---|---|---|---|
| 64b | A | 3 | 55.187 | 0 | 92.4 | 7.2 | [11, 13, 14, 15, 15, 180] | 11 |
| 64b | G | 3 | 55.188 | 0 | 92.4 | 8.7 | [13, 13, 14, 15, 101, 206] | 13 |
| 64b | M | 3 | 55.187 | 0 | 92.4 | 7.2 | [14, 15, 32, 32, 110, 112] | 7 |
| 64b | S | 3 | 55.114 (−0.13%) | 0 | 88.1 | 8.0 | [21, 21, 27, 124, 212, 282] | 32 |
| imix | A | 3 | 16.368 | 0 | 17.4 | 10.0 | [13, 13, 13, 13, 14, 14] | 1 |
| imix | G | 3 | 16.368 | 0 | 16.9 | 9.8 | [13, 13, 15, 19, 20, 22] | 1 |
| imix | M | 3 | 16.368 | 0 | 16.8 | 9.8 | [13, 14, 18, 19, 50, 50] | 1 |
| imix | S | 3 | 16.369 | 0 | 19.4 | 10.0 | [17, 17, 18, 18, 167, 169] | 1 |

在 64B 線速下逐一施壓，每次只連續查詢一種 RPC：

| RPC | 每秒次數 | 每次耗時（中位數） | TX Mpps | latency 最大 μs |
|---|---|---|---|---|
| `get_stats` | 37 | 26.8 ms | 55.117（−0.13%） | [17, 19, 21, 72] |
| `get_utilization` | 896 | 1.1 ms | 55.191（無差異） | [18, 21, 329, 450] |
| `get_port_xstats_values`（2 個 port） | 101 輪 | 每個 port 4.8 ms | 55.143（−0.08%） | [22, 23, 240, 499] |

結論：

- **每 1–2 秒查詢一次**（GUI 的實際用法）時，吞吐量、丟包、DP CPU、latency 平均都沒有可量測的差異。latency 最大值本來就會偶爾跳到 100–200 μs，基準情境 A 也有一次 180 μs，所以 G 和 M 的最大值都還在雜訊範圍內。
- 只有比實際用法高出 25–900 倍的連續查詢才看得出影響。`get_stats` 會讓吞吐量下降約 0.1%；`get_utilization` 和 xstats 不影響吞吐量，但 latency 尖峰會更常出現。
- 據此做的設計：
  - 統計每台主機只輪詢一次，不管開著幾個瀏覽器。
  - `server.stats_interval` 最小 0.5 秒。
  - 每核心 CPU/mbuf 和 xstats 預設關閉，要由使用者開啟（附上這份數據的警語），間隔可選 1、2、5、10 秒，後端重啟後恢復關閉。
  - 速率圖表和事件紀錄只用已經收到的資料，不會多打 RPC，所以預設顯示。

重跑方式（先停掉 GUI 服務並接好 loopback）：

```bash
systemctl --user stop trex-gui
./run_monitor.sh                 # 約 12 分鐘；REPS、DURATION 可調
python3 analyze.py monitor-results.jsonl
python3 analyze_rpc.py monitor-rpc.jsonl
```
