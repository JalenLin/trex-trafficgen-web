# 部署說明：在 TRex 主機上執行 GUI 後端

[English](deployment.en.md) | **繁體中文**

這份文件說明如何把 GUI 後端裝在 TRex 主機本身，讓使用者直接用瀏覽器連上該主機操作。

**後端和 TRex 在同一台時，一定要把後端綁定在 TRex 不打流的 CPU 上。** 安裝腳本會自動處理，下面說明原因、怎麼選 CPU，以及怎麼確認有綁好。

如果後端裝在另一台機器（管理機或個人電腦），不需要綁定，可以跳過 CPU 相關的章節。

---

## 1. 為什麼要綁定 CPU

TRex 用 DPDK 打流，每個打流核心都在跑忙碌迴圈（busy polling）。Linux 預設可以把任何程序排到任何核心上，包括 TRex 正在打流的核心。後端被排上去時，會跟 TRex 搶 CPU，直接影響封包的發送時間。

2026-10-28 在實驗室主機上的實測結果如下：Ryzen 7 3800X、ConnectX-4 Lx 2×25G、TRex v3.08 `-c 14`，兩個 port 對接成 loopback，每種情境跑 3 輪，每輪 30 秒，測試期間有 3 個瀏覽器在看即時統計。

| 封包 | 情境 | TX Mpps | 丟包 | latency 平均 | latency 最大值（6 個樣本） |
|---|---|---|---|---|---|
| 64B | 沒有 GUI | 55.321 | 0 | 7.0 μs | 11–23 μs |
| 64B | **GUI 綁在 core 0** | 55.332 | 0 | 7.2 μs | 12–16 μs，有一次 131 μs |
| 64B | GUI 不綁定 | 55.321 | 0 | 8.5 μs | 13–17 μs，有兩次 99 和 200 μs |
| IMIX | 沒有 GUI | 16.369 | 0 | 9.8 μs | 13–36 μs |
| IMIX | **GUI 綁在 core 0** | 16.369 | 0 | 9.7 μs | 13–27 μs |
| IMIX | GUI 不綁定 | 16.361 | 0 | 11.2 μs | 13–21 μs |

- **綁定時**：吞吐量、丟包、平均 latency 都量不到差異。
- **不綁定時**：平均 latency 增加約 1.5 μs，偶爾出現 100 到 200 μs 的尖峰，吞吐量也有輕微下降。
- **綁定也不是零影響**：綁在 core 0 時 6 個樣本裡有一次 131 μs 的尖峰，推測是跟 TRex 的 master thread 搶同一個核心。如果你的測試對 latency 的尾端（最大值、jitter）很敏感，請看第 2 節的「空出一個核心」。

原始數據和測試腳本在 `bench/`，重跑方式見第 8 節。

---

## 2. 怎麼選 CPU

### TRex 的執行緒分配

打開 `/etc/trex_cfg.yaml` 的 `platform` 區塊：

```yaml
platform:
    master_thread_id: 0       # 控制執行緒：處理 RPC、統計，大部分時間閒置
    latency_thread_id: 8      # latency 量測執行緒
    dual_if:
      - socket: 0
        threads: [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15]   # 打流執行緒池
```

另外看 TRex 啟動指令的 `-c N`，這是實際用來打流的核心數：

```bash
ps -eo args | grep "[_]t-rex-64"
```

### 選擇規則

依序選第一個符合的：

1. **完全沒被 TRex 用到的實體核心**：最好的選擇。例如 TRex 用 `-c 12`，threads 清單最後兩個沒用到，而且它們剛好是同一顆實體核心的兩個 HT sibling，就選這一對。
2. **`master_thread_id`**：沒有空閒核心時的選擇，也是安裝腳本的預設值。master 大部分時間閒置，第 1 節的測試就是這種配置。
3. **絕對不要選**：
   - `latency_thread_id`：會直接干擾 latency 量測。
   - `dual_if.threads` 裡正在使用的核心：會直接拖慢打流。
   - master 的 HT sibling，如果它是 latency 或打流執行緒的話。

查詢哪些邏輯核心是同一顆實體核心：

```bash
lscpu -e=CPU,CORE
```

### 空出一個核心

如果 TRex 用滿所有核心（例如實驗室主機的 `-c 14`），又在意 latency 的尾端，可以把 TRex 改成少用一對核心（例如 `-c 12`），把空出來的那對給 GUI。代價是 64B 小封包的最大速率會下降，請先實測確認能不能接受。

### 設定方式

在 `config.yaml` 裡設定：

```yaml
server:
  cpu_affinity: [0]       # 可以指定多個，例如 [7, 15]
```

後端啟動時會先綁定自己，之後開出來的 worker 子程序和所有執行緒都會繼承。用 systemd、手動啟動或任何方式啟動都會生效。

如果後端偵測到它跟 TRex 在同一台（設定檔裡有主機的 `server` 是 `127.0.0.1` 或 `localhost`）卻沒有設定 `cpu_affinity`，啟動時會印出 `WARNING`。

---

## 3. 安裝

TRex 主機常常沒有 pip、沒有 `python3-venv`、也不能上網，所以安裝方式是**在開發機打包、拿到 TRex 主機上離線安裝**。預設安裝不需要 sudo。

### 3.1 在開發機打包

```bash
deploy/make-bundle.sh 3.12        # 參數是 TRex 主機上 python3 的版本
# 產生 dist/trex-gui-<版本>-py3.12-x86_64.tar.gz
```

Python 版本必須跟 TRex 主機一致，因為部分相依套件是編譯過的 wheel。可以在 TRex 主機上用 `python3 --version` 查。

### 3.2 在 TRex 主機安裝

```bash
tar xzf trex-gui-0.1.0-py3.12-x86_64.tar.gz
cd trex-gui-0.1.0-py3.12-x86_64
./install.sh
```

安裝腳本會做這些事：

1. 把程式裝到 `~/trex-gui`，並建立獨立的 Python 虛擬環境。不需要 pip，也不需要網路。
2. 找出 TRex 的安裝位置：優先用正在執行的 TRex，找不到就用 `/opt/trex/` 底下最新的版本。
3. 從 `/etc/trex_cfg.yaml` 讀出 `master_thread_id`，產生 `config.yaml` 並設定 `cpu_affinity`。如果選到的核心同時也是 latency 或打流執行緒，會印出警告。
4. 安裝成 systemd 的使用者服務並啟動。

如果 `config.yaml` 已經存在，安裝腳本不會覆蓋它，所以重新安裝或升級不會蓋掉你改過的設定。

### 3.3 選項

| 選項 | 用途 |
|---|---|
| `--prefix DIR` | 安裝到其他位置 |
| `--trex-dir DIR` | 自動偵測找錯 TRex 版本時，手動指定 |
| `--trex-cfg FILE` | TRex 設定檔不在 `/etc/trex_cfg.yaml` 時使用 |
| `--listen ADDR` | 監聽位址，預設 `127.0.0.1`；`0.0.0.0` 開放給整個網段，見第 5 節。只在第一次產生 `config.yaml` 時生效 |
| `--system` | 安裝成系統服務。要用 `sudo ./install.sh --system` 執行，服務會以執行 sudo 的那個帳號身分運行 |
| `--no-service` | 只安裝檔案，不建立服務 |

### 3.4 開機自動啟動

使用者服務預設在**該帳號登出後就會停止，開機也不會自動啟動**。要讓它一直運行，有兩種做法：

```bash
sudo loginctl enable-linger $USER        # 做法一：讓使用者服務常駐
sudo ./install.sh --system               # 做法二：改裝成系統服務
```

---

## 4. 驗證綁定

安裝或修改 `cpu_affinity` 之後，執行以下兩個檢查。系統服務請把 `systemctl --user` 換成 `systemctl`，`journalctl --user` 換成 `journalctl`。

**1. 啟動 log 應該顯示正確的 CPU，而且沒有 WARNING：**

```bash
journalctl --user -u trex-gui | grep -E "CPU affinity|WARNING" | tail -2
# INFO:     CPU affinity: 0
```

**2. 服務底下每個程序的每個執行緒都只能用指定的 CPU。**
worker 程序要在連線之後才會出現，所以請先在網頁上按「連線」，再執行：

```bash
CG=$(systemctl --user show trex-gui -p ControlGroup --value)
for pid in $(cat /sys/fs/cgroup$CG/cgroup.procs); do
  grep -h Cpus_allowed_list /proc/$pid/task/*/status
done | sort | uniq -c
#      13 Cpus_allowed_list:	0
```

輸出應該只有一行，而且是你設定的 CPU。如果出現像 `0-15` 這種範圍，代表沒綁好。

---

## 5. 使用者怎麼連

後端預設只聽 `127.0.0.1:8080`。有兩種連入方式：

### 方式一：直接開放給網段（實驗室網路建議用這個）

安裝時加 `--listen 0.0.0.0`，或把現有 `config.yaml` 的 `server.host` 改成 `0.0.0.0` 後重啟服務。使用者直接開 `http://<TRex 主機>:8080` 即可。

**目前沒有登入機制**，任何連得到 8080 的人都能控制打流。這在隔離的實驗室網段可以接受，因為 TRex 本身的 RPC port（4500/4501）預設就聽在 `0.0.0.0`、也沒有驗證，開放 GUI 並沒有多出原本不存在的風險。但**不要在會連到辦公室或正式網路的機器上這樣做**。

主機有開防火牆（例如 ufw）的話，需要放行 TCP 8080。

### 方式二：SSH tunnel

網段不夠隔離時，維持 `127.0.0.1`，讓使用者用 SSH tunnel 連入：

```bash
ssh -L 8080:127.0.0.1:8080 <帳號>@<TRex 主機>
```

再用瀏覽器開 http://127.0.0.1:8080 。

---

## 6. 日常操作

```bash
systemctl --user status trex-gui      # 狀態
systemctl --user restart trex-gui     # 改完 config.yaml 後重啟
journalctl --user -u trex-gui -f      # 看 log
```

**不用 systemd、手動啟動**：

```bash
cd ~/trex-gui/backend && ../.venv/bin/python -m trex_gui -c ../config.yaml
```

綁定設定在 `config.yaml` 裡，所以手動啟動一樣會生效。

---

## 7. 升級與移除

**升級**：用新的安裝包重新執行 `./install.sh`。程式和虛擬環境會被替換，`config.yaml` 和 `data/`（使用者建立的 stream 定義）會保留。

**TRex 升級**：修改 `config.yaml` 裡的 `client_path`，指到新版 TRex 的 `automation/trex_control_plane/interactive`。如果新版 TRex 的執行緒配置有變，記得一併檢查 `cpu_affinity`。

**移除**：

```bash
systemctl --user disable --now trex-gui
rm ~/.config/systemd/user/trex-gui.service
rm -rf ~/trex-gui          # 會一併刪除 data/ 裡的 stream 定義，需要的話先備份
```

---

## 8. 重跑效能測試

換了機器、TRex 版本或 `-c` 參數之後，建議重跑一次第 1 節的測試，確認在新環境下綁定一樣沒有影響。

監控功能對打流的影響另有一組測試（`bench/run_monitor.sh`），數據與重跑方式見 [bench/README.md](../bench/README.md)。

**前提**：TRex 的兩個 port 要對接成 loopback（直接對接，或在交換器上把兩個 port 放進同一個獨立 VLAN），而且測試期間沒有其他人在用這台 TRex。

測試腳本會把 port 暫時改成 L2 模式。**測完要記得改回原本的 L3 設定，順序是先恢復交換器、再恢復 TRex**，這樣 ARP 才解析得到 gateway。

把專案的 `bench/` 目錄複製到 TRex 主機上，然後：

```bash
systemctl --user stop trex-gui       # 測試會自己啟動和停止 GUI，正式服務要先停

cd bench
DRY_RUN=1 REPS=1 ./run_all.sh        # 先空跑：只檢查 GUI 的啟動、停止和綁定，不發流量
./run_all.sh                         # 正式跑，約 14 分鐘，結果寫入 results.jsonl
python3 analyze.py results.jsonl     # 輸出摘要表格

# 改回 L3 模式，格式是 port:本機IP:gateway
python3 bench.py --restore-l3 0:10.0.0.2:10.0.0.1 1:192.168.200.2:192.168.200.1
systemctl --user start trex-gui
```

可以用環境變數調整：

| 變數 | 預設值 | 用途 |
|---|---|---|
| `GUI_DIR` | `~/trex-gui` | GUI 的安裝位置 |
| `TREX_CLIENT` | `/opt/trex/v3.08/automation/trex_control_plane/interactive` | TRex client 路徑 |
| `PIN_CPU` | `0` | 情境 B 要綁定的 CPU |
| `REPS` / `DURATION` | `3` / `30` | 輪數和每輪秒數 |

`run_all.sh` 會自己產生測試專用的設定檔（綁定與不綁定各一份），不會讀你的 `config.yaml`。它也會檢查每個情境的執行緒綁定是否正確，不對就中止。

測試期間請在另一台機器執行 `bench/subs.py`，透過 SSH tunnel 模擬有人在看統計，否則 GUI 不會輪詢 TRex，測不出影響：

```bash
ssh -f -N -L 18080:127.0.0.1:8080 <帳號>@<TRex 主機>
python3 bench/subs.py ws://127.0.0.1:18080/api/hosts/local/stats 3
```

---

## 9. 疑難排解

| 現象 | 原因與處理 |
|---|---|
| 啟動時出現 `WARNING: ... may use every CPU` | 後端跟 TRex 在同一台但沒設定 `cpu_affinity`，照第 2 節設定 |
| `this bundle is for python X but python3 is Y` | 安裝包的 Python 版本不符，在開發機用 `deploy/make-bundle.sh Y` 重新打包 |
| `TRex client not found` | 自動偵測找不到 TRex，用 `--trex-dir /opt/trex/vX.XX` 指定 |
| 網頁上按連線出現 `failed to load TRex client` | `config.yaml` 的 `client_path` 不對，或 TRex 版本的 client 不完整 |
| 登出後服務停了 | 使用者服務的預設行為，見 3.4 節 |
| port 8080 被佔用 | 改 `config.yaml` 的 `server.port` |
