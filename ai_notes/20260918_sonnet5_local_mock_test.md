# 變更紀錄：新增本機 mock 測試（TODO Phase 2）

## 變更摘要

新增一支不依賴真實 Nexus/Edge 環境的本機單元測試，用假模組取代 `oneapi`、`libACSAction`、`FileTransfer`，直接呼叫 `SampleMonitor` 的 callback，驗證 `sample.py` 的 Python 側邏輯（包含上一輪加入的 `ActionManager.set_message` 測試樁）。

## 修改與新增檔案

- 新增：`Edge/oneAPI_py3.10/tests/test_sample_local.py`
- 新增：`ai_notes/20260918_sonnet5_local_mock_test.md`（本檔案）

## 技術細節與邏輯

- 放在 `tests/` 而不是 `bin/`，因為 `Dockerfile` 是 `COPY bin/. ./bin`，放進 `bin/` 會被打包進 image。
- 用 `sys.modules` 注入假的 `oneapi`（`Monitor` 基底類別、`DataType` 等）、`libACSAction`（`FakeActionManager`，以 dict 記錄 `set_message`、`get` 回傳 JSON）、`FileTransfer`，再 `import sample`。
- 測試項目：`{"action":"list"}` 會先寫入再取回測試訊息、`health` 仍回 `ok`、未知指令回 `unsupported`、`consumeData` 分派 `MEASURED_PARAMETRIC` 事件不會崩潰。
- 執行方式：`cd Edge/oneAPI_py3.10 && python3 -m unittest discover -s tests -v`，目前 4 項全數通過（本機 Python 3.13）。

## 待執行事項與注意事項

- 這只驗證 Python 側接線與既有分支沒被改壞。`FakeActionManager.get` 的回傳格式是自訂的，**不代表真實 `libACSAction` 回傳的格式**，Java 端 `FetchAction` 能否解析、彈窗是否出現，仍需在真實環境驗證。
- 本機 Python 版本（3.13）與 image 內的 Python 3.10 不同，但測試只用標準函式庫，不影響結果。
- 變更仍在 `mchien728_sonnet5` 分支的工作目錄，尚未 commit。
