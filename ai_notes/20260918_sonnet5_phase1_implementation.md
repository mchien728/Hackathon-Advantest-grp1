# 變更紀錄：Phase 1 異常偵測器實作

## 變更摘要

依 [Phase 1 spec](20260918_sonnet5_phase1_spec.md) 的預設值實作異常偵測器及其離線工具：執行期偵測器（僅標準函式庫）、由離線 CSV 擬合的基準線、合成異常注入與評估工具、單元測試。全部為新增檔案，沒有修改任何既有檔案。實作過程中發現 spec 對 CSV 的一項事實判斷有誤（見「技術細節」），已在 spec 中更正。

## 修改與新增檔案

全部位於 `Edge/oneAPI_py3.10/`：

| 檔案 | 說明 | 進 image |
|---|---|---|
| `bin/detector.py` | 偵測器：`Detector.load/update/end_touchdown/reset`，五種異常（`outlier`、`mean_shift`、`variance_change`、`mean_drift`、`site_imbalance`） | 是 |
| `bin/model/baseline.json` | 3035 個測項的基準線（中位數/MAD）與校準後參數，288 KB | 是 |
| `tools/fit_baseline.py` | 從 `TestCase1_OfflineData.csv` 擬合基準線並做品質檢查 | 否 |
| `tools/inject_anomalies.py` | 由基準線產生乾淨串流並注入異常 | 否 |
| `tools/evaluate_detector.py` | 子指令：`sweep`（取捨曲線）、`calibrate`（校準並寫入參數）、`verify`（全規模驗證）、`replay`（重播真實 CSV） | 否 |
| `tests/test_detector.py` | 14 項單元測試 | 否 |
| `ai_notes/20260918_sonnet5_phase1_spec.md` | 更正 2.3 節事實錯誤，新增第 11 節實作結果與差異 | — |

## 技術細節與邏輯

**重要更正**：spec 原先寫「CSV 沒有埋異常」是錯的。我最初用平均值/標準差類統計量，被離群值本身撐大而漏掉。改用中位數/MAD 並以模擬純雜訊為對照後發現：約 110 個測項（多為 `subflow1` 的 `CP`）在 DUT 索引 7、11、15、19、23（皆為 site 4）有 +8 到 +13σ 的離群值；少數測項另有約 240σ 的尖峰。其餘四類（site 偏移、漂移、位移、變異）與純雜訊一致。

**為此做的設計調整**
- 基準線改用中位數 + 1.4826×MAD；品質檢查改看去除離群值後的偏度/峰度（排除的測項從 129 降到 6）。
- 餵給 CUSUM、漂移、site 視窗的 z 先截斷在 ±4（變異用 ±3），`outlier` 用未截斷值。未截斷時單一尖峰會讓警報持續 20～30 個 touchdown。
- 變異統計量用「同一 site 連續兩筆差的平方」的 EWMA，不受位移與 site 偏移干擾。
- 測項 key 自動去掉開頭的 `<數字>_`，避免離線基準線（無 test number）與執行期事件對不上。
- 沒見過的測項自動暖機（前 40 個值），基準線檔缺失或損毀時不會崩潰。

**校準方法**：以「每 5,000 顆 DUT 最多 1 次誤判、同一 pin 群組需 ≥3 個測項告警」反推每個偵測器的穩態警報比例上限（1.45e-5），在單一串流上量測不同門檻的警報比例與偵測延遲，因誤報事件太罕見而以尾端外推求門檻：`cusum_h=12.3`、`ewma_lambda=0.05`、`ewma_L=9.0`、`drift_thr=4.7`、`site_thr=4.6`，已寫入 `baseline.json` 並同步為 `detector.py` 的預設值。

**驗證結果（本機 Python 3.13）**
- 3029 個測項 × 2500 個 touchdown（10,000 顆 DUT）乾淨重播：誤判 0 次；每個 touchdown 33.3 ms。
- 注入異常偵測率皆為 1.00；延遲：位移 +3σ 為 8 DUT、漂移 36、site 偏移 40、突發離群 4。**標準差 ×2 為 44 DUT，未達暫定目標 30**（誤報預算下的取捨）。
- `update()` 延遲 p50 0.9 µs、p99 2.2 µs。
- 重播真實 CSV：第 0 個 touchdown 無警報，**第 1 個 touchdown（DUT 5–8）起判為異常**，與埋入的異常起點吻合。
- 單元測試：`test_detector.py` 14 項全數通過。

## 待執行事項與注意事項

- **警報有黏性**：視窗型偵測器在異常結束後仍會持續約一個視窗長度（重播時第 1 至 19 個 touchdown 都判為異常）。Phase 3 建議只在判定由正常轉為異常的瞬間呼叫 `set_message`。
- **尚未在 Edge pod 量測效能**（Python 3.10）。部署後需重跑 `evaluate_detector.py verify`。
- **測項名稱與 site 對應尚未用真實事件驗證**（`site = DUT 序號 % 4 + 1` 為推定，但 CSV 內五個離群點全落在同一 site，與推定一致）。
- 校準門檻由尾端外推而來，10,000 顆 DUT 的乾淨重播零誤判提供了支持，但統計上仍只能說明誤判率不高於約每 10,000 顆 2～3 次。
- `tests/test_sample_local.py` 的 `test_list_request_returns_seeded_message` 目前失敗（檢查的是已還原的測試樁），Phase 3 會取代它。
- 先前 `git stash` 暫存的 `sample.py` 變更（TODO 註解與測試樁）仍在 stash 中，未套用。
- 所有變更仍在 `mchien728_sonnet5` 分支的工作目錄，**尚未 commit、未切回 `main`**。
- 依 AGENTS.md，請在合併前先做 Code Review。
