# 任務書 B：Edge 整合（`sample.py` 接線）

> 你是 **B**。你負責 `Edge/oneAPI_py3.10/bin/sample.py`、`tests/test_sample_local.py`、`tests/fake_events.py`（新增）。你是整條關鍵路徑的中心：A 的偵測器 → 你的接線 → E 的部署 → C 的驗證。

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
把偵測器接進 `sample.py`：事件進來 → 偵測 → 轉為異常時寫 `ActionManager.set_message`；提供 `get_state()` 給 D；全部可以在本機用假事件測試。

## 2. 你擁有的檔案
`bin/sample.py`、`tests/test_sample_local.py`、`tests/fake_events.py`（新增）。`bin/main.py` 由 D 改一行啟動儀表板，你不動。
**重要**：目前 `sample.py` 是原版。先前的 TODO 註解與固定訊息測試樁在 `git stash` 裡，**不要套用**。

## 3. 任務清單

### B1（S1，約 90 分鐘）假事件工具 `tests/fake_events.py`
讓你和其他人不需要真實 Nexus 就能驅動 `SampleMonitor`。`sample.py` 目前會呼叫的欄位如下，假物件要提供同名方法：
- **TestStart**：`get_TimeStamp`、`get_ResultCount`、`query_HeadSite(i)`、`query_XCoord(i)`、`query_YCoord(i)`
- **TestEnd**：上述加上 `query_PartFlag`、`query_NumOfTest`、`query_SBinResult`、`query_HBinResult`、`query_TestTime`、`query_PartId`、`query_PartText`
- **ParametricTest**：`get_ResultCount`、`query_HeadSite`、`query_TestNumber`、`query_TestText`、`query_LowLimit`、`query_HighLimit`、`query_Unit`、`query_TestFlag`、`query_Result`、`query_ResultScaling`、`query_LowLimitScaling`、`query_HighLimitScaling`、`query_ParamFlag`、`query_TestSuite`、`query_MeasurementName`
- **LotStart / WaferStart**：`get_LotId`、`get_WaferId`（其餘欄位可回傳空值）
步驟：
1. 寫 `FakeData(kind, rows)`，`getType()` 回傳對應的 `DataType` 常數（`tests/test_sample_local.py` 已示範如何用 `sys.modules` 注入假的 `oneapi`）。
2. 寫 `FakeTestCell(testerId="group-1", testerIP="127.0.0.1")`。
3. 寫 `csv_touchdown_events(csv_path)`：讀 `SmarTest/Case_Smt870/src/TestCase1/TestCase1_OfflineData.csv`（每列一個測項、每欄一顆 DUT；`x`、`y` 列是座標），以 4 顆 DUT 為一個 touchdown，依序產生 `TESTSTART` → 每個測項一筆 `MEASURED_PARAMETRIC`（4 個 site 的值）→ `TESTEND`。site 對應為 `DUT 序號 % 4 + 1`。
**驗收**：用它把整份 CSV 重播一次，不出錯。

### B2（S1 到 S2，約 3 小時）`sample.py` 接線
1. **`__init__`**：`self.detector = Detector.load()`；`self.tester_id = None`；`self.recent = deque(maxlen=50)`；`self.totals`、`self.lot`、`self.wafer`、`self.dies`（本 touchdown 的晶粒資訊暫存）。
2. **測項 key**：在檔案上方加 `make_test_key(number, suite, measurement)`，預設 `f"{number}_{suite}#{measurement}"`（偵測器會自動去掉開頭的 `數字_`）。**這只是暫定規則**：基準線的 key 是 `Main.Suite1#CP` 這種格式，但真實事件的欄位（尤其 `#` 後面是什麼）要等 C 的探查結果；對不上時偵測器會自動暖機（前 40 個值），不會壞掉。
3. **`consumeData`**：分派前先存 `self.tester_id = tc.testerId`（`consumeTestEnd` 沒有收到 `tc`）。
4. **`consumeTestStart`**：保留 `mTouchdownCnt += 1`；清空 `self.dies`；讀出每個 site 的 x、y 存起來。
5. **`consumeParametricTest`**：在 callback 內**立刻**讀出 `query_TestNumber`、`query_TestSuite`、`query_MeasurementName`、`query_Result`、site（`toSite(query_HeadSite(i))`）；呼叫 `self.detector.update(key, site, value, self.mTouchdownCnt)`。拿掉逐欄位 `print`（改成 `ACS_DEBUG_EVENTS=1` 才印）；每個 touchdown 有上千次呼叫，印字會拖慢阻塞的 callback。
6. **`consumeTestEnd`**：`verdict = self.detector.end_touchdown()`；組出 `Record`（含本 touchdown 的 `dies`）放進 `self.recent`、更新 `totals`；若 `verdict["onset"]`：`ActionManager.set_message(self.tester_id, verdict["message"])`；若 `verdict["cleared"]`：`ActionManager.clean(self.tester_id)`。
7. **`consumeLotStart` / `consumeWaferStart`**：保留 `mTouchdownCnt = 0`；加 `self.detector.reset("lot")` / `reset("wafer")`；記錄 lot / wafer 名稱。
8. **`get_state()`**：回傳 0.3 的結構（複本）。
9. **保護**：每個偵測器呼叫包 `try/except`，出錯只 `logging.exception`，**不可讓事件處理中斷**；量測每個 callback 耗時，超過預算（單次 `consumeParametricTest` > 5 ms 或整個 touchdown > 150 ms）記警告。
**注意**：`ActionManager.get` 只能在 `consumeTPRequest` 呼叫（manual 規定）；`consumeTPRequest` 現有的 `"list"` 分支會自動取回你寫入的訊息，不用改。

### B3（S2，約 60 分鐘）測試
擴充 `tests/test_sample_local.py`（取代失敗的舊測項）：
1. 重播 CSV：第 0 個 touchdown 不寫訊息；第 1 個 touchdown（DUT 5–8）`set_message` 被呼叫**恰好一次**。
2. 連續異常期間不重複寫入；`cleared` 時呼叫 `clean`。
3. 偵測器丟例外時 callback 不外洩例外。
4. `LotStart` 後偵測器狀態被重置。
5. `get_state()` 結構符合契約，且回傳的是複本（修改回傳值不影響內部）。
6. 效能：用假事件量 `consumeParametricTest` 每個 touchdown 的總耗時。
**驗收**：`python3 -m unittest discover -s tests` 全部通過（含 A 的 `test_detector`）；每個 touchdown < 150 ms（本機）。

### B4（S2）交接給 E 與 D
- 通知 E：分支已可部署（附本機測試輸出）。
- 通知 D：`get_state()` 已實作（D 可以改用真實資料）。
- 寫 `ai_notes/` 紀錄。

### B5（S3）整合除錯
依 C、E 回報修 bug；測項 key 的組法依 C 的探查結果調整；必要時協助 A 調整 `normalize_key`。

### B6（S4）演練
在 E 主持下完整跑一次 `prod_run`；準備備援（若真機出狀況，改用 CSV 重播 + 儀表板展示）。

## 4. 交接與依賴
- **A → 你**：`onset`/`cleared`/`info()`（A1）。在那之前先照 0.3 的契約寫，用暫時的 stub 測試。
- **C → 你**：真實事件的 key / 單位 / site 對應。
- **你 → D**：`get_state()`。**你 → E**：可部署的分支。

## 5. 常見坑
- `consumeTestEnd`、`consumeParametricTest` 沒有收到 `tc`；需要 testerId 就存成實例變數。
- Manual 規定：欄位必須在 callback 內立刻讀出，離開後資料會被清掉。
- `query_Result` 可能需要搭配 `query_ResultScaling`（單位換算），請等 C 的確認再決定。
- 不要在 `consumeData` 分派路徑裡做網路、檔案或大量列印。
- `sample.py` 是 SDK 附的範例檔，保留原有的 DFF / SFTP 註解與函式，不要刪。
