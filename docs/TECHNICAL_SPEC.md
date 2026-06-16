# TECHNICAL_SPEC.md: 企業級 IT 維運 AI Agent 平台技術規格與開發指南

## 1. 專案概述 (Project Overview)
本專案旨在開發一套基於零信任架構（Zero-Trust Architecture）的「智能 ITOps 代理平台」。系統具備跨系統狀態查詢、RAG 知識庫檢索、自動化故障排除與高風險操作審批能力。
本文件作為 AI 輔助開發（如 Cline, Cursor）之最高指導原則，所有生成的程式碼皆需嚴格遵守以下架構與安全規範。

---

## 2. 全局 AI 開發約束條件 (Global AI Coding Constraints)
為確保達到企業級軟體工程標準，AI 在生成程式碼時**必須**默認實作以下進階機制，無需開發者反覆提醒：

1.  **防禦性編程與錯誤重試 (Defensive Programming & Retries)：**
    * 所有對外部 API（包含 Mock API 與 LLM API）的呼叫，**強制實作 Exponential Backoff（指數退避）重試機制**（建議使用 `tenacity` 套件），以處理 Rate Limits (`429`) 或暫時性網路錯誤 (`5xx`)。
    * 嚴禁吞噬例外錯誤（Swallowing Exceptions）。所有 API 呼叫失敗必須回傳具備結構化錯誤訊息的 JSON，並引導 Agent 重新規劃，禁止讓系統直接 Crash。
2.  **不可篡改之審計日誌 (Immutable Audit Logging)：**
    * 所有具備「狀態變更」之工具呼叫（如：解鎖帳號、清除快取、抹除設備），除了基本的 Debug Log 外，**必須**將執行紀錄（包含 `user_id`, `action`, `parameters`, `timestamp`, `status`）寫入資料庫的 `audit_logs` 表中，並預留未來演進為 Append-only（僅限新增）之防篡改架構。
3.  **非同步優先 (Async-First)：**
    * 後端 FastAPI 路由、資料庫查詢（如 `asyncpg` 或 SQLAlchemy Async）與 LLM 呼叫，**全面強制使用 `async/await` 架構**，確保高併發下的系統吞吐量。
4.  **強型別與驗證 (Strict Typing & Validation)：**
    * 所有 Python 函式必須包含完整的 Type Hints。
    * 所有傳入 API 網關與 MCP 工具的資料，**強制使用 Pydantic v2 進行 Schema 驗證**。
5.  **機密管理與設定 (Secrets Management)：**
    * 嚴禁在程式碼中 Hardcode 任何 API Key、密碼或連線字串。
    * 所有環境變數必須透過 `pydantic-settings` 統一進行型別與預設值驗證，並由 `.env` 檔案動態注入。
6.  **強制結構化輸出 (Structured Generation)：**
    * 所有 LLM 的推論請求，若涉及後續程式邏輯判斷（如意圖路由），必須強制啟用 LLM 的 JSON Mode 或 Structured Output 功能，並以 Pydantic Schema 定義回傳格式，確保狀態機解析穩定。
7.  **自動降級備援 (Automated Fallback)：**
    * 在呼叫雲端 LLM API 時需實作 Fallback 邏輯。若主要模型發生非 Rate Limit 之系統異常（如 `500 Internal Server Error`），需自動捕獲例外並切換至地端備援模型（如 Ollama）進行推論，確保服務不中斷。

---

## 3. 系統架構與技術棧 (Architecture & Tech Stack)

### 3.1. 前端層 (Frontend)
* **框架：** Next.js (App Router) + TypeScript + Tailwind CSS。
* **AI 整合：** Vercel AI SDK (實作 Streaming UI 與 Tool Call 渲染)。
* **獨立模組：** IT 主管審批儀表板（Approval Dashboard），用於處理 HITL 請求。

### 3.2. API 網關與安全層 (API Gateway & Security Layer)
* **框架：** FastAPI (Python 3.10+)。
* **身分認證：** POC 階段實作 JWT (JSON Web Tokens)，架構需預留介接 Entra ID (OIDC/SAML) 之擴充彈性。
* **權限控制 (RBAC + ABAC Hybrid)：** PyCasbin，嚴格驗證 Request 角色權限，並預留擴充屬性級控制（如：時間、設備狀態、風險分數）之介面。
* **資料脫敏：** 請求進入 Agent 前，透過 Microsoft Presidio 攔截並遮蔽 PII（如身分證字號、私人 Email）。

### 3.3. Agent 核心編排層 (Agent Orchestration Layer)
* **框架：** LangGraph + LangChain Core。
* **記憶體與狀態：** 整合 PostgreSQL 作為 Checkpoint Saver，實現斷點續傳。
* **護欄 (Guardrails)：** NVIDIA NeMo Guardrails，限制對話必須聚焦於 IT 維運，阻擋 Prompt Injection。
* **模型選型：** 預設採用 Gemini API (如 `gemini-3.5-flash` 或 `gemini-3.1-flash-lite`) 作為推論大腦。

### 3.4. 模擬基礎設施層 (Mock Infrastructure & Tools)
* 基於 Model Context Protocol (MCP) 開發獨立工具。
* 透過 Docker Compose 啟動獨立的 FastAPI Mock Server 與 PostgreSQL，模擬真實企業環境（包含 CMDB 與 KB）。

### 3.5. 測試與持續整合 (Testing & CI/CD)
* **測試框架：** 使用 `pytest` 進行單元測試與整合測試。
* **測試覆蓋要求：** 所有新增之 MCP 工具與 FastAPI 路由，AI 必須同步生成對應的測試案例，確保邊界條件（Edge Cases）與異常捕獲邏輯正確運作。
* **版本控制：** 程式碼需符合 GitHub 協作規範，確保未來能順利串接 GitHub Actions 執行自動化測試流水線。

---

## 4. 核心工作流與狀態機設計 (LangGraph Workflow)

LangGraph 狀態機需完整實作「企業工單生命週期 (Incident Lifecycle)」，包含以下核心 Nodes 與 Edges：

1.  **`Incident_Creation_Node`**：接收使用者問題，自動於 ITSM 系統中建立或關聯追蹤工單 (Ticket)。
2.  **`Diagnosis_&_RAG_Node`**：判斷意圖並強制呼叫 KB Tool 檢索 IT SOP，確保後續操作符合標準流程。
3.  **`Permission_Check_Node`**：工具執行前的攔截點，調用 Casbin 確認使用者是否具備對應設備/服務之操作權限。
4.  **`Tool_Execution_Node`**：實際呼叫 Mock IAM/MDM/CMDB API 進行查詢或修復。
5.  **`HITL_Approval_Node` (關鍵)**：
    * **觸發條件：** 當判斷意圖為高風險操作（如 `Device Wipe` 或 `Reset Admin Password`）時觸發。
    * **行為：** 呼叫 LangGraph 的 `interrupt()` 凍結當前執行狀態（State），並向審批儀表板發送 Webhook，等待主管審批後方可 Resume。
6.  **`Ticket_Closure_Node`**：驗證修復結果，寫入 Resolution Notes 並自動關閉工單。

---

## 5. Mock API 與資料庫綱要 (Mock API & Database Schema)

開發期間需實作以下 Mock 微服務與對應數據表：

### 5.1. 數據庫綱要 (PostgreSQL)
* **IAM/MDM 領域：**
  * `users` 表：`id`, `email`, `role`, `account_status` (Active/Locked)。
  * `devices` 表：`device_id`, `owner_id`, `os_version`, `compliance_status`, `disk_space_mb`。
* **ITSM/CMDB 領域 (新增)：**
  * `cmdb_relations` 表：`asset_id`, `dependency_id`, `relation_type` (模擬設備、網路與核心服務之依賴關係)。
  * `incidents` 表：`ticket_id`, `user_id`, `status` (Open/Resolved/Closed), `issue_description`, `resolution_notes`。
* **安全領域：**
  * `audit_logs` 表：記錄所有變更操作。

### 5.2. MCP 註冊工具列表 (MCP Tools)
* **`Mock_KB_Tool` (RAG 知識庫)**
    * `query_sop(query: str)`：模擬 RAG 檢索維運手冊，提供 Agent 處置標準。
* **`Mock_CMDB_Tool` (組態管理)**
    * `get_asset_dependencies(asset_id: str)`：查詢特定設備若重啟或抹除，將影響哪些關聯服務。
* **`Mock_ITSM_Tool` (工單管理)**
    * `create_ticket(user_id: str, issue: str)`：建立新工單。
    * `resolve_ticket(ticket_id: str, notes: str)`：填寫修復紀錄並結案。
* **`Mock_IAM_Tool` (身分管理)**
    * `check_account_status(email: str)`：回傳帳號狀態。
    * `unlock_account(email: str)`：將狀態改為 Active（需 Audit Log）。
* **`Mock_MDM_Tool` (端點管理)**
    * `get_device_health(device_id: str)`：回傳硬碟與合規狀態。
    * `clear_system_cache(device_id: str)`：釋放硬碟空間（需 Audit Log）。
    * `remote_wipe_device(device_id: str)`：**嚴格綁定 HITL 審批流程**。

---

## 6. LLMOps 與可觀測性 (Observability)
* 全面導入 **Langfuse** 進行全鏈路監控。
* 所有 LLM 呼叫、Tool Calls 與 LangGraph 節點轉換，必須包裝在 Langfuse 的 Trace 與 Span 中。
* **SLA 與成本追蹤：** 需於 Dashboard 明確量化並追蹤 `Token Cost per Ticket`（單一工單成本）與 `MTTR`（平均修復時間），以利後期進行 Evals 自動化評估與投資報酬率 (ROI) 調校。