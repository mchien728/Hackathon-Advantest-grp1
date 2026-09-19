# Phase 1 Spec：異常偵測器（已實作，見第 11 節）

> 狀態：**已依預設實作（僅場景一的一部分）**。**2026-09-19 補充：官方題目（`Question_20260919.pdf`）比本 spec 的範圍大，見第 0 節、4.1、12 節。**第 2.3 節原先「沒有埋異常」的結論**有誤**，已更正；實作結果與和原 spec 的差異記錄在第 11 節。

---

## 0. 題目要求（`ai_notes/Question_20260919.pdf`，2026-09-19 補充；優先於本文其他假設）

**題目**：用 ACS RTDI 開發即時監測量產的方案，用 AI/ML 發現問題或預測 IC 效能，佈署到生產線；發現問題時即時通知/詢問，或與測試機台軟體互動。

**兩個場景**
1. **場景一（異常偵測 + 報告）**：即時偵測異常，並把異常整理成報告，通知特定人員或供其查詢。
2. **場景二（預測）**：預測 IC 的溫度，並把結果通知機台軟體。

**評分**：完成度 60%（符合場景 10%、能在 ACS Gemini 順利運行 25%、正確的時機偵測問題或預測結果 25%）；創新 40%（資料分析方法 15%、**異常報告的呈現是否新穎 25%**）。

**資料**：25 片 wafer × 80 顆 device × 約 3000 測項，csv 格式的 25 份 data log（**訓練用，目前不在 repo**）；另有「用來評估結果的測試程式」。**訓練資料有 wafer 層級的標籤**（題目第 3 頁）：

| 標籤 | wafer |
|---|---|
| Site unbalance | W1 |
| Low yield（yield 低於 80，推定為 80%） | W3、W9 |
| Mean Trend Up | W14 |
| Mean Trend Down | W18 |
| Stdev Trend Up | W23 |
| Stdev Trend Down | W25 |
| Normal（共 18 片） | W2、W4–W8、W10–W13、W15–W17、W19–W22、W24 |

**測試流程與「不可洩漏」規則**（第 4 頁）：Start → PreBind → PreRun → Main：Suite1–14 → IDDQ_flow →（receive_temp_predict1 → sensor1 → subflow1）→ … →（receive_temp_predict6 → sensor6 → subflow6）→ 依 `fail_rate` 分 bin。**訓練預測 sensorN 的模型時，不能使用尚未執行的測項結果**（例：預測 sensor1 不能用 subflow1 之後的資料）。

**執行期協定**（第 5、6 頁）
- 場景二：測試程式把要預測的測項編號送給容器（`100_Main.sensor1_CP`、`120_Main.sensor2_DS0`、`140_Main.sensor3_IO4`、`160_Main.sensor4_IO1`、`180_Main.sensor5_IO2`、`200_Main.sensor6_IO3`），容器預測後回傳。題目附的範例是在 `consumeTPRequest` 加 `key == "predict"` 分支，把各 site 的預測值組成字串，呼叫 `ActionManager.set_wait(tc.testerId, wait, message)`，再 `response = ActionManager.get(tc.testerId)`。
- 場景一：偵測到異常後，用 `ActionManager.set_message(tc.testerId, "…")` 把訊息回傳給測試程式（機台名稱從每個 event 的 `tc.testerId` 取得）。

**目前的落差**：本 spec 的偵測器只涵蓋場景一的一部分（見 4.1）；**場景二完全還沒做**（見第 12 節）；佔 25% 的「異常報告」目前只有 `message` 一行字。

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

> 補充：題目的異常分類比教材第 29 頁更完整——多了 **Low yield**，且平均值與標準差的趨勢都分「上升 / 下降」（第 0 節）。

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

- **這份 CSV 就是題目的 W1**：CSV 的 `wafer` 列為 1、`lot` 為 A12345；W1 的標籤是 Site unbalance，與我們發現的「site 4 突發」吻合（推定，待確認）。sensor1～6 的值約 27.6～35.0，每個 sensor 的標準差僅約 0.09～0.16（場景二的預測難度基準，見第 12 節）。

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

### 4.1 與題目分類的對照與缺口

| 題目標籤 | 對應偵測 | 現況 |
|---|---|---|
| Site unbalance | `site_imbalance` | 有（W1 的 site 4 突發也被 `outlier` / `mean_shift` 抓到） |
| Mean Trend Up / Down | `mean_drift`、`mean_shift` | 有偵測，但**沒有回報方向**（`Alert` 沒有上升/下降欄位） |
| Stdev Trend Up | `variance_change` | 有 |
| **Stdev Trend Down** | — | **缺**：變異的 EWMA 只偵測增加，不偵測減少 |
| **Low yield（< 80）** | — | **缺**：完全沒有良率偵測 |
| 整片 wafer 屬於哪一類的報告 | — | **缺**：目前只有逐 touchdown 的判定，沒有 wafer 層級的分類與彙總 |

**需要補的項目**（會改到契約，需通知 A、B、D、E）
1. `Alert` 增加 `direction`（`"up"` / `"down"`）；CUSUM 有正負兩側，可直接取得方向；變異偵測改成雙邊。
2. 良率偵測：用 `consumeTestEnd` 的 `query_PartFlag` / `query_SBinResult` / `query_HBinResult` 累積良率，與 80% 比較；早期樣本少，需用二項分佈的信賴界避免誤報；`consumeWaferEnd` 的 `get_GoodCount` / `get_TestedCount` 可做 wafer 結束時的最終確認。
3. wafer 層級彙總：`{"wafer": ..., "label": "Site unbalance|Low yield|Mean Trend Up|...|Normal", "onset_td": ..., "evidence": [...]}`，供報告與儀表板使用。
4. 原本「同 pin 群組 ≥3 個測項」的判定規則要重新檢討：題目要的是「wafer 是哪一類」，不是「這個 touchdown 有沒有異常」。

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

## 6. 驗證計畫（合成注入 + 有標籤的 25 片 wafer）

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

### 6.4 用有標籤的 25 片 wafer 驗證（資料尚未取得）

題目提供了 wafer 層級標籤，所以**可以算真正的準確率**（之前「沒有標籤」的假設已不成立）。
1. 每片 wafer 依序餵 80 顆 device 給偵測器，取得預測的標籤與首次警報的位置。
2. 指標：wafer 層級的混淆矩陣與準確率（含 Normal）、每種異常的偵測率、**18 片 Normal 上的誤報率**、首次警報相對於異常起點的延遲。
3. **限制**：每種異常只有 1～2 片（Site unbalance 1 片、Low yield 2 片、其餘各 1 片），樣本極少。不能同時拿它們調參數又拿來報告準確率；建議用合成注入設計與調參，用這 25 片做留出驗證，或做 leave-one-wafer-out，並在報告誠實標示樣本數。
4. 「正確的時機」如何量化題目沒說明（見 9.1）。

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

### 9.1 題目讀完後的狀態

| 原問題 | 狀態 |
|---|---|
| 1 資料來源 | **已回答**：25 份有標籤的訓練 log + 評估用測試程式。**仍待**：取得資料（不在 repo） |
| 2 驗收數值 | 評分項目已知（第 0 節），但「正確的時機」怎麼量化仍未知 |
| 3 判定規則 | 需重新設計：題目要的是 wafer 分類 + 報告（4.1 第 4 點） |
| 4 測項 key | 命名規則 `<測項編號>_<test suite>#<pin>`（第 3 頁範例）；題目中目標測項寫成 `100_Main.sensor1_CP`，`#` 與 `_` 不一致，仍需用真實事件確認 |
| 7 不做 IsolationForest | 環境限制不變；訓練在本機做，執行期只評估 |

**仍待向主辦方確認**：① 「正確的時機」的定義；② Low yield 的 80 是百分比嗎；③ 場景二的 `predict` 請求由誰、怎麼送（見 12.4）；④ 訓練資料怎麼取得；⑤ 報告要通知誰、用什麼形式。

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
6. **題目（第 0 節）的範圍比本 spec 大**：缺 Stdev Trend Down、Low yield、wafer 層級報告（4.1），以及整個場景二（第 12 節）。

## 12. 場景二：溫度預測（新增，尚未實作）

### 12.1 要求
測試程式在每個 sensorN 之前送出預測請求，容器要回傳**每個 site** 的預測值；預測結果與資料中真實的 sensor 值比較評分（「用來評估結果的測試程式」）。目標測項共 6 個（見第 0 節）。

### 12.2 資料事實
- W1 的 sensor 值：sensor1 均值 34.10、sd 0.089；sensor2 34.32、0.129；sensor3 27.85、0.131；sensor4 34.16、0.134；sensor5 31.37、0.158；sensor6 34.87、0.098。
- **只用均值預測，誤差就約等於 sd（約 0.1）**：模型的價值在於比這個基準好多少，評估時應報告相對於「用訓練均值預測」的改善幅度。
- 訓練資料：25 片 × 80 顆 = 2000 個樣本，特徵數約 3000，遠多於樣本數，需要正則化或特徵篩選。

### 12.3 不可洩漏規則與可用特徵
CSV 的列順序即執行順序（已核對）。預測 sensorN 只能用它**之前**執行的測項：

| 目標 | 可用 | 不可用 |
|---|---|---|
| sensor1 | Suite1–14、IDDQ_flow | subflow1 及之後 |
| sensorN（N ≥ 2） | 上列 + sensor1..N−1 + subflow1..N−1 | subflowN 及之後、sensorN 本身 |

訓練時做特徵篩選、標準化等，也只能用訓練 wafer，且用「依 wafer 分組的交叉驗證」，避免同一片 wafer 同時出現在訓練與驗證。

### 12.4 執行期協定（待確認）
- 請求形式（依題目第 5 頁範例）：`{"key": "predict", "data": "<測項編號>"}`；回應：對每個 site 算預測值，組成 `prediction <編號>: (site,value) ...`，`ActionManager.set_wait(tc.testerId, wait, message)`，再回傳 `ActionManager.get(tc.testerId)`。
- **repo 內找不到送出 `predict` 的地方**：`AdaptiveTest.java` 只送 `{"action":"list"}`，`sample.py` 也沒有 `predict` 分支。要向主辦方取得評估用測試程式，或用 `libACS.jar`（`FetchAction` 可帶自訂命令）確認。
- 需要知道有哪些 site：可由 `consumeLotStart` 的 `get_TotalHeadSiteList()` 取得。
- **時序風險**：預測請求走 TPService（ZMQ），量測資料走 Kafka，是不同通道。請求到達時，該 touchdown 前面測項的資料是否已被 `consumeData` 收到，**必須用真實環境驗證**。

### 12.5 評估
預測值 vs 資料中真實的 sensor 值：RMSE、MAE，並報告相對於均值基準的改善（skill = 1 − RMSE²/var）。

### 12.6 建議做法（草案）
1. 每個 sensor 各自一個模型；先用正則化線性模型（Ridge / PLS）+ 特徵篩選，`numpy` 就能訓練，本機做，不進 image。
2. 匯出標準化參數與權重成 JSON；執行期純 Python 做點積（約 3000 個乘加 × 4 個 site，成本很低）。
3. 依 wafer 分組交叉驗證，逐 sensor 報告 RMSE 與相對均值基準的改善；若 site 效應明顯，把 site 當特徵。
4. 進階（選配）：梯度提升樹；需權衡執行期只能用純 Python / `numpy` 評估。

### 12.7 待辦與風險
訓練資料取得、`predict` 請求的送法、時序驗證、預測請求的處理時間預算（每個 touchdown 有 6 次請求）、與場景一共用 `consumeTPRequest` 時的分派邏輯。

---

## 修改與新增檔案
- 新增：`ai_notes/20260918_sonnet5_phase1_spec.md`（本檔案）

## 技術細節與邏輯
- 依據：`ai_notes/Question_20260919.pdf`（官方題目）、`doc/WorkShop_Material.pdf` 第 28–29 頁、`doc/ONEAPI_Manual.pdf`（callback 阻塞規則）、離線 CSV 的實測統計、以及對 Edge dev pod 與 Host Controller 的唯讀環境檢查。
- 第 2.3 節的統計以本機 numpy 計算：site 間差異採 ANOVA 型統計量、漂移為線性回歸斜率 × 80 / σ、位移為前後各 40 顆的平均差 z 值。

## 待執行事項與注意事項
- 本文件僅為 spec，**尚未實作**；等你確認第 9 節後才會開始。
- 我推定 `site = DUT 序號 % 4`，尚未用真實事件驗證。
- 目前工作目錄仍在 `mchien728_sonnet5` 分支，未 commit。
