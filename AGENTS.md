# AI Agent Guidelines & Operating Protocols

Welcome to the **Hackathon-Advantest-grp1** repository. This document outlines the mandatory rules, workflows, directory structure, and logging requirements for all AI coding assistants (e.g., Gemini, ChatGPT, Claude, GitHub Copilot) operating on this project.

---

## 📁 Repository Directory Layout

Please familiarize yourself with the project structure before modifying or adding files:

```text
.
├── Edge
│   ├── EdgeLog
│   │   ├── EdgeLog
│   │   ├── conf
│   │   │   └── setup.ini
│   │   └── logs
│   └── oneAPI_py3.10
│       ├── Dockerfile
│       ├── bin
│       │   ├── AdvantestLogging.py
│       │   ├── FileTransfer.py
│       │   ├── libACSAction.so
│       │   ├── liboneAPI.so
│       │   ├── main.py
│       │   ├── oneapi.py
│       │   ├── oneapi_DFF.py
│       │   ├── requirements.txt
│       │   └── sample.py
│       ├── py-app.dockerfile
│       ├── py-app.log
│       ├── requirements.txt
│       └── tag.sh
├── README.md
├── SmarTest
│   ├── Case_Smt870
│   │   ├── DEVICE_JAVA_VERSION_CHANGED_TO_21.txt
│   │   ├── lib
│   │   ├── logger.ini
│   │   ├── model_Smt8
│   │   ├── patfaildef.csv
│   │   ├── src
│   │   │   ├── ACSTML
│   │   │   ├── CustomTML
│   │   │   ├── TestCase1
│   │   │   ├── common
│   │   │   └── patterns
│   │   ├── start_smt
│   │   └── util
│   ├── Util
│   │   ├── logging_config.py
│   │   ├── logs
│   │   ├── startSmt.py
│   │   └── tpExec
│   ├── app_descriptor.json
│   ├── recipe
│   ├── runTp.sh
│   └── workspace
├── ai_notes
│   └── 20260914_gemini_overview.md
├── doc
│   ├── ONEAPI_Manual.pdf
│   └── WorkShop_Material.pdf
└── images
    └── app_descriptor_py.json
```

---

## ⚠️ Coding Style & Constraints (Strictly Enforced)
When generating or modifying any source code, all AI agents MUST strictly adhere to the following commenting rules:

1. **English Only:** Do NOT write code comments in Chinese or any other non-English language. All inline comments and docstrings must be in English.
2. **Single-Line Limit:** Keep comments extremely concise. Every comment must be restricted to a single line. Do NOT write multi-line comments or paragraphs.
3. **Comment-to-Code Ratio:** The total volume of comments MUST NOT exceed the volume of the actual code. Avoid over-commenting; let the code be self-explanatory through good naming conventions.


## ⚙️ Mandatory AI Agent Workflow Protocol

Every AI agent participating in code generation, refactoring, or documentation MUST strictly follow the step-by-step workflow below.

```
[1. Create/Switch Branch] ──> [2. Perform Work] ──> [3. Generate Traditional Chinese Log] ──> [4. Switch Back & Notify]
   (ghuser_modelname)          (Code & Test)         (ai_notes/YYYYMMDD_model_filename.md)     (Request Human Code Review)
```

### Step 1: Git Branch Protocol
Before modifying any files or writing code:
1. Identify the GitHub user name (`<ghuser>`) and the AI model name (`<modelname>`).
2. Create and switch to a dedicated feature branch formatted as:
   ```bash
   git checkout -b <ghuser>_<modelname>
   ```
   *Example:* `git checkout -b feedc0de_gemini3flash`
3. All code modifications **must** take place inside this feature branch.

---

### Step 2: Implementation & Technical Rules
1. **Never Edit Directly on VMs:** Do not attempt to run live edits on the Host Controller or Edge Server VMs. Develop locally, containerize using Docker, and prepare for deployment on the Edge Server.
2. **Preserve Authentic Code:** Adhere closely to existing variable conventions, architectural patterns (OneAPI SDK v3.2.0 for Python 3.10), and established dependencies.
3. **Non-Blocking Callbacks:** When editing `Monitor.consumeData()` in `Edge/oneAPI_py3.10/`, ensure heavy data processing operations do not block the OneAPI main thread.

---

### Step 3: Mandatory Activity Logging (`ai_notes/`)
After finishing a task or code iteration, the AI Agent **MUST** create a change log file inside the `ai_notes/` folder.

- **File Path Format:** `ai_notes/YYYYMMDD_<modelname>_<filename_or_feature>.md`
  - *Example:* `ai_notes/20260914_gemini3flash_agents_protocol.md`
- **Language Requirement:** The content of the log file MUST be written in **Traditional Chinese (繁體中文)**.
- **Log File Content Requirements:**
  1. **變更摘要 (Summary of Changes):** High-level overview of what was implemented.
  2. **修改與新增檔案 (Modified/Created Files):** List of affected file paths.
  3. **技術細節與邏輯 (Technical Details & Rationale):** Why and how changes were made.
  4. **待執行事項與注意事項 (Next Steps & Notes):** Potential risks, dependencies, or follow-up tasks.

---

### Step 4: Branch Cleanup & Code Review Notification
Once code implementation and the `ai_notes/` entry are complete:
1. Switch back to the original branch (e.g., `main`):
   ```bash
   git checkout main
   ```
2. Prompt the human developer (repo owner/master) in the chat response to perform a **Code Review** before merging `<ghuser>_<modelname>` into the primary branch.

---

## 📝 Example Response Checklist for AI Agents

When handing back control to the developer, ensure your response includes:
- [x] Confirmation of branch creation/usage (`<ghuser>_<modelname>`).
- [x] Summary of code changes made.
- [x] Path to the newly created Traditional Chinese log file in `ai_notes/`.
- [x] Switch back to original branch (`main`).
- [x] Explicit reminder asking the user to review the code before merging.
