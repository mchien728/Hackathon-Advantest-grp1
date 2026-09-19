# 任務書 A：場景一偵測器（補齊題目分類 + wafer 報告資料 + 標籤驗證）

> 你是 **A**。你負責 `Edge/oneAPI_py3.10/bin/detector.py`、`bin/model/baseline.json`、`tools/`（偵測相關）、`tests/test_detector.py`。B、D 依賴你的介面，**請先做 A1**。
> **2026-09-19 更新**：官方題目公布，偵測範圍比原本大（缺標準差下降、良率過低、wafer 分類），且訓練資料有標籤，可以算真正的準確率。

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
1. 偵測器能安全接進 `sample.py`（A1），並在 Edge pod 上確認效能（A2）。
2. **補齊題目的 7 種分類**：標準差下降（A3）、良率過低（A4）、wafer 層級分類與報告資料（A5）。
3. 用**有標籤的 25 片 wafer** 算出真正的準確率（A6）。
4. 交出講稿用的最終數字與限制（A7、A8）。

## 2. 你擁有的檔案
`bin/detector.py`、`bin/model/baseline.json`、`tools/fit_baseline.py`、`tools/inject_anomalies.py`、`tools/evaluate_detector.py`、`tools/eval_labeled_wafers.py`（新增）、`tools/wafer_labels.json`（新增）、`tests/test_detector.py`；文件 `ai_notes/20260918_sonnet5_phase1_spec.md`。
**硬性限制**：`bin/detector.py` 只能用標準函式庫；`update()` 必須 O(1)；改任何偵測器後要重新校準（`python3 tools/evaluate_detector.py calibrate`）並跑全部測試。

## 3. 任務清單

### A1（S1，最優先，約 60 分鐘）`onset` / `cleared` / `info()` / `direction`
**為什麼**：視窗型偵測器在異常結束後仍持續約一個視窗長度，B 只該在「轉為異常」時寫訊息；題目的分類有上升/下降之分，Alert 需要方向。
1. 讀 `bin/detector.py` 的 `_verdict()`、`end_touchdown()`、`reset()`。
2. `Detector.__init__` 加 `self._prev_anomaly = False`；`end_touchdown()` 取得 verdict 後加入 `verdict["onset"] = anomaly and not prev`、`verdict["cleared"] = prev and not anomaly`，再更新 `_prev_anomaly`；「沒有警報」時回傳的字典也含兩個欄位（`False`）；`reset()` 把它設回 `False`。
3. `info()`：`monitored_tests`、`baseline_tests`、`load_error`。
4. **方向**：`_raise(...)` 多收一個 `direction`。`mean_shift`：`cp` 較大 → `"up"`，`cn` 較大 → `"down"`；`mean_drift`：回歸斜率 `zs` 為正 → `"up"`；`site_imbalance`：該 site 平均高於其他 site → `"up"`；`outlier`：`z` 的正負；`variance_change`：先固定 `"up"`（A3 補下降）。
5. 更新 `tests/test_detector.py`：欄位集合加入 `onset`、`cleared`、`direction`；新增測試：連續異常只有第一個 touchdown `onset`；恢復後恰好一次 `cleared`；`info()` 數字正確；位移 +3σ 的方向為 `up`、−3σ 為 `down`。
6. 更新 spec 第 5 節，並通知 B、D。
**驗收**：`python3 -m unittest tests.test_detector -v` 全過；`python3 tools/evaluate_detector.py replay` 仍在第 1 個 touchdown 起判異常。

### A2（S1，約 60 分鐘）Edge pod 效能量測
1. 在 `Edge/oneAPI_py3.10` 下複製檔案到 pod（登入密碼手動輸入，**不要寫進指令或檔案**）：
```
scp -o ProxyJump=advantest -P 29022 bin/detector.py debugger@advantestcell.local:~/project/oneAPI_py3.10/bin/
scp -o ProxyJump=advantest -P 29022 -r bin/model debugger@advantestcell.local:~/project/oneAPI_py3.10/bin/
scp -o ProxyJump=advantest -P 29022 -r tools tests debugger@advantestcell.local:~/project/oneAPI_py3.10/
```
2. `ssh -J advantest -p 29022 debugger@advantestcell.local`，然後：
```
cd ~/project/oneAPI_py3.10
python3 -m unittest discover -s tests 2>&1 | tail -5     # test_sample_local 的 1 項失敗是已知
python3 tools/evaluate_detector.py verify --clean-tests 3029 --clean-td 300 --reps 3 --horizon 60
```
3. 記錄每個 touchdown 的毫秒數、`update()` 的 p50 / p99、誤判數；和本機（33.3 ms / touchdown、p99 2.2 µs）比較。
4. **決策規則**：每個 touchdown 超過 150 ms → 寫小工具把次要測項的 `monitor` 設 `false`（白名單），不要手改 JSON。
5. 把數字寫進 `ai_notes/`。**注意**：不要在 pod 直接改程式，改本機再 `scp`。

### A3（S1 到 S2，約 2 小時）標準差下降（Stdev Trend Down）+ 上升的方向
**現況**：`variance_change` 只有「EWMA 高於上界」才警報，變異變小完全偵測不到。
1. 在 `update()` 內對 `ev`（EWMA）加下界：`ev <= lcl` 觸發，`lcl = 1 − L_low * sd_e`（注意下界不能為負，必要時取對數尺度或用較小的 `L_low`）。狀態多一個 `ev_low_on`；警報的 `direction` 為 `"down"`，上界觸發為 `"up"`。
2. **陷阱**：`z` 已截斷，變異變小時樣本更集中，`ev` 會往 0 靠近；下界比上界更容易受基準線 σ 估計偏誤影響，務必校準。
3. 在 `tools/inject_anomalies.py` 的 `variance_change` 支援 `magnitude < 1`（例如 0.5）；在 `evaluate_detector.py` 加情境 `variance_change 0.5x` 與掃描下界參數，校準到同樣的誤報預算。
4. 補單元測試（×0.5 偵測到且 `direction == "down"`；乾淨資料不誤報）。
**驗收**：標準差 ×0.5 的偵測率 ≥ 90%；乾淨資料 10,000 顆 DUT 仍為 0 次誤判；既有情境無退步。

### A4（S1 到 S2，約 3 小時）良率過低（Low yield）偵測
**題目**：Low yield = yield 低於 80（推定為 80%，待 E0 向主辦方確認）。W3、W9 是這類。
1. `update_device(site, passed, seq)`：累積本 wafer 的已測顆數 `n` 與通過顆數 `k`（可另外維護每個 site 的數字）。
2. 判定：`n ≥ n_min`（暫定 10）後，以 **Wilson 上界**（95%）檢查：`upper(k, n) < 0.80` 才觸發 `low_yield`（避免早期樣本少誤報）。`Alert` 的 `test` 放 `"yield"`，`score = (0.80 − upper) / 0.80` 之類可比較的數值，`direction = "down"`。
3. **「通過」怎麼定義**：STDF 的 `PART_FLG` 第 3 位為 1 代表失敗；範例資料 `PF=0`、`SBin=1` 代表通過。暫定 `passed = (PartFlag == 0)`（或 `SBin == 1`）；**請 C 的探查確認實際欄位語意**，並把判斷抽成 `is_pass(part_flag, sbin)` 小函式方便修改。
4. `end_wafer()` 時用最終良率再確認一次（也可用 B 傳入的 `get_GoodCount` / `get_TestedCount`）。
5. 校準：正常 wafer 的良率分佈要看真實資料（E 取得後），在那之前用合成資料（正常良率 95%～100%、低良率 60%～75%）；補單元測試與 `evaluate_detector.py` 情境。
**驗收**：合成低良率（良率 70%）在 80 顆內偵測到；合成正常（良率 ≥ 95%）不誤報；單元測試通過。

### A5（S2，約 3 小時）wafer 層級分類 `end_wafer()`
**目的**：題目要的是「這片 wafer 是哪一類」與報告，不是「這個 touchdown 有沒有異常」。
1. 整片 wafer 期間累積所有 Alert（依 kind、direction、test、site 統計，記錄各類第一次出現的 touchdown）。
2. 分類規則（先簡單、可解釋，避免過度設計）：
   - 有 `low_yield` 且最終良率 < 0.80 → `Low yield`
   - 否則 `site_imbalance` 集中在**同一個 site** 且涉及測項數超過門檻 → `Site unbalance`
   - 否則 `mean_shift` / `mean_drift` 的方向一致（≥ 80% 為 `up`）且涉及測項數超過門檻 → `Mean Trend Up`；`down` 同理
   - 否則 `variance_change` 方向一致 → `Stdev Trend Up` / `Stdev Trend Down`
   - 都沒有 → `Normal`
   多種同時成立時，用「涉及測項數 × 平均分數」最高者，並在 `evidence` 與 `summary` 註明次要類別。
3. `WaferReport` 各欄位：`onset_td`（該類別第一次出現的 touchdown）、`confidence`（0 到 1，可用涉及測項比例與分數換算）、`yield`、`n_devices`、`evidence`（最多 5 筆代表性 Alert）、`summary`（繁體中文一句話，例如「判定為 Site unbalance：site 4 自第 2 個 touchdown 起偏高，影響 110 個測項」）。
4. `end_wafer()` 後重置 wafer 層級累積器，但保留基準線與各測項狀態（除非 `reset("wafer")`）。
5. 單元測試：對每一類用 `inject_anomalies` 產生合成 wafer（含 Normal），驗證標籤正確；CSV 重播（W1）應為 `Site unbalance`。
6. 通知 B（呼叫時機）、D（`WaferReport` 格式與 `summary`）。
**驗收**：合成 7 類各 20 次，wafer 層級分類準確率 ≥ 90%（暫定）；CSV 重播 W1 → `Site unbalance`。

### A6（S2 到 S3，約 3 小時）用有標籤的 25 片 wafer 驗證與重估基準線
**前提**：E 完成 `tools/wafer_data.py`（解析寬表 csv）並取得 25 份資料。在此之前先做 `wafer_labels.json` 與腳本骨架，用 W1 測試。
1. 建 `tools/wafer_labels.json`：`{"W1": "Site unbalance", "W3": "Low yield", "W9": "Low yield", "W14": "Mean Trend Up", "W18": "Mean Trend Down", "W23": "Stdev Trend Up", "W25": "Stdev Trend Down"}`，其餘為 `"Normal"`。
2. **重估基準線**：`fit_baseline.py` 改成能吃多份寬表 csv，只用 **Normal wafer** 擬合（18 片 × 80 顆，比單片穩健得多），重新校準並更新 `baseline.json`。
3. 寫 `tools/eval_labeled_wafers.py`：逐片依 PID 順序重播（site 取 `Site` 欄，touchdown 由 4 顆一組），呼叫 `update` / `update_device` / `end_touchdown` / `end_wafer`，輸出：每片預測標籤 vs 真實標籤、7 類混淆矩陣、準確率、每類召回率、**18 片 Normal 上被誤判的片數**、`onset_td`。
4. **避免自己騙自己**：每種異常只有 1～2 片，不要同時拿它們調參又報準確率。做 **leave-one-wafer-out**：評估某一片時，基準線不含該片；參數用合成資料校準；在報告誠實標示樣本數。
5. 產出報告 `ai_notes/`，並通知 E（Demo 用數字）與 D（哪些 wafer 適合當展示）。
**驗收**：有完整混淆矩陣與逐片結果；報告寫明限制。

### A7（S3，約 60 分鐘）最終驗證
在 pod 重跑 `verify`；更新最終數字；`baseline.json` 有變動就通知 C（重新部署）。

### A8（S4）講稿要點
偵測了哪 7 類（對應題目）、為什麼用統計方法（可解釋、執行期免套件、即時）、25 片標籤 wafer 的結果、最終數字、**誠實的限制**（每類樣本極少、門檻為外推值、測項名稱與良率欄位語意需真實環境確認、警報有黏性）。

### （選配，僅在 A1–A6 完成後）群組層級統計量與學習式判定器
群組統計量：同一 pin 群組、同一 site 的 `Σz`、`Σz²` 合併成少數幾條串流，可提高變異偵測靈敏度；學習式判定器可用有標籤的 wafer 訓練小型分類器取代手寫分類規則（需留出驗證）。做不完就放掉。

## 4. 交接與依賴
- **你 → B、D**：A1（欄位）、A4（`update_device`）、A5（`end_wafer` 與 `WaferReport`）。B 在此之前先照 0.3 的契約寫，用暫時的 stub。
- **E → 你**：`wafer_data.py` 與 25 份資料（A6）。**C → 你**：`PartFlag` / `SBin` 的實際語意（A4）；key 格式若不同，你調整 `normalize_key` 並通知 B。
- **你 → C**：`baseline.json` 有變就通知重新部署。

## 5. 常見坑
- 極端值（CSV 有約 240σ 的尖峰）會讓累積型偵測器持續告警；輸入已做截斷（±4 / ±3），改動時不要拿掉。
- `evaluate_detector.py sweep` 的誤報率是單串流外推值，改參數後務必再跑 `verify`。
- 本機是 Python 3.13、pod 是 3.10：不要用 3.11 以後的語法。
- 不要在 `bin/` 底下留下 `__pycache__` 或暫存檔（會被打包進 image）。
