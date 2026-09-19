# 任務書 D：儀表板（Phase 5）

> 你是 **D**。你負責 `Edge/oneAPI_py3.10/bin/dashboard.py`（新增）、`tools/dashboard_demo.py`（新增）、`tests/test_dashboard.py`（新增），以及 `bin/main.py` 裡啟動儀表板的那一小段。你可以**完全不依賴 B**，用 CSV 重播的假資料獨立開發。

---

## 0. 共同背景（五份任務書相同）

**專案**：Advantest 黑客松 grp1。在 Edge Server 上即時判斷每個 touchdown 的量測資料是否異常，並把決策回傳給機台（Nexus）。Edge 端程式在 `Edge/oneAPI_py3.10/`（Python，在容器內執行）；測試程式在 `SmarTest/Case_Smt870/`（Java/flow，在 Host Controller 執行）。
**現況**：Phase 1 偵測器已完成（`bin/detector.py`、`bin/model/baseline.json`、`tools/`、`tests/`），細節見 `ai_notes/20260918_sonnet5_phase1_spec.md` 第 11 節；整體計畫見 `ai_notes/20260918_sonnet5_hackathon_todo_plan.md`。
**角色與時段**：A 偵測器｜B Edge 整合（`sample.py`）｜C SmarTest/真機｜D 儀表板｜E 部署與 Demo。時段：S0 啟動 → S1 平行開發 → S2 整合一 → S3 整合二/驗證 → S4 凍結與 Demo。

### 0.1 與 AI 協作的規則（來自 `AGENTS.md`）
1. 請你的 AI 先讀 `AGENTS.md` 與本任務書。建議第一句話：「先讀 AGENTS.md 和這份任務書，列出你打算做的步驟給我確認，確認後才動手。」
2. 每個人開自己的分支：`git checkout -b <GitHub帳號>_<AI模型名>`（例：`feedc0de_gemini3flash`）。所有修改都在分支上，**commit / push 由人類執行**。
3. 程式碼註解只用英文、單行、量不超過程式碼。
4. 不要直接在 VM 上改程式；本機開發、測試，再同步。**不要把密碼、金鑰寫進 repo**（工作坊密碼在 `doc/WorkShop_Material.pdf` 第 21 頁）。
5. 完成一項工作後，在 `ai_notes/` 新增 `YYYYMMDD_<模型名>_<功能>.md`，**繁體中文**，含：變更摘要、修改與新增檔案、技術細節與邏輯、待執行事項與注意事項。
6. `Monitor` 的 callback 是阻塞式：重運算不可卡住 `consumeData`（AGENTS.md 明文規定）。

### 0.2 環境速查（實測，2026-09-19）
- **Host Controller**：`ssh advantest`（`user@100.114.133.30`，金鑰 `~/.ssh/ssh_private_key`，向隊友取得設定）。主機名 `group-1`，RHEL 7.9、Python 3.6，專案在 `~/Case_Event/`。**帳號 `user` 五人共用，可能有人正在跑 SmarTest**；`user` 沒有 docker 權限，`tag.sh` 需 `sudo`（權限未確認）；Host 可連外網。
- **Edge 開發 pod**：`ssh -J advantest -p 29022 debugger@advantestcell.local`（密碼見教材第 21 頁，登入時手動輸入）。Ubuntu 22.04、Python 3.10、有 `numpy`/`flask`/`paramiko`/`jsonschema`/`requests`；**沒有** `pandas`/`scikit-learn`/`matplotlib`/`pillow`；**不能連外網**；只有 `/home/debugger/project` 在容器重啟後保留。
- **本機測試**：`cd Edge/oneAPI_py3.10 && python3 -m unittest discover -s tests`（`test_sample_local.py` 有 1 項已知失敗，B 會取代）。
- **打包**：`Dockerfile` 是 `COPY bin/. ./bin`，`bin/` 底下所有檔案都會進 image。執行期相依只能用標準函式庫 + `numpy` + `flask`。

### 0.3 共同介面契約（改動前必須通知相關人，並同步五份任務書）
```python
det = Detector.load(path=None)                  # 預設 bin/model/baseline.json；失敗不丟例外，det.load_error 有訊息
alerts = det.update(test_key, site, value, seq) # 逐筆呼叫，回傳「新觸發」的 Alert 清單
verdict = det.end_touchdown()                   # 每個 touchdown 結束呼叫一次
det.reset(scope="lot")                          # "lot" 或 "wafer"
det.info()                                      # {"monitored_tests": int, "baseline_tests": int, "load_error": str|None}   (A1 新增)

Alert   = {"kind": "outlier|mean_shift|variance_change|mean_drift|site_imbalance", "test": str, "site": int|None, "score": float, "seq": int}
Verdict = {"anomaly": bool, "onset": bool, "cleared": bool, "score": float, "n_alerts": int,
           "top_alerts": [Alert, ...最多 5 筆], "message": str(<=200 字元)}          # onset / cleared 為 A1 新增
```
`SampleMonitor.get_state()`（B 實作、D 使用）：
```python
{"lot": str|None, "wafer": str|None, "touchdown": int,
 "totals": {"touchdowns": int, "anomaly_touchdowns": int},
 "latest": Record|None, "recent": [Record, ...最近至多 50 筆，舊到新],
 "detector": {"monitored_tests": int, "load_error": str|None}}
Record = {"td": int, "time": float(epoch 秒), "anomaly": bool, "onset": bool, "cleared": bool, "score": float,
          "n_alerts": int, "top_alerts": [Alert, ...], "message": str,
          "dies": [{"site": int, "x": int|None, "y": int|None, "part_id": int|None, "sbin": int|None}, ...]}
```
`get_state()` 必須回傳快照（複本），且成本低。

### 0.4 回報格式
完成一項就回報：**完成了什麼**、**驗收結果（附指令輸出）**、**未完成或風險**。契約異動要先講，再改。

---

## 1. 你的目標與完成定義
做一個能在 Edge 容器裡跑、**不需要任何外部資源**的即時儀表板：顯示目前狀態、偵測到的異常、wafer map，供 Demo 使用；同時提供一個**離線 demo 模式**（不連 Nexus，用 CSV 重播驅動），Demo 時真機出狀況也能展示。

## 2. 你擁有的檔案
`bin/dashboard.py`、`tools/dashboard_demo.py`、`tests/test_dashboard.py`；`bin/main.py` 只加下面 D4 的那一小段；`SmarTest/app_descriptor.json` 的修改**只提供片段給 E**（E 負責部署）。

## 3. 硬性限制
- **Edge 容器不能連外網**：不可使用 CDN（Chart.js、Bootstrap、Google Fonts 等）；所有 CSS / JS 內嵌。
- **沒有 `matplotlib` / `pillow`**：圖用內嵌 SVG（純字串組出來）。
- 只能用標準函式庫 + `flask`（pod 上是 3.1.2）；Python 3.10 相容。
- 儀表板出任何錯都不能影響偵測主流程。

## 4. 任務清單

### D1（S1，約 2 小時）`bin/dashboard.py`
介面：`start_dashboard(get_state, host="0.0.0.0", port=5000)`：在背景 daemon thread 啟動 Flask（`use_reloader=False`、`threaded=True`），不阻塞呼叫者。`get_state` 是回傳 0.3 `state` 字典的函式（由 B 的 `SampleMonitor.get_state` 提供）。
路由：
- `GET /api/state`：回傳 `get_state()` 的 JSON；`get_state` 丟例外時回 `{"error": "..."}` 與 HTTP 500，不要讓 Flask 崩潰。
- `GET /`：單一 HTML 頁（CSS、JS 全部內嵌），每秒 `fetch('/api/state')` 更新畫面。
- `GET /healthz`：回 `ok`。

### D2（S1，約 90 分鐘）離線 demo 模式 `tools/dashboard_demo.py`
讓你不需要 B 就能開發，也是 Demo 的備援。
1. 讀 CSV（`SmarTest/Case_Smt870/src/TestCase1/TestCase1_OfflineData.csv`），用 `Detector` 逐 touchdown 重播（4 顆 DUT 一組，site = DUT 序號 % 4 + 1，x/y 取 CSV 的 `x`、`y` 列）。
2. 每個 touchdown 產生一個 `Record`（含 `dies`），維護 0.3 結構的 `state`。
3. 用 `start_dashboard` 啟動，並以固定間隔（可用參數調整，預設 1 秒 / touchdown）推進，播完可循環。
4. 支援 `--inject drift|variance|site` 合成注入（用 `tools/inject_anomalies.py`），展示不同異常類型。
執行：`cd Edge/oneAPI_py3.10 && python3 tools/dashboard_demo.py` → 瀏覽器開 `http://localhost:5000`。

### D3（S1 到 S2，約 3 小時）畫面內容
1. **頂部狀態列**：lot、wafer、目前 touchdown、異常 touchdown 數；異常時整條變紅並顯示 `latest.message`；`detector.load_error` 不為空時顯示黃色警告列。
2. **Wafer map（內嵌 SVG）**：以 `dies` 的 `x`、`y` 畫格子（CSV 內 x 約 0 到 11、y 約 0 到 8；範圍用資料動態計算）。灰色 = 尚未測；綠色 = 正常；紅色 = 該 touchdown 有異常且該 site 在 `top_alerts` 中；橘色 = 該 touchdown 異常但非該 site。滑鼠移上去顯示 `part_id`、site、bin。
3. **Site 狀態**：4 個方塊（site 1 到 4），顯示最近一次是否有該 site 的告警。
4. **分數趨勢（內嵌 SVG 折線圖）**：`recent` 的 `score` 對 `td`，異常點標紅，`onset` 標記一個小三角形。
5. **告警表**：最新 `top_alerts` 前 5 筆（kind、test、site、score）。
6. 版面要能在 1280×720 投影時看清楚（字大、對比高）。

### D4（S2，約 30 分鐘）接進 `bin/main.py`
在 `main()` 內 `Interface.registerMonitor(myMonitor)` 之後加入（包 `try/except`，失敗只記 log）：
```python
try:
    from dashboard import start_dashboard
    start_dashboard(myMonitor.get_state)
except Exception:
    logging.exception("dashboard failed to start")
```
`myMonitor.get_state` 由 B 提供；B 完成前用 `getattr(myMonitor, "get_state", lambda: {})` 保護。**不可讓 `signal.pause()` 之前的流程被 Flask 阻塞。**

### D5（S2，約 30 分鐘）開放連接埠（交給 E 套用）
依 `doc/ONEAPI_Manual.pdf` 第 73–74 頁的格式，在 `SmarTest/app_descriptor.json` 的 `requirements` 加：
```json
"requirements": {"gpu": false, "exposed_ports": [5000], "mapped_ports": ["5000:5000"]}
```
把片段和「請確認 `mapped_ports` 的語意與 Edge 主機位址」交給 E（可先問講師）。
**怎麼從外面看到頁面**（擇一，需與 E 一起確認 Edge 位址）：Host 上的 Firefox 直接開 Edge 位址的 5000 埠；或在你的電腦用 SSH 通道：`ssh -N -L 5000:<Edge位址>:5000 advantest`，再開 `http://localhost:5000`。

### D6（S3，約 2 小時）測試與打磨
1. `tests/test_dashboard.py`（用 Flask test client）：`/api/state` 回傳結構正確；`get_state` 丟例外時回 500 且服務仍可用；`/` 回傳 HTML 且**不含任何 `http://` 或 `https://` 外部資源**（用字串檢查）。
2. 接上 B 的真實 `get_state()`，與離線 demo 對照畫面是否一致。
3. 打磨：異常的視覺對比、`onset` 提示、空資料（尚未收到事件）時的畫面。
4. 效能：`/api/state` 回傳大小 < 100 KB，`recent` 最多 50 筆。

### D7（S4）Demo 素材
1. 三張關鍵截圖：正常、異常起點（DUT 5–8）、異常持續。
2. 一段 30 秒的螢幕錄影（離線 demo 模式即可）。
3. 交給 E 放進簡報。

## 5. 交接與依賴
- **B → 你**：`get_state()` 實作完成的通知（在那之前用離線 demo 開發）。
- **你 → E**：D5 的 `app_descriptor.json` 片段。
- **你 → E**：D7 的截圖與影片。

## 6. 常見坑
- 內嵌 HTML 裡的 JS 用 Python 字串包起來時，注意 `{`、`}` 與 f-string 衝突；建議整份 HTML 用普通字串常數，不要用 f-string。
- `get_state()` 是在別的執行緒被呼叫的，B 必須回傳複本；你也不要修改收到的字典。
- 容器重啟或重新部署後頁面會重置，這是預期行為。
- 不要在 `bin/` 留下 `__pycache__` 或測試暫存檔。
