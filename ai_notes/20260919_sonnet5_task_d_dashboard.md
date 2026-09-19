# 任務書 D：儀表板與異常報告（占 25% 的「報告呈現」）

> 你是 **D**。你負責 `Edge/oneAPI_py3.10/bin/dashboard.py`、`bin/report.py`（新增）、`tools/dashboard_demo.py`、`tests/test_dashboard.py`，以及 `bin/main.py` 裡啟動儀表板的那一小段。你可以**完全不依賴 B**，用假資料獨立開發。
> **2026-09-19 更新**：題目要求把異常「整理成報告」通知特定人員或供查詢，且「異常報告的呈現是否新穎」占 25%，是創新項中最高的單項。這是你這份任務書最重要的部分。另外多了場景二的「預測 vs 實際」面板。

---

## 0. 共同背景（五份任務書相同）

**專案**：Advantest 黑客松 grp1。官方題目（`ai_notes/Question_20260919.pdf`）有兩個場景：
1. **場景一**：在模擬量產中即時偵測異常，整理成報告，通知特定人員或供其查詢。
2. **場景二**：預測 IC 的溫度（`sensor1`～`sensor6` 六個測項），把結果通知機台軟體。

**評分**：完成度 60%（符合場景 10%、能在 ACS Gemini 順利運行 25%、正確的時機偵測問題或預測結果 25%）；創新 40%（資料分析方法 15%、**異常報告的呈現是否新穎 25%**）。
**資料**：25 片 wafer × 80 顆 × 約 3000 測項的訓練 log，**有 wafer 層級標籤**：W1 Site unbalance；W3、W9 Low yield（yield < 80）；W14 Mean Trend Up；W18 Mean Trend Down；W23 Stdev Trend Up；W25 Stdev Trend Down；其餘 18 片 Normal。**訓練 log 目前不在 repo，需向主辦方取得（E0）**。repo 內的 `TestCase1_OfflineData.csv` 是其中的 W1。
**不可洩漏規則**：預測 sensorN 不可使用尚未執行的測項。流程：Suite1–14 → IDDQ_flow →〔predict1 → sensor1 → subflow1〕→ … →〔predict6 → sensor6 → subflow6〕。
**現況**：場景一偵測器已完成一部分（`bin/detector.py` 等；缺標準差下降、良率過低、wafer 分類，見 `ai_notes/20260918_sonnet5_phase1_spec.md` 第 0、4.1、12 節）；場景二、wafer 報告、預測請求協定都還沒做。
**角色與時段**：A 場景一偵測器｜B Edge 整合（`sample.py`）｜C 真機與部署｜D 儀表板與報告｜E 場景二預測與 Demo。時段：S0 啟動 → S1 平行開發 → S2 整合一 → S3 整合二/驗證 → S4 凍結與 Demo。

### 0.1 與 AI 協作的規則（來自 `AGENTS.md`）
1. 請你的 AI 先讀 `AGENTS.md` 與本任務書。建議第一句話：「先讀 AGENTS.md 和這份任務書，列出你打算做的步驟給我確認，確認後才動手。」
2. 每個人開自己的分支：`git checkout -b <GitHub帳號>_<AI模型名>`（例：`feedc0de_gemini3flash`）。所有修改都在分支上，**commit / push 由人類執行**（push 用 `git push -u origin <分支名>`）。
3. 程式碼註解只用英文、單行、量不超過程式碼。
4. 不要直接在 VM 上改程式；本機開發、測試，再同步。**不要把密碼、金鑰寫進 repo**（工作坊密碼在 `doc/WorkShop_Material.pdf` 第 21 頁）。
5. 完成一項工作後，在 `ai_notes/` 新增 `YYYYMMDD_<模型名>_<功能>.md`，**繁體中文**，含：變更摘要、修改與新增檔案、技術細節與邏輯、待執行事項與注意事項。
6. `Monitor` 的 callback 是阻塞式：重運算不可卡住 `consumeData`（AGENTS.md 明文規定）。

### 0.2 環境速查（實測，2026-09-19）
- **Host Controller**：`ssh advantest`（`user@100.114.133.30`，金鑰 `~/.ssh/ssh_private_key`，向隊友取得設定）。主機名 `group-1`，RHEL 7.9、Python 3.6，專案在 `~/Case_Event/`。**帳號 `user` 五人共用，可能有人正在跑 SmarTest**；`user` 沒有 docker 權限，`tag.sh` 需 `sudo`（權限未確認）；Host 可連外網。
- **Edge 開發 pod**：`ssh -J advantest -p 29022 debugger@advantestcell.local`（密碼見教材第 21 頁，登入時手動輸入）。Ubuntu 22.04、Python 3.10、有 `numpy`/`flask`/`paramiko`/`jsonschema`/`requests`；**沒有** `pandas`/`scikit-learn`/`matplotlib`/`pillow`；**不能連外網**；只有 `/home/debugger/project` 在容器重啟後保留。
- **本機測試**：`cd Edge/oneAPI_py3.10 && python3 -m unittest discover -s tests`（`test_sample_local.py` 有 1 項已知失敗，B 會取代）。
- **打包**：`Dockerfile` 是 `COPY bin/. ./bin`，`bin/` 底下所有檔案都會進 image。執行期相依只能用標準函式庫 + `numpy` + `flask`。訓練與分析工具放 `tools/`（不進 image），本機可用 `numpy`。

### 0.3 共同介面契約（改動前必須通知相關人，並同步五份任務書）
```python
# ---- 偵測器（A 擁有）----
det = Detector.load(path=None)                  # 預設 bin/model/baseline.json；失敗不丟例外，det.load_error 有訊息
alerts = det.update(test_key, site, value, seq) # 逐筆量測，回傳「新觸發」的 Alert 清單
det.update_device(site, passed, seq)            # 每顆 device 測完呼叫一次（良率偵測用）                 [A4 新增]
verdict = det.end_touchdown()                   # 每個 touchdown 結束呼叫一次
report = det.end_wafer()                        # 每片 wafer 結束呼叫一次，回傳 WaferReport               [A5 新增]
det.reset(scope="lot")                          # "lot" 或 "wafer"
det.info()                                      # {"monitored_tests": int, "baseline_tests": int, "load_error": str|None}   [A1 新增]

Alert   = {"kind": "outlier|mean_shift|variance_change|mean_drift|site_imbalance|low_yield", "test": str,
           "site": int|None, "score": float, "seq": int, "direction": "up|down"|None}          # direction、low_yield 為新增
Verdict = {"anomaly": bool, "onset": bool, "cleared": bool, "score": float, "n_alerts": int,
           "top_alerts": [Alert, ...最多 5 筆], "message": str(<=200 字元)}                      # onset / cleared 為 A1 新增
WaferReport = {"wafer": str|None, "label": "Normal|Site unbalance|Low yield|Mean Trend Up|Mean Trend Down|Stdev Trend Up|Stdev Trend Down",
               "onset_td": int|None, "confidence": float, "yield": float|None, "n_devices": int,
               "evidence": [Alert, ...最多 5 筆], "summary": str}

# ---- 預測器（E 擁有）----
pred = Predictor.load(path=None)                # 預設 bin/model/predictor.json；失敗不丟例外，pred.load_error
pred.begin_touchdown()                          # 每個 touchdown 開始（TestStart）呼叫
pred.observe(test_key, site, value)             # 每筆量測結果餵入（只保存有用的特徵），O(1)
res = pred.predict(target, sites)               # target 如 "100_Main.sensor1_CP" 或 "sensor1"
                                                # → {"target": str, "values": {site: float}, "fallback": bool, "missing": int}
pred.info()
```
`SampleMonitor.get_state()`（B 實作、D 使用）：
```python
{"lot": str|None, "wafer": str|None, "touchdown": int,
 "totals": {"touchdowns": int, "anomaly_touchdowns": int},
 "latest": Record|None, "recent": [Record, ...最近至多 50 筆，舊到新],
 "wafer_reports": [WaferReport, ...最近 10 片], "predictions": [PredRecord, ...最近 30 筆],
 "detector": {"monitored_tests": int, "load_error": str|None}, "predictor": {"load_error": str|None}}
Record = {"td": int, "time": float, "anomaly": bool, "onset": bool, "cleared": bool, "score": float,
          "n_alerts": int, "top_alerts": [Alert, ...], "message": str,
          "dies": [{"site": int, "x": int|None, "y": int|None, "part_id": int|None, "sbin": int|None}, ...]}
PredRecord = {"td": int, "time": float, "target": str, "values": {site: float},
              "actual": {site: float}|None, "error": {site: float}|None, "fallback": bool}     # actual / error 在實際值到達後補上
```
`get_state()` 必須回傳快照（複本），且成本低。
**回傳給機台的訊息格式**：場景一 `ActionManager.set_message(tc.testerId, message)`；場景二 `ActionManager.set_wait(tc.testerId, wait, "prediction <target>: (1,34.12) (2,34.08) ...")` 再 `ActionManager.get(tc.testerId)`（題目第 5 頁範例）。

### 0.4 回報格式
完成一項就回報：**完成了什麼**、**驗收結果（附指令輸出）**、**未完成或風險**。契約異動要先講，再改。

---

## 1. 你的目標與完成定義
1. 一個能在 Edge 容器裡跑、**不需要任何外部資源**的即時儀表板。
2. **異常報告**：每片 wafer 結束時產生一份清楚、有辨識度的報告，可在頁面查詢、可下載，讓「特定人員」一眼看懂發生什麼事、影響哪裡、該做什麼。
3. **預測面板**：場景二的預測 vs 實際。
4. 離線 demo 模式（不連 Nexus）當 Demo 備援。

## 2. 你擁有的檔案
`bin/dashboard.py`、`bin/report.py`、`tools/dashboard_demo.py`、`tests/test_dashboard.py`；`bin/main.py` 只加下面 D5 的那一小段；`SmarTest/app_descriptor.json` 的修改**只提供片段給 C**（C 負責部署）。

## 3. 硬性限制
- **Edge 容器不能連外網**：不可使用 CDN（Chart.js、Bootstrap、Google Fonts 等）；所有 CSS / JS 內嵌。
- **沒有 `matplotlib` / `pillow`**：圖用內嵌 SVG（純字串組出來）。
- 只能用標準函式庫 + `flask`（pod 上是 3.1.2）；Python 3.10 相容。
- 儀表板出任何錯都不能影響偵測主流程。

## 4. 任務清單

### D1（S1，約 2 小時）`bin/dashboard.py`
介面：`start_dashboard(get_state, host="0.0.0.0", port=5000)`：在背景 daemon thread 啟動 Flask（`use_reloader=False`、`threaded=True`），不阻塞呼叫者。`get_state` 是回傳 0.3 `state` 字典的函式（由 B 的 `SampleMonitor.get_state` 提供）。
路由：`GET /api/state`（回傳 `get_state()` 的 JSON；丟例外時回 `{"error": "..."}` 與 HTTP 500，服務不可崩潰）、`GET /`（單一 HTML 頁，每秒輪詢）、`GET /healthz`（回 `ok`）。

### D2（S1，約 90 分鐘）離線 demo 模式 `tools/dashboard_demo.py`
讓你不需要 B 也能開發，也是 Demo 的備援。
1. 讀 `TestCase1_OfflineData.csv`，用 `Detector` 逐 touchdown 重播（4 顆 DUT 一組，site = DUT 序號 % 4 + 1，x/y 取 CSV 的 `x`、`y` 列），產生 0.3 結構的 `state`。
2. 用 `start_dashboard` 啟動，可調間隔（預設 1 秒 / touchdown），播完可循環。
3. `--inject drift|variance|site|lowyield` 用 `tools/inject_anomalies.py` 合成不同異常；`--wafers <資料夾>` 在 E 取得 25 份標籤 wafer 後，可依序播放多片 wafer（展示 Normal 與各類異常）。
4. 場景二先用假的預測值（真實值加雜訊）展示面板。
執行：`cd Edge/oneAPI_py3.10 && python3 tools/dashboard_demo.py` → 瀏覽器開 `http://localhost:5000`。
**在 A、E 的模組完成前**，`WaferReport` 與預測資料先用你自己的假資料（依 0.3 的格式）。

### D3（S1 到 S2，約 3 小時）即時畫面
1. **頂部狀態列**：lot、wafer、目前 touchdown、異常 touchdown 數；異常時整條變紅並顯示 `latest.message`；`detector.load_error` / `predictor.load_error` 非空時顯示黃色警告列。
2. **Wafer map（內嵌 SVG）**：以 `dies` 的 `x`、`y` 畫格子（範圍由資料動態計算）。灰 = 尚未測；綠 = 正常；紅 = 該 touchdown 異常且該 site 在 `top_alerts`；橘 = 異常但非該 site。滑鼠移上顯示 `part_id`、site、bin。
3. **Site 狀態**：4 個方塊，顯示最近一次是否有該 site 的告警。
4. **分數趨勢（內嵌 SVG 折線）**：`recent` 的 `score` 對 `td`，異常點標紅，`onset` 標小三角形。
5. **告警表**：最新 `top_alerts` 前 5 筆（kind、direction、test、site、score）。
6. 版面要能在 1280×720 投影時看清楚（字大、對比高）。

### D4（S1 到 S3，約 5 小時）**異常報告** `bin/report.py` 與報告頁（重點）
**設計目標**：讓「特定人員」不用看數據，就知道這片 wafer 出了什麼事、從什麼時候開始、影響哪裡、該做什麼。
1. **報告內容**（由 `WaferReport` 加上你的呈現）：
   - 標題與結論：wafer、`label`（用顏色與圖示區分 7 類）、信心度、良率。
   - **時間線**：`onset_td` 標在 touchdown 軸上，顯示「第幾顆 DUT 起異常」。
   - **影響範圍**：哪些 site、哪些 pin 群組、多少個測項（由 `evidence` 與統計整理）；在 wafer map 上標出受影響的 die。
   - **證據圖**：代表性測項的走勢（內嵌 SVG，標示正常範圍與異常區段）。
   - **白話說明與建議動作**（規則式文字，依 `label` 而定），例如 Site unbalance → 「檢查 site N 的探針卡或接觸」；Low yield → 「檢查良率下降的起點與相關測項」；Mean/Stdev Trend → 「檢查設備或製程是否在漂移」。這些文字要清楚標示是建議而非結論。
2. **可查詢**：`GET /reports`（列出最近的 wafer，可依標籤篩選）、`GET /api/reports`（JSON）。
3. **可下載 / 可分享**：`GET /report/<wafer>.html`（**單一自足的 HTML**，無外部資源，可直接寄給人）、`GET /report/<wafer>.json`。
4. **通知**：wafer 結束時 B 會用 `set_message` 送出 `summary` 到機台；儀表板上異常時要有醒目的橫幅。如果要寫檔，寫到容器內固定資料夾 `reports/`，並在畫面上說明容器重啟會清空。
5. **多片總覽（Demo 亮點）**：一頁顯示多片 wafer 的標籤色帶（像 25 格的熱度圖）與各自的 `label`，一眼看出哪幾片有問題；離線 demo 模式播放 25 片標籤 wafer 時特別好看。
6. 建議加入的「新穎」元素（擇 2 到 3 項，做得精緻比全做重要）：異常起點動畫回放、die 層級歸因、把報告用自然語言摘要、依嚴重度排序的待處理清單、報告之間的比較。
**驗收**：對合成的 7 類 wafer 各產生一份報告，內容正確、可下載、無外部資源；請不熟悉專案的隊友看報告，30 秒內能說出「這片有什麼問題」。

### D5（S2，約 30 分鐘）接進 `bin/main.py`
在 `main()` 內 `Interface.registerMonitor(myMonitor)` 之後加入（包 `try/except`）：
```python
try:
    from dashboard import start_dashboard
    start_dashboard(myMonitor.get_state)
except Exception:
    logging.exception("dashboard failed to start")
```
B 完成前用 `getattr(myMonitor, "get_state", lambda: {})` 保護。**不可讓 `signal.pause()` 之前的流程被 Flask 阻塞。**

### D6（S2，約 30 分鐘）開放連接埠（交給 C 套用）
依 `doc/ONEAPI_Manual.pdf` 第 73–74 頁格式，在 `SmarTest/app_descriptor.json` 的 `requirements` 加：
```json
"requirements": {"gpu": false, "exposed_ports": [5000], "mapped_ports": ["5000:5000"]}
```
把片段和「請確認 `mapped_ports` 的語意與 Edge 主機位址」交給 C（可先問講師）。**怎麼從外面看到**（擇一，需與 C 確認 Edge 位址）：Host 上的 Firefox 直接開 Edge 位址的 5000 埠；或 SSH 通道：`ssh -N -L 5000:<Edge位址>:5000 advantest`，再開 `http://localhost:5000`。

### D7（S2 到 S3，約 2 小時）預測面板（場景二）
1. 表格：六個 sensor × 各 site 的**預測值、實際值、誤差**（`PredRecord` 的 `values`、`actual`、`error`）；`fallback` 為真時標示「保底值」。
2. 折線圖：預測 vs 實際隨 touchdown 的變化；顯示累計 RMSE / MAE。
3. 注意 `actual` 是實際值到達後才補上，畫面要能處理「尚未到達」。

### D8（S3，約 2 小時）測試與打磨
1. `tests/test_dashboard.py`（Flask test client）：`/api/state`、`/reports`、`/report/<wafer>.html` 結構正確；`get_state` 丟例外時回 500 且服務仍可用；HTML **不含任何 `http://` 或 `https://` 外部資源**（字串檢查）。
2. 接上 B 的真實 `get_state()`，與離線 demo 對照畫面是否一致。
3. 空資料（尚未收到事件）時的畫面；`/api/state` 大小 < 100 KB。

### D9（S4）Demo 素材
三張關鍵截圖（正常、異常起點、異常持續）、一份完整的異常報告範例（HTML）、一段 30 秒螢幕錄影（離線 demo 模式）；交給 E 放進簡報。

## 5. 交接與依賴
- **A → 你**：`WaferReport` 格式與 `summary`（A5）。**E → 你**：預測資料格式（`PredRecord`）與 25 份標籤 wafer。**B → 你**：`get_state()`。
- **你 → C**：D6 的 `app_descriptor.json` 片段。**你 → E**：D9 的素材。

## 6. 常見坑
- 內嵌 HTML 裡的 JS 用 Python 字串包起來時，注意 `{`、`}` 與 f-string 衝突；整份 HTML 用普通字串常數。
- `get_state()` 在別的執行緒被呼叫，B 必須回傳複本；你也不要修改收到的字典。
- 容器重啟或重新部署後頁面與報告會重置，這是預期行為。
- 報告文字用繁體中文；`label` 用契約裡的英文字串當鍵，顯示時再對應中文。
- 不要在 `bin/` 留下 `__pycache__` 或測試暫存檔。
