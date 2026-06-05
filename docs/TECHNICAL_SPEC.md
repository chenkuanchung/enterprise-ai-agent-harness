# 企業級 AI Agent Runtime Platform 系統技術規格書

**Document Version:** 2.0 (Production-Ready Architecture)
**Target Profile:** 適用於企業內部標準化 Agent 基礎設施構建
**Author:** 系統架構設計師

## 1. 系統概述 (Executive Summary)

### 1.1 產品定位
本系統為一套高度可擴充的 **AI Agent Runtime Platform (代理運行平台)**。其核心價值在於提供「Agent Harness（外骨骼基礎設施）」，將 LLM 的非確定性邏輯，封裝進嚴謹的軟體工程生命週期中，提供統一的工具調度、狀態管理、權限控制與全鏈路監控。

### 1.2 企業級設計原則
* **Security & Compliance First (安全與合規優先)**：內建三層 Guardrails、嚴格的 RBAC 權限控管與不可篡改的審計日誌。
* **Cost & Performance Optimized (成本與效能最佳化)**：導入混合模型路由 (Hybrid Routing) 與語意快取 (Semantic Caching)，極小化高昂的 API 呼叫。
* **Decoupled Architecture (解耦架構)**：將「業務邏輯」、「提示詞」、「工具介面」與「底層模型」完全抽離，避免供應商綁定 (Vendor Lock-in)。

---

## 2. 系統架構拓撲 (Architecture Topology)

系統分為三大邏輯層：

1. **控制面 (Control Plane)**：負責 API 網關、身分認證 (Auth/RBAC)、Guardrails 審查與路由。
2. **執行面 (Execution Plane)**：LangGraph 狀態機運行環境、MCP 工具伺服器、模型推論引擎 (Gemini / Local LLM)。
3. **數據面 (Data Plane)**：狀態持久化 (State DB)、向量上下文記憶 (Vector DB)、監控與審計日誌 (Observability & Audit Logs)。

---

## 3. 核心模組詳細設計 (Core Module Specifications)

### 3.1 權限與合規安全模組 (Security, RBAC & Audit)
* **RBAC (角色權限控制)**：
    * 所有的 MCP Tool 在註冊時必須宣告 `required_permissions` (例如：`finance:read`, `system:write`)。
    * 當使用者發起 Request 時，API Gateway 解析 JWT Token 獲取 User Role。
    * 當 Agent 決定呼叫工具時，Harness 底層的 **Tool Executor Node** 會先進行比對。若權限不足，系統不會執行工具，而是回傳 `PermissionDeniedError` 給 LLM，迫使 LLM 改變計畫或回報使用者。
* **Audit Logging (合規審計日誌)**：
    * 獨立於效能監控 (Tracing) 之外，所有觸及高敏感資料庫或執行寫入動作 (如寄信、刪除) 的行為，強制寫入不可篡改的 Elasticsearch 或關聯式資料庫中。
    * 紀錄欄位包含：`Timestamp`, `User_ID`, `Agent_ID`, `Tool_Name`, `Executed_Parameters`, `Approval_Status`。
* **Data Masking (資料脫敏)**：
    * 整合 Microsoft Presidio，在 Prompt 離開企業內網送往外部 LLM (如 Gemini) 前，自動將機密資訊替換為脫敏標籤。

### 3.2 Agent Harness & Orchestration (狀態機與編排模組)
* **持久化與斷點續傳 (Checkpointing)**：
    * 利用 PostgreSQL 作為 Checkpoint Saver。Agent 執行到一半若伺服器重啟，或是進入 Human-in-the-loop (HITL) 等待人類審批時，狀態 (State) 會被凍結並存入 DB。
* **Multi-Agent Orchestration (多代理協作)**：
    * 實作 **Supervisor Pattern**：一個高級 Planner Agent 負責拆解任務，並將 Sub-tasks 分發給專責的 Worker Agents。
* **Timeouts & Retry 策略**：
    * 在 Harness 層對所有外部 Tool Call 包裝 Circuit Breaker (斷路器) 與 Exponential Backoff (指數退避重試)，防止 Agent 因外部 API 塞車而無限卡死。

### 3.3 MCP 工具生態與隔離機制 (Tool Registry & Isolation)
* **動態工具發現 (Dynamic Discovery)**：
    * 支援 Model Context Protocol (MCP)。平台啟動時動態抓取各業務系統提供的 JSON-RPC Schema，轉換為 Agent 可理解的 Tools。
* **Multi-Tenancy 隔離 (多租戶架構)**：
    * 危險工具必須綁定 Sandbox 機制。不同部門 (Tenants) 的 Agent 只能讀寫掛載於自己 Workspace 下的檔案路徑，杜絕跨部門資料越權。

### 3.4 企業級 Guardrails 系統 (雙模型防禦網)
1. **Input Guardrail**：Lite 模型判斷 Prompt 是否包含惡意注入 (Prompt Injection) 或偏離業務主題 (Topic Jailbreak)。
2. **Action Guardrail**：Pydantic 進行工具參數強型別校驗；Lite 模型評估工具呼叫的邏輯合理性與破壞性。
3. **Output Guardrail**：Lite 模型進行 Groundedness Check (事實一致性檢驗)，確保回覆不含捏造數據或敏感系統路徑。

### 3.5 LLMOps、效能與評估 (Operations & Evals)
* **語意快取 (Semantic Caching)**：
    * 導入 RedisVL。高度相似的問題直接計算 Embedding 相似度，若達標則直接返回 Cache 答案，繞過 LLM 推理。
* **Prompt Management (提示詞版本控制)**：
    * 將 Prompt 抽離至 Langfuse 或資料庫管理，支援動態熱更新 (Hot Reload) 與 A/B 測試。
* **全鏈路可觀測性 (Tracing & Eval Pipeline)**：
    * 利用 Langfuse 記錄每一步 Graph Node 的 Token 消耗與延遲。
    * 建立 CI/CD Eval Pipeline：當更換模型版本時，自動執行 Golden Dataset 批次測試，防止系統靜默退化 (Silent Regression)。

---

## 4. 基礎設施與技術選型 (Tech Stack)

* **Orchestration & Framework**: `FastAPI`, `LangGraph`
* **LLM Inference**: `Gemini API` (Main), `Ollama` (Guardrails/Worker)
* **Tool Protocol**: `MCP (Model Context Protocol)` SDK
* **Data Validation & Auth**: `Pydantic v2`, `JWT`
* **State & Persistence**: `PostgreSQL`
* **Caching & Memory**: `Redis`
* **LLMOps**: `Langfuse`
* **Deployment**: `Docker Compose`

---

## 5. 核心 API 介面設計草案 (API Specifications)

* `POST /v1/chat/completions`：標準化對話入口。
* `POST /v1/agents/{agent_id}/runs`：觸發特定 Agent 執行長時間任務。
* `GET /v1/agents/runs/{run_id}/stream`：(SSE) 實時訂閱 Agent 執行進度與思考鏈。
* `POST /v1/approvals/{run_id}`：HITL 介面，供管理員送出審批決定。
* `GET /v1/tools`：動態回傳當前使用者有權限呼叫的 MCP Tools 列表。