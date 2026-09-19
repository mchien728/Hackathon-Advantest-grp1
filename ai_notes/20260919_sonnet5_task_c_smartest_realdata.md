# 任務書 C：SmarTest 與真實事件（Phase 2 探查 + Phase 4）

> 你是 **C**。你負責 `SmarTest/Case_Smt870/src/TestCase1/*` 的修改、`Edge/oneAPI_py3.10/tools/probe_keys.py`（新增），以及所有「碰真機」的探查與驗證。你和 E 是**唯二會在共用 Host 上執行 `runTp.sh` 的人**。

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
1. **用真實事件回答三個問題**：測項 key 怎麼組、量測值單位要不要換算、site 怎麼對應。這是最可能翻盤的風險，越早越好。
2. 準備並驗證 Phase 4：機台端彈窗顯示偵測器的訊息。
3. （若團隊選閉環）試驗讓決策真的改變測試流程。

## 2. 你擁有的檔案
`SmarTest/Case_Smt870/src/TestCase1/TestCase1_4site_ft.prog`、`TestCase1_PreRun.flow`、`TestCase1_PostRun.flow`、`Main.flow`；`Edge/oneAPI_py3.10/tools/probe_keys.py`。

## 3. 使用共用 Host 的安全規則（必讀）
1. **執行任何 `runTp.sh` 之前**先確認沒有人在跑：
```
ssh advantest 'ps -eo user,pid,etime,args | grep -E "HPSmarTest|Drecipe" | grep -v grep'
```
有輸出就代表有人在用，先問隊友。**`runTp.sh` 一開始會 kill 現有的 SmarTest 與 tcct**，會直接中斷別人。
2. 團隊維護一張使用時段表（E 負責建立），你要用之前先登記。
3. 修改 Host 上的檔案前先備份：`cp -a <檔案> <檔案>.bak_$(date +%Y%m%d_%H%M)`。
4. Host 上 Python 是 3.6；Host 的 log 時間是 UTC（比台灣時間慢 8 小時）。

## 4. 任務清單

### C1（S1，約 2 小時）真實事件探查 `tools/probe_keys.py`
**目的**：查清楚 `consumeParametricTest` 收到的欄位長什麼樣子，決定測項 key、單位、site 的對應規則。
1. 在本機寫 `tools/probe_keys.py`：繼承 `Monitor`，`consumeData` 只處理 `DATA_TYP_MEASURED_PARAMETRIC`、`DATA_TYP_PRODUCTION_TESTSTART`、`DATA_TYP_PRODUCTION_TESTEND`，把每筆以 JSON 一行寫進檔案（不要 `print` 上千行）。參數量測每筆至少記錄：`query_TestNumber`、`query_TestText`、`query_TestSuite`、`query_MeasurementName`、`query_HeadSite`（與 `toHead`/`toSite` 結果）、`query_Result`、`query_ResultScaling`、`query_LowLimit`、`query_HighLimit`、`query_Unit`。TestStart/TestEnd 記錄 `query_XCoord`、`query_YCoord`、`query_HeadSite`、`query_PartId`。
2. 連線方式參考 `bin/main.py`：`AppInfo.name` 用**獨特名稱**（例如 `probe_c`），`Interface.connect(me, True, False)`（不開 TPService，避免佔用連接埠）；收到 SIGINT 要 `Interface.disconnect()`。
3. **風險**：目前 Edge 上已有部署的 `py-app` 也在消費同一串流；多一個客戶端會有什麼影響（例如訊息被分掉）**未知**。先問講師，並選沒有人在做測試的時段、只跑一次 `eng_run 1` 就停。
4. 複製到 pod 執行（登入密碼手動輸入）：
```
scp -o ProxyJump=advantest -P 29022 tools/probe_keys.py debugger@advantestcell.local:~/project/oneAPI_py3.10/bin/
ssh -J advantest -p 29022 debugger@advantestcell.local
cd ~/project/oneAPI_py3.10/bin && python3 probe_keys.py > /tmp/probe.log 2>&1 &
```
5. 另開一個終端到 Host：`cd ~/Case_Event/SmarTest && ./runTp.sh eng_run 1`（若程式尚未載入先 `./runTp.sh load`）。跑完後回 pod 停掉 probe，取回輸出檔。
6. 分析並回答（寫成報告 `ai_notes/YYYYMMDD_<模型名>_probe_report.md`）：
   - 基準線 key 是 `Main.Suite1#CP`。真實事件的 `TestSuite`、`MeasurementName`、`TestNumber` 能組出同樣的 key 嗎？`#` 後面的 pin 名稱在哪個欄位？
   - `query_Result` 的值和 CSV 對得上嗎（例如 `Main.Suite1#CP` 的值約 1.15）？是否需要乘 `query_ResultScaling`？
   - `toSite(query_HeadSite)` 是 1 到 4 嗎？和「DUT 序號 % 4 + 1」一致嗎？
   - 每個 touchdown 有幾筆 `MEASURED_PARAMETRIC`？（預期約 3035 筆）
7. 把結論通知 **A**（`normalize_key`）與 **B**（`make_test_key`）。
**驗收**：報告明確回答上述三個問題，附原始輸出範例各 5 筆。

### C2（S1，約 60 分鐘）準備 Phase 4 的檔案修改（先不執行）
在**本機 repo**（你的分支）與 **Host** 的 `~/Case_Event/SmarTest/Case_Smt870/src/TestCase1/`（先備份）準備以下修改：
1. `TestCase1_4site_ft.prog`：`var Boolean pause_eot= false;` 改 `true`（`runAdaptive` 已是 `true`）。
2. `TestCase1_PostRun.flow`：解除 `displayAction.execute()` 區塊的註解。
3. `TestCase1_PreRun.flow`：解除 `AdaptiveTestStep.execute()` 區塊的註解。
4. `Main.flow`：只解除**一組** `receive_temp_predict1.execute(); sensor1.execute(); subflow1.execute();`。
5. 移除先前留在這三個 flow 檔的 `TODO(Phase 4)` 註解（改完就不需要了）。
先在本機檢查 diff，再同步到 Host；`.flow` 用 `//` 註解，不要動到其他行。

### C3（S2，約 60 分鐘）彈窗驗證
前提：B 已交付可用的 `sample.py`，E 已部署（或先用簡單測試樁驗證管線）。
1. 登記時段、確認沒人在跑（見第 3 節）。
2. `cd ~/Case_Event/SmarTest && ./runTp.sh load && ./runTp.sh eng_run 1`。
3. 預期：`AdaptiveTest` 送出 `{"action":"list"}` → `consumeTPRequest` → `ActionManager.get()` → `ShowAction` 彈窗顯示訊息。
4. 沒有彈窗時的排查：
   - `~/Case_Event/Edge/EdgeLog/EdgeLog log | tail -40`：看 py-app 有沒有收到 `list` 請求、有沒有錯誤。
   - 確認 `pause_eot`、`runAdaptive` 在 SmarTest 裡顯示為 `true`。
   - 把 `Main.flow` 裡對應 `AdaptiveTest` 的 `debugLevel` 暫時設為 `1`，看 `PrintModifySetupPool` 輸出。
   - **時序**：偵測器在 touchdown N 的 `TestEnd` 才寫訊息，`AdaptiveTest` 是在流程的哪個位置讀取的？確認訊息會在下一個 touchdown 被讀到，並回報 B。
**驗收**：彈窗出現，內容是偵測器的訊息；記錄截圖。

### C4（S3，選配；僅在團隊選擇閉環時）讓決策真的改變測試流程
1. 檢查 `SmarTest/Case_Smt870/lib/libACS.jar` 內的 action 類別，了解支援哪些動作與格式：
```
unzip -l SmarTest/Case_Smt870/lib/libACS.jar | grep -i action
/usr/lib/jvm/java-11/bin/javap -cp SmarTest/Case_Smt870/lib/libACS.jar libACS.Adaptive.ActionInstruction.ActionDef
```
（Host 上的 Java 11 路徑同上；也可用 `javap -p` 看私有欄位。）
2. 依序試驗（每一步都用 `./runTp.sh eng_run 1` 驗證，並記錄機台實際行為）：`set_wait` → `settest`（bypass 一個 test suite）→ `setprogvar`（改一個測試程式變數）。
3. 若某一步不穩定或不確定，停在前一步，並在 `ai_notes/` 寫明。
**驗收**：至少一種動作真的改變了測試流程（例如等待、跳過某 suite），有 log 或截圖證據；否則寫清楚卡在哪。

### C5（S4）備援與 Demo 手冊
1. 錄一段完整的成功執行影片（螢幕錄影）與關鍵截圖（彈窗、SmarTest 狀態、EdgeLog 輸出）。
2. 寫一份「怎麼在 Host 上跑 Demo」的步驟手冊（指令、預期畫面、失敗時的處理），交給 E。

## 5. 交接與依賴
- **你 → A、B**：C1 的結論（越早越好，通知後 A 才知道要不要調 `normalize_key`，B 才能定案 key 組法）。
- **B、E → 你**：C3 需要 B 的 `sample.py` 與 E 的部署。
- **你 → E**：C5 的手冊與影片。

## 6. 常見坑
- 共用帳號：`runTp.sh` 的 `cleanEnv()` 會 kill 別人的 SmarTest，這是最容易出事的地方。
- `runTp.sh` 每次都會把 `SmarTest/app_descriptor.json` 複製到 `/opt/acs/nexus/conf/app_descriptor.json`，並在 SmarTest session 啟動時自動部署。
- `.flow` / `.prog` 是 SmarTest 的原始碼，改完要重新載入（`./runTp.sh load`）才會生效。
- `tcct` 有時會留下 defunct 行程，不影響操作，但看到不要驚訝。
