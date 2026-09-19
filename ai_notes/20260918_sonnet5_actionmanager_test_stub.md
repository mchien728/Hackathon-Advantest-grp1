# 變更紀錄：在 `sample.py` 加入 ActionManager 寫入測試樁

## 變更摘要

為了讓團隊能在 Phase 3（真正的模型推論）完成前，先驗證「AdaptiveTest → ActionManager → ShowAction 彈窗」這條決策迴路的管線本身是否接通，在 `consumeTPRequest` 的 `"list"` 分支加入一個暫時性的測試樁（stub）：不管內容為何，先寫入一則固定訊息到 `ActionManager` 信箱，讓 Java 測試流程端能真的取到非空的 action，觸發 `ShowAction` 彈窗。

## 修改與新增檔案

- `Edge/oneAPI_py3.10/bin/sample.py`
  - `consumeTPRequest`：拿掉原本純註解、沒有實際作用的 `#ActionManager.set_message(...)`/`#ActionManager.set_wait(...)` 兩行
  - 在 `elif key_action == "list":` 分支內，於呼叫 `ActionManager.get(tc.testerId)` 之前，加入一行 `ActionManager.set_message(tc.testerId, "py-app test message: adaptive loop wiring OK")`
- 新增：`ai_notes/20260918_sonnet5_actionmanager_test_stub.md`（本檔案）

## 技術細節與邏輯

- 依照 `doc/ONEAPI_Manual.pdf` 第 68 頁的官方簽名 `set_message(testerid, reason)` 呼叫，確保參數符合規格。
- 放在 `"list"` 分支、`get()` 呼叫之前，是因為 `get` 必須在 `consumeTPRequest` 事件裡呼叫（manual 規定），而 `set_message` manual 標示為 "Any time"，所以放在同一個 request 處理流程內、寫入後立刻讀出，是驗證管線最簡單、不需要額外事件觸發的做法。
- 這是**暫時性測試樁**，不是 Phase 3 的正式邏輯——正式版本應該把 `set_message`（或 `set_wait`/`setprogvar`）的呼叫移到 `consumeParametricTest`/`consumeTestEnd` 裡，並依模型推論結果決定訊息內容與呼叫哪個 `ActionManager` 方法，而不是每次 `"list"` 請求都固定寫死同一句話。

## 待執行事項與注意事項

- 這個 stub 只解決 Python（Edge App）側的管線驗證，**要真的看到彈窗還需要使用者在遠端環境（如截圖中的 `/home/vincent/Case_Event/SmarTest/`）自行完成三項 SmarTest 端修改**（不在本次程式碼變更範圍內，因為那是不同環境的檔案）：
  1. `TestCase1_4site_ft.prog`：把 `var Boolean pause_eot= false;` 改成 `true`
  2. `TestCase1_PostRun.flow`：解除 `displayAction.execute()` 區塊的註解
  3. `TestCase1_PreRun.flow`：解除 `AdaptiveTestStep.execute()` 區塊的註解
- 驗證通過後，記得把這個 stub 換成 Phase 3 真正依模型判斷結果決定內容的邏輯，不要讓這句寫死的測試訊息留到正式版本。
- 本次變更目前仍在 `mchien728_sonnet5` 分支的工作目錄，尚未 commit。
