# Phase 1 Spec：異常偵測器（已實作，見第 11 節）

> 狀態：**已依預設實作**。第 2.3 節原先「沒有埋異常」的結論**有誤**，已更正；實作結果與和原 spec 的差異記錄在第 11 節。

---

## 1. 目標與範圍

**目標**：產出一個可在 Edge Server 上即時運作的異常偵測器，以及驗證它的離線工具，供 Phase 3 接進 `sample.py`。

**範圍內**
- 偵測器函式庫（執行期，純 Python 標準函式庫）
- 離線建立基準線（baseline）的工具
- 合成異常注入 + 評估工具（沒有標籤，靠注入異常驗證）
- 單元測試

**範圍外**（後續 Phase 處理）
- 接進 `sample.py`、呼叫 `ActionManager`（Phase 3）
- Flask 儀表板（Phase 5）、Java flow 修改（Phase 4）、Docker 打包（Phase 6）

## 2. 已查證的事實（設計依據）

### 2.1 教材第 29 頁定義了要偵測的異常（`doc/WorkShop_Material.pdf`）
1. **Site 間不平衡**：4 個 site 的箱形圖中某個 site 明顯偏離（圖上標 "Significantly Different"）
2. **趨勢問題**：平均值上升/下降（線性漂移）、標準差趨勢改變（散佈越來越大）、量測值位移（階梯式跳變）
3. **基準假設**：沒有異常時，量測值分佈為**常態分佈**（Gaussian）

### 2.2 資料格式
- 教材第 28 頁的資料集是「寬表」：每列一顆元件，欄位為 `PID, Lot, Wafer, Site, X, Y, PF, SBin, HBin, Test Time`，之後每個測項一欄，欄名為 `<test number>_<test suite>#<pin>`（例：`220_Main.Suite1#CP`），表頭另有 `Pin / Test Num / High Limit / Low Limit` 列。
- 教材範例的上下限是 High=0.6、Low=1.8（**高低顛倒**），量測值卻在 1.2 附近 → **偵測器不可依賴上下限**，只看分佈。
- `example.csv`（教材的資料集）**不在 repo 裡**。repo 內可用的是 `SmarTest/Case_Smt870/src/TestCase1/TestCase1_OfflineData.csv`（「長表」：每列一個測項、每欄一顆 DUT）。

### 2.3 離線 CSV 實測結果
- 80 顆 DUT；**3035 列**是帶 Pin 的數值測項（19 種 pin，多數為 `CP`）；另有 1 列 pattern（功能測試）、以及 lot/wafer/x/y 資訊列。
- 4 site 對應：推定 `site = DUT 序號 % 4`（教材範例 Site 欄為 1,2,3,4,1,2…，ACS 畫面上 DUT 77–80 對應 site 1–4）。**這是推定，需要在 Phase 2/7 用真實事件確認。**
- **這份 CSV 有埋異常**（原 spec 寫「沒有」是錯的，因為我最初用平均值/標準差類的統計量，被離群值本身撐大而漏掉）。改用中位數/MAD 為基礎並以「模擬純雜訊」當對照後：
  1. **Site 4 突發離群值**：約 110 個測項（多數是 `subflow1` 的 `CP`）在 DUT 索引 7、11、15、19、23（0 起算，即第 2 至 6 個 touchdown 的 site 4）出現 **+8 到 +13σ** 的偏高值。這也支持 `site = DUT 序號 % 4` 的對應（五個離群點全部落在同一個 site）。
  2. **個別極端尖峰**：少數測項有單筆高達約 240σ 的值，以及零星其他離群點。
  3. 其餘四類統計量（site 中位數偏移、Theil–Sen 漂移、前後半段位移、前後半段標準差比）的超標數（各約 0 到 7 個）與純雜訊預期（約 3 個）一致，**沒有埋 site 偏移、漂移、位移、變異**。
- 影響：基準線必須用**穩健統計量**（中位數 + 1.4826×MAD）；極端值進入累積型偵測器前必須**截斷**，否則單一尖峰會把 EWMA、site 視窗與漂移視窗撐爆，警報持續 20～30 個 touchdown（實測踩到，見第 11 節）。

### 2.4 環境限制（實測）
- Edge dev pod：Python 3.10.12、有 `numpy 2.2.6`、`flask`；**沒有** `pandas`/`scikit-learn`/`matplotlib`/`pillow`/`joblib`/`onnxruntime`，且 pod **不能連外網**。
- 本機 WSL 是 Python 3.13，程式碼必須同時相容 3.10。
- 官方 manual：`consumeData` 等 callback 是**阻塞式**，處理太慢會卡住後續事件；欄位必須在 callback 內立即讀出。

## 3. 設計決策

| 決策 | 選擇 | 理由 | 替代方案 |
|---|---|---|---|
| 演算法 | SPC 統計法（CUSUM/EWMA/回歸斜率） | 沒有標籤、常態假設成立、可解釋、環境不需額外套件 | `IsolationForest`：需要 `scikit-learn`，pod 沒裝也不能連外網 |
| 執行期相依 | **只用標準函式庫** | 逐筆 O(1) 純量運算，純 Python 比 numpy 逐次呼叫還快；連 numpy 都不需要 | 用 numpy（多一個相依，逐筆更慢） |
| 離線工具相依 | 允許 numpy | 只在本機跑，不進 image | — |
| 更新方式 | 串流式，逐筆更新狀態 | 符合阻塞 callback 的效能要求 | 批次重算（延遲高） |
| 基準線 | 離線基準線 JSON 為先驗；**遇到沒見過的測項自動暖機**（前 N 顆學平均/標準差） | 離線資料只有 80 顆、且 lot 之間會不同；也能避免測項名稱對不上時整個失效 | 只用離線基準線（脆弱） |
| 判定粒度 | 每個 touchdown 產生一個彙總判定 | 3035 個測項若逐項告警會爆量 | 逐項告警 |
| 訓練責任 | **由我們自行訓練，沒有現成模型提供**（2026-09-19 由使用者確認） | 執行期環境的限制（無 `scikit-learn`、不能連外網）只約束「執行期」；訓練在本機或 Gemini 進行，產出檔案再部署 | — |

## 4. 偵測規格

對每個測項維護狀態。標準化：`z = (x − μ) / σ`（μ、σ 來自基準線或暖機）。**以下參數皆為暫定值，最終以校準結果為準**（見 6.2）。

| 異常類型 | 對應教材 | 統計量 | 暫定參數 |
|---|---|---|---|
| `mean_shift` | 量測值位移 | 雙邊 CUSUM（作用於 z） | k=0.5，h 由校準決定 |
| `mean_drift` | 平均值上升/下降 | 最近 W 個 touchdown 平均值的線性回歸斜率 t 統計量 | W=30，門檻由校準決定 |
| `variance_change` | 標準差趨勢改變 | z² 的 EWMA | λ=0.1，控制界限由校準決定 |
| `site_imbalance` | Site 間不平衡 | 各 site 最近 Ws 筆平均與基準 μ 的差（以 σ/√Ws 標準化） | Ws=20，須連續 3 個 touchdown 同方向 |
| `outlier` | （補充，非教材項目） | `|z|` 單筆門檻 | 5 |

**彙總判定（每個 touchdown）**：同一 pin 群組內累積 ≥ K 個測項告警，或任一告警分數 ≥ S_hard，則 `anomaly = True`（暫定 K=3）。原因：真實異常通常牽動一整群相關測項，且一次監控約 12,000 條串流（3035 測項 × 4 site），單條門檻設在 3σ 會產生大量誤報。

## 5. 介面契約（Phase 3 / Phase 5 會依賴，改動需通知）

```python
det = Detector.load("model/baseline.json")            # baseline 檔可缺席，缺席時全部測項走暖機
alerts = det.update(test_key, site, value, seq)       # 逐筆呼叫，O(1)，回傳 list[Alert]（多數情況為空）
verdict = det.end_touchdown()                         # 每個 touchdown 結束時呼叫一次
det.reset(scope="lot")                                # "lot" 或 "wafer"
```

```python
Alert   = {"kind": "mean_shift|mean_drift|variance_change|site_imbalance|outlier",
           "test": str, "site": int | None, "score": float, "seq": int}
Verdict = {"anomaly": bool, "score": float, "n_alerts": int,
           "top_alerts": [Alert, ...],                # 最多 5 筆，供 set_message 與儀表板使用
           "message": str}                            # 單行摘要，長度上限 200 字元
```

- `test_key` 格式沿用教材：`<test number>_<test suite>#<pin>`。**執行期事件的 `query_TestNumber`/`query_TestSuite`/`query_MeasurementName` 能否組出同一個 key 尚未驗證**（見第 9 節問題 4）。
- `baseline.json`：`{"version": 1, "tests": {"<test_key>": {"mu": float, "sigma": float, "n": int}}, "params": {...}}`，預估約數百 KB。

## 6. 驗證計畫（無標籤，靠合成注入）

### 6.1 測試資料
- **乾淨資料**：由離線 CSV 擬合每個測項的 (μ, σ)，再以常態分佈**產生任意長度的乾淨串流**（因為原始資料只有 80 顆，不夠估計低誤報率）。
- **異常注入**（依教材四類，注入強度可調）：
  - 位移：從第 t0 顆起加 `+a·σ`
  - 漂移：從第 t0 顆起每顆加 `b·σ/顆` 的斜率
  - 變異：從第 t0 顆起標準差乘以 `c`
  - Site 不平衡：某一 site 加 `+d·σ`
  - 注入範圍：整個 pin 群組（例如 `CP` 的一部分測項），模擬真實情境

### 6.2 校準與驗收（**數值為提案，請確認或調整**）
| 項目 | 提案標準 |
|---|---|
| 誤報率 | 乾淨串流上，每 5,000 顆 DUT 最多 1 次錯誤的 `anomaly=True` |
| 位移 ≥ 3σ | 偵測率 ≥ 95%，延遲 ≤ 20 顆 DUT |
| Site 偏移 ≥ 3σ | 偵測率 ≥ 95%，延遲 ≤ 40 顆 DUT |
| 標準差 ×2 | 偵測率 ≥ 90%，延遲 ≤ 30 顆 DUT |
| 漂移（80 顆內累積 ≥ 4σ） | 偵測率 ≥ 90% |

- **門檻不採用教科書常數**，而是以「達成誤報率目標」為條件，在乾淨串流上校準 h、W 等參數，並把最終值寫進 `baseline.json` 的 `params`。
- 評估工具輸出偵測率、延遲、誤報率的報告（文字表格）。

### 6.3 基準線品質檢查
對每個測項做偏度/峰度檢查，回報偏離常態的比例（呼應 2.3 節標準差比尾巴偏重的現象），偏離嚴重的測項標記為「不監控」或改用較保守門檻。

## 7. 效能預算（**提案，需在 Edge pod 實測**）
- 單次 `update()`：p99 ≤ 200 µs
- 單個 touchdown（3035 測項 × 4 site ≈ 12,000 次更新 + 一次 `end_touchdown()`）：≤ 150 ms
- 記憶體：每條串流狀態為常數大小（數個浮點數與一個長度 ≤ 30 的環形緩衝）
- 若超出預算：支援設定「只監控指定測項/pin」的白名單作為退路

## 8. 交付物與檔案配置（全部為新增檔案）

| 路徑 | 用途 | 是否進 image |
|---|---|---|
| `Edge/oneAPI_py3.10/bin/detector.py` | 偵測器（僅標準函式庫） | 是（在 `bin/`） |
| `Edge/oneAPI_py3.10/bin/model/baseline.json` | 基準線與校準後參數 | 是 |
| `Edge/oneAPI_py3.10/tools/fit_baseline.py` | 從 CSV 擬合基準線（numpy） | 否 |
| `Edge/oneAPI_py3.10/tools/inject_anomalies.py` | 合成串流與異常注入 | 否 |
| `Edge/oneAPI_py3.10/tools/evaluate_detector.py` | 校準 + 產出驗收報告 | 否 |
| `Edge/oneAPI_py3.10/tests/test_detector.py` | 單元測試（`unittest`） | 否 |

- 程式碼註解遵守 AGENTS.md：英文、單行、量不超過程式碼。
- `detector.py` 不得 import `oneapi`/`libACSAction`，保持可在本機獨立測試。

## 9. 需要你確認的問題（附我的建議預設）

1. **資料來源**：用 repo 內的 `TestCase1_OfflineData.csv` 當乾淨基準 + 合成注入異常？教材的 `example.csv` 不在 repo，你們手上有嗎？ → 建議：先用 CSV，有 `example.csv` 再補一個轉接器。
2. **執行期相依**：偵測器只用標準函式庫（不依賴 numpy）？ → 建議：是。
3. **異常類型**：採用教材四類 + 補充的 `outlier`？ → 建議：是。
4. **測項 key**：執行期事件要組出和基準線一致的 key，需在真實環境確認欄位；在此之前先靠「暖機」保底。這個風險你接受嗎？ → 建議：接受，並在 Phase 2 加一支印出真實 key 的小工具。
5. **驗收數值**（6.2 節）：誤報率、偵測率、延遲是否合理？有沒有評審或題目要求的指標？
6. **判定規則**：K=3 個測項同 pin 群組告警才算異常，是否符合你們想展示的情境？
7. **不做 `IsolationForest`**（環境沒有 `scikit-learn`）：可以接受作為「後續選配」嗎？

## 10. 確認後的實作步驟

1. `tools/fit_baseline.py`：讀 CSV → 輸出 `baseline.json`（含基準線品質檢查）
2. `bin/detector.py`：先做 `outlier` 與彙總判定，補單元測試
3. 依序加入 `mean_shift`、`variance_change`、`mean_drift`、`site_imbalance`，每加一種就補測試
4. `tools/inject_anomalies.py` + `tools/evaluate_detector.py`：校準參數，產出驗收報告
5. 在 Edge dev pod 實測效能預算（需你確認可以部署/複製檔案到 pod）
6. 更新 `ai_notes` 並回報結果，交給 Phase 3 接線

## 11. 實作結果與和原 spec 的差異

### 11.1 已建立的檔案（均位於 `Edge/oneAPI_py3.10/`）
`bin/detector.py`、`bin/model/baseline.json`（288 KB，含校準後參數）、`tools/fit_baseline.py`、`tools/inject_anomalies.py`、`tools/evaluate_detector.py`、`tests/test_detector.py`（14 項，全數通過）。沒有修改任何既有檔案。

### 11.2 和原 spec 不同的地方
| 項目 | 原 spec | 實作 | 原因 |
|---|---|---|---|
| 累積型偵測器的輸入 | 直接用 z | **先截斷**：CUSUM/漂移/site 視窗用 ±4、變異用 ±3；`outlier` 用未截斷的 z | CSV 內有 240σ 尖峰，單筆就把視窗撐爆，警報持續 20～30 個 touchdown（實測踩到） |
| 變異統計量 | z² 的 EWMA | **同一 site 連續兩筆差的平方（÷2）** 的 EWMA | 不受平均值位移、site 偏移影響，避免兩種異常互相誤觸 |
| 基準線估計 | 平均值/標準差 | **中位數 + 1.4826×MAD**；品質檢查改看去除離群值後的偏度/峰度 | 資料內有埋離群值；原本的矩統計量把 119 個最有價值的測項誤排除（現在 3035 個中只排除 6 個） |
| 測項名稱 | 完整 key | **自動去掉開頭的 `<數字>_`** 再比對 | CSV 沒有 test number，執行期事件有；避免對不上 |
| 觸發時機 | 逐項 | `outlier`、`mean_shift`、`variance_change` 在 `update()`；`mean_drift`、`site_imbalance` 在 `end_touchdown()` | 後兩者以 touchdown 為單位累積 |
| 驗收數值 | 固定提案值 | **暫定目標 + 取捨曲線**（`evaluate_detector.py sweep`），參數由誤報率預算校準 | 你同意的調整 |

### 11.3 校準結果（`evaluate_detector.py calibrate`，誤報預算：3029 個測項、每 5,000 顆 DUT 最多 1 次誤判）
每種偵測器的穩態警報比例必須 ≤ 1.45e-5（由 K=3 的 Poisson 尾端反推）。以尾端外推得到的參數：

| 異常 | 參數 | 偵測率 | 中位延遲（DUT） | 暫定目標 |
|---|---|---|---|---|
| 位移 +3σ | `cusum_h=12.3` | 1.00 | 8 | ≥95%、≤20 |
| 標準差 ×2 | `ewma_lambda=0.05`、`ewma_L=9.0` | 1.00 | 40 | ≥90%、≤30（**延遲超標**） |
| 漂移 0.2σ/touchdown | `drift_thr=4.7` | 1.00 | 44 | ≥90%、≤80 |
| 單一 site +3σ | `site_thr=4.6` | 1.00 | 40 | ≥95%、≤40 |

- 變異是唯一沒達標的項目：誤報預算下，標準差 ×2 的偵測要累積較多樣本。想更快就得放寬誤報率（取捨曲線在 `sweep` 的輸出裡）。
- 這些門檻是**外推**得到的（誤報事件太罕見，無法直接量到），因此另以全規模乾淨資料重播驗證（見 11.5）。

### 11.4 用 CSV 內真實埋的異常重播（`evaluate_detector.py replay`）
- 第 0 個 touchdown（DUT 1–4）：無警報。
- **第 1 個 touchdown（DUT 5–8）起判為異常**：正是 site 4 第一個離群點（DUT 8）出現的時間，約 107 個測項同時告警。
- 第 3 至 10 個 touchdown：`mean_shift` 陸續觸發；第 11 個起：`site_imbalance` 約 84 個測項。
- **之後整段（到第 19 個 touchdown）都維持異常**：因為偵測視窗仍包含前面那五個離群點。這是視窗記憶的特性，見 11.6。

### 11.5 全規模驗證
`evaluate_detector.py verify`（本機 Python 3.13）：

- **乾淨資料重播**：3029 個測項 × 2500 個 touchdown（10,000 顆 DUT）→ **誤判 0 次**（暫定目標 ≤ 2 次）；每個 touchdown（約 12,000 筆更新 + 判定）耗時 33.3 ms。
- **注入異常**（20 個 `CP` 測項、10 次重複、事前無誤報）：

| 情境 | 強度 | 偵測率 | 中位延遲（DUT） | 暫定目標 | 結果 |
|---|---|---|---|---|---|
| 位移 | +3σ | 1.00 | 8 | ≥0.95、≤20 | 達標 |
| 位移 | +5σ | 1.00 | 4 | ≥0.95、≤12 | 達標 |
| 標準差 | ×2 | 1.00 | 44 | ≥0.90、≤30 | **延遲未達標** |
| 漂移 | 0.2σ/touchdown | 1.00 | 36 | ≥0.90、≤80 | 達標 |
| Site 偏移 | +3σ | 1.00 | 40 | ≥0.95、≤40 | 達標（剛好在界線） |
| 突發離群（site 4，連續 5 個 touchdown） | +9σ | 1.00 | 4 | ≥0.95、≤8 | 達標 |

- **`update()` 延遲**：p50 0.9 µs、p99 2.2 µs、最大 216 µs（本機）。**Edge pod 上的數字尚未量測**（Python 3.10、CPU 不同），部署後需重跑。

### 11.6 已知限制與 Phase 3 要注意的事
1. **警報有黏性**：視窗型偵測器（`site_imbalance`、`mean_drift`）會在異常結束後持續一段時間（約一個視窗長度）。Phase 3 建議**只在判定由「正常」轉為「異常」的那一刻**呼叫 `set_message`，不要每個 touchdown 都寫。
2. **變異偵測較慢**（40 DUT，未達暫定目標 30）。
3. **測項名稱是否對得上仍未在真實環境驗證**；對不上時偵測器會自動暖機（前 40 個值），但會失去離線基準線的即時性。
4. **`site = DUT 序號 % 4 + 1` 仍是推定**，但 CSV 內五個離群點全落在同一個 site，與此推定一致。
5. `tests/test_sample_local.py` 內 `test_list_request_returns_seeded_message` 目前會失敗（它檢查已還原的測試樁），Phase 3 會取代它。

---

## 修改與新增檔案
- 新增：`ai_notes/20260918_sonnet5_phase1_spec.md`（本檔案）

## 技術細節與邏輯
- 依據：`doc/WorkShop_Material.pdf` 第 28–29 頁、`doc/ONEAPI_Manual.pdf`（callback 阻塞規則）、離線 CSV 的實測統計、以及對 Edge dev pod 與 Host Controller 的唯讀環境檢查。
- 第 2.3 節的統計以本機 numpy 計算：site 間差異採 ANOVA 型統計量、漂移為線性回歸斜率 × 80 / σ、位移為前後各 40 顆的平均差 z 值。

## 待執行事項與注意事項
- 本文件僅為 spec，**尚未實作**；等你確認第 9 節後才會開始。
- 我推定 `site = DUT 序號 % 4`，尚未用真實事件驗證。
- 目前工作目錄仍在 `mchien728_sonnet5` 分支，未 commit。
