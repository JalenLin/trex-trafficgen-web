# User guide

**English** | [繁體中文](user-guide.md)

This guide explains how to send traffic, read stats and run tests with TRex GUI. For installation and deployment see [deployment.en.md](deployment.en.md); to build from source see [building.en.md](building.en.md).

---

## 1. Concepts

- **Host**: one TRex server. The GUI can be connected to several at once. Hosts are listed in the backend's `config.yaml` and chosen on the left.
- **Acquiring a port**: a TRex port has one owner at a time. You must acquire a port before you can transmit on it, change its settings or capture on it. All GUI users share the TRex username from the config file, so the GUI doesn't tell its users apart; a port held by the TRex console or another tool shows that owner's name.
- **Stream**: one kind of packet plus how it is sent (rate, continuous or burst). The GUI saves stream definitions on the backend and sends them to TRex when you press Start.
- **Selected vs. current port**: the **checkboxes** in the port list on the left decide which ports the toolbar actions (Acquire, Start, Stop, …) apply to. **Clicking a row** decides which port the Streams, Port settings and similar tabs show.
- **L2 / L3 mode**: in L3 mode you enter the port's IP and gateway, and TRex resolves the destination MAC by ARP. **Traffic can't start until ARP resolves.** In L2 mode you enter the destination MAC directly, for example the other port's MAC when two ports are cabled back to back.

---

## 2. Layout

| Area | Contents |
|---|---|
| Top bar | "Overview & port map", language (繁中 / English), appearance (light / dark / system). Language and appearance are remembered in the browser |
| Left side | TRex host list (Connect / Disconnect) and the port list of the current host (link, speed, status, owner) |
| Top of the host page | Toolbar: Acquire, Force acquire, Release, Start, Stop, Pause, Resume, Reset, rate multiplier, duration. Session export / import is at the top right |
| Host page tabs | Streams, Stats, Monitor, Profile, RFC 2544, PCAP, pg / Latency, Port settings, Port details |

---

## 3. Sending traffic for the first time

1. Pick a host on the left and press **Connect**.
2. Tick the ports you want and press **Acquire** on the toolbar.
   - If a port is in use by someone else, **Force acquire** interrupts their test; the GUI asks you to confirm first.
3. Check the mode on the **Port settings** tab:
   - L3: enter the local IPv4 and the gateway. You can transmit once it shows "Resolved".
   - L2: enter the destination MAC.
4. Click a port, press "+ Add stream" on the **Streams** tab, set up the packet and rate in the editor and save (see section 4).
5. Press **Start** on the toolbar.
   - **Rate multiplier**: empty means 1×. You can also write `2` (2×), `50%` (half of line rate), `10kpps` or `1gbps`.
   - **Duration**: if set, traffic stops automatically after that many seconds; empty means run until you press Stop.
6. Watch the rates on the **Stats** or **Monitor** tab.
7. When you're done, press **Stop**, then **Release**. Releasing also removes the streams the GUI put on TRex. The stream definitions saved in the GUI are kept, so you can send them again after acquiring the port next time.

If you change the streams of a port that is transmitting, press Start again for the change to take effect. When a port is already transmitting, Start asks for confirmation, then stops and restarts it.

**Reset** stops traffic, removes the streams on TRex, clears these ports' stats and turns off service mode. The ports stay yours.

---

## 4. Stream editor

### Packet
- **Layers**: add them top to bottom. The available protocols are all the layers in the Scapy bundled with that TRex release, about 2,600 in TRex v3.08; common ones are listed first.
- **Fields**: leave a field empty and Scapy fills it in, e.g. lengths, checksums, and the type or proto of the layer above.
- **Preview**: the hex dump and decoded packet on the right update as you edit. Click a byte in the hex dump or a field in the decoded tree to jump to that field's editor.
- **Unreasonable headers produce warnings, never errors**, so you can still send malformed packets on purpose for negative tests. Examples: layers that don't fit together, a manual field that contradicts the next layer, a manually overridden len or chksum.
- **Frame size**: fixed, or incrementing, decrementing or random. When the size varies, the IP, IPv6 and UDP length fields and checksums are fixed automatically.
- **Payload fill**: below Frame size. Choose zeros, a fixed byte, incrementing / decrementing bytes, random (fixed seed), repeated text or repeated hex.

### Field engine
Make a field change from packet to packet: increment, decrement or random, with a range and step. Bit fields such as VLAN ID and MPLS label are supported. Checksums are recomputed automatically.

### Transmit
- **Mode**: continuous, single burst, multi-burst.
- **Rate**: pps, bps (L1 or L2), or % of line rate.
- **Flow stats**: choose flow stats or latency and set a pg_id; the results appear on the "pg / Latency" tab. Latency pg_ids must be unique; when streams are copied to other ports, the GUI picks new ones automatically.

### Send packets
**Send packets…** at the bottom of the editor sends the packet you are editing N times, with a gap you choose, without saving it first. Use it to check quickly whether the other end receives it.

### Templates
- **Personal templates**: stored in your browser and visible only to you. Export / import them as JSON to move them to another computer.
- **Shared templates**: stored on the backend and shared by everyone and every host.
- **Built-in templates**: for example IMIX (64 / 594 / 1518 bytes in a 7:4:1 ratio).

**Copy to other ports…** on the Streams tab copies all streams of a port to several other ports.

---

## 5. Control while transmitting

- **Whole port**: use Pause, Resume and Change rate on the toolbar.
- **Single stream**: while transmitting, the Streams tab shows Pause, Resume and Rate buttons for each stream.
  - TRex marks this feature as experimental. If you change a single stream's rate and then change the whole port's rate from the toolbar, the two rate records disagree. When the exact rate matters, stop and start again.

---

## 6. Stats and monitoring

| Tab | Contents |
|---|---|
| Stats | Per-port TX/RX rates (pps, L1/L2 bps, utilization), packets, bytes, errors. Switch between "Ports as columns" and "Ports as rows", or show only the selected ports. **Clear stats** resets the counters |
| pg / Latency | Per pg_id: TX/RX, packets per port, latency avg / min / max / jitter, sequence checks (dropped, out of order, duplicate), latency histogram |
| Monitor | Rate chart (total or per port, bps/pps, 1/5/15 minutes, switchable to a table; click a legend item to hide its line) and event log (GUI actions with the source IP, TRex events) |
| Port details | Driver, speed, link, mode, destination, promiscuous, flow control per port |
| Overview & port map | Totals and per-port rates of all hosts side by side, port pairs across hosts, port map (see section 9) |

**The cost of monitoring**: every query is handled by the TRex master thread. The rate chart and event log only use data the GUI already receives, so they are shown by default. **Advanced monitoring** (per-core CPU and mbuf, NIC xstats) sends extra requests to TRex, so it is off by default; read the warning on screen before turning it on. Measurements are in [bench/README.en.md](../bench/README.en.md).

If you clear stats while traffic is running, TX and RX are not reset at exactly the same moment, so there is a small error. To check for loss, clear the stats while traffic is stopped.

---

## 7. Port settings

- **L2 / L3**, VLAN (up to two tags, QinQ), IPv6, promiscuous, multicast, flow control, link up/down. Items the NIC doesn't support are hidden.
- **Apply to other ports**: VLAN, IPv6 on/off, promiscuous, multicast and flow control can be applied to the other selected ports at once. MAC, IP and gateway differ per port, so they are never applied in bulk.
- **Ping**: send pings from the port to check the path.
- **Port profiles**: save the L2/L3 settings of several ports as a set (on the backend, per host). Before applying, the GUI lists how each port will change.
  - After TRex restarts, port settings go back to the defaults in `trex_cfg.yaml`. The GUI notices and offers to re-apply the last profile; it never re-applies it on its own.
  - The GUI also tells you when settings were changed outside the GUI, for example from the TRex console.
- **Namespace nodes** (bottom of the page): emulated hosts behind the port, each with a MAC, IPv4 + gateway, VLAN, IPv6 and MTU.
  - TRex's `trex_cfg.yaml` must contain `stack: linux_based`; without it the page explains what to change.
  - Nodes answer ARP only while the port is in service mode.
  - "Filtered" service mode needs TRex to be started with `--software`.
  - Known issue: in testing, nodes answered ARP but not ping. The cause hasn't been found yet.

---

## 8. PCAP and Python profiles

### PCAP
- **Library**: upload pcap / pcapng (pcapng is converted to pcap; Ethernet only), download, rename, delete. The library is on the backend and shared by everyone.
- **Replay**: keep the original packet timing with a speed-up, or use a fixed gap; set a count and a time limit; choose whether MACs come from the pcap or the port. Replay sends packet by packet on a timer, so it suits low to medium rates.
- **Preview / to streams**: tick packets and turn them into streams. They are split into protocol fields, with lengths and checksums recomputed. Use this for high rates.
- **Capture**: capture TX, RX or both, with a limit and a BPF filter; on stop the capture is saved to the library. Capture also works on remote hosts; the packets are sent back to the machine running the GUI.
  - Captured packets go through the CPU, so capture is for debugging, not line-rate recording.
  - To capture traffic sent or received by streams, tick **Service mode**. Both TX and RX ports then enter service mode during the capture and go back to their previous mode afterwards.

### Python profiles
The **Profile** tab lists two folders on the server: TRex's own examples (`<trex>/stl`) and the shared folder (`data/profiles`). A profile's parameters become a form; choose the ports, multiplier and duration, then press **Start**.

- A profile replaces the port's streams on TRex, but the streams saved on the Streams tab are untouched; pressing Start on the toolbar later sends those again.
- A profile is Python code that runs on the GUI backend, so uploading from the web page is off by default. Administrators copy files into `data/profiles` over SSH.

---

## 9. Multiple hosts: overview, pairs and port map

**Overview & port map** shows all hosts side by side. It only uses each host's existing stats stream and adds no requests.

- **Port pairs across hosts**: pick two ports that are wired together (directly or through a device under test) to compare "A sent vs. B received", with the difference and loss rate.
  - A direction that is still transmitting is marked "running", because packets in flight count toward the difference.
  - "Clear stats on these hosts" clears both ends at once.
- **Port map**: links between ports and to the outside, from each port's L2 destination MAC, L3 gateway and the cross-host pairs. It is shown even with a single host.
  - With many hosts the map is wider than the page and scrolls sideways. **Show as table** gives the same information as a table.

---

## 10. RFC 2544

The **RFC 2544** tab measures a device under test (DUT) or a loopback per RFC 2544.

1. **Test settings**
   - Choose port pairs (TX → RX, optionally bidirectional).
   - Choose frame sizes. The defaults are 64 / 128 / 256 / 512 / 1024 / 1280 / 1518; custom sizes from 64 to 9216 are allowed.
   - Tick the tests:
     - **Throughput**: binary search for the highest rate with loss at or below the acceptable loss.
     - **Latency**: latency at the throughput rate.
     - **Frame loss rate**: step down from the maximum rate, recording the loss at each rate.
     - **Back-to-back**: the longest burst that gets through without loss.
   - Set the trial time, resolution, maximum rate and acceptable loss. The page estimates the total time; running every test at every size can take hours.
2. **Run status**: shows the current trial and progress; you can stop the test part way. While it runs, other actions can't start traffic on the ports it uses.
3. **Results**: per frame size, throughput (% of line rate / Mpps / Gbps), latency, the loss curve and the back-to-back length. Export as JSON / CSV.
4. **History**: every test is saved on the backend and can be reopened or deleted.

Notes:
- **Loss is counted with the NIC's hardware port counters**, so keep other traffic off these ports during the test.
- **Throughput is judged on the rate actually sent.** When TRex itself can't send at the requested rate, the result is marked "TRex-limited": the bottleneck is the traffic generator, not the DUT.
- **In a loopback test** (two TRex ports cabled together) the result includes the limit of TRex's own receive side. For example, the lab host reached only about 53% bidirectional at 64B because TRex can't receive more than about 27 Mpps per port; 512B and 1518B reached 100%.

---

## 11. Session export / import

**Export session** at the top right of the host page saves the streams, port settings and port profiles of every port on the host to one JSON file.

**Import session…** lets you map each port to a different port or another host, and choose what to import:
- Replace the streams.
- Apply the port settings. They are applied only to ports you have acquired. When a port is mapped to a different port number, this is unticked by default so it doesn't bring over another port's IP.
- Add the port profiles. Profiles with the same name are skipped.

---

## 12. Where data is stored

| Data | Location | Visible to |
|---|---|---|
| Stream definitions | Backend `data/<host>/port-<n>.json` | Everyone |
| Shared templates | Backend `data/templates.json` | Everyone, all hosts |
| PCAP library | Backend `data/pcaps/` | Everyone |
| Port profiles | Backend `data/<host>/port-profiles.json` | Everyone |
| RFC 2544 results | Backend `data/<host>/rfc2544/` | Everyone |
| Shared Python profiles | Backend `data/profiles/` | Everyone |
| Personal templates, language, appearance, selected ports, tabs, layout, unsaved drafts | Browser localStorage | Only you; reset when browser data is cleared |
| Event log | Backend memory (the most recent few hundred entries) | Everyone; cleared when the backend restarts |
| Rate chart history | Browser tab memory | Only you; cleared on reload |

The location of `data/` is set by `server.data_dir` in `config.yaml`; the default is `data/` next to the config file. To back up, back up that folder.

---

## 13. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Start does nothing, or the port shows "ARP unresolved" | In L3 mode the gateway didn't answer ARP. Check the cabling and the gateway, or press "Re-resolve" in Port settings; for ports cabled back to back, use L2 mode |
| Buttons are greyed out | The port isn't acquired, or it is transmitting (L2/L3 settings can only change while stopped) |
| Stream traffic doesn't show up in a capture | Tick **Service mode** when capturing |
| RX is slightly lower than TX in Stats | Stats were cleared while traffic was running, or packets were still in flight. Compare after stopping traffic |
| pg / Latency is empty | The stream's Transmit settings don't have flow stats or latency turned on |
| The host shows as disconnected | TRex isn't running, or the backend can't reach TCP 4501 / 4500. The reason is shown on screen |
| Namespace says it needs `stack: linux_based` | TRex's `trex_cfg.yaml` must be changed and TRex restarted. This affects every user, so check with the administrator first |

**There is no login yet.** Anyone who can reach the GUI can control traffic, so only expose it on an isolated lab network (see section 5 of [deployment.en.md](deployment.en.md)).
