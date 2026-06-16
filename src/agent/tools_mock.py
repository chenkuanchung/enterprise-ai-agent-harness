from langchain_core.tools import tool

# ==========================================
# 1. 知識庫與組態領域 (KB & CMDB)
# ==========================================

@tool
def query_sop(query: str) -> str:
    """
    模擬 RAG 知識庫檢索 (Mock_KB_Tool)。
    當使用者詢問 IT 維運標準作業程序 (SOP)、故障排除步驟、或公司規定時，呼叫此工具。
    """
    return f"[KB 檢索結果] 針對「{query}」的處置建議：請先驗證員工身分，查閱設備合規狀態。若為硬碟空間不足，請引導清理快取；若為帳號鎖定，請於確認身分後解鎖。"

@tool
def get_asset_dependencies(asset_id: str) -> str:
    """
    查詢組態相依性 (Mock_CMDB_Tool)。
    在執行重啟伺服器、遠端抹除等「具破壞性操作」前，【必須】呼叫此工具確認影響範圍。
    """
    if "server" in asset_id.lower():
        return f"[CMDB 警告] 資產 {asset_id} 託管了 HR-Payroll-System 與 Access-Control-System。影響範圍：高 (High)。"
    return f"[CMDB 資訊] 資產 {asset_id} 無重大關聯服務。影響範圍：低 (Low)。"

# ==========================================
# 2. 工單管理領域 (ITSM)
# ==========================================

@tool
def create_ticket(user_id: str, issue: str) -> str:
    """
    建立新工單 (Mock_ITSM_Tool)。
    當使用者初次回報問題，且目前對話記憶中沒有正在處理的工單 (ticket_id) 時呼叫。
    """
    # 實務上這裡會寫入 PostgreSQL 的 incidents 表
    mock_ticket_id = "INC-2026001"
    return f"[ITSM 系統] 已成功為使用者 {user_id} 建立工單，單號為 {mock_ticket_id}。問題描述：{issue}"

@tool
def resolve_ticket(ticket_id: str, notes: str) -> str:
    """
    解決並關閉工單 (Mock_ITSM_Tool)。
    當確認問題已排除，Agent 準備結案時呼叫，寫入修復紀錄。
    """
    return f"[ITSM 系統] 工單 {ticket_id} 狀態已更新為 Resolved。修復紀錄：{notes}"

@tool
def update_ticket_status(ticket_id: str, status: str, notes: str) -> str:
    """
    更新工單狀態與備註 (Mock_ITSM_Tool)。
    當遇到需要主管審批的高風險操作 (需轉為 Pending_Approval)，
    或需要等待使用者提供更多資訊時 (需轉為 Pending_User) 呼叫此工具。
    支援的狀態包含: Open, Pending_Approval, Pending_User, Resolved, Closed。
    """
    return f"[ITSM 系統] 工單 {ticket_id} 狀態已更新為 {status}。備註：{notes}"

@tool
def get_ticket_details(ticket_id: str) -> str:
    """
    查詢工單詳細資訊與當前狀態 (Mock_ITSM_Tool)。
    當使用者詢問特定工單的處理進度，或 Agent 需要接手處理之前的未結案工單時呼叫。
    """
    # 這裡模擬回傳一個正在等待簽核的工單狀態
    return f"[ITSM 系統] 工單 {ticket_id} 詳細資訊：\n- 狀態: Pending_Approval\n- 描述: 申請遠端抹除設備 MAC-001\n- 最新紀錄: 已發送簽核通知給直屬主管，等待核准中。"

# ==========================================
# 3. 身分與端點管理領域 (IAM & MDM)
# ==========================================

@tool
def check_account_status(email: str) -> str:
    """
    查詢員工帳號狀態 (Mock_IAM_Tool)。
    用於檢查帳號是否被鎖定 (Locked) 或正常 (Active)。
    """
    if "hacker" in email.lower():
        return f"[IAM 系統] 帳號 {email} 狀態為：Locked (連續登入失敗)。"
    return f"[IAM 系統] 帳號 {email} 狀態為：Active。"

@tool
def unlock_account(email: str) -> str:
    """
    解鎖員工帳號 (Mock_IAM_Tool)。
    注意：這是一個狀態變更操作，系統底層會自動產生 AuditLog。
    """
    return f"[IAM 系統] 帳號 {email} 已成功解鎖，狀態恢復為 Active。"

@tool
def get_device_health(device_id: str) -> str:
    """
    查詢設備健康度 (Mock_MDM_Tool)。
    用於獲取設備的合規狀態 (Compliance) 與硬碟剩餘空間。
    """
    return f"[MDM 系統] 設備 {device_id} 狀態：Compliant。剩餘硬碟空間：150 MB (極低)。"

@tool
def clear_system_cache(device_id: str) -> str:
    """
    清理設備系統快取 (Mock_MDM_Tool)。
    用於釋放硬碟空間。
    """
    return f"[MDM 系統] 已對設備 {device_id} 下達清理快取指令。目前剩餘硬碟空間：15 GB。"

@tool
def remote_wipe_device(device_id: str) -> str:
    """
    遠端抹除設備資料 (Mock_MDM_Tool)。
    【極高危險操作】：將設備恢復原廠設定。呼叫此工具前，必須確保已取得主管簽核。
    """
    return f"[MDM 系統] 已成功對設備 {device_id} 執行遠端抹除 (Wipe)。"

# 將所有工具打包成一個列表，方便後續綁定給 LLM
# 將所有工具打包成一個列表，方便後續綁定給 LLM
IT_OPS_TOOLS = [
    query_sop,
    get_asset_dependencies,
    create_ticket,
    resolve_ticket,
    update_ticket_status,
    get_ticket_details,
    check_account_status,
    unlock_account,
    get_device_health,
    clear_system_cache,
    remote_wipe_device
]