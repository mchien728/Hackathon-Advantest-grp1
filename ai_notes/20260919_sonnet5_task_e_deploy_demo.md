# 任務書 E：部署與 Demo（Phase 0、6、7）

> 你是 **E**。你負責「把大家的成果安全地送上機台並驗收」：sudo 與部署、共用 Host 的協調、端到端驗收、Demo 故事與簡報、最後的文件與 Code Review 流程。你和 C 是**唯二會在共用 Host 上執行 `runTp.sh` 的人**。

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
1. 團隊能安全、可重複地把新版本送上機台並驗收。
2. Demo 有完整的故事、簡報與備援。
3. 每個分支都有繁中紀錄並通過 Code Review。

## 2. 你擁有的檔案與權責
`Edge/oneAPI_py3.10/Dockerfile`、`py-app.dockerfile`、`tag.sh`、`SmarTest/app_descriptor.json`（套用 D 給的片段）、簡報與 Demo 文件。你也是**共用 Host 的協調人**。

## 3. 任務清單

### E0（S0，約 30 分鐘）啟動會議與 Host 協調
1. 請在 Host 上執行（**這件事我的 AI 之前被系統擋下，需要你本人執行**）：`sudo -l`，記錄 `user` 能用 sudo 執行哪些指令；`groups` 看有沒有 `docker`。
2. 沒有權限就問工作坊講師：由誰代為 build / push？或有沒有免 sudo 的方式？
3. 建立**共用 Host 使用時段表**（共享文件或試算表）：欄位為時段、使用者、目的、預計結束時間。規則：跑 `runTp.sh` 之前先登記，並先執行：
```
ssh advantest 'ps -eo user,pid,etime,args | grep -E "HPSmarTest|Drecipe" | grep -v grep'
```
4. 主持 S0 決策並記錄在 `ai_notes/20260918_sonnet5_hackathon_todo_plan.md` 的 Phase 0：**閉環或安全牌**、**ML 選配層做不做**。

### E1（S1，約 90 分鐘）部署準備
1. 刪掉 `Dockerfile` 與 `py-app.dockerfile` 裡先前加的兩行 `TODO(Phase 6)` 註解（`COPY bin/. ./bin` 已包含新檔案，不需要額外 COPY）。
2. 寫好並**乾跑**（dry-run）同步流程，把本機程式碼送到 Host。Host 上的專案路徑是 `~/Case_Event/Edge/oneAPI_py3.10/`：
```
cd Edge/oneAPI_py3.10
rsync -av --dry-run --exclude '__pycache__' --exclude 'py-app.log' ./ advantest:~/Case_Event/Edge/oneAPI_py3.10/
```
不要加 `--delete`。正式同步前先在 Host 備份：`cp -a ~/Case_Event/Edge/oneAPI_py3.10 ~/Case_Event/Edge/oneAPI_py3.10.bak_$(date +%Y%m%d_%H%M)`。若 Host 沒有 `rsync`，改用 `scp -r`。
3. 確認 build / 部署流程（教材第 25、26 頁與 `SmarTest/runTp.sh`）：
   - build 與 push：`cd ~/Case_Event/Edge/oneAPI_py3.10 && sudo ./tag.sh`（推到 `unifiedserver.local/grp1/py-app:latest`）。
   - 部署：`runTp.sh` 會把 `SmarTest/app_descriptor.json` 複製到 `/opt/acs/nexus/conf/`，SmarTest session 啟動時 Nexus 會自動部署（`Auto_Deploy` 已開）。必要時手動：`/opt/acs/nexus/bin/AppDeployer start`（`Session is not ready` 代表 SmarTest 還沒就緒，等 30 秒重試）。
   - 驗證：`~/Case_Event/Edge/EdgeLog/EdgeLog log | tail -40`。
   - **回滾**：`tag.sh` 一律推 `latest`，沒有舊版本可切回。所以每次部署前都要備份上一版原始碼（見上），需要時還原原始碼再 build。
4. 寫成一頁「部署手冊」放進 `ai_notes/`。
5. 開始寫 Demo 故事（見 E2）。

### E2（S1 到 S2，約 3 小時）Demo 故事、簡報骨架與注入情境
1. **故事主線**（建議）：「機台已經有上下限判斷，但看不到跨 DUT、跨 site 的趨勢問題；我們在 Edge 上即時偵測，並在 DUT 5–8 就通知機台。」
2. **主線畫面**：CSV 內真實埋的 site 4 突發異常（DUT 8、12、16、20、24 有 +8～13σ 離群值）；第 1 個 touchdown 起判為異常。
3. **補充畫面**：用 `tools/inject_anomalies.py` 合成的漂移、標準差變大、單一 site 偏移（可請 D 的 `dashboard_demo.py --inject` 展示）。
4. 簡報骨架：問題與價值（扣回教材第 4 頁的 ROI）→ 架構（Nexus → Edge → 決策回傳）→ 方法（四類異常）→ Demo → 數字與**誠實的限制**（沒有標籤、效果由合成注入與埋入異常驗證、門檻為外推值）。
5. 數字向 A 取（最終版在 S3）。

### E3（S2，約 90 分鐘）第一次整合部署
前提：B 通知分支可部署。
1. 登記時段、確認沒人在跑。
2. 同步（含備份）→ `sudo ./tag.sh` → 觸發部署 → `EdgeLog log` 確認新版載入（沒有 `load_error`、有收到事件）。
3. 通知 C 進行彈窗驗證（C3），並一起處理問題。
4. 若 D 的儀表板已合併：套用 D5 的 `app_descriptor.json` 片段（`exposed_ports`/`mapped_ports`），並和 D 一起確認怎麼從外面看到頁面。
5. 寫 `ai_notes/` 紀錄。

### E4（S3，約 2 小時）端到端驗收
依序執行並逐項打勾（每項附證據：輸出或截圖）：
```
cd ~/Case_Event/SmarTest
./runTp.sh load
./runTp.sh eng_run 1
./runTp.sh prod_run
```
**驗收清單**
1. `EdgeLog log` 顯示新版 py-app 正常運作，沒有例外與 `load_error`。
2. 第 0 個 touchdown 無異常；**第 1 個 touchdown（DUT 5–8）起判為異常**。
3. 機台端收到訊息（彈窗或 `set_message` 內容）。
4. 儀表板顯示正確（若已部署）。
5. 在 Edge pod 上的效能數字（來自 A2 / A5）符合預算（每個 touchdown < 150 ms）。
6. 連續跑 `prod_run` 兩次，第二次仍正常（reset 邏輯正確）。
失敗項目回報給對應的人：偵測邏輯找 A、接線找 B、真機流程找 C、畫面找 D。

### E5（S4）收尾
1. **簡報與備援**：完成簡報；備援包含 C 的螢幕錄影、D 的截圖與離線 demo（`tools/dashboard_demo.py`）。
2. **文件**：確認每個人都有 `ai_notes/` 的繁中紀錄；把最終狀態更新到 `ai_notes/20260918_sonnet5_hackathon_todo_plan.md`。
3. **Code Review 與合併**（AGENTS.md 要求合併前人類審查）：
   - 每人把自己的分支 push：`git push -u origin <分支名>`（注意是 `origin`，不是分支名）。
   - 建議合併順序：A → B → D → C → E（依賴由深到淺）；每合併一支就重跑 `python3 -m unittest discover -s tests`。
   - 審查重點：`bin/` 底下沒有多餘檔案（`__pycache__`、暫存檔）、沒有密碼或金鑰、註解為英文單行、`ai_notes/` 紀錄齊全。
4. **最終部署**：合併完成後從 `main` 重新 build 部署一次，並再跑一遍 E4 清單。

## 4. 交接與依賴
- **B → 你**：可部署的分支（E3）。**A → 你**：`baseline.json` 有變就通知你重新部署。
- **D → 你**：`app_descriptor.json` 片段（D5）與 Demo 素材（D7）。
- **C → 你**：Demo 手冊與影片（C5）。**你 → 所有人**：Host 時段表、驗收結果。

## 5. 常見坑
- **不要在 Host 上直接改程式再 build**：要從本機同步，才能留下紀錄並避免版本混亂。
- `sudo ./tag.sh` 會從 `unifiedserver.local` 拉 base image 並在結束時刪除本機映像檔，屬於預期行為。
- 部署後 `py-app` 是新容器：舊容器的狀態（儀表板累積資料）會消失。
- Host 的 log 時間是 UTC，和台灣時間差 8 小時，排查時別對錯時間。
- 工作坊密碼只存在教材裡，不要貼進任何 repo 檔案、commit 或 PR。
