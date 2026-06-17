import json
from mcp.server.fastmcp import FastMCP
from sqlalchemy.future import select

# 引入資料庫連線與模型
from src.db.session import AsyncSessionLocal
from src.db.models import User, Device, AuditLog, CMDBRelation
from src.core.config.settings import settings
from src.db.models import Incident
import uuid

# 初始化 FastMCP 伺服器
mcp = FastMCP("GlobalTech-ITOps-Tools", host="0.0.0.0", port=8001)

def format_success(data: dict) -> str:
    return json.dumps({"status": "success", "data": data}, ensure_ascii=False)

def format_error(message: str) -> str:
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)

# ==========================================
# 透過 MCP 協定暴露的 IAM 工具
# ==========================================
@mcp.tool()
async def check_account_status(email: str) -> str:
    """查詢特定員工的帳號狀態 (Active 或 Locked)。當帳號鎖定或無法登入時優先呼叫。"""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).filter_by(email=email))
            user = result.scalars().first()
            if not user:
                return format_error(f"找不到信箱為 '{email}' 的員工紀錄。")
            return format_success({"email": user.email, "name": user.full_name, "account_status": user.account_status})
        except Exception as e:
            return format_error(f"資料庫查詢異常: {str(e)}")

@mcp.tool()
async def unlock_account(email: str) -> str:
    """解鎖被鎖定的員工帳號。將狀態從 Locked 改為 Active。"""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).filter_by(email=email))
            user = result.scalars().first()
            if not user:
                return format_error(f"找不到信箱為 '{email}' 的員工。")
            if user.account_status == "Active":
                return format_error(f"員工 '{email}' 的帳號已經是 Active 狀態。")

            user.account_status = "Active"
            audit_log = AuditLog(
                tenant_id=user.tenant_id, user_id=user.id, agent_id=settings.AGENT_ID,
                action="Unlock Account", tool_name="unlock_account", parameters={"email": email}, status="Success"
            )
            session.add(audit_log)
            await session.commit()
            return format_success({"message": f"已成功解鎖 '{email}' 的帳號，目前狀態為 Active。"})
        except Exception as e:
            await session.rollback()
            return format_error(f"帳號解鎖失敗: {str(e)}")

# ==========================================
# 透過 MCP 協定暴露的 MDM & CMDB 工具
# ==========================================
@mcp.tool()
async def get_device_health(device_id: str) -> str:
    """查詢特定設備的健康狀態 (作業系統、合規狀態與剩餘硬碟空間)。"""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(Device).filter_by(device_id=device_id))
            device = result.scalars().first()
            if not device:
                return format_error(f"查無設備編號 '{device_id}'。")
            return format_success({"device_id": device.device_id, "os_version": device.os_version, "compliance_status": device.compliance_status, "disk_space_mb": device.disk_space_mb})
        except Exception as e:
            return format_error(f"資料庫查詢異常: {str(e)}")

@mcp.tool()
async def clear_system_cache(device_id: str) -> str:
    """遠端清除設備系統快取，釋放硬碟空間。當設備容量不足時呼交。"""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(Device).filter_by(device_id=device_id))
            device = result.scalars().first()
            if not device:
                return format_error(f"找不到設備 '{device_id}'。")

            freed_space = 51200 
            device.disk_space_mb += freed_space
            
            audit_log = AuditLog(
                tenant_id=device.tenant_id, user_id=device.owner_id, agent_id=settings.AGENT_ID,
                action="Clear System Cache", tool_name="clear_system_cache", parameters={"device_id": device_id, "freed_space_mb": freed_space}, status="Success"
            )
            session.add(audit_log)
            await session.commit()
            return format_success({"message": f"已成功為設備 '{device_id}' 清除快取。", "freed_space_mb": freed_space, "current_disk_space_mb": device.disk_space_mb})
        except Exception as e:
            await session.rollback()
            return format_error(f"清除快取失敗: {str(e)}")

# ==========================================
# 透過 MCP 協定暴露的通用工單查詢工具
# ==========================================
@mcp.tool()
async def get_ticket_details(ticket_id: str) -> str:
    """
    [通用工具] 查詢 ITSM 工單的詳細資訊與最新狀態。
    用途：當使用者詢問特定工單進度，或 Agent 需要確認工單是否已被主管核准時呼叫。
    """
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(Incident).filter_by(ticket_id=ticket_id))
            incident = result.scalars().first()
            
            if not incident:
                return format_error(f"找不到工單 '{ticket_id}'。")
                
            return format_success({
                "ticket_id": incident.ticket_id,
                "status": incident.status,
                "issue_description": incident.issue_description,
                "resolution_notes": incident.resolution_notes
            })
        except Exception as e:
            return format_error(f"查詢工單失敗: {str(e)}")

# ==========================================
# 透過 MCP 協定暴露的 ITSM 變更工具
# ==========================================
@mcp.tool()
async def create_ticket(email: str, issue_description: str) -> str:
    """
    [通用工具] 建立新的 ITSM 維運工單。
    參數說明：
    - email: 申請者的員工信箱 (Agent 請直接從 state 上下文中取得)
    - issue_description: 問題描述與申請事由
    """
    async with AsyncSessionLocal() as session:
        try:
            # 隨機產生一個擬真的工單編號
            ticket_id = f"INC-{str(uuid.uuid4())[:8].upper()}"
            
            # 🔍 【優化】直接用 email 去查出真實的 UUID 與 Tenant
            user = await session.execute(select(User).filter_by(email=email))
            user_obj = user.scalars().first()
            if not user_obj:
                return format_error(f"找不到信箱為 '{email}' 的員工，無法建立工單。")

            # 寫入資料庫時，我們依然使用正規的 UUID (user_obj.id)
            new_incident = Incident(
                ticket_id=ticket_id,
                tenant_id=user_obj.tenant_id,
                user_id=user_obj.id,  # 系統底層自動轉換！
                status="Open",
                issue_description=issue_description
            )
            session.add(new_incident)
            await session.commit()
            return format_success({"ticket_id": ticket_id, "status": "Open", "message": "工單已成功建立"})
        except Exception as e:
            await session.rollback()
            return format_error(f"建立工單失敗: {str(e)}")

@mcp.tool()
async def update_ticket_status(ticket_id: str, status: str, resolution_notes: str = "") -> str:
    """
    [通用工具] 更新工單狀態與備註。
    參數說明：
    - status: 支援 'Pending_Approval' (等待主管簽核), 'Resolved' (已解決), 'Closed' 等狀態。
    - resolution_notes: 處理紀錄或備註。
    注意：若涉及高風險軟體(Tier 4)或設備抹除，必須先將狀態改為 'Pending_Approval'。
    """
    async with AsyncSessionLocal() as session:
        try:
            incident = await session.execute(select(Incident).filter_by(ticket_id=ticket_id))
            inc_obj = incident.scalars().first()
            if not inc_obj:
                return format_error(f"找不到工單 {ticket_id}")

            inc_obj.status = status
            if resolution_notes:
                inc_obj.resolution_notes = resolution_notes
            
            await session.commit()
            return format_success({"ticket_id": ticket_id, "new_status": status, "message": "工單狀態已更新"})
        except Exception as e:
            await session.rollback()
            return format_error(f"更新工單失敗: {str(e)}")

@mcp.tool()
async def remote_wipe_device(device_id: str) -> str:
    """
    [極高風險工具] 遠端抹除設備資料 (恢復原廠設定)。
    警告：呼叫此工具前，相關工單必須已經處於核准狀態。
    """
    async with AsyncSessionLocal() as session:
        try:
            device = await session.execute(select(Device).filter_by(device_id=device_id))
            dev_obj = device.scalars().first()
            if not dev_obj:
                return format_error(f"找不到設備 {device_id}")

            # 模擬抹除：標記合規狀態並清空硬碟數據
            dev_obj.compliance_status = "Wiped"
            dev_obj.disk_space_mb = 0
            
            # 寫入重大審計日誌
            audit_log = AuditLog(
                tenant_id=dev_obj.tenant_id, user_id=dev_obj.owner_id, agent_id=settings.AGENT_ID,
                action="Remote Wipe Device", tool_name="remote_wipe_device", parameters={"device_id": device_id}, status="Success"
            )
            session.add(audit_log)
            await session.commit()
            return format_success({"device_id": device_id, "message": "已成功向設備發送遠端抹除指令。"})
        except Exception as e:
            await session.rollback()
            return format_error(f"設備抹除失敗: {str(e)}")

if __name__ == "__main__":
    # 使用 FastMCP 內建的 SSE 傳輸層啟動伺服器
    mcp.run(transport="sse")