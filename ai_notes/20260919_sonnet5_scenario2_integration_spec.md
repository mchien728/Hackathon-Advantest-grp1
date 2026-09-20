# 情境二整合 Spec：6 個溫度 sensor 預測模型 × 情境一應用

> 日期：2026-09-19。狀態：**S2-1～S2-6 已實作並通過本機測試（見第 14 節）**；機台測試（L5）與 Docker 部署（L6）尚未做。
> 依據：隊友的 `scenario2_final_models_claude_code_guide.md` 與 `manifest.json`；官方題目 PDF（第 3～5 頁）；機台實測（`ai_notes/20260919_sonnet5_scenario1_progress.md` 第七輪）；VM 上較新的 `Main.flow`、`Predict.java`（取自 `Smartest.zip`）。
> 每一項都標明「已確認」或「假設」，避免把猜測當事實。

---

## 1. 目標與範圍

**目標**：測試程式在每個 sensor 測項**之前**發出預測請求（編號 1～6），Edge 容器只用「已經發生的測項」預測該 sensor 的值（每個 site 一個值），在時限內回傳給測試程式；同時不影響情境一的異常偵測與前端顯示。

**範圍內**：驗證模型、載入與推論、per-site 資料暫存、請求回應、`get_state()` 的預測欄位、本機與機台測試、打包。
**範圍外**：重新訓練模型（除非驗證失敗）、前端畫面的視覺設計（任務 D）。

## 2. 已確認的事實

| # | 事實 | 來源 |
|---|---|---|
| F1 | 6 個目標編號 1～6 對應 `100_Main.sensor1#CP`、`120_Main.sensor2#DS0`、`140_Main.sensor3#IO4`、`160_Main.sensor4#IO1`、`180_Main.sensor5#IO2`、`200_Main.sensor6#IO3` | 題目 PDF 第 5 頁、`manifest.json` |
| F2 | 測試程式把編號發給容器，容器預測後回傳；訓練時不得使用尚未執行的測項 | 題目 PDF 第 4、5 頁 |
| F3 | 機台上的流程順序：`Suite1–14 → IDDQ_flow → predict1 → sensor1 → subflow1 → predict2 → sensor2 → subflow2 → … → predict6 → sensor6`，與訓練 CSV 的欄位順序一致（sensor1 在第 40 欄，前面剛好是 29 個測項；sensor2 在 541 欄，中間夾 sensor1 與 500 個 subflow1 測項） | VM 上 `Main.flow`（`Smartest.zip`）、隊友文件第 1 節 |
| F4 | 測試程式的 `receive_temp_predictK` 是 `ACSTML.Predict`，送出 `{"key":"predict","data":K}`；等待回覆的逾時是 `timeout`（預設 **1 秒**）；回覆裡的 `wait` 動作若有 `reason`，會以 `DIEINFO:<site>_<x>_<y>;… <reason>` 送到 MessUI 訊息視窗 | `Predict.java` |
| F5 | `sample.py` 已有 `predict` 分支（隊友寫的佔位版）：`ActionManager.set_wait(tc.testerId, 10, "prediction K: (site,value) …")`，再 `ActionManager.get(tc.testerId)`；目前 value 固定 25.22 | `sample.py` 第 138 行起 |
| F6 | 執行期量測事件的測項名稱 = `query_TestSuite + "#" + query_TestText`，去掉訓練欄名的 `NNN_` 前綴後一致；量測值 `query_Results(i)[0]` 是 float；一則事件含所有 active site | 機台實測、`py-app.log` |
| F7 | 量測事件走 Kafka，`predict` 請求走 ZMQ（TPService），**是兩條不同的通道** | OneAPI 手冊、`sample.py` 的 `consumeData` 與 `consumeTPRequest` |
| F8 | Edge 開發 pod 只有 `numpy`、`flask`（無 `scikit-learn`、`pandas`、`joblib`），不能連外網；`bin/requirements.txt` 只有 `pytz`，且 `py-app.dockerfile`/`Dockerfile` 沒有 `pip install` | 環境調查、`Dockerfile` |
| F9 | 機台上一個 touchdown 的事件處理約 3～5 秒（含 3036 個測項），測試程式每個 touchdown 約 12 秒 | 機台實測 |

## 3. 最大風險（依嚴重度）

| 風險 | 說明 | 對策 |
|---|---|---|
| **R1：容器裡沒有 scikit-learn** | 模型是 sklearn 的 `joblib`（Ridge、HistGradientBoosting），F8 顯示執行環境沒有 sklearn，也不能上網安裝。直接 `joblib.load` 會失敗 | **預設把模型轉成純 numpy 格式**（見第 5 節），執行期只需要 numpy。若之後確認 image 裡有相同版本的 sklearn，再開 `joblib` 後端當備援 |
| **R2：Kafka 與 ZMQ 賽跑** | `predict` 請求可能比它需要的最後幾筆量測事件先到（F7），特別是 F9 顯示事件處理有延遲 | 預測前檢查所需特徵是否到齊；未到齊時在**不超過約 0.5 秒**內輪詢等待，仍不齊則回覆「未就緒」，不填 0、不編造數值 |
| **R3：回覆時限 1 秒** | F4 的 `timeout=1`。預測本身很快（Ridge 是一次向量內積，HGB 約毫秒級），但等特徵的時間要納入 | 等待上限 0.5 秒；記錄每次的耗時（`latency_ms`） |
| **R4：sensor5 是最難的目標** | 最終模型 R²=0.885（其他 ≥ 0.99）；HistGradientBoosting 要用純 numpy 重現樹的推論，實作量最大 | 先做 Ridge 五個；sensor5 的匯出獨立驗證，過不了就退回 Ridge/ExtraTrees 並註明精度損失（基線 Ridge 的 MAE 約 0.0596，HGB 為 0.0547） |
| **R5：模型內含的前處理未知** | 隊友說「有些模型是 pipeline」，但 `.joblib` 還沒看到，不知道有沒有 `StandardScaler` 等 | 匯出工具必須逐一處理 pipeline 內每個步驟，且用「與 sklearn 的 `predict` 逐筆比對」驗證（第 8 節） |
| **R6：版本不一致** | 訓練用 sklearn 1.6.1、numpy 2.2.3；pod 的 numpy 是 2.2.6 | 純 numpy 後端可避開 sklearn 版本問題；若用 joblib 後端，載入時遇到版本警告一律視為錯誤回報 |

## 4. 架構

沿用情境一的分層：**不依賴機台的邏輯獨立成檔，`sample.py` 只做翻譯**。

```
機台 ──Kafka 事件──► sample.py.consumeMultiParametric ─┬─► scenario1.measurement()   （情境一，已完成）
                                                       └─► scenario2.observe()      （新增，同一筆量測兩邊都吃）
機台 ──ZMQ 請求────► sample.py.consumeTPRequest("predict") ──► scenario2.predict(k, sites) ──► set_wait + get
                                                                            │
                                     scenario1.get_state() ◄── scenario2 的預測紀錄（predictions）
```

```
bin/
├─ detector.py, scenario1.py            # 情境一（不動）
├─ scenario2.py                         # 新增：glue（per-site 暫存、請求處理、預測紀錄）
├─ predictor.py                         # 新增：純 numpy 推論，不 import oneapi
├─ model/
│  ├─ baseline.json                     # 情境一
│  └─ sensors/                          # 新增：匯出後的模型
│     ├─ manifest.json
│     └─ sensor1.npz … sensor6.npz  (或 .json)
tools/
├─ validate_sensor_models.py            # 新增：對 .joblib 做驗證（隊友文件第 11～20 節）
└─ export_sensor_models.py              # 新增：joblib → numpy 格式，並與 sklearn 逐筆比對
```

> 隊友文件建議放在 `scenario1/`、`scenario2/` 子資料夾。本 spec 採用**扁平檔案**以與目前的 `detector.py`、`scenario1.py` 一致並避免改動 import 路徑；若團隊偏好子資料夾，只需搬移檔案並調整 import，介面不變。

## 5. 模型匯出格式（純 numpy）

**目的**：執行期只用 `numpy`，不需要 sklearn / joblib / pandas。

| 模型 | 匯出內容 | 推論 |
|---|---|---|
| Ridge（sensor 1、2、3、4、6） | `features`（欄名清單）、`coef`、`intercept`；若有 `StandardScaler` 則加 `mean`、`scale` | `y = ((x - mean) / scale) @ coef + intercept` |
| HistGradientBoosting（sensor 5） | `features`、`baseline`（初始預測）、每棵樹的節點陣列（特徵索引、門檻、左右子節點、葉值、缺值走向）、`learning_rate` 已內含於葉值時要注意 | 逐棵樹走訪並加總，最後加 `baseline` |

**匯出工具必須做到**：
1. 逐一處理 pipeline 內每一步；遇到不認得的步驟就中止並報錯，不猜。
2. 對訓練資料的多筆 die，比較「匯出後的推論」與「sklearn 的 `predict`」，**最大絕對差 ≤ 1e-9**（Ridge）／**≤ 1e-6**（HGB）才算通過。
3. 在 manifest 記錄：來源檔的 sha256、sklearn/numpy 版本、特徵數、通過的比對筆數。

## 6. 模組介面

```python
# predictor.py（純 numpy；本機可測）
class SensorPredictor:
    @classmethod
    def load(cls, dir=None) -> "SensorPredictor"      # 預設 bin/model/sensors；失敗不丟例外，load_error 有訊息
    info() -> {"sensors": {1: {"target": str, "model": str, "n_features": int}, ...}, "load_error": str|None}
    required(sensor: int) -> list[str]                # 該 sensor 的特徵名（已去掉 NNN_ 前綴，依儲存順序）
    predict(sensor: int, x: np.ndarray) -> float      # x 依 required() 的順序，長度必須相符

# scenario2.py（glue）
class Scenario2:
    def __init__(self, predictor=None, wait_ms=500)
    def test_start(self)                              # 新 touchdown：清空所有 site 的暫存
    def observe(self, suite, text, site, value)       # O(1)，在事件執行緒
    def predict(self, sensor: int, sites: list[int]) -> dict
        # → {"sensor": k, "target": str, "values": {site: float|None}, "ready": bool, "missing": {site: n},
        #    "latency_ms": float, "message": str}
    def actual(self, suite, text, site, value)        # 收到 sensor 實測值時補上 actual / error
    def predictions(self) -> list                     # 最近 30 筆，給 get_state()
```

**per-site 暫存**：一個 `numpy` 陣列 `store[site_index, key_index]`，初始全 `nan`；`key_index` 由所有模型特徵的聯集在載入時決定。`observe` 只是一次索引賦值，`predict` 取 `store[site, idx_k]`，`nan` 的位置即為缺少的特徵。**每個 touchdown 的 `test_start` 清空**，以免用到上一個 touchdown 的資料。site 以 `(head, site)` 為鍵（目前只有 head 1，但仍保留）。

## 7. 執行流程

**量測（事件執行緒）**：`consumeMultiParametric` 對每筆結果呼叫 `scenario1.measurement(...)` 與 `scenario2.observe(...)`；若這筆是某個 sensor 的實測值（`Main.sensorK#…`），另外呼叫 `scenario2.actual(...)`。

**請求（TPService 執行緒）**：
1. `consumeTPRequest` 收到 `{"key":"predict","data":K}`；`K` 可能是整數或字串，先轉成整數並確認在 1～6，否則回 `unsupported` 並記錄。
2. 取 `self.sites`（`TestStart` 記下的 active sites）。
3. 對每個 site 檢查 `required(K)` 是否都非 `nan`；缺的就在 `wait_ms` 內每 20 ms 重試。
4. 到齊的 site 呼叫 `predict`；沒到齊的 site 值為 `None`。
5. 組訊息，格式沿用隊友的佔位版：`prediction K: (1,34.972) (2,34.981) …`；未就緒的 site 寫 `(3,not_ready:37)`（缺 37 個特徵），**不填 0、不使用未來的測項**。
6. `ActionManager.set_wait(tc.testerId, wait, message)`，再 `ActionManager.get(tc.testerId)` 並回傳（與現有 `predict` 分支相同）。
7. 整段包 `try/except`：任何例外都回傳含錯誤說明的訊息，**不讓請求執行緒崩潰**，也不讓測試程式卡住。

**時限**：請求處理整體目標 < 0.8 秒（Predict.java 逾時 1 秒）。

## 8. `get_state()` 的預測欄位

情境一目前的 state 沒有 `predictions`。新增（接在既有欄位後面，不改動舊欄位）：

```jsonc
"predictions": [                          // 最近 30 筆，舊到新
  {"td": 5, "sensor": 4, "target": "160_Main.sensor4#IO1",
   "values": {"1": 34.97, "2": 34.98, "3": 35.02, "4": 34.95},
   "actual": {"1": 34.972, ...} | null,   // sensor 實測值到達後補上
   "error":  {"1": 0.002, ...} | null,
   "ready": true, "missing": 0, "latency_ms": 3.4}
],
"predictor_error": null                   // 模型載入失敗時的訊息
```

`td` 從 1 起算，與其他欄位一致。

**選配（創新加分）**：預測值與實測值的殘差可以當成情境一的額外異常訊號（例如某片 wafer 的 sensor 誤差突然變大）。這是設計想法，需先驗證再決定是否加入。

## 9. 測試計畫

| 層級 | 測試 | 需要機台 |
|---|---|---|
| L0 模型驗證 | 隊友文件第 11～20 節：檔案、鍵、manifest、特徵數、無重複、特徵都在 CSV 標頭且都在目標之前、多顆 die 的預測、NaN 輸入 | 否 |
| L1 匯出等價 | `export_sensor_models.py` 的比對（第 5 節） | 否 |
| L2 單元測試 | `predictor.py`：載入失敗不崩、特徵順序、缺特徵回報；`scenario2.py`：`test_start` 清空、per-site 不互相污染、未就緒不編造數值、K 非法值的處理、逾時上限 | 否 |
| L3 重播 | 用真實訓練 wafer，依 F3 的流程順序餵事件（在 `predict K` 的時間點才呼叫 `predict`），確認：所需特徵在那個時間點全部到齊；預測值與離線 `predict` 一致 | 否 |
| L4 賽跑測試 | 模擬「請求比最後幾筆量測早到」：確認會等待、逾時後回「未就緒」而不是用 0 | 否 |
| L5 機台探針 | 擴充 `machine_probe.py`：記錄 sensor 事件的真實 `TestSuite`/`TestText`（確認能組出 `Main.sensorK#…`）；量測 `predict` 請求相對於最後一筆量測事件的到達時間差 | 是 |
| L6 端到端 | 部署映像檔後，用 `eng_run` 跑完整流程，看 MessUI 收到的訊息與 `get_state()` | 是（且需 Docker 部署） |

**注意**：模型是用全部 25 片訓練的，所以拿訓練 wafer 重播得到的誤差是**樣本內**的，會比真實低。L3 檢驗的是「執行期路徑與離線預測一致、時序正確」，**不是準確率**；真正的泛化誤差請看隊友的 GroupKFold 結果（例如 sensor4 MAE 0.0062、sensor5 MAE 0.0547）。

## 10. 驗收標準

- [ ] 6 個 `.joblib` 通過 L0，且 6 個匯出模型通過 L1 的等價比對
- [ ] 容器內只用 `numpy` 即可載入並推論（不 import sklearn/joblib/pandas）
- [ ] L3 重播：6 個 sensor 在各自的請求時間點，所需特徵 100% 已到齊
- [ ] L4：特徵未到齊時不回傳任何編造的數值
- [ ] 單次預測請求處理 < 0.8 秒（機台上量測）
- [ ] 4 個 site 的預測互不混淆
- [ ] `get_state()` 含 `predictions`，且整份 state 仍 < 100 KB
- [ ] 情境一的既有測試全數通過，沒有回歸
- [ ] 機台上 MessUI 收到訊息，格式與時限符合

## 11. 待確認事項

| # | 問題 | 對誰 |
|---|---|---|
| Q1 | **評分讀哪裡的預測值？** MessUI 訊息文字、程式變數，還是 datalog？目前假設是訊息文字（`set_wait` 的 reason） | 主辦方 |
| Q2 | 訊息格式有規定嗎？（是否要寫完整目標名稱、小數位數） | 主辦方 |
| Q3 | 4 個 site 是否都要預測，還是只預測 active sites？ | 主辦方 |
| Q4 | `.joblib` 裡有沒有 `StandardScaler` 之類的前處理？sensor5 的 HGB 參數（樹數、深度）是多少？ | 隊友（模型作者） |
| Q5 | Docker 的基底映像檔有沒有 sklearn？能不能在 build 時 `pip install`？（決定 R1 要不要退回 joblib 後端） | 有 sudo 的人 |
| Q6 | 隱藏資料的 sensor 是否也在同樣的流程位置？ | 主辦方 |

## 12. 實作順序

| 步驟 | 內容 | 依賴 |
|---|---|---|
| S2-1 | 拿到 `.joblib`，跑 L0 驗證並回報 PASS/FAIL | 檔案 |
| S2-2 | `export_sensor_models.py`（先 Ridge，最後 HGB），跑 L1 | S2-1 |
| S2-3 | `predictor.py` + 單元測試 | S2-2 |
| S2-4 | `scenario2.py` + L2、L3、L4 測試 | S2-3 |
| S2-5 | `sample.py` 接線（`observe`、`predict` 分支、`actual`），保留隊友的分支結構 | S2-4 |
| S2-6 | `get_state()` 加 `predictions`，更新任務書的介面契約 | S2-4 |
| S2-7 | 機台 L5 | S2-5，且**機台沒人在用** |
| S2-8 | Docker 打包與 L6 | S2-7、sudo 權限 |

**在檔案還沒上傳的現在就能先做**：S2-3 到 S2-6 可以先用**假模型**（隨機係數的 Ridge）把整條路徑做完並測完，等真的檔案到了再替換，這樣不會白等。

## 13. 提醒

- 沒有 review 前不要 merge；`.joblib` 與訓練資料不要 commit（`.gitignore` 已排除 `training/`，`.joblib` 需另外加）。
- 不要修改模型；驗證失敗要先說明原因（隊友文件第 11 節的要求）。
- 機台使用要與隊友協調，避免同時 `load`／`eng_run`。

---

## 14. 實作結果（2026-09-19 更新）

### 14.1 模型驗證（S2-1，`tools/validate_sensor_models.py`）
在與訓練相同版本的環境（scikit-learn 1.6.1、joblib 1.4.2、numpy 2.2.3、pandas 2.2.3）驗證 `bin/final_models/`：**79/79 項通過**（資料夾 1 項、每個 sensor 13 項）——7 個檔案齊全、載入無版本警告、鍵與 manifest 一致、特徵數 29/400/20/600/400/800、無重複、全部特徵都在 CSV 標頭且**都排在目標之前**、5 個 die 的預測有限且無 NaN 輸入。
內部結構：sensor 1、3 是「中位數補值 → 標準化 → Ridge(α=10)」，sensor 2、4、6 是「標準化 → Ridge(α=10)」，sensor 5 是「中位數補值 → HistGradientBoosting」（250 棵樹、共 15,250 個節點、無類別特徵）。

**兩個要注意的地方**
1. **補值步驟會悄悄補上缺值**：sklearn 管線裡的 `SimpleImputer` 遇到缺特徵會用訓練中位數補，不會報錯。所以執行期必須**自己**先檢查缺值（`scenario2.py` 已做），不能靠模型。
2. **煙霧測試是樣本內的，會過度樂觀**：對全部 2000 顆訓練 die 的樣本內 MAE 是 0.0029～0.018（sensor 5 為 0.0061），而交叉驗證 MAE 是 0.0035～0.0207（sensor 5 為 **0.0547**）。sensor 5 的樣本內誤差只有交叉驗證的九分之一，表示它明顯過擬合訓練 wafer；對沒看過的 wafer，預期誤差約 0.055，是六個裡最差的，其餘五個約等於各自的交叉驗證值。

### 14.2 轉成純 numpy（S2-2，`tools/export_sensor_models.py`）
6 個模型轉成 `bin/model/sensors/`（共約 370 KB）：Ridge 把標準化折進係數（`w = coef/scale`、`b = intercept − mean·w`）；HGB 匯出全部樹的節點陣列。**與 sklearn 逐筆比對（`tools/check_sensor_export.py`，2000 顆 die × 6 個 sensor）最大差距約 1e-14**（容許 Ridge 1e-9、HGB 1e-6）。執行期只需 `numpy`，**不需要 sklearn/joblib/pandas**（R1 已解決）。速度：Ridge 每次約 0.01～0.02 ms，sensor 5 約 0.7 ms。

### 14.3 程式
| 檔案 | 內容 |
|---|---|
| `bin/predictor.py` | 純 numpy 推論；載入失敗不丟例外；缺值或 NaN 一律拒絕，不補值 |
| `bin/scenario2.py` | 每個 site 一列的 `numpy` 暫存（`test_start` 清空）、`observe`、`predict`（缺特徵時最多等 500 ms，逾時回 `not_ready:<缺幾個>`）、實測值到達後補 `actual`/`error`、`state()` |
| `bin/sample.py` | `consumeMultiParametric` 同時餵 Scenario1 與 Scenario2；`consumeTestStart` 清空暫存；`predict` 分支改呼叫 Scenario2（取代 25.22 佔位值）；`get_state()` 合併 `predictions`、`predictor_error` |
| `tests/test_sensor_predictor.py`、`tests/test_scenario2.py` | 16 個新測試（含用真實 wafer 依流程順序重播 6 個 sensor、4 個 site 不混淆、缺特徵不編造、晚到的量測會被等到、`predict` 請求經 `sample.py` 的完整路徑、壞輸入不崩） |

**測試結果**：55 個測試，只有既有的 `test_list_request_returns_seeded_message` 失敗。

### 14.4 已用真實機台事件確認的對應
本機的真實事件紀錄（`py-app.log`）中，6 個 sensor 都以 `TestSuite#TestText` 出現，且與模型目標一致：`Main.sensor1#CP`、`Main.sensor2#DS0`、`Main.sensor3#IO4`、`Main.sensor4#IO1`、`Main.sensor5#IO2`、`Main.sensor6#IO3`；紀錄裡 33 種測項有 27 種是模型特徵。

### 14.5 尚未做／需要注意
- **機台測試（L5）**：`predict` 請求相對於最後一筆量測事件的到達時間差（Kafka 與 ZMQ 賽跑），只能在機台上量；目前程式用「最多等 500 ms」防禦。
- **`set_wait` 的等待時間**：`ACS_PREDICT_WAIT` 預設沿用隊友的 10，手冊沒說單位，若是秒，每個 touchdown 6 次預測會多等 60 秒，需在機台上量並調小。
- **Docker**：`bin/` 會整包進映像檔，`bin/final_models/*.joblib`（約 1.9 MB，pickle 格式）執行期用不到，建議移到 `bin/` 之外（例如 `models_src/`）再打包；`bin/model/sensors/` 才是執行期用的。
- **評分讀取方式**（GDR、MessUI 視窗或程式變數）仍待主辦方確認（Q1）。


### 14.6 機台實測發現與鍵值修正（2026-09-20）
**機台實測（`eng_run 20`，datalog `/tmp/STDF/test.edl`）**：`predict` 請求都有收到回覆（20 個 TD × 6 = 120 筆），但只有 sensor3 有預測值；sensor 1、2、4、5、6 每次都回 `not_ready`，缺的特徵數固定為 7、6、3、2、2。

**缺特徵的 7 個測項與原因**
| 類型 | 測項 | 原因 |
|---|---|---|
| 鍵值對應（已修正） | `Suite14#CP`、`Suite14#MR` | 事件的 `TestText` 是 `PinGrp`，且一次帶 2 個結果（腳位 CP、MR）；原程式只取第一個結果，鍵值為 `Suite14#PinGrp` |
| 鍵值對應（已修正） | `Suite3#IO2` | 事件的 `TestText` 是 `IO1`，腳位名稱是 `IO2`；訓練欄位用腳位名稱 |
| 機台上未執行（未解決） | `Suite1_0#DS0`（測項編號 240）、`Suite9_0#DS7`（420）、`Suite9_1#S0`（440）、`Suite9_0_0#S1`（460） | repo、`Smartest.zip`、機台三個版本的 `Main.flow` 都只有定義、沒有 `.execute()`；機台資料紀錄中這 4 個測項編號為 0 行，但訓練資料有 |

**修改**：`bin/sample.py` 的 `consumeMultiParametric` 改成以腳位名稱組鍵值（`query_PinResults` + `query_PinName`，第 k 個結果對應第 k 個腳位），結果數與腳位數不符或查詢失敗時退回 `TestText` 與第一個結果（與舊行為相同）。腳位名稱以（suite、測項編號、結果數）快取。情境一與情境二共用，所以情境一也多監控到這 3 個測項。
**依據**：`py-app.log` 的 30 種事件中，`TestText` 組鍵值對得上訓練欄位 28 種，`PinName` 對得上 30 種；兩者結果不同的只有 `Suite3` 與 `Suite14`。
**測試**：新增 6 個測試（拆 pin group、腳位名稱優先、一般測項不變、退回機制、快取、查詢失敗不影響）；全部測試 73 個，只有既有的 `test_list_request_returns_seeded_message` 失敗。本機微基準：每個 TD 約多 8 ms（Python 端，API 呼叫以假物件代替）。

**尚未驗證**
- 「第 k 個結果對應第 k 個腳位」的順序：機台資料裡 `Suite14` 的 CP、MR 數值太接近，無法區分，需以探針逐 die 對照 datalog。
- 真實 API 呼叫的額外時間（每個 TD 約 12,000 次 `query_TestNumber`），需在機台上看 callback 時間。

**仍會 `not_ready` 的 sensor（類型 B 未解決）**：sensor1 缺 4 個、sensor2 缺 3 個、sensor4／5／6 各缺 `Suite9_1#S0`。補上訓練中位數的試算（樣本內）：這 4 個特徵補值後 MAE 變化 ≤ 0.0002，但尚未做保留集驗證，且與「缺特徵不編造」原則衝突，需決定；另一條路是移除這 4 個特徵重新訓練，或向主辦方確認評分用的流程是否執行它們。
**sensor3 機台誤差**：80 筆（TD×site）MAE 0.083、平均偏差 −0.083（全部偏低），實測標準差 0.247；離線交叉驗證的預期約 0.02 以下。機台重播資料不等於任何一片訓練 wafer，原因（分佈不同或其他）未確認。

---

## 15. 新版 sensor 1、sensor 5 模型的本機評估（2026-09-20）

**備份**：原本的 sensor1、sensor5 已備份到 `Edge/oneAPI_py3.10/model_backup/20260920_original_sensor1_sensor5/`（原 `.joblib`、執行期用的 `.npz`、`runtime_manifest.json`、`SHA256SUMS.txt`，逐位元核對一致）。此資料夾在 `bin/` 之外，不會被打包進映像檔。

**新模型**（放在 `bin/model/sensors/`）：
| 檔案 | 內容 |
|---|---|
| `sensor1_generalized.joblib` | Huber 迴歸（α=0.001），29 個特徵，標準化器另存於檔內（不是管線的一部分）；交叉驗證 MAE 0.00301 |
| `sensor5_delta.joblib` | 預測「sensor5 − sensor4」的差值，Ridge(α=0.01)，200 個特徵；**執行期公式：`sensor5 預測 = 實測的 sensor4 + 模型預測`**；交叉驗證 MAE 0.00258 |

**評估結果（本機，與訓練時相同版本的套件）**
| 項目 | sensor 1：舊 → 新 | sensor 5：舊 → 新 |
|---|---|---|
| bundle 內的交叉驗證 MAE | 0.00348 → 0.00301 | 0.0546 → **0.00258** |
| 訓練 wafer（樣本內）MAE | 0.0032 → 0.0028 | 0.0061 → 0.0023 |
| **B13456 第 2 片 wafer MAE**（訓練批以外的批號） | 0.383 → 0.401（**沒有改善**） | 0.433 → **0.0076（改善 98%）** |
| 時序檢查 | 全部特徵在目標之前 | 全部特徵與參考 sensor4 都在目標之前 |

- sensor 5：差值模型的效果極大，而且符合物理直覺（sensor5 與 sensor4 很接近，只需預測小的差值）。執行期要求 sensor4 的實測值已到達；到不齊時回 `not_ready`。
- sensor 1：對這片 wafer 仍有約 +0.40 的固定偏移，新模型沒有改善；sensor 1 是最先測的 sensor，只有 29 個前面的測項可用，沒有更早的 sensor 可當參考。
- 「B13456 沒有用來調參」是檔案內 `training_policy` 的說法，我無法獨立驗證；B13456 只有一片 wafer，樣本很少。

**支援新格式的程式修改**：`tools/export_sensor_models.py`（Huber 與獨立標準化器、`--override SENSOR=FILE`、記錄 `mode`/`reference`）、`bin/predictor.py`（`reference()`、`predict(sensor, x, ref)`，缺參考值時拒絕預測）、`bin/scenario2.py`（從每個 site 的暫存取出參考值並納入缺值檢查）、`tools/check_sensor_export.py`（改為支援新格式；sklearn 參考實作 `predict_bundle` 放在這個檔案裡）。新舊模型的一次性比較腳本（`compare_sensor_models.py`）已刪除，結果記錄在本節。

**驗證**：轉成 numpy 的 v2 與 sklearn 逐筆比對（2000 顆 die × 6 個 sensor）最大差距約 1e-14；B13456 依真實流程順序經 `Scenario2` 重播，120 次請求全部有回覆；測試共 86 個，只有既有的 1 個失敗。**已切換（2026-09-20）**：使用中的 `bin/model/sensors/` 現在是新版（sensor 1 為 Huber、sensor 5 為差值模型，`manifest.json` 與 `sensor1.npz`、`sensor5.npz` 已重新產生；2、3、4、6 與原本逐位元相同）。過程中曾有一次 `manifest.json` 與新的 `sensor5.npz` 不一致（特徵數 400 對 200），預測器因此拒絕載入並讓所有請求回 `not_ready`，重新轉換後已修復。兩個新的 `.joblib` 另存於 `model_backup/20260920_new_sensor1_sensor5/`，原本的兩個舊模型在 `model_backup/20260920_original_sensor1_sensor5/`；`bin/model/sensors/` 內的兩個 `.joblib` 執行期不會讀，建議移出 `bin/`。測試共 84 個，只有既有的 1 個失敗。

**切換方式**：把 `bin/model/sensors_v2/` 的 `sensor1.npz`、`sensor5.npz`、`manifest.json` 複製到 `bin/model/sensors/`（或把 `predictor.py` 的預設資料夾改成 `sensors_v2`）。

**manifest.json 的用途**：`bin/final_models/manifest.json`（隊友的，825 位元組）只有 `tools/validate_sensor_models.py` 會讀，執行期不用；`bin/model/sensors/manifest.json`（匯出工具產生）是**執行期必讀**：`predictor.py` 靠它知道每個 sensor 的檔名、目標、特徵順序與參考 sensor，缺少它模型就載入失敗（`predictor_error`，所有請求回 `not_ready`）。

**更新（2026-09-20）**：sensor 1 已改回原本的 Ridge（由 `bin/final_models/sensor1.joblib` 重新轉換，與備份的原版 `sensor1.npz` 逐位元相同）；sensor 5 維持新的差值模型。B13456 各 sensor 的 MAE：1=0.3829、2=0.0200、3=0.0832、4=0.0446、5=0.0076、6=0.0548。轉換工具改為「全部模型都成功後才寫檔」，避免中途失敗留下部分更新、`manifest.json` 與 `.npz` 不一致的情況（曾發生一次，預測器因此拒絕載入）。

