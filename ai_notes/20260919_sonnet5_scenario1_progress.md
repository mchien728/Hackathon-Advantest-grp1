# 情境一進度紀錄（即時更新）

> 目標：情境一「即時判斷異常並分類、通知機台、提供前端數值」。本文件每完成一步就更新一次。
> 分支：`mchien728_sonnet5`。**尚未 commit**（由使用者自行 commit）。

## 變更摘要
- 2026-09-19：開始情境一接線（把 `sample.py` 的事件餵給 `Detector`，`get_state()` 補齊契約，異常時通知機台）。

## 修改與新增檔案
| 檔案 | 內容 |
|---|---|
| `Edge/oneAPI_py3.10/bin/scenario1.py`（新） | 事件與偵測器的銜接層：`lot_start / wafer_start / test_start / measurement / test_end / wafer_end / pop_message / get_state`；純 Python，本機可測 |
| `Edge/oneAPI_py3.10/bin/sample.py` | callback 接線（見下）；`get_state()` 改回傳 `Scenario1.get_state()`；`consumeData` 結尾用 `pop_message()` 呼叫 `ActionManager.set_message`；**移除**原本每 3 個 touchdown 送 "Site 1 Abnormal Happen" 的示範程式；`consumeMultiParametric` 的逐欄位 print 改成 `ACS_DEBUG_EVENTS=1` 才印 |
| `Edge/oneAPI_py3.10/bin/detector.py` | 新增 `cls_yield_min_dev=20`：良率判斷至少要 20 顆 die，避免前幾個 touchdown 誤報 Low yield |
| `Edge/oneAPI_py3.10/tests/test_scenario1.py`（新） | 6 個測試：契約欄位、JSON、複本、壞資料不崩、爬升 wafer 報告與訊息只送一次、Normal 不送訊息、真實 wafer（W14、W2）經 Scenario1 |

## 第二輪進度（不需主辦方回覆就能做的事，已完成）
1. **壓力測試 `tools/stress_wafers.py`（新）**：把 W14/W18/W23/W1 的異常形狀按比例（1.0～0.05 倍）注入 6 片 Normal wafer，檢查偵測器在多弱的異常下失效。第一次結果顯示 **Stdev Trend Up 只有完整強度才抓得到、Site unbalance 在 0.5 倍就漏**，是弱點。
2. **找到誤報原因**：Normal wafer 的變異數誤報數與該片 wafer 的整體雜訊大小高度相關（W22 為 1.00、W15 為 0.97、W24 為 0.97 的誤報最多；W4 為 0.85 幾乎沒有）。
3. **修改 `detector.py`**：(a) 新增「wafer 雜訊規模補償」`scale`（與 offset 一起在前 2 個 touchdown 估計，只套用在有 baseline 的測項）；(b) 新增 wafer 分類專用、較鬆的門檻 `ewma_L_cls=6.0`、`site_thr_cls=3.7`（不影響逐 touchdown 的 `anomaly` 判決）；(c) `cls_var_min` 30→20。`fit_baseline_wafers.py` 同步把各 wafer 拉到同一雜訊規模再擬合 baseline，並重新輸出 `baseline.json`。
4. **試過但放棄的**：`cls_site_min` 降到 12 會讓 W23（強變異數上升）被誤判成 Site unbalance；`cls_group_min` 降到 20 會讓強變異數的合成 wafer 被誤判成 Mean Trend Down。兩者都維持原值（20、30）。
5. **結果**：真實 25 片留一片驗證 **仍為 24/25**（只有 W25 錯），Normal 的最大誤報數：變異 4、site 3、平均值 5（門檻 20／20／30）。壓力測試（6 片 Normal 底）：

| 異常 | 完整強度(=真實) | 0.5 倍 | 0.3 倍 | 0.2 倍 | 0.1 倍 |
|---|---|---|---|---|---|
| Mean Trend Up / Down | 6/6 | 6/6 | 6/6 | 6/6 | 0/6 |
| Stdev Trend Up | 6/6 | 6/6 | 6/6 | 0/6 | 0/6 |
| Site unbalance | 6/6 | 6/6 | 0/6 | 0/6 | 0/6 |
| 對照組（無異常） | 誤報 0/6 | | | | |

修改前：Stdev Trend Up 只有完整強度偵測到，0.5 倍就 0/6；Site unbalance 0.5 倍為 5/6。偵測延遲：Stdev Trend Up 由第 6 個 touchdown 提前到第 5 個。
6. **`Smartest.zip` 比對（唯讀）**：zip 內的 `SmarTest` 是**比 repo 新**的機台版本：`Main.flow` 已把 `receive_temp_predict1..6` 改成呼叫新的 `ACSTML.Predict`（送出 `{"key":"predict","data":N}`，與 `sample.py` 內隊友加的 `predict` 分支對得上），另外新增 `Predict.java` 與編譯後的 class。repo 內尚未同步。**這是情境二的接口，不是情境一的問題，但 repo 與機台版本不一致需要處理（任務 C）。**

## 第三輪：`get_state()` 加入 die 座標
- 新增 `wafer_map`（目前這片的每顆 die：td、site、x、y、part_id、sbin、passed、outliers、suspect，加 x/y 範圍）、`wafer_reports[i].die_map`、`recent[i].wafer`；`Detector.die_flags()` 提供每顆 die 的離群測項數。
- 測試：`test_wafer_map_has_die_coordinates_and_resets_per_wafer`；W14 整份 state 34 KB（< 100 KB）。詳見 v3 spec 第 12 節。

## 第四輪：`get_state()` 精簡
- 依你的意見刪掉大量重複欄位與 `summary`：輸出改為 `lot/wafer/touchdown/label/confidence/indicators/wafer_map/history/finished`，約 4～5 KB（原 34 KB）。`summary` 只用在通知機台的訊息，不放進 state。
- 同步更新：`tests/test_scenario1.py`、`tools/demo_state.py`（現在輸出的就是精簡版 state）、五份任務書的介面契約（B、D 加了更新提醒）、v3 spec 第 13 節。
- 結果：35 個測試只有既有的 1 個失敗。

## 第五輪：touchdown 統一 1 起算、state 新增 `error`
- 偵測器的 `series`、`onset_td` 改為從來源就是 1 起算，`scenario1` 不再 +1；W14 驗證：`mean_trend`、`ramp_shape`、`finished`、`history` 首個異常皆為 4。
- state 新增 `error`（`Detector.load_error`），避免 baseline 載入失敗時前端毫不知情。
- 35 個測試只有既有的 1 個失敗。

## 第六輪：沒有 WaferStart 的備案、清理舊工具
- **備案（`scenario1.py`）**：從未收到 `WaferStart` 時，若新的 touchdown 的 die 座標 (x, y) 與目前這片已測過的重複，就視為換片：先結算上一片（進入 `finished`），再以 `auto-N` 命名開新的一片；收到過真正的 `WaferStart` 後就關閉此推測。`LotEnd` 會結算最後一片（`sample.py` 的 `consumeLotEnd` 已接上）；沒有資料的 `wafer_end` 會被忽略，不會產生空報告或重複報告。限制：同一片 wafer 內若有複測（同座標再測）會被誤判成換片。
- **清理**：刪除 `tools/evaluate_detector.py`、`tools/inject_anomalies.py`、`tools/eval_validation.py`（用舊模擬資料寫的，取代者是 `eval_wafers.py`、`stress_wafers.py`）。前兩個在 git 歷史內仍可還原，`eval_validation.py` 未曾 commit。`tools/fit_baseline.py` 保留，因為 `fit_baseline_wafers.py` 共用它的 `fit_values`。任務書 A、D 與舊 spec 內提到這些工具的地方已過時。
- 測試 38 個，只有既有的 1 個失敗。

## 第七輪：機台實測（2026-09-19，VM `group-1`、Edge 開發 pod `dev-app-*`）
**做法**：`user@group-1` 用金鑰連線；在 Edge 開發 pod 的獨立資料夾 `/data/project/scenario1_test/`（不動隊友的 `/data/project/oneAPI_py3.10`）放我們的程式，用新增的 `tools/machine_probe.py`（繼承 `SampleMonitor`，記錄事件順序、真實欄位、每個 touchdown 的 callback 時間、`get_state()`）連上 Nexus 事件串流；在 VM 用 `runTp.sh load` 再 `eng_run N` 執行測試程式產生真實事件。

**確認的事實（取代先前的假設）**
| 項目 | 結果 |
|---|---|
| 事件順序 | `LotStart → TestStart → [TestSuiteStart, Measurement, MultiParam, TestSuiteEnd] × 約 3030 → TestFlowEnd → TestEnd → LotEnd`；TestEnd 在所有量測之後 |
| WaferStart / WaferEnd | **不會送**（20 個 touchdown 只有 1 次 LotStart、1 次 LotEnd）→ 備案是必要的，且運作正常：wafer 命名 `auto-1`，LotEnd 時結算，`finished` 有一筆、80 顆 die |
| 測項 key | `TestSuite + "#" + TestText` 例：`Main.Suite1` + `CP`；量測值 `query_Results(i)` 是含 1 個 float 的 list |
| die 座標 | **TestStart 的 x、y 一律是 -32768（無效）**，TestEnd 才有真值（例如 (2,6)、(7,6)…，範圍 x 0～11、y 0～8）；`part_id` 是空字串；`part_flag` `0x0`、`sbin`、`hbin` 是 int；`sbin=1` 為通過 |
| 批號 | `LotStart` 的 `get_LotId()` 有值（`A3847573`） |
| 處理時間 | 每個 touchdown 約 12,000 次 `update`；callback 總時間穩態約 3～5 秒（含探針本身的量測開銷，偶爾到 10～12 秒），測試程式每個 touchdown 約 12 秒 → 約 30～40% 的時間預算，跟得上。`TestEnd`（判斷與分類）約 140 ms |

**因實測修正的問題**
1. 「座標重複就換片」備案原本用 TestStart 的座標，但那是無效值，會每個 touchdown 都誤判成換片。改成：忽略 -32768，並改在 `TestEnd`（座標有效時）判斷；新增測試 `test_unset_coordinates_at_test_start_do_not_trigger_rollover`。換片時該 touchdown 的量測已進入舊的偵測器，新一片從 td 1 起算，這一個 touchdown 的量測不計入新片（已知的小損失）。
2. `consumeTestSuiteStart/End`、`consumeMeasurementData`、`consumeTestFlow*` 與 `consumeData` 開頭的逐事件 print 全部改成 `ACS_DEBUG_EVENTS=1` 才印（每個 touchdown 約 12,000 行輸出）。

**結果**：20 個 touchdown 全部處理完、無錯誤；`get_state()` 在機台上輸出符合格式；wafer 在 LotEnd 正確結算。
**但分類結果不能當準確率**：機台上 `TestCase1_OfflineData.csv` 重播的資料**和訓練 wafer 不是同一份分佈**（第 1 個 touchdown 就有 137 個測項在 `subflow4` 大幅偏離 baseline，標籤先是 Mean Trend Down/Up 來回，第 13 個 touchdown 起變成 Site unbalance，最後 `auto-1` 被判 Site unbalance）。這份資料本來就帶有預埋的異常（site 4 的突發等）。要驗證真正的準確率，必須把訓練 wafer（例如 W14、W2）轉成機台讀得懂的格式重播。
**尚未做**：把我們的程式打包成 Docker 映像檔部署（需要 sudo，`user` 沒有 docker 權限）；目前 Edge 上實際運作的仍是舊映像檔 `grp1/py-app:latest`。

**環境紀錄**：Edge 開發 pod 重建後主機金鑰變了（pod 名稱不同）；我從 VM 獨立取得指紋（`SHA256:oJsjDJ...`）與本機看到的相同，並使用暫時的 known_hosts 檔連線，沒有修改 `~/.ssh/known_hosts`。VM 上 `runTp.sh` 需要 `DISPLAY=:1 XAUTHORITY=/home/user/.Xauthority`（否則 SmarTest 不會啟動、`AppDeployer` 回 `Session is not ready`）。機台目前狀態：SmarTest 執行中、探針已停止、`/data/project/scenario1_test/` 保留。

## 技術細節與邏輯
- **測項 key 對應（S1-1，來源：`Edge/oneAPI_py3.10/py-app.log` 的真實事件）**：`key = query_TestSuite + "#" + query_TestText`。例：`Main.IDDQ_flow.IDDQ_A1` + `IO1` → `Main.IDDQ_flow.IDDQ_A1#IO1`，與訓練 CSV 欄名去掉 `160_` 前綴後一致。`query_TestNumber`（如 80000）在事件裡與 CSV 前綴不同，因此不使用。
- **量測值**：`consumeMultiParametric` 取 `query_Results(index)[0]`（真實 log 內 `Cnt(1)`）。`consumeParametricTest` 只有 Lotid/waferid 之類，偵測器不監控，未接。
- **die 通過與否**：`query_SBinResult == 1`（`DefineBins.java` 的 bin 1 是 passed）。
- **touchdown 邊界**：`TestStart` 記下 4 個 site 的座標並把 touchdown 計數 +1；`TestEnd` 送出每顆 die 的 sbin 並呼叫 `end_touchdown()`。
- **通知機台的原則**：只在「wafer 的即時分類由 Normal 變成某個異常類別」時送一次（例：`TD4: wafer looks like Mean Trend Up`），wafer 結束時若還沒送過才補送摘要。**不再**因為單顆 die fail（subflow1 五個測項同時尖峰）送訊息，否則 Normal wafer 也會被通知（W2 曾出現 4 則、W25 出現 3 則誤報）。
- **Record 新增 `label` 欄位**：每個 touchdown 當下的 wafer 即時分類，前端可畫「分類隨時間變化」。
- **WaferReport**：`confidence = 比值/(1+比值)`（比值是各準則的 value/threshold 最大者，良率取 threshold/value）；Normal 則是 `1/(1+比值)`。這是簡單的邊界度量，不是機率。`onset_td` 為 1 起算。`evidence` 目前放各 subflow 的觸發數（`groups`），與任務書 0.3 的 Alert 清單不同。
- **本機驗證**：`python3 -m unittest discover -s tests` → 34 個測試只有 1 個失敗（既有的 `test_list_request_returns_seeded_message`，與本次無關，Phase 3 取代）。W14 經 Scenario1 重播 0.8 秒，TD4 判出 Mean Trend Up；W2、W25 全程無訊息。留一片驗證仍 24/25，Low yield 穩定判對的 touchdown 為 W3=4、W9=8。

## 待執行事項與注意事項
- [x] S1-1 事件測項名稱與 CSV 欄名的對應（已由真實事件確認）
- [x] S1-2 `sample.py` 接線（量測、device、touchdown、wafer、lot）
- [x] S1-3 分類改變時通知機台（避免洗版）
- [x] S1-4 `get_state()` 契約欄位齊備（`predictions` 為空陣列、`predictor` 標示未安裝，等場景二）
- [x] S1-5 本機假事件測試
- [ ] **S1-6 Stdev Trend Down（W25）仍未找到訊號**：用 W23 當模板、逐 subflow 找「變異偏小」的暫時性突起與 20 個 touchdown 的逐步趨勢，皆與 Normal 無異（最強候選 z=2.9，Normal 最高 2.2，W1 也有 2.8），不加規則以免過擬合，需向主辦方確認
- [x] S1-7 更新 v3 spec（第 10 節）
- [x] **機台實測（部分完成，見第七輪）**：事件順序、座標、欄位格式、處理時間已確認；尚未做：以訓練 wafer 重播驗證準確率、Docker 映像檔部署。原先待確認項目：要驗證：`consumeMultiParametric` 的 `query_Results` 型別、`query_SBinResult` 對 bin 的意義、`consumeWaferStart/End` 是否真的會送出（真實 log 只看到 LotStart/LotEnd，沒有 WaferStart，若機台不送 wafer 事件，`reset("wafer")` 與 `wafer_end()` 不會被呼叫，wafer 分類需改以 lot 或 touchdown 數切分）
- [ ] **效能**：每個 touchdown 約 12,000 筆 `update`，離線約 0.05 秒/touchdown；`consumeData` 不可阻塞，需在機台上量測實際 callback 時間
- [ ] 前端（任務 D）尚未做，可用 `tools/demo_state.py` 與 `Scenario1.get_state()` 的輸出開發
- [ ] `sample.py` 內原有他人加入的 `predict` 分支與 `self.sites` 保留未動；commit 前請確認沒有與隊友衝突
- [ ] 請人 code review 後再 merge；尚未 commit

## 第八輪：資料路徑、後端主動推送、去除假的第二個標籤（2026-09-20）
- **訓練資料路徑**：資料已移到 `SmarTest/training/`（`Data/` 與 `TrainDataInfo.txt`）。三個測試檔（`test_scenario1/2`、`test_sensor_predictor`）的 `DATA_DIR` 改為只認這個路徑；工具的 `--data`、`--labels` 一律由指令傳入，沒有預設路徑。指令範例：`python3 tools/eval_wafers.py --data ../../SmarTest/training/Data --labels ../../SmarTest/training/TrainDataInfo.txt`。
- **後端主動 POST 給前端**：新增 `bin/pusher.py`（`StatePusher`，只用標準函式庫的背景執行緒）。設定 `ACS_FRONTEND_URL`（例如容器內 `http://127.0.0.1:5000/api/state`）後，`main.py` 會每 `ACS_PUSH_INTERVAL` 秒（預設 3）把 `get_state()` 用 `POST` 送出，本文為 JSON，另加 `seq`（遞增）與 `sent_at`（秒）；沒設定網址就不推送。前端連不上不會影響事件處理：只在第 1、10、之後每 100 次連續失敗時記錄，恢復時記錄一次；網址只接受 `http://`、`https://`。`tools/mock_frontend.py` 是測試用的接收端（`POST /api/state` 存下、`GET /api/state` 回傳最新一筆）。本機驗證：真實 `SampleMonitor` 加 W14 事件，19 次推送 19 次收到、0 失敗；新增 6 個測試（`tests/test_pusher.py`）。尚未在機台上跑，也還沒有真正的前端伺服器。
- **去除假的第二個標籤**：`detector.py` `_group_counts` 中，已被判為 site 失衡的測項不再算進「平均值趨勢」與「波動變大」的計數（第 456–461 行）。W1 的平均值趨勢計數由 53 降為 6，訓練 wafer 不再出現雙標籤；留一片驗證仍 24/25，壓力測試不變；兩個獨立異常（不同測項）仍保留兩個標籤（`tests/test_detector.py` 新增 2 個測試）。
- 全部測試 81 個，只有既有的 `test_list_request_returns_seeded_message` 失敗。

