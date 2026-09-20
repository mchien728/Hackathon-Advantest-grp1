# 後端實作細節（依檔案分類）

範圍：Edge 容器裡的 Python 後端（`Edge/oneAPI_py3.10/bin/`）。三個檔案由上往下串接：

```
機台事件 ──► sample.py ──► scenario1.py ──► detector.py
                 │                            （偵測與分類）
                 └──► scenario2.py / predictor.py（場景二，預測 sensor 溫度）
```

---

## 1. sample.py

> **角色：機台事件的入口，把 OneAPI 事件翻譯成對場景一、場景二的呼叫，並處理機台的 predict 請求與回傳訊息。**

檔案：[sample.py](../Edge/oneAPI_py3.10/bin/sample.py)（`SampleMonitor`，繼承 OneAPI 的 `Monitor`）

| 部分 | 做什麼 |
|---|---|
| 事件分派 `consumeData` | 依事件類型呼叫 `consumeLotStart`、`consumeTestStart`、`consumeMultiParametric`、`consumeTestEnd` 等；每次結束時取出場景一想通知機台的訊息，用 `ActionManager.set_message` 送出 |
| 量測事件 `consumeMultiParametric` | 一次事件含多個 site 的結果。**以腳位名稱組測項鍵值**（`suite#腳位`，`query_PinResults` + `query_PinName`），一個結果有多個腳位就拆成多筆；腳位名稱以（suite、測項編號、結果數）快取；查不到或數量不符時退回 `suite#TestText` 與第一個結果。每筆量測同時餵給場景一與場景二 |
| touchdown 邊界 | `consumeTestStart` 記錄本次啟用的 site 並呼叫 `scenario1.test_start`、`scenario2.test_start`；`consumeTestEnd` 送出每顆 die 的 bin 與座標（`sbin == 1` 視為通過） |
| lot / wafer | `consumeLotStart/End`、`consumeWaferStart/End` 轉給場景一；機台實際不會送 WaferStart，由場景一自動換片 |
| predict 請求 `consumeTPRequest` | `key == "predict"` 時呼叫 `Scenario2.predict` 取得各 site 的預測值，組成 `prediction K: (site,value) ...`，用 `ActionManager.set_wait(tester, wait, 訊息)` 再 `ActionManager.get` 取回動作字串當回覆；`wait` 預設 10，可用環境變數 `ACS_PREDICT_WAIT` 調整。另處理 `list`、`health`、`reset_td`，不認得的回 `unsupported` |
| 狀態輸出 | `get_state()` 合併場景一的狀態與場景二的 `predictions`；`get_wafer(id)` 轉給場景一 |
| 其他 | 逐事件的除錯輸出（每個 TD 約 12,000 行）預設關閉，設 `ACS_DEBUG_EVENTS=1` 才印；所有場景呼叫都包 `try/except`，出錯不會影響機台的事件處理 |

---

## 2. scenario1.py

> **角色：事件與偵測器之間的銜接層，管理 lot / wafer / touchdown 的生命週期，保存前端要顯示的狀態，並決定何時通知機台。**

檔案：[scenario1.py](../Edge/oneAPI_py3.10/bin/scenario1.py)（`Scenario1`，純 Python，不依賴 oneapi，可在本機測試）

| 部分 | 做什麼 |
|---|---|
| 生命週期 | `lot_start` → `wafer_start` → `test_start` → `measurement`（每筆量測）→ `test_end` → `wafer_end` / `lot_end` |
| 自動換片 | 機台不送 WaferStart，所以用「die 座標重複」判斷換片；`TestStart` 的座標是無效值 `-32768`，只在 `TestEnd`（座標有效時）判斷；wafer 自動命名 `auto-1`、`auto-2`…，LotEnd 時結算 |
| 每個 TD 結束 | 呼叫 `Detector.end_touchdown` 與 `end_wafer`，取得即時判斷與 wafer 標籤；記錄該 TD 的每顆 die（site、座標、bin、是否通過、爆量測項數、所在 subflow） |
| 通知機台 | 只有在 wafer 標籤不是 Normal、與上次送出的不同、且**連續 3 個 touchdown 都一樣**（`label_stable_td=3`）時，才產生 `TD<n>: wafer looks like <標籤>`；wafer 結束時若最終標籤還沒送過，補送一次。用 `pop_message()` 交給 `sample.py` |
| 前端狀態 `get_state()` | 目前 wafer 的標籤、信心度、8 項指標、die 地圖、最近 50 個 TD 的標籤歷史、最近 10 片摘要，以及 `wafers`（每片的標籤清單、條件進度、各 site 彙整）；回傳的是複本，整份約 7～22 KB |
| 展開明細 `get_wafer(id)` | 一片 wafer 的完整資料：每個 TD、每顆 die、TD × Site 熱度圖、成立的測項清單（含觸發的指標）；保留最近 10 片，`id` 形如 `001_auto-1` |
| 執行緒安全 | 用鎖保護共用狀態，供前端執行緒同時讀取；本機壓力測試（256 次輪詢）沒有例外 |

---

## 3. detector.py

> **角色：偵測核心，把每筆量測轉成「偏離基準線幾個標準差」，用多種統計指標找出異常，再依「有多少測項一起異常」把整片 wafer 分類。**

檔案：[detector.py](../Edge/oneAPI_py3.10/bin/detector.py)（`Detector`，純 Python，只用標準函式庫）

### 3.1 前置：換成 z 值
- 每個測項有自己的基準線（平均、標準差，來自 Normal 訓練 wafer，存在 `model/baseline.json`）；沒有基準線的測項用前 40 筆以穩健統計估計。
- 前 2 個 touchdown 估計整片 wafer 的共同偏移與雜訊規模並補償（限制在 0.6～1.6 倍）。
- 基準線不符時（前 4 筆中至少 3 筆同方向超出 ±6σ）改用暖機估計。

### 3.2 測項層級的指標
| 指標 | 計算 | 警報 |
|---|---|---|
| outlier | 單筆 \|z\| | ≥ 6 |
| mean_shift（CUSUM） | z 截在 ±4，累加 (z − 0.5)，上下兩側 | 累積 ≥ 12.3 |
| mean_drift | 每個 TD 取各 site 平均，最近 30 個 TD 做回歸斜率 | 顯著度 ≥ 4.7 |
| variance_change | 同一 site 相鄰兩筆 z 的差平方，指數加權（λ=0.05） | 超過管制線（警報 L=9、分類 L=6） |
| site_imbalance | 每 site 最近 20 筆平均，與其他 site 平均相比 | 警報 ≥ 4.6、分類 ≥ 3.7，連續 3 個 TD |

用相鄰差值算變異數，所以整體位準移動不會被誤判成變異數變大；離群值會被截斷，單顆 die 讀到極端值不會讓變異數指標誤觸發。

### 3.3 三個層級的判斷
| 層級 | 條件 |
|---|---|
| Touchdown 即時判斷（`_verdict`） | 同一個 pin 有 ≥ 3 個測項同時警報，或任一警報分數 ≥ 3 倍門檻。只用於顯示，不通知機台 |
| Die（`die_flags`、`die_detail`） | 同一個 TD、同一個 site，在同一 subflow 內有 ≥ 3 個測項 outlier，標為可疑 die |
| Wafer 分類（`_labels`、`_classify`） | 各條件**獨立判斷**，計數是「同一 subflow 內的最大值」：Site unbalance ≥ 20、Mean Trend Up/Down ≥ 30（up 與 down 各自計數）、Stdev Trend Up ≥ 20、Low yield（累積良率 < 0.8 且 ≥ 20 顆 die）。`labels` 列出所有成立的；`label` 取第一個（優先順序：Site → Mean → Stdev → Low yield）|

### 3.4 其他介面
`update`（逐筆量測）、`end_touchdown`、`update_device`（良率，bin 3 不計）、`end_wafer`、`metrics`（8 項判斷準則的快照）、`evidence`（成立的測項與觸發的指標）、`reset`、`load`（載入失敗不丟例外）。

### 3.5 驗證結果
- 25 片訓練 wafer 留一片驗證：**24/25** 正確（W25 Stdev Trend Down 沒有對應類別，判成 Normal）。
- 分類的分隔度：異常片的計數比 Normal 片最大值高一個數量級（Site 98 vs 3、Mean 110 vs 5、Stdev 93 vs 4）。
- 機台實測：每個 TD 的 callback 約 1.7～2.6 秒（測試程式每個 TD 約 12 秒）；機台上的標籤時間軸與離線重播同一份資料的結果逐個 TD 一致。

---

## 已知限制
- 沒有 Stdev Trend Down 類別；良率是整片累積值，早期樣本少會暫時波動。
- 場景一的訊息目前**沒有實際出現在機台端**：測試程式裡取回並顯示動作的步驟被註解掉了，而且 `set_message` 使用的機台名稱（資料事件）可能和預測請求的機台名稱（`group-1`）不同，尚未驗證。
- 門檻依 25 片訓練 wafer 調整，沒有獨立測試片。

## 其他相關檔案（未展開）
- [scenario2.py](../Edge/oneAPI_py3.10/bin/scenario2.py)：場景二的銜接層，保存每個 site 的量測、處理 predict 請求、記錄預測與實測誤差。
- [predictor.py](../Edge/oneAPI_py3.10/bin/predictor.py)：只用 numpy 的六個 sensor 預測模型推論，缺任何一個特徵就拒絕預測。
