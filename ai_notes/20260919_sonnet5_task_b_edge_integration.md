# 任務書 B：Edge 整合（`sample.py`：場景一 + 場景二接線）

> 你是 **B**。你負責 `Edge/oneAPI_py3.10/bin/sample.py`、`tests/test_sample_local.py`、`tests/fake_events.py`（新增）。你是整條關鍵路徑的中心：A 的偵測器與 E 的預測器 → 你的接線 → C 的部署 → 驗證。
> **2026-09-19 更新**：題目新增場景二（預測溫度）與 wafer 層級報告，你要多接 `predict` 請求、良率與 wafer 結束事件。

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
把偵測器與預測器接進 `sample.py`：場景一（偵測、良率、wafer 報告、`set_message`）與場景二（`predict` 請求、`set_wait`）；提供 `get_state()` 給 D；全部可以在本機用假事件測試。

## 2. 你擁有的檔案
`bin/sample.py`、`tests/test_sample_local.py`、`tests/fake_events.py`（新增）。`bin/main.py` 由 D 改一行啟動儀表板，你不動。
**重要**：目前 `sample.py` 是原版。先前的 TODO 註解與固定訊息測試樁在 `git stash` 裡，**不要套用**。

## 3. 任務清單

### B1（S1，約 90 分鐘）假事件工具 `tests/fake_events.py`
讓你和其他人不需要真實 Nexus 就能驅動 `SampleMonitor`。假物件要提供 `sample.py` 用到的欄位：
- **LotStart**：`get_LotId`、`get_TotalHeadSiteList`（回傳 site 清單，格式待 C 的探查確認）；**WaferStart**：`get_WaferId`；**WaferEnd**：`get_WaferId`、`get_TestedCount`、`get_GoodCount`
- **TestStart**：`get_ResultCount`、`query_HeadSite(i)`、`query_XCoord(i)`、`query_YCoord(i)`
- **TestEnd**：上述加 `query_PartFlag`、`query_SBinResult`、`query_HBinResult`、`query_PartId`、`query_TestTime`、`query_NumOfTest`、`query_PartText`
- **ParametricTest**：`get_ResultCount`、`query_HeadSite`、`query_TestNumber`、`query_TestText`、`query_LowLimit`、`query_HighLimit`、`query_Unit`、`query_TestFlag`、`query_Result`、`query_ResultScaling`、`query_LowLimitScaling`、`query_HighLimitScaling`、`query_ParamFlag`、`query_TestSuite`、`query_MeasurementName`
步驟：
1. 寫 `FakeData(kind, rows)`（`getType()` 回傳對應 `DataType` 常數；`tests/test_sample_local.py` 已示範用 `sys.modules` 注入假 `oneapi`）與 `FakeTestCell(testerId="group-1", testerIP="127.0.0.1")`。
2. 寫 `csv_touchdown_events(csv_path)`：讀 `SmarTest/Case_Smt870/src/TestCase1/TestCase1_OfflineData.csv`，每 4 顆 DUT 一個 touchdown，依序產生 `TESTSTART` → 每個測項一筆 `MEASURED_PARAMETRIC` → `TESTEND`；整片結束再產生 `WAFEREND`。site = `DUT 序號 % 4 + 1`。
3. 寫 `predict_request(target)`：回傳 JSON 字串 `{"key": "predict", "data": target}`，用來測 `consumeTPRequest`。
**驗收**：把整份 CSV 重播一次，不出錯。

### B2（S1 到 S2，約 3 小時）場景一接線
1. **`__init__`**：`self.detector = Detector.load()`；`self.tester_id = None`；`self.recent = deque(maxlen=50)`；`self.wafer_reports = deque(maxlen=10)`；`self.totals`、`self.lot`、`self.wafer`、`self.sites`、`self.dies`。
2. **測項 key**：檔案上方加 `make_test_key(number, suite, measurement)`，預設 `f"{number}_{suite}#{measurement}"`（偵測器會自動去掉開頭 `數字_`）。**暫定規則**，等 C 的探查結果；對不上時偵測器會自動暖機，不會壞掉。
3. **`consumeData`**：分派前先存 `self.tester_id = tc.testerId`。
4. **`consumeLotStart`**：保留 `mTouchdownCnt = 0`；`self.detector.reset("lot")`；存 `self.lot` 與 `self.sites`（由 `get_TotalHeadSiteList()`；場景二要用）。**`consumeWaferStart`**：`reset("wafer")`、存 `self.wafer`。
5. **`consumeTestStart`**：保留 `mTouchdownCnt += 1`；清空 `self.dies`；讀出每個 site 的 x、y；`self.predictor.begin_touchdown()`（B3）。
6. **`consumeParametricTest`**：在 callback 內**立刻**讀出 `query_TestNumber`、`query_TestSuite`、`query_MeasurementName`、`query_Result`、site（`toSite(query_HeadSite(i))`）；`self.detector.update(...)`；同時 `self.predictor.observe(...)`（B3）；若這筆是 sensor 目標測項，補上對應 `PredRecord` 的 `actual` 與 `error`。拿掉逐欄位 `print`（改成 `ACS_DEBUG_EVENTS=1` 才印）。
7. **`consumeTestEnd`**：對每個 site 呼叫 `self.detector.update_device(site, passed, td)`（`passed` 用 `is_pass(part_flag, sbin)` 小函式，暫定 `PartFlag == 0`，等 C 確認）；`verdict = self.detector.end_touchdown()`；組出 `Record`（含 `dies`）放進 `self.recent`、更新 `totals`；`verdict["onset"]` 時 `ActionManager.set_message(self.tester_id, verdict["message"])`；`verdict["cleared"]` 時 `ActionManager.clean(self.tester_id)`。
8. **`consumeWaferEnd`**：`report = self.detector.end_wafer()`，放進 `self.wafer_reports`；並用 `set_message` 送出 `report["summary"]`（wafer 層級的通知，題目要求「整理成報告」）。
9. **保護**：每個偵測器 / 預測器呼叫包 `try/except`，出錯只 `logging.exception`，**不可讓事件處理中斷**；量測每個 callback 耗時，超過預算（單次 `consumeParametricTest` > 5 ms 或整個 touchdown > 150 ms）記警告。

### B3（S2，約 3 小時）場景二接線：`predict` 請求
**協定（題目第 5 頁範例）**：測試程式把要預測的測項編號送來，容器預測各 site 的值，放在 `set_wait` 的說明字串回傳。
1. `__init__` 加 `self.predictor = Predictor.load()`（`load_error` 記錄即可，失敗不中斷）；`self.predictions = deque(maxlen=30)`；等待秒數 `self.predict_wait = int(os.environ.get("ACS_PREDICT_WAIT", "10"))`。
2. 在 `consumeTPRequest` 加分支（放在 `list` 分支前，不動其他分支）：
```python
elif key == "predict":
    res = self.predictor.predict(str(data), self.sites)
    message = f"prediction {data}: " + " ".join(f"({s},{v:.2f})" for s, v in sorted(res["values"].items()))
    ActionManager.set_wait(tc.testerId, self.predict_wait, message)
    response = ActionManager.get(tc.testerId)
```
   `data` 可能是字串或整數、可能是 `"100_Main.sensor1_CP"` 或 `"sensor1"`，交給 `Predictor` 正規化；預測失敗要有保底（回傳訓練均值、`fallback=True`），**不可回傳空值或丟例外**。
3. 記錄一筆 `PredRecord`（`actual` / `error` 等實際值到達後在 `consumeParametricTest` 補上，見 B2 第 6 點）。
4. **時序風險（請務必量測並回報）**：`predict` 請求走 TPService（ZMQ），量測資料走 Kafka，是不同通道。請求到達時，該 touchdown 前面測項的資料是否已被 `consumeParametricTest` 收到？用 `res["missing"]` 記錄缺特徵的次數；若常常缺，通知 E 與 C，需要決定保底策略（例如改用上一個 touchdown 的特徵或均值）。
5. **時間預算**：`consumeTPRequest` 是阻塞的，一個 touchdown 有 6 次預測請求；`predict()` 必須 < 5 ms（E 保證），你要量測整個分支耗時並記 log。
6. 用 `sensor1` 到 `sensor6` 各送一次請求，確認回傳字串格式與 site 數量正確。

### B4（S2，約 90 分鐘）測試
擴充 `tests/test_sample_local.py`（取代失敗的舊測項）：
1. 重播 CSV：第 0 個 touchdown 不寫訊息；第 1 個 touchdown（DUT 5–8）`set_message` 恰好一次；連續異常期間不重複寫入；`cleared` 時呼叫 `clean`。
2. `WaferEnd` 後 `wafer_reports` 有一筆且 `set_message` 送出摘要；`LotStart` 後偵測器被重置。
3. `predict` 請求：回傳非空字串、含所有 site；預測器丟例外時仍回傳保底值且 callback 不外洩例外。
4. 偵測器 / 預測器丟例外時 callback 不外洩例外。
5. `get_state()` 結構符合 0.3，且回傳的是複本。
6. 效能：用假事件量整個 touchdown 的耗時（目標 < 150 ms）。
**驗收**：`python3 -m unittest discover -s tests` 全部通過（含 A 的 `test_detector`、E 的 `test_predictor`）。

### B5（S2）交接
通知 C：分支可部署（附本機測試輸出）；通知 D：`get_state()` 已實作；寫 `ai_notes/` 紀錄。

### B6（S3）整合除錯
依 C 回報修 bug；key 組法、`is_pass`、`sites` 格式依 C 的探查結果調整；持續記錄 `predict` 的缺特徵率與耗時。

### B7（S4）演練
在 C 主持下完整跑一次 `prod_run`；準備備援（真機出狀況時，用 CSV 重播 + 儀表板展示）。

## 4. 交接與依賴
- **A → 你**：`onset`/`cleared`/`info()`（A1）、`update_device`（A4）、`end_wafer`（A5）。在那之前先照 0.3 寫，用暫時 stub。
- **E → 你**：`Predictor`（`bin/predictor.py`）與 `predictor.json`。同樣先照 0.3 寫。
- **C → 你**：真實事件的 key / 單位 / site 對應 / `PartFlag` 語意 / `TotalHeadSiteList` 格式 / `predict` 請求的實際送法。
- **你 → D**：`get_state()`。**你 → C**：可部署的分支。

## 5. 常見坑
- `consumeTestEnd`、`consumeParametricTest` 沒有收到 `tc`；需要 testerId 就存成實例變數。
- Manual 規定：欄位必須在 callback 內立刻讀出，離開後資料會被清掉。
- `ActionManager.get` 只能在 `consumeTPRequest` 呼叫（manual 規定）。
- `consumeTPRequest` 必須回傳字串；現有 `key == "timeout"` 分支會 `sleep`，不要動。
- `query_Result` 可能需要搭配 `query_ResultScaling`，等 C 確認再決定。
- 不要在 `consumeData` 分派路徑裡做網路、檔案或大量列印。
- `sample.py` 是 SDK 附的範例檔，保留原有的 DFF / SFTP 註解與函式，不要刪。
