# 任務書 E：場景二預測（資料處理 + 訓練 + 預測器）、主辦方窗口與 Demo

> 你是 **E**。你負責 `Edge/oneAPI_py3.10/bin/predictor.py`、`bin/model/predictor.json`、`tools/wafer_data.py`、`tools/train_predictor.py`、`tools/eval_predictor.py`、`tests/test_predictor.py`，也是**對主辦方的窗口**（所有需要問講師的問題都由你統一問）。後段負責簡報、Demo 與最後的合併流程。
> **2026-09-19 更新**：原本 E 負責的部署工作移交給 C；你改負責**場景二（預測溫度）**，這是題目中真正需要「自己訓練模型」的部分。

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
1. **取得訓練資料並回答主辦方的關鍵問題**（E0）——這是全隊的前提。
2. 做出六個 sensor 的預測模型，**誤差明顯低於「用平均值預測」的基準**（E3、E4）。
3. 交出符合契約的 `Predictor`（`bin/predictor.py`），可以在 Edge 上即時使用（E5）。
4. 後段：簡報、Demo、最後的合併與文件（E7）。

## 2. 你擁有的檔案
`bin/predictor.py`、`bin/model/predictor.json`、`tools/wafer_data.py`、`tools/train_predictor.py`、`tools/eval_predictor.py`、`tests/test_predictor.py`。`tools/wafer_data.py` 也給 A 用（標籤 wafer 驗證），請優先完成並通知 A。

## 3. 任務清單

### E0（S0，最優先，約 60 分鐘）對主辦方的問題與取得資料
**你是唯一的窗口**，一次問完，避免各人重複問。請問講師（並記錄答案到 `ai_notes/`）：
1. **訓練資料**：25 份 data log csv 在哪裡取得？格式是否為題目第 3 頁的寬表（每列一顆 device，欄位 `PID, Lot, Wafer, Site, X, Y, PF, SBin, HBin, Test Time` + 各測項欄，欄名 `<測項編號>_<test suite>#<pin>`）？
2. **評估方式**：預測與異常偵測各怎麼評分？看哪些指標（預測誤差用 RMSE / MAE？）？「正確的時機偵測問題」怎麼量化？
3. **`predict` 請求**：評估用的測試程式（題目「Test program for result evaluation」）是否會自己送 `{"key":"predict","data":"<編號>"}`？我們能不能修改測試程式的 Java（`AdaptiveTest`）？
4. **Low yield**：「yield 低於 80」的 80 是百分比嗎？良率怎麼定義（`PF`、`SBin`）？
5. **報告與通知**：異常報告要通知誰、用什麼形式？（儀表板查詢是否足夠？）
6. **標籤 wafer 與 `TestCase1_OfflineData.csv`**：那份 CSV 是不是 W1？評分時使用哪些 wafer？
7. **ACS Gemini 環境**：我們目前用的 Host / Edge pod 是否就是評分環境？有沒有部署上的限制？
把答案通知全隊（特別是 A、B、C）。若資料要下載，先放在**本機**（不要進 repo，太大也可能有授權限制）。
**驗收**：資料到手、答案記錄完成。

### E1（S1，約 2 小時）資料解析 `tools/wafer_data.py`
1. 解析寬表 csv：前幾列是 `Pin`、`Test Num`、`High Limit`、`Low Limit` 表頭，之後每列一顆 device。輸出結構：device 資訊（`PID, Lot, Wafer, Site, X, Y, PF, SBin, HBin, Test Time`）與測項欄位（欄名、測項編號、suite、pin、數值矩陣）。
2. **欄位順序 = 執行順序**（請用 `TestCase1_OfflineData.csv` 的列順序與題目第 4 頁流程圖核對）。輸出每個測項屬於哪個流程區塊（Suite1–14、IDDQ_flow、sensorN、subflowN），供不可洩漏規則使用。
3. 支援一次載入 25 個檔案，並附 wafer 編號；提供 `iter_devices(wafer)` 依 PID 順序迭代（A 的驗證會用）。
4. 用 `TestCase1_OfflineData.csv`（長表，是 W1）先測；資料到手後改測寬表。
5. 補 `tests/test_wafer_data.py`（用小型假資料）。
**驗收**：能載入 25 個檔案並印出每片的 device 數與測項數；通知 A。

### E2（S1，約 2 小時）資料探索
1. 每個 sensor 在各 wafer / 各 site 的均值與標準差；不同 wafer 之間是否有差異？site 之間呢？異常 wafer（W14、W18…）上 sensor 有沒有變化？
2. **基準線**：以「訓練均值」（依 site）預測的 RMSE，約等於標準差（W1 上 sensor 標準差約 0.09～0.16）。這是你必須超越的基準。
3. sensor 與更早測項的相關性：是否存在明顯的預測訊號（例如 IDDQ、特定 suite）？只看不可洩漏規則允許的特徵。
4. 寫成簡短報告，決定特徵策略。

### E3（S1 到 S2，約 4 小時）訓練與評估 `tools/train_predictor.py`、`tools/eval_predictor.py`
**特徵可用性（不可洩漏）**

| 目標 | 可用 | 不可用 |
|---|---|---|
| sensor1 | Suite1–14、IDDQ_flow | subflow1 及之後 |
| sensorN（N ≥ 2） | 上列 + sensor1..N−1 + subflow1..N−1 | subflowN 及之後、sensorN 本身 |

1. 每個 sensor 各自一個模型；樣本 = 2000 顆 device（25 片 × 80），特徵約 3000 個，遠多於樣本，**必須正則化或特徵篩選**。
2. 先做基準：依 site 的訓練均值。再試 Ridge（`numpy` 解析解）與 PLS / 主成分迴歸；特徵先做標準化（用訓練 wafer 的統計量）。可把 `site` 當特徵。
3. **依 wafer 分組的交叉驗證**（不可讓同一片 wafer 同時在訓練與驗證），逐 sensor 報告 RMSE、MAE，以及**相對均值基準的改善**：skill = 1 − RMSE²/var。
4. 異常 wafer 會不會拖累模型？比較「全部 wafer 訓練」與「只用 Normal wafer 訓練」，並分別看在異常 wafer 上的預測誤差。
5. 本機用 `numpy` 即可；`scikit-learn` 可以裝在本機做對照，但**最終匯出的模型必須能純 Python / `numpy` 評估**。
6. 匯出 `bin/model/predictor.json`：每個 sensor 的特徵清單（`test_key`）、標準化參數、權重、截距、保底均值（依 site）、訓練摘要。檔案盡量 < 2 MB。
**驗收**：報告每個 sensor 的 CV RMSE 與 skill；至少多數 sensor 明顯優於基準。若某個 sensor 無法改善，誠實回報並保底用均值。

### E4（S2，約 3 小時）執行期 `bin/predictor.py`
1. 依 0.3 契約實作 `Predictor`：`load` / `begin_touchdown` / `observe` / `predict` / `info`。只依賴標準函式庫（若用 `numpy`，pod 已有 2.2.6；但請確認速度與相容性）。
2. `observe(test_key, site, value)`：只保存被模型用到的特徵（用 dict 查表，O(1)）；key 用 `normalize_key` 同樣的規則（去掉開頭 `數字_`），與 A 的偵測器一致。
3. `predict(target, sites)`：
   - `target` 接受多種寫法（`"100_Main.sensor1_CP"`、`"Main.sensor1"`、`"sensor1"`、整數 `100`），統一對應到六個 sensor。
   - 對每個 site 用該 site 目前收集到的特徵算預測；**缺的特徵**用訓練均值補上，並記錄 `missing` 與 `fallback`（缺太多時整個 site 回傳保底均值）。
   - **永遠回傳有效數值**（不可丟例外、不可回空）。
4. 效能：`predict()` 一次呼叫（含所有 site）< 5 ms；`observe()` 逐筆 O(1)。
5. `tests/test_predictor.py`：契約欄位、缺特徵保底、`target` 各種寫法、載入失敗（檔案缺失 / 損毀）不崩潰、效能、與離線評估的預測值一致。
**驗收**：單元測試通過；用離線資料逐 touchdown 餵入，預測值與 `eval_predictor.py` 的結果一致。

### E5（S2）交接
通知 B（可整合，附使用範例）、D（`PredRecord` 格式）、A（`wafer_data.py`）；寫 `ai_notes/` 紀錄。

### E6（S2 到 S3，約 2 小時）整合驗證
1. 和 B 一起用 `predict_request("sensor1")` 到 `"sensor6"` 測 `consumeTPRequest` 的整個流程。
2. 和 C 一起在真機驗證：請求到達時，前面測項的資料是否已收到（`missing` 比例）；必要時決定保底策略。
3. 在 Edge pod 量 `predict()` 的耗時。
4. 把預測 vs 實際的整體誤差報告交給 D（面板）與講稿。

### E7（S3 到 S4）簡報、Demo、合併
1. **Demo 故事**：一片 wafer 開測 → 即時偵測（場景一）→ wafer 結束產生報告 → 每個 sensor 前的預測與實際比較（場景二）。主線可以用 W1（Site unbalance）；再放一片 Normal 與一片其他異常，展示分類。
2. **簡報骨架**：問題與價值（教材第 4 頁的 ROI）→ 架構（Nexus → Edge → 決策回傳）→ 場景一方法與結果 → 場景二方法與結果 → Demo → 數字與**誠實的限制**（每類異常樣本極少、預測的適用範圍、門檻為外推值）。對照評分表逐項說明。
3. **收尾**：確認每個人都有 `ai_notes/` 的繁中紀錄；依 AGENTS.md，合併前需要人類 Code Review。
4. **合併順序建議**：A → E → B → D → C；每合併一支就重跑 `python3 -m unittest discover -s tests`。審查重點：`bin/` 底下沒有多餘檔案（`__pycache__`、暫存檔、資料檔）、沒有密碼或金鑰、註解為英文單行、`ai_notes/` 紀錄齊全。
5. 最終部署由 C 從 `main` 重新 build 一次，並再跑一遍驗收清單。

## 4. 交接與依賴
- **你 → 全隊**：E0 的答案（越早越好）。**你 → A**：`wafer_data.py` 與 25 份資料。**你 → B、D**：`Predictor` 與 `PredRecord`。
- **C → 你**：真實事件的 key 與 `predict` 請求實際到達的時序（E6）。
- **A → 你**：偵測與標籤驗證的最終數字（簡報用）。**D、C → 你**：截圖、錄影與手冊（簡報用）。

## 5. 常見坑
- **不可洩漏**：特徵篩選、標準化、超參數選擇都只能用訓練資料；驗證一律依 wafer 分組。
- 樣本 2000 顆、特徵 3000 個，容易過擬合；沒有明顯優於均值基準時不要硬上複雜模型。
- 執行期讀取 `predictor.json` 要快、且檔案缺失時不能崩潰（保底均值）。
- 預測請求與量測資料走不同通道（ZMQ / Kafka），請求到達時特徵可能還沒齊；務必有保底策略並量測缺失率。
- 資料檔不要放進 repo（`bin/` 內任何檔案都會進 image）。
