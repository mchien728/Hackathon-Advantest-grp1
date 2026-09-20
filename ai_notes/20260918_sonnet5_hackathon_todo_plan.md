# Hackathon 實作計畫：TODO List / API 對照表 / 創意方向

> 最後更新：2026-09-19。狀態標記：`[x]` 已完成、`[~]` 部分完成、`[ ]` 待辦。
> Phase 1 的設計與實作細節見 [20260918_sonnet5_phase1_spec.md](20260918_sonnet5_phase1_spec.md)、[20260918_sonnet5_phase1_implementation.md](20260918_sonnet5_phase1_implementation.md)。

**環境速查**（實測）
- Host Controller / Nexus：`ssh advantest`（主機名 `group-1`，RHEL 7.9，Python 3.6，測試專案在 `~/Case_Event/`）。**帳號 `user` 是大家共用的，且同時可能有人在跑 SmarTest。**
- Edge 開發 pod：從 Host 跳板 `ssh -J advantest -p 29022 debugger@advantestcell.local`（密碼見 `doc/WorkShop_Material.pdf` 第 21 頁；請勿寫進 repo）。Ubuntu 22.04、Python 3.10、只有 `numpy`/`flask`/`paramiko`/`jsonschema`/`requests`，**沒有** `pandas`/`scikit-learn`/`matplotlib`/`pillow`，**不能連外網**；只有 `/home/debugger/project` 會在容器重啟後保留。
- Host 可連外網（可下載 pip wheel）；`user` 沒有 docker 權限，`tag.sh` 需 `sudo`（權限未確認）。

---

## 一、TODO List

### Phase 0：確認事項

- [x] `setup.cfg` Action 格式 → 已解決：`doc/ONEAPI_Manual.pdf` 第 68 頁有完整 `ActionManager` API（見第二節）
- [x] `receive_temp_predict` 的 temp → 高度確認是溫度：manual 的 `set_wait` 範例即為 `set_wait("smartest_host",10,"temperature")`
- [x] 模型由我們自行訓練，沒有現成模型提供（2026-09-19 確認）
- [x] Edge / Nexus 存取權 → 已確認可連（見上方環境速查）
- [ ] 確認 `user` 的 sudo 權限（決定能不能自己 `sudo ./tag.sh`）
  1. 由你在 Host 上執行 `sudo -l`，記下允許的指令
  2. 沒有權限就向工作坊講師（教材作者）詢問誰能代為 build/push，或有沒有免 sudo 的方式
  3. 把結論記在本節
- [ ] 團隊拍板：「完整閉環（`setprogvar`/`settest` 真的改測試流程）」或「安全牌（判斷 + `set_message` + 儀表板）」
  1. 對照 Phase 4 的工作量與風險（要改 SmarTest 端三個檔案、重新載入測試程式、與其他隊員共用機台）
  2. 決定 demo 主敘事：抓到什麼、系統做了什麼、怎麼證明有效
  3. 決定後在本節記錄，並據此決定 Phase 4 是否進行
- [ ] 決定是否加 ML 選配層（群組層級統計量 + 學習式判定器，見 Phase 1 選配項）

### Phase 1：異常偵測器（核心已完成）

- [x] 確認資料內容
  1. 確認 `TestCase1_OfflineData.csv` 無 pass/fail/bin 標籤
  2. 以中位數/MAD 與「模擬純雜訊」對照掃描 → 發現**埋了異常**：約 110 個測項在 site 4 的 DUT 8、12、16、20、24 有 +8～13σ 離群值；另有少數約 240σ 尖峰；其餘四類與純雜訊一致
- [x] 建模與匯出（自行訓練 = 由資料擬合基準線 + 校準門檻）
  1. `tools/fit_baseline.py`：中位數 + MAD 擬合 3035 個測項，去離群值後做形狀檢查（排除 6 個）
  2. `bin/detector.py`：五種偵測（`outlier`、`mean_shift`、`variance_change`、`mean_drift`、`site_imbalance`），僅標準函式庫
  3. `tools/evaluate_detector.py calibrate`：以誤報預算校準門檻並寫入 `bin/model/baseline.json`
- [x] 本機驗證：乾淨資料 10,000 顆 DUT 零誤判；注入異常偵測率 100%（標準差 ×2 延遲 44 DUT，未達暫定目標 30）；CSV 重播從 DUT 5–8 起判為異常；`update()` p99 2.2 µs；14 項單元測試通過
- [ ] 在 Edge pod 量測效能（Python 3.10）
  1. 把 `bin/detector.py`、`bin/model/`、`tools/`、`tests/` 複製到 pod 的 `~/project/oneAPI_py3.10/`（`scp` 需經跳板：`scp -o ProxyJump=advantest -P 29022 ...`）
  2. 在 pod 內執行 `python3 -m unittest discover -s tests`
  3. 執行 `python3 tools/evaluate_detector.py verify --clean-tests 3029 --clean-td 300`
  4. 若每個 touchdown 超過 150 ms，改用「只監控指定測項/pin」的白名單（在 `baseline.json` 把不重要測項的 `monitor` 設 `false`）
- [ ] 處理警報黏性（Phase 3 前需要）
  1. 在 `end_touchdown()` 的回傳加 `onset`（本 touchdown 由正常轉異常）與 `cleared`（由異常轉正常）欄位
  2. 補單元測試（連續異常只在第一個 touchdown 標 `onset`）
  3. 更新 spec 第 5 節的介面契約
- [ ] （選配）群組層級統計量：把同一 pin 群組、同一 site 的所有測項的 z 取平均（位移）與 z² 取平均（變異）
  1. 在 `Detector` 內每個 touchdown 累積各（pin, site）的總和與計數
  2. 對這幾條群組序列套 CUSUM/EWMA
  3. 在 `evaluate_detector.py` 加群組情境校準與驗證
  4. 補單元測試；驗收：標準差 ×2 且影響 ≥20 個測項時，延遲明顯低於 44 DUT
- [ ] （選配）學習式判定器：取代「同群組 ≥3 個測項」的手寫規則
  1. 定義每個 touchdown 的特徵向量（各類警報數、群組統計量、最高分數、受影響 site 數）
  2. 用 `inject_anomalies.py` 產生帶標籤資料：多種異常、多種強度、受影響測項比例不同，加上乾淨資料
  3. 在本機安裝 `scikit-learn`，訓練 Logistic Regression 或梯度提升樹
  4. 匯出成 JSON（權重或樹結構）；`detector.py` 以純 Python 評估
  5. 驗證：留出一種訓練時沒用的異常類型，並用 CSV 真實埋的 site 4 突發當外部驗證
  6. 與規則式判定並列比較，決定是否採用；誠實標示標籤是合成的

### Phase 2：本機驗證與真實事件探查

- [~] 既有 `tests/test_sample_local.py`（4 項；其中 `test_list_request_returns_seeded_message` 因 `sample.py` 已還原而失敗，Phase 3 會取代）
- [ ] CSV 重播腳本（模擬真實事件，驗證 `sample.py` 接線）
  1. 寫 `FakeParametricData`：提供 `get_ResultCount`、`query_HeadSite`、`query_TestNumber`、`query_TestSuite`、`query_MeasurementName`、`query_Result`…
  2. 由 CSV 逐 touchdown 組出 4 個 site 的事件，依序呼叫 `consumeTestStart` → `consumeParametricTest` → `consumeTestEnd`
  3. 驗證結果與 `evaluate_detector.py replay` 一致
- [ ] 真實事件探查（驗證 key、單位、site 對應）
  1. 寫 `tools/probe_keys.py`：繼承 `Monitor`，只印 `query_TestNumber`/`query_TestSuite`/`query_MeasurementName`/`query_HeadSite`/`query_Result`/`query_ResultScaling`
  2. 先確認不會干擾正在跑的 `py-app`（同時多個 OneAPI 客戶端的行為未知，先問講師或選沒人在跑的時段）
  3. 在 pod 執行（教材第 22 頁：`python3 main.py` 的方式），再用 `./runTp.sh eng_run 1` 觸發事件
  4. 對照 `baseline.json` 的 key，必要時調整 key 組法與 `normalize_key`
  5. 確認 `query_Result` 是否要乘 `query_ResultScaling`，以及 `site = toSite(query_HeadSite)` 是否等於 DUT 序號 % 4 + 1

### Phase 3：把偵測器接進 `sample.py`

（`sample.py` 目前是原版，先前的 TODO 註解與測試樁在 `git stash` 裡，不套用）
- [ ] `SampleMonitor.__init__`
  1. `self.detector = Detector.load()`（記錄 `load_error`，失敗不中斷）
  2. 加 `self.tester_id`、`self.recent = deque(maxlen=200)`（給 Phase 5 儀表板）
- [ ] `consumeData`：分派前先存 `self.tester_id = tc.testerId`（`consumeTestEnd` 沒有收到 `tc`）
- [ ] `consumeParametricTest`
  1. 在 callback 內立刻讀出 `query_TestNumber`/`query_TestSuite`/`query_Result`/site（manual：離開 callback 資料會被清掉）
  2. 組 key 後呼叫 `self.detector.update(key, site, value, touchdown_seq)`
  3. 拿掉逐欄位 `print`（改成除錯開關）；每個 touchdown 上千次呼叫，印字會拖慢阻塞的 callback
- [ ] `consumeTestEnd`
  1. `verdict = self.detector.end_touchdown()`，存進 `self.recent`
  2. 只在 `onset` 時 `ActionManager.set_message(self.tester_id, verdict["message"])`；`cleared` 時 `ActionManager.clean(self.tester_id)`
- [ ] `consumeLotStart` / `consumeWaferStart`：呼叫 `self.detector.reset("lot")` / `reset("wafer")`
- [ ] 保護與監控
  1. 每個偵測器呼叫包 `try/except`，出錯只記 log，不中斷事件處理
  2. 量每次 callback 耗時，超過預算就記警告
- [ ] 測試：擴充 `tests/test_sample_local.py`，用 `FakeParametricData` 驗證上述行為（取代失效的舊測項）

### Phase 4：（若選擇閉環）打開 Java 測試流程

- [ ] 先跟隊友協調：帳號共用，`runTp.sh` 一開始會 kill 現有的 SmarTest/tcct，會中斷別人的執行
- [ ] 在 Host 的 `~/Case_Event/SmarTest/Case_Smt870/src/TestCase1/` 修改
  1. `TestCase1_4site_ft.prog`：`var Boolean pause_eot= false;` 改為 `true`（`runAdaptive` 已是 `true`）
  2. `TestCase1_PostRun.flow`：解除 `displayAction.execute()` 區塊的註解
  3. `TestCase1_PreRun.flow`：解除 `AdaptiveTestStep.execute()` 區塊的註解
  4. `Main.flow`：先只解除一組 `receive_temp_predict1`/`sensor1`/`subflow1`，不要一次全開
- [ ] 本機 repo 同步一份相同修改（在 `mchien728_sonnet5` 分支）
- [ ] 重新載入並驗證：`./runTp.sh load` → `./runTp.sh eng_run 1`，確認彈窗出現 Phase 3 寫入的訊息
- [ ] （進階）真的改測試流程
  1. 讀 `AdaptiveTest.java`/`libACS.jar` 確認 action JSON 格式與 `execACSAdaptive` 支援的種類
  2. 先用 `set_wait` 驗證，再試 `setprogvar`/`settest`
  3. 每加一種動作就重跑 `eng_run 1` 確認機台行為

### Phase 5：視覺化 / 前端

- [ ] Flask 服務
  1. 在 `main.py` 的 `main()` 開頭啟動背景 thread 跑 Flask（`daemon=True`，避免擋住 `signal.pause()`）
  2. 路由：`/api/state`（最新 verdict、最近 N 筆、統計）、`/`（頁面，定時輪詢）
- [ ] 開放連接埠：在 `SmarTest/app_descriptor.json` 的 `requirements` 加 `exposed_ports`/`mapped_ports`（manual 第 73–74 頁格式）；`runTp.sh` 每次會把它複製到 `/opt/acs/nexus/conf/`
- [ ] 圖表：**pod 沒有 `matplotlib`/`pillow` 且不能連外網**，優先用內嵌 SVG/Canvas 的純 HTML 畫 wafer map 與趨勢圖（不需任何套件）；若堅持用 `matplotlib`，需在 Host 下載 wheel 再傳進 image
- [ ] 顯示內容：目前 touchdown 判定、前 5 筆告警、wafer map（用 `query_XCoord`/`query_YCoord` 著色異常 die）、各 site 狀態
- [ ] 先用假資料在本機把頁面做出來，再接 `self.recent`

### Phase 6：打包部署

- [ ] 整理 Dockerfile：`COPY bin/. ./bin` 已包含 `detector.py` 與 `model/`，不需新增 COPY；刪除 `Dockerfile`、`py-app.dockerfile` 裡先前加的兩行 `TODO(Phase 6)` 註解
- [ ] 同步程式碼到 Host：把 `Edge/oneAPI_py3.10/` 複製到 Host 的 `~/Case_Event/Edge/oneAPI_py3.10/`（`rsync`/`scp`），先備份原檔
- [ ] Build 與 push：`cd ~/Case_Event/Edge/oneAPI_py3.10 && sudo ./tag.sh`（推到 `unifiedserver.local/grp1`）
- [ ] 部署：`runTp.sh` 會複製 `app_descriptor.json` 並在 SmarTest session 啟動時自動部署（`Auto_Deploy` 已開）；必要時手動 `/opt/acs/nexus/bin/AppDeployer start`
- [ ] 驗證部署：`~/Case_Event/Edge/EdgeLog/EdgeLog log` 看 `py-app` 的 log 是否載入新版、有無 `load_error`

### Phase 7：端到端驗證 + demo 準備

- [ ] 排定不與隊友衝突的時段，先在 Host 確認沒有人在跑 SmarTest
- [ ] 執行順序：部署新版 → `./runTp.sh load` → `./runTp.sh eng_run 1` → `./runTp.sh prod_run`
- [ ] 驗收清單
  1. `EdgeLog log` 看到判定結果，第 1 個 touchdown（DUT 5–8）起判為異常
  2. 機台端收到訊息（彈窗，或 `set_message` 內容）
  3. 儀表板顯示正確
  4. 在 Edge pod 上重跑 `verify` 與延遲量測
- [ ] Demo 準備
  1. 準備「乾淨 → 異常 → 恢復」三段故事；用 CSV 真實埋的 site 4 突發當主線
  2. 準備一段合成異常注入（漂移、標準差變大）展示其他偵測類型
  3. 誠實說明：沒有標籤，效果由合成注入與真實埋入異常驗證
  4. 扣回最初投影片的 ROI 故事（即時性、模型與測試程式解耦）

---

## 二、API / Function 對照表

| Phase | 名稱 | 來源 | 用途 |
|---|---|---|---|
| 1 | `Detector.load(path)` / `update(key, site, value, seq)` / `end_touchdown()` / `reset(scope)` | `bin/detector.py`（自寫） | 偵測器主介面（Phase 3 呼叫） |
| 1 | `robust_stats(vals)` | `bin/detector.py` | 中位數 + MAD 估計 |
| 1（選配） | `LogisticRegression` / `GradientBoostingClassifier` | `scikit-learn`（僅本機訓練，不進 image） | 學習式判定器 |
| 2 | `FakeParametricData` + 手動呼叫 callback | 自寫 | 不連真實 Nexus 也能測 `sample.py` |
| 3 | `data.query_Result(index)` / `query_TestNumber(index)` / `query_TestSuite(index)` / `query_HeadSite(index)` + `toSite(...)` | `liboneAPI`（`consumeParametricTest`） | 取得量測值、測項與 site |
| 3 | `data.query_XCoord(index)` / `query_YCoord(index)` | `liboneAPI` | wafer map 座標 |
| 3 | `ActionManager.set_message(testerid, reason)` | `libACSAction` | 寫入提示訊息到決策信箱 |
| 3 | `ActionManager.clean(testerid)` | `libACSAction` | 清除信箱 |
| 3 | `ActionManager.set_wait(testerid, wait_time, reason)` | `libACSAction` | 讓機台暫停等待 |
| 3 | `ActionManager.setprogvar(testerid, tp_variable, site, value)` | `libACSAction` | 改變測試程式變數（閉環核心） |
| 3 | `ActionManager.settest(testerid, suitelist, state)` | `libACSAction` | bypass/啟用 test suite |
| 3 | `ActionManager.get(testerid)`（已存在於 `consumeTPRequest`） | `libACSAction` | 機台端取回決策 |
| 3（選用） | `AdvantestResult.log_result(key, value)` | `AdvantestLogging.py` | 結構化 JSON log |
| 4 | `AdaptiveTestStep.execute()` | `ACSTML.AdaptiveTest`（Java） | 向 py-app 要決策 |
| 4 | `LibACSTM.FetchAction(...)` / `execACSAdaptive(...)` | Java（`libACS.jar`） | 取得並套用決策 |
| 4 | `displayAction.execute()` → `JOptionPane.showMessageDialog(...)` | `ACSTML.ShowAction`（Java） | 彈窗顯示決策 |
| 5 | `Flask(__name__)` / `@app.route(...)` / `app.run(host, port)` | `flask`（pod 已有） | 儀表板 API |
| 5 | 內嵌 SVG/Canvas | 純 HTML/JS | 畫 wafer map（不依賴 `matplotlib`/`pillow`） |
| 6 | `sudo ./tag.sh`（`docker build` + `push`） | Docker CLI（Host） | 打包送到 `unifiedserver.local/grp1` |
| 6 | `/opt/acs/nexus/bin/AppDeployer start`、`EdgeLog log` | Nexus 平台工具 | 觸發部署、查容器 log |
| 7 | `./runTp.sh {load\|eng_run\|prod_run}` | `SmarTest/runTp.sh` | 載入、單次、產線模擬 |

---

## 三、這次黑客松要發揮創意的地方

技術上「怎麼接」的問題都有現成 API 可查（見上表），**創意空間不在接線，而在下面三個沒有標準答案的判斷題**：

### 1. 「異常」到底要偵測什麼

機台自己已經用 `query_LowLimit`/`query_HighLimit` 做基本 pass/fail，AI 只重做一次超限判斷就沒有意義。教材第 29 頁定義的異常（site 間不平衡、平均值漂移、標準差變化、量測值位移）都是單顆測項看不出、要靠跨 DUT / 跨 site 統計才抓得到的；目前偵測器已涵蓋。可以再延伸的方向：
- **群組層級**：異常通常牽動一整群測項，群組統計量可大幅提升靈敏度
- **wafer 空間相關性**：某區域 die 集中出現輕微異常（需要真實座標資料）

### 2. 決策要怎麼「用」——記錄 vs 真的介入

- 保守做法：`set_message` 只提示/記錄，不干預生產
- 積極做法：`setprogvar`/`settest` 動態調整測試——對應最初投影片「adaptive test 縮短測試時間」的 ROI 故事，但整合風險較高

### 3. 沒有標籤，怎麼向評審證明 AI 有效

CSV 沒有標籤，但**內含真實埋入的 site 4 突發異常**，可當作不是我們自己造的驗證；另外用合成注入展示其他異常類型與偵測延遲。搭配 wafer map 視覺化，用視覺說服力補足資料限制。誠實說明：這證明「抓得到我們定義的異常」，不是實際不良率。

**一句話**：管線、API、SDK 已經有答案；真正屬於這次黑客松的創意，是「AI 該看什麼、該做什麼決定、以及怎麼證明這個決定是對的」。

---

## 修改與新增檔案

- 新增：`ai_notes/20260918_sonnet5_hackathon_todo_plan.md`（本檔案，2026-09-19 依 Phase 1 完成狀態與環境實測重寫）

## 技術細節與邏輯

- 每個項目補上具體步驟，狀態依實際進度標記。
- 依實測更新：Edge pod 缺 `matplotlib`/`pillow`（Phase 5 改用內嵌 SVG）、`bin/` 會整包複製進 image（Phase 6 不需額外 COPY）、帳號共用需協調（Phase 4/7）、密碼不寫入 repo。
- 資料來源：`doc/ONEAPI_Manual.pdf`、`doc/WorkShop_Material.pdf`、`SmarTest/Case_Smt870/src/TestCase1/*`、對 Host 與 Edge pod 的唯讀環境檢查。

## 待執行事項與注意事項

- 本文件為規劃文件，不涉及程式邏輯異動。
- Phase 0 仍有兩項待決定（sudo 權限、閉環深度）；ML 選配層是否做也待你決定。
- 變更仍在 `mchien728_sonnet5` 分支的工作目錄，尚未 commit。
