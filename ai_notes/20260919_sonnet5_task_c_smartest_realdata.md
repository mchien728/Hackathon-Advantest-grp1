# 任務書 C：真機、測試程式與部署（探查 + `predict` 請求 + 部署）

> 你是 **C**。你負責 `SmarTest/Case_Smt870/src/`（Java / flow）的修改、`Edge/oneAPI_py3.10/tools/probe_keys.py`（新增）、**所有碰真機與部署的工作**，以及共用 Host 的協調。你是**唯一會在共用 Host 上執行 `runTp.sh` 與 `sudo ./tag.sh` 的人**（其他人不要碰）。
> **2026-09-19 更新**：原本 E 負責的部署工作移交給你；新增「讓測試程式送出 `predict` 請求」的工作（場景二的關鍵前提）；閉環（`setprogvar`）降為選配。

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
1. **用真實事件回答問題**：測項 key、量測值單位、site 對應、`PartFlag` 語意、`TotalHeadSiteList` 格式（C1）。
2. **讓測試程式送出 `predict` 請求並顯示回傳訊息**（C2、C3）——場景二的前提。
3. **安全、可重複地部署**新版本並做端到端驗收（C4、C5）。
4. 協調共用 Host，避免大家互相踩到。

## 2. 你擁有的檔案
`SmarTest/Case_Smt870/src/ACSTML/AdaptiveTest.java`（若需修改）、`src/TestCase1/TestCase1_4site_ft.prog`、`TestCase1_PreRun.flow`、`TestCase1_PostRun.flow`、`Main.flow`；`Edge/oneAPI_py3.10/tools/probe_keys.py`；`Dockerfile`、`py-app.dockerfile`、`tag.sh`、`SmarTest/app_descriptor.json`（套用 D 給的片段）。

## 3. 使用共用 Host 的安全規則（必讀）
1. **執行任何 `runTp.sh` 之前**先確認沒有人在跑：
```
ssh advantest 'ps -eo user,pid,etime,args | grep -E "HPSmarTest|Drecipe" | grep -v grep'
```
有輸出代表有人在用。**`runTp.sh` 一開始會 kill 現有的 SmarTest 與 tcct**，會直接中斷別人。
2. 建立並維護**使用時段表**（共享文件；欄位：時段、使用者、目的、預計結束）；別人要用真機時來找你登記。
3. 修改 Host 檔案前先備份：`cp -a <檔案> <檔案>.bak_$(date +%Y%m%d_%H%M)`。
4. Host 上 Python 是 3.6；Host 的 log 時間是 UTC（比台灣慢 8 小時）。
5. **`sudo -l`**：請先在 Host 上執行並記錄結果（我的 AI 之前被系統擋下，需要你本人執行）；沒有權限就問講師誰能代為 build / push。

## 4. 任務清單

### C1（S1，約 2 小時）真實事件探查 `tools/probe_keys.py`
**目的**：查清楚事件欄位的真實樣子。
1. 寫 `tools/probe_keys.py`：繼承 `Monitor`，`consumeData` 處理 `DATA_TYP_MEASURED_PARAMETRIC`、`DATA_TYP_PRODUCTION_LOTSTART`、`DATA_TYP_PRODUCTION_TESTSTART`、`DATA_TYP_PRODUCTION_TESTEND`、`DATA_TYP_PRODUCTION_WAFEREND`，每筆以 JSON 一行寫進檔案（不要 `print` 上千行）。記錄：
   - 參數量測：`query_TestNumber`、`query_TestText`、`query_TestSuite`、`query_MeasurementName`、`query_HeadSite`（與 `toHead`/`toSite`）、`query_Result`、`query_ResultScaling`、`query_LowLimit`、`query_HighLimit`、`query_Unit`
   - TestStart / TestEnd：`query_XCoord`、`query_YCoord`、`query_HeadSite`、`query_PartId`、**`query_PartFlag`、`query_SBinResult`、`query_HBinResult`**
   - LotStart：**`get_TotalHeadSiteList()`**；WaferEnd：`get_TestedCount`、`get_GoodCount`
2. 連線方式參考 `bin/main.py`：`AppInfo.name` 用**獨特名稱**（例如 `probe_c`），`Interface.connect(me, True, False)`（不開 TPService）；收到 SIGINT 要 `Interface.disconnect()`。
3. **風險**：Edge 上已有部署的 `py-app` 也在消費同一串流，多一個客戶端會有什麼影響**未知**。先問講師，選沒有人在測試的時段，只跑一次 `eng_run 1` 就停。
4. 複製到 pod 執行（登入密碼手動輸入）：
```
scp -o ProxyJump=advantest -P 29022 tools/probe_keys.py debugger@advantestcell.local:~/project/oneAPI_py3.10/bin/
ssh -J advantest -p 29022 debugger@advantestcell.local
cd ~/project/oneAPI_py3.10/bin && python3 probe_keys.py > /tmp/probe.log 2>&1 &
```
5. 另開終端到 Host：`cd ~/Case_Event/SmarTest && ./runTp.sh eng_run 1`（尚未載入先 `./runTp.sh load`）。
6. 分析並寫報告 `ai_notes/YYYYMMDD_<模型名>_probe_report.md`，回答：
   - 基準線 key 是 `Main.Suite1#CP`。真實事件的 `TestSuite`、`MeasurementName`、`TestNumber` 能組出同樣的 key 嗎？`#` 後的 pin 名稱在哪個欄位？
   - `query_Result` 和 CSV 對得上嗎（例如 `Main.Suite1#CP` 約 1.15）？要不要乘 `query_ResultScaling`？
   - `toSite(query_HeadSite)` 是 1 到 4 嗎？和「DUT 序號 % 4 + 1」一致嗎？
   - `PartFlag` / `SBin` 什麼值代表通過、失敗？
   - `TotalHeadSiteList` 的格式（例如 `[1, 2, 3, 4]` 或 head/site 編碼）？
   - 每個 touchdown 有幾筆參數量測（預期約 3035）？
7. 把結論通知 **A、B、E**。
**驗收**：報告明確回答以上問題，附原始輸出範例各 5 筆。

### C2（S1 到 S2，約 3 小時）讓測試程式送出 `predict` 請求
**背景**：題目說「測試程式會將需要預測的測項編號發送給 container」，容器端預期收到 `{"key":"predict","data":"<編號>"}`。但 repo 內的 `AdaptiveTest.java` 是寫死 `Cmd = "{\"action\":\"list\"}"`，沒有 `predict`。
1. **先問**（透過 E0）：評估用的測試程式（題目「Test program for result evaluation」）是否已經會送 `predict`？如果評分時會換成主辦方的測試程式，我們只需要容器端正確；但為了自己測試，仍需要一個能送出的版本。
2. 讀 `SmarTest/Case_Smt870/src/ACSTML/AdaptiveTest.java`：`execute()` 呼叫 `RunApaptiveTest(Cmd, AppName, debugLevel, timeout)`，內部 `global_variable.LibACSTM.FetchAction(AppLoc, appname, timeout, Cmd, DebugAction)`；收到 `wait` 動作時，`reason` 會經 `sendToFifo` 交給 `util/MessUI` 顯示。
3. 修改（保持預設行為不變）：在 `AdaptiveTest` 加兩個 public 參數 `cmdKey`、`cmdData`（預設空字串）；`execute()` 中若 `cmdKey` 非空，`Cmd` 改為 `{"key":"<cmdKey>","data":"<cmdData>"}`，否則維持 `{"action":"list"}`。
4. 在 `Main.flow` 的六個 `receive_temp_predictN` 加上參數，例如 `receive_temp_predict1 { cmdKey= "predict"; cmdData= "100_Main.sensor1_CP"; ... }`；六個編號依序為 `100_Main.sensor1_CP`、`120_Main.sensor2_DS0`、`140_Main.sensor3_IO4`、`160_Main.sensor4_IO1`、`180_Main.sensor5_IO2`、`200_Main.sensor6_IO3`。
5. 解除 `Main.flow` 中 `receive_temp_predictN.execute(); sensorN.execute(); subflowN.execute();` 六組的註解（場景二需要全部），並移除先前留在 `.flow` 的 `TODO(Phase 4)` 註解。
6. **編譯**：確認 SmarTest 載入時會重新編譯 `src/ACSTML/*.java`（可能需要 `./runTp.sh load`；若失敗看 SmarTest 輸出），在本機 repo 與 Host 各同步一份（Host 先備份）。
**驗收**：`./runTp.sh eng_run 1` 時，容器端 log（`EdgeLog log`）出現收到 `{"key":"predict","data":"100_Main.sensor1_CP"}`。

### C3（S2，約 90 分鐘）顯示驗證（場景一與場景二）
前提：B 的 `sample.py` 已部署。
1. 場景二：`set_wait` 的說明字串（預測值）應經 `AdaptiveTest` 的 `sendToFifo` 由 `util/MessUI` 顯示；確認 `util/MessUI` 在 Gemini 環境能執行（需要顯示環境）。
2. 場景一：`set_message` 的訊息應由 `ShowAction` 彈窗顯示。需要：`TestCase1_4site_ft.prog` 的 `pause_eot` 改 `true`（`runAdaptive` 已是 `true`）、`TestCase1_PostRun.flow` 解除 `displayAction.execute()` 區塊、`TestCase1_PreRun.flow` 解除 `AdaptiveTestStep.execute()` 區塊。
3. 沒有顯示時的排查：`~/Case_Event/Edge/EdgeLog/EdgeLog log | tail -40`；確認 `pause_eot`、`runAdaptive` 為 `true`；把 `AdaptiveTest` 的 `debugLevel` 暫設 1。
4. **時序**：確認訊息會在哪個時間點被讀到（偵測器在 touchdown N 的 `TestEnd` 才寫訊息，`AdaptiveTest` 在流程的哪個位置讀取），並回報 B。
**驗收**：兩種訊息都在機台端顯示，附截圖。

### C4（S2，約 2 小時）部署（原 E 的工作，移交給你）
1. 從本機同步到 Host 專案 `~/Case_Event/Edge/oneAPI_py3.10/`（先備份，不加 `--delete`）：
```
cd Edge/oneAPI_py3.10
rsync -av --dry-run --exclude '__pycache__' --exclude 'py-app.log' ./ advantest:~/Case_Event/Edge/oneAPI_py3.10/
```
確認乾跑輸出無誤後才去掉 `--dry-run`；Host 沒有 `rsync` 就用 `scp -r`。備份：`cp -a ~/Case_Event/Edge/oneAPI_py3.10 ~/Case_Event/Edge/oneAPI_py3.10.bak_$(date +%Y%m%d_%H%M)`。
2. build 與 push：`cd ~/Case_Event/Edge/oneAPI_py3.10 && sudo ./tag.sh`（推到 `unifiedserver.local/grp1/py-app:latest`）。
3. 部署：`runTp.sh` 會把 `SmarTest/app_descriptor.json` 複製到 `/opt/acs/nexus/conf/`，SmarTest session 啟動時自動部署（`Auto_Deploy` 已開）。必要時手動 `/opt/acs/nexus/bin/AppDeployer start`（`Session is not ready` 表示 SmarTest 尚未就緒，等 30 秒重試）。
4. 驗證：`~/Case_Event/Edge/EdgeLog/EdgeLog log | tail -40`，確認新版載入、沒有 `load_error`、有收到事件。
5. **回滾**：`tag.sh` 一律推 `latest`，沒有舊版本可切回，所以每次部署前備份上一版原始碼，需要時還原再 build。
6. 套用 D 的 `app_descriptor.json` 片段（`exposed_ports`/`mapped_ports`），並和 D 確認怎麼從外面看到頁面。
7. 刪掉 `Dockerfile`、`py-app.dockerfile` 裡先前留下的兩行 `TODO(Phase 6)` 註解（`COPY bin/. ./bin` 已包含新檔案）。
8. 寫成一頁「部署手冊」放進 `ai_notes/`。

### C5（S3，約 2 小時）端到端驗收
依序執行並逐項打勾（每項附證據）：
```
cd ~/Case_Event/SmarTest
./runTp.sh load
./runTp.sh eng_run 1
./runTp.sh prod_run
```
**驗收清單**
1. `EdgeLog log` 顯示新版 py-app 正常運作，沒有例外與 `load_error`。
2. **場景一**：第 0 個 touchdown 無異常；第 1 個 touchdown 起判為異常；wafer 結束時有報告訊息。
3. **場景二**：六個 sensor 的 `predict` 請求都收到回覆，機台端顯示預測值；儀表板的預測 vs 實際有資料。
4. 儀表板顯示正確（若已部署）。
5. Edge pod 上的效能（A2 / A7）符合預算（每個 touchdown < 150 ms；`predict` < 5 ms）。
6. 連續跑 `prod_run` 兩次，第二次仍正常（reset 邏輯正確）。
失敗項目回報給對應的人：偵測找 A、接線找 B、畫面找 D、預測找 E。

### C6（S4）備援與 Demo 手冊
1. 錄一段完整的成功執行影片與關鍵截圖（訊息顯示、SmarTest 狀態、EdgeLog 輸出）。
2. 寫「怎麼在 Host 上跑 Demo」的手冊（指令、預期畫面、失敗處理），交給 E。

### （選配）閉環：讓決策真的改變測試流程
只有在 C1–C5 都完成後才做。檢查 `SmarTest/Case_Smt870/lib/libACS.jar` 的 action 類別：
```
unzip -l SmarTest/Case_Smt870/lib/libACS.jar | grep -i action
/usr/lib/jvm/java-11/bin/javap -cp SmarTest/Case_Smt870/lib/libACS.jar libACS.Adaptive.ActionInstruction.ActionDef
```
依序試 `set_wait` → `settest` → `setprogvar`，每步用 `./runTp.sh eng_run 1` 驗證並記錄。

## 5. 交接與依賴
- **你 → A、B、E**：C1 的結論（越早越好）。**E → 你**：E0 對主辦方的答案（評估用測試程式、`predict` 的送法）。
- **B → 你**：可部署的分支。**D → 你**：`app_descriptor.json` 片段。**A → 你**：`baseline.json` 有變就重新部署。
- **你 → E**：C6 的手冊與影片。

## 6. 常見坑
- 共用帳號：`runTp.sh` 的 `cleanEnv()` 會 kill 別人的 SmarTest，這是最容易出事的地方。
- `runTp.sh` 每次都會把 `SmarTest/app_descriptor.json` 複製到 `/opt/acs/nexus/conf/`。
- `.flow` / `.prog` / `.java` 是 SmarTest 的原始碼，改完要重新載入（`./runTp.sh load`）才會生效。
- `sudo ./tag.sh` 會從 `unifiedserver.local` 拉 base image 並在結束時刪除本機映像檔，屬預期行為。
- 部署後 `py-app` 是新容器：舊容器的狀態（儀表板累積資料）會消失。
- 工作坊密碼只存在教材裡，不要貼進任何 repo 檔案、commit 或 PR。
