# 任務書 A：偵測器（Phase 1 剩餘與強化）

> 你是 **A**。你負責 `Edge/oneAPI_py3.10/bin/detector.py`、`bin/model/baseline.json`、`tools/`、`tests/test_detector.py`。B 依賴你的介面，**請先做 A1**。

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
1. 偵測器能安全接進 `sample.py`：新增 `onset`/`cleared`/`info()`（A1）。
2. 在 Edge pod（Python 3.10）上確認效能（A2）。
3. 改善「標準差 ×2 要 44 個 DUT 才抓到」的延遲，並視情況加學習式判定器（A3、A4）。
4. 交出講稿用的最終數字與限制（A5、A6）。

## 2. 你擁有的檔案
`bin/detector.py`、`bin/model/baseline.json`、`tools/fit_baseline.py`、`tools/inject_anomalies.py`、`tools/evaluate_detector.py`、`tests/test_detector.py`；文件 `ai_notes/20260918_sonnet5_phase1_spec.md`。其他人不要改這些檔案，需要就找你。
**硬性限制**：`bin/detector.py` 只能用標準函式庫；`update()` 必須 O(1)；改任何偵測器後要重新校準（`python3 tools/evaluate_detector.py calibrate`）並跑全部測試。

## 3. 任務清單

### A1（S1，最優先，約 45 分鐘）新增 `onset` / `cleared` / `info()`
**為什麼**：視窗型偵測器在異常結束後仍會持續約一個視窗長度（CSV 重播時第 1 到 19 個 touchdown 全部判為異常）。B 只該在「轉為異常」的那一刻寫 `set_message`，所以需要這兩個欄位。
1. 讀 `bin/detector.py` 的 `_verdict()`、`end_touchdown()`、`reset()`。
2. `Detector.__init__` 加 `self._prev_anomaly = False`。
3. `end_touchdown()` 取得 verdict 後加入：`verdict["onset"] = verdict["anomaly"] and not self._prev_anomaly`、`verdict["cleared"] = self._prev_anomaly and not verdict["anomaly"]`，再更新 `_prev_anomaly`。`_verdict()` 在「沒有警報」時回傳的字典也要含這兩個欄位（值為 `False`）。
4. `reset()` 把 `_prev_anomaly` 設回 `False`。
5. 新增 `info()`：`monitored_tests` = 基準線中 `monitor` 為真的測項數；`baseline_tests` = 基準線總數；`load_error` = `self.load_error`。
6. `tests/test_detector.py`：`test_verdict_schema_and_message_length` 的欄位集合加入 `onset`、`cleared`；新增測試：連續異常只有第一個 touchdown 的 `onset` 為 `True`；恢復正常後恰好一次 `cleared`；`info()` 數字正確。
7. 更新 `ai_notes/20260918_sonnet5_phase1_spec.md` 第 5 節，並通知 B、D（契約已含此欄位）。
**驗收**：
```
cd Edge/oneAPI_py3.10
python3 -m unittest tests.test_detector -v          # 全數通過
python3 tools/evaluate_detector.py replay            # 仍在第 1 個 touchdown 起判異常，且沒有錯誤輸出
```

### A2（S1，約 60 分鐘）Edge pod 效能量測
1. 在專案根目錄的 `Edge/oneAPI_py3.10` 下，把檔案複製到 pod（登入密碼由你手動輸入，**不要寫進指令或檔案**）：
```
scp -o ProxyJump=advantest -P 29022 bin/detector.py debugger@advantestcell.local:~/project/oneAPI_py3.10/bin/
scp -o ProxyJump=advantest -P 29022 -r bin/model debugger@advantestcell.local:~/project/oneAPI_py3.10/bin/
scp -o ProxyJump=advantest -P 29022 -r tools tests debugger@advantestcell.local:~/project/oneAPI_py3.10/
```
2. 登入 pod：`ssh -J advantest -p 29022 debugger@advantestcell.local`，然後：
```
cd ~/project/oneAPI_py3.10
python3 -m unittest discover -s tests 2>&1 | tail -5     # test_sample_local 的 1 項失敗是已知
python3 tools/evaluate_detector.py verify --clean-tests 3029 --clean-td 300 --reps 3 --horizon 60
```
3. 記錄：每個 touchdown 的毫秒數、`update()` 的 p50 / p99、誤判次數；和本機（33.3 ms / touchdown、p99 2.2 µs）比較。
4. **決策規則**：若 pod 上每個 touchdown 超過 150 ms，寫一支小工具把次要測項的 `monitor` 設為 `false`（白名單），不要手改 JSON；否則維持現狀。
5. 把數字寫進 `ai_notes/`。
**驗收**：有 pod 上的實測數字與結論。**注意**：pod 上只有 `/home/debugger/project` 會保留；不要在 pod 直接改程式，改本機再 `scp`。

### A3（S1 到 S2，約 2 到 3 小時）群組層級統計量（改善變異偵測延遲）
**為什麼**：現在每個測項各自偵測，為了壓低誤報門檻很嚴，所以標準差 ×2 要 44 個 DUT。異常通常牽動一整群測項，把同一 pin 群組的測項合併成少數幾條串流，靈敏度會大幅提高。
1. 每個 touchdown 對每個（pin, site）累積：測項數 `n`、`Σz`、`Σz²`（用截斷後的 z）。pin 由測項 key 取 `#` 之後的部分（狀態裡預先算好，避免每筆重算）。
2. 標準化：`g_mean = Σz / sqrt(n)`（H0 下約 N(0,1)）；`g_var = (Σz²/n − 1) * sqrt(n/2)`（H0 下約 N(0,1)）。
3. 對 `g_mean`（每個 pin × site 一條）與 `g_var`（每個 pin 一條，合併各 site）各套 CUSUM / EWMA。新增 alert 種類 `group_shift`、`group_variance`，`test` 欄放 pin 名稱。
4. 判定規則：群組層級的警報本身就代表多個測項，可直接使 `anomaly = True`（不必再湊 K 個測項）。
5. 校準：群組串流只有約 19 pin × 4 site 條，誤報預算比逐測項寬鬆很多，門檻可以低得多。在 `tools/evaluate_detector.py` 新增情境「標準差 ×2 影響 ≥20 個測項」「位移 1σ 影響 ≥20 個測項」，用 `sweep` 產出取捨曲線，再校準。
6. 補單元測試；重新跑 `verify`，確認既有情境沒有退步、每個 touchdown 仍 < 150 ms。
7. 更新 spec 第 4、11 節。
**驗收**：標準差 ×2 且影響 ≥20 個測項時，中位延遲明顯低於 44 DUT（目標 ≤ 20），乾淨資料重播 10,000 顆 DUT 仍為 0 次誤判，既有情境的偵測率與延遲沒有變差。

### A4（S2，選配；若 A3 沒做完就放掉）學習式判定器
用合成標籤訓練一個小模型，取代「同群組 ≥3 個測項」的手寫規則。
1. 定義每個 touchdown 的特徵：各類警報數、同群組最大警報測項數、最高分數、受影響 site 數、群組統計量。
2. 新增 `tools/train_combiner.py`：用 `inject_anomalies.generate` 產生資料（多種異常、多種強度、不同受影響測項數）加上乾淨資料；標籤為「該 touchdown 已在異常區間內」。
3. 本機安裝 `scikit-learn`（`pip install scikit-learn`，只在本機，不進 image），訓練 Logistic Regression；把權重匯出到 `baseline.json` 的 `"combiner": {"features": [...], "w": [...], "b": ..., "threshold": ...}`。
4. `detector.py` 若讀到 `combiner` 就用純 Python 計算 `sigmoid(w·x + b)`，否則沿用規則。
5. 驗證：留出一種訓練時沒用過的異常類型；用 CSV 真實埋的 site 4 突發當外部驗證；與規則式並列比較（同誤報下的偵測率、延遲）。
6. 只有在明顯較好時才採用；否則保留為選配並在講稿說明。
**驗收**：報告並列比較表，明確寫出採用或不採用的理由。

### A5（S3，約 1 小時）最終驗證與數字
1. 在 pod 重跑 `verify`，記錄最終數字（誤判、各異常偵測率與延遲、`update()` 延遲）。
2. 更新 `baseline.json` 的參數並通知 B、E（若有變動，E 需重新 build）。
3. 把最終數字與已知限制寫進 `ai_notes/`。

### A6（S4）講稿要點
準備一頁說明，內容至少包含：偵測了哪四類異常（教材第 29 頁）、為何用統計方法（沒有標籤、可解釋、執行期免套件）、CSV 內真實埋的 site 4 突發異常如何被抓到、最終數字、**誠實的限制**（沒有標籤、效果由合成注入與埋入異常驗證、門檻為外推值、測項名稱對應需真實環境驗證、警報有黏性）。

## 4. 交接與依賴
- **你 → B**：A1 完成後立刻通知（B 在 S1 先照契約寫，等你的欄位）。
- **C → 你**：C 的探查結果若顯示 key 格式不同，你調整 `normalize_key`（並通知 B）。
- **你 → E**：`baseline.json` 有變就通知 E 重新部署。

## 5. 常見坑
- 極端值（CSV 內有約 240σ 的尖峰）會讓累積型偵測器持續告警；輸入已做截斷（±4 / ±3），改動時不要拿掉。
- `evaluate_detector.py sweep` 的誤報率是單串流外推值，改參數後務必再跑 `verify` 做全規模乾淨重播確認。
- 本機是 Python 3.13、pod 是 3.10：不要用 3.11 以後的語法。
- 不要在 `bin/` 底下留下 `__pycache__` 或測試暫存檔（會被打包進 image）。
