import json
from mcp.server.fastmcp import FastMCP
from sqlalchemy.future import select

# 引入資料庫連線與模型
from src.db.session import AsyncSessionLocal
from src.db.models import User, Device, AuditLog, CMDBRelation
from src.core.config.settings import settings

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

if __name__ == "__main__":
    # 使用 FastMCP 內建的 SSE 傳輸層啟動伺服器
    mcp.run(transport="sse")