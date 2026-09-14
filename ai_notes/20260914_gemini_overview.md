# 專案總覽 (Project Overview) - by Gemini

本專案基於 Advantest ACS Real-Time Data Infrastructure (RTDI) 架構與 ACS Gemini 模擬平台，利用 ACS Nexus OneAPI (Python SDK) 開發實時晶片測試數據監控與 AI/ML 自動化控制應用。

---

## 📌 1. 目前開發進度

- **2026.09.14**：完成 `Case_Event/` 目錄數據上傳與彙整，提供模擬事件資料與測試案例。
- **環境設定完成**：已建立 ACS Gemini 虛擬機 (VM) 環境，並設定好 Host Controller (HC) 與 Edge Server 之間的連線管道。
- **SDK 與框架整合**：完成 ACS Nexus OneAPI Python SDK (v3.2.0) 的套件解析與監控器 (Monitor) 基礎框架搭建。

---

## 🛠️ 2. 程式架構與運作邏輯

本程式的核心目的是在半導體測試（Test Cell / Production Run）過程中，透過 OneAPI 即時接收測試事件資料，進行動態分析並向測試機發送控制指令。

```
+------------------+   Nexus Data Event   +------------------+
|    ACS Nexus     | -------------------> | OneAPI Application|
| (Host Controller)|                      |  (on Edge Server)|
+------------------+ <------------------- +------------------+
                       Control Command
```

### 核心模組說明
1. **連線管理 (`Interface`)**：
   - 使用 `connect()` 與 ACS Nexus 建立雙向通訊機制通道。
   - 透過 `getConnectionState()` 確認指令通道狀態，確保指令可成功送達。

2. **事件監控器 (`Monitor` Callback)**：
   - 繼承 `Monitor` 類別並實作 `consumeData(tc, data)` 回呼函數。
   - **生產事件 (Production Events)**：監聽 `PRODUCTION_LOTSTART`、`PRODUCTION_WAFERSTART`、`PRODUCTION_TESTEND` 等事件。
   - **量測數據 (Measured Data)**：解析 `MEASURED_PARAMETRIC`（參數測試）、`MEASURED_FUNCTIONAL`（功能測試）與 `MEASURED_SCAN`（掃描測試）等數據。

3. **自動化控制指令 (`sendCommand`)**：
   - 當分析邏輯發現異常或滿足特定條件時，調用控制 API：
     - `settest`：動態跳過 (bypass) 特定測試套件 (Test Suite)。
     - `setpat`：旁路特定平行測試組 (Parallel Group)。
     - `setprogvar`：動態調整測試程式變數。
     - `setpause`：暫停生產線以進行檢驗。

---

## 🚀 3. 環境與使用說明

> ⚠️ **重要開發原則**：**請勿直接在 Virtual Machine (Host Controller & Edge Server) 上進行開發與寫程式**。請在本地端開發、測試打包成 Docker Image 後，再部署至 Edge Server 執行。

### (1) 存取虛擬機環境
1. 登入 ACS Gemini Dashboard：[https://sandbox.gemini.te-cloud.advantest.com/dashboard/virtual-machine](https://sandbox.gemini.te-cloud.advantest.com/dashboard/virtual-machine)
2. 啟動 `grp1` 相關 VM 並進行連線，進入 **Host Controller (HC)**。
3. 連線至 **Edge Server**：
   - Web 介面：`http://advantestcell.local:29080`
   - SSH 連線：`ssh edge`

### (2) 本地開發與部署流程
1. **開發環境**：建議使用 Python 3.9 / 3.10 / 3.11 環境（依據需求安裝 `jsonschema` 等依賴套件）。
2. **容器化打包**：
   - 參考 `ubuntu.Dockerfile.example` 撰寫 Dockerfile。
   - 執行 `./build_base_image.sh` 建立 Docker Image。
3. **部署與生產模擬**：
   - 將 Docker Image 部署至 ACS Edge Server 執行。
   - 透過 Gemini 平台重放 STDF / 事件串流資料（Replay），進行模擬營運測試 (Production Run Simulation)。

---

## 📋 4. 接下來怎麼做 (Roadmap & TODO)

- [ ] **解析 `Case_Event/` 數據**：對已上傳的事件數據進行特徵清洗與分析，確認 key/value 欄位結構。
- [ ] **優化 `consumeData` 處理效率**：確保回呼函數不會阻塞事件接收線程（若計算耗時需實作非同步處理）。
- [ ] **實作 AI/ML 模型決策邏輯**：結合實時量測數據（如 `MEASURED_PARAMETRIC`），訓練/整合異常檢測模型。
- [ ] **整合指令控制邏輯**：測試根據模型預測結果觸發 `settest` 或 `setprogvar` 等操作。
- [ ] **端到端模擬與效能評估**：在 ACS Gemini 平台上進行完整 STDF 重放測試，評估良率保護與測試時間縮短效果。
