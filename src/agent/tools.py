# src/agent/tools.py 僅為早期快速迭待開發期使用，目前已停用
# 此專案 AI Agent 使用的工具全部交由 mcp 管理

# import json
# from langchain_core.tools import tool
# from sqlalchemy.future import select

# from src.db.session import AsyncSessionLocal
# from src.db.models import User, Device, Incident, CMDBRelation, AuditLog
# from src.core.config.settings import settings

# # ==========================================
# # 工具通用輔助函數 (統一回傳結構，防禦性編程)
# # ==========================================
# def format_success(data: dict) -> str:
#     """統一成功回傳格式"""
#     return json.dumps({"status": "success", "data": data}, ensure_ascii=False)

# def format_error(message: str) -> str:
#     """統一錯誤回傳格式，引導 Agent 重新規劃"""
#     return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


# # ==========================================
# # IAM 領域工具 (身分與存取管理)
# # ==========================================
# @tool
# async def check_account_status(email: str) -> str:
#     """
#     查詢特定員工的帳號狀態 (Active 或 Locked)。
#     當使用者反映無法登入、VPN 失敗或帳號被鎖定時，必須先呼叫此工具查證。
#     """
#     async with AsyncSessionLocal() as session:
#         try:
#             result = await session.execute(select(User).filter_by(email=email))
#             user = result.scalars().first()
            
#             if not user:
#                 return format_error(f"IAM 系統中找不到信箱為 '{email}' 的員工紀錄。請向使用者確認信箱是否正確。")
                
#             return format_success({
#                 "email": user.email,
#                 "name": user.full_name,
#                 "account_status": user.account_status
#             })
#         except Exception as e:
#             return format_error(f"資料庫查詢發生異常: {str(e)}")


# @tool
# async def unlock_account(email: str) -> str:
#     """
#     解鎖被鎖定的員工帳號。將狀態從 Locked 改為 Active。
#     """
#     async with AsyncSessionLocal() as session:
#         try:
#             result = await session.execute(select(User).filter_by(email=email))
#             user = result.scalars().first()
            
#             if not user:
#                 return format_error(f"找不到信箱為 '{email}' 的員工。")
#             if user.account_status == "Active":
#                 return format_error(f"員工 '{email}' 的帳號已經是 Active 狀態，不需解鎖。")

#             # 變更狀態
#             user.account_status = "Active"
            
#             # 寫入防篡改審計日誌
#             audit_log = AuditLog(
#                 tenant_id=user.tenant_id,
#                 user_id=user.id,
#                 agent_id=settings.AGENT_ID,
#                 action="Unlock Account",
#                 tool_name="unlock_account",
#                 parameters={"email": email},
#                 status="Success"
#             )
#             session.add(audit_log)
#             await session.commit()
            
#             return format_success({"message": f"已成功解鎖 '{email}' 的帳號，目前狀態為 Active。"})
#         except Exception as e:
#             await session.rollback()
#             return format_error(f"帳號解鎖失敗: {str(e)}")


# # ==========================================
# # MDM 領域工具 (端點設備管理)
# # ==========================================
# @tool
# async def get_device_health(device_id: str) -> str:
#     """
#     查詢特定設備的健康狀態 (包含作業系統、合規狀態與剩餘硬碟空間)。
#     """
#     async with AsyncSessionLocal() as session:
#         try:
#             result = await session.execute(select(Device).filter_by(device_id=device_id))
#             device = result.scalars().first()
            
#             if not device:
#                 return format_error(f"MDM 系統中查無設備編號 '{device_id}'。")
                
#             return format_success({
#                 "device_id": device.device_id,
#                 "os_version": device.os_version,
#                 "compliance_status": device.compliance_status,
#                 "disk_space_mb": device.disk_space_mb
#             })
#         except Exception as e:
#             return format_error(f"資料庫查詢發生異常: {str(e)}")


# @tool
# async def clear_system_cache(device_id: str) -> str:
#     """
#     遠端清除設備系統快取，釋放硬碟空間 (預設釋放 50GB)。
#     當設備容量不足時可呼叫此工具修復。
#     """
#     async with AsyncSessionLocal() as session:
#         try:
#             result = await session.execute(select(Device).filter_by(device_id=device_id))
#             device = result.scalars().first()
            
#             if not device:
#                 return format_error(f"找不到設備 '{device_id}'。")

#             # 釋放 50GB (51200 MB)
#             freed_space = 51200 
#             device.disk_space_mb += freed_space
            
#             # 寫入審計日誌
#             audit_log = AuditLog(
#                 tenant_id=device.tenant_id,
#                 user_id=device.owner_id,
#                 agent_id=settings.AGENT_ID,
#                 action="Clear System Cache",
#                 tool_name="clear_system_cache",
#                 parameters={"device_id": device_id, "freed_space_mb": freed_space},
#                 status="Success"
#             )
#             session.add(audit_log)
#             await session.commit()
            
#             return format_success({
#                 "message": f"已成功為設備 '{device_id}' 清除快取。",
#                 "freed_space_mb": freed_space,
#                 "current_disk_space_mb": device.disk_space_mb
#             })
#         except Exception as e:
#             await session.rollback()
#             return format_error(f"清除快取失敗: {str(e)}")


# # ==========================================
# # CMDB 與 ITSM 領域工具 (組態與工單管理)
# # ==========================================
# @tool
# async def get_asset_dependencies(asset_id: str) -> str:
#     """
#     查詢特定伺服器或設備乘載的重要系統相依性。
#     在執行高風險操作前，必須先呼叫此工具確認影響範圍。
#     """
#     async with AsyncSessionLocal() as session:
#         try:
#             result = await session.execute(select(CMDBRelation).filter_by(asset_id=asset_id))
#             relations = result.scalars().all()
            
#             if not relations:
#                 return format_success({"asset_id": asset_id, "dependencies": [], "message": "該設備無其他相依系統，可安全操作。"})
                
#             deps = [r.dependency_id for r in relations]
#             return format_success({
#                 "asset_id": asset_id,
#                 "dependencies": deps,
#                 "message": f"警告：該設備乘載了 {len(deps)} 個相依系統，操作將影響服務運作。"
#             })
#         except Exception as e:
#             return format_error(f"CMDB 查詢異常: {str(e)}")


# # 將寫好的工具統整成 List 供 LangGraph 綁定
# IT_OPS_TOOLS = [
#     check_account_status,
#     unlock_account,
#     get_device_health,
#     clear_system_cache,
#     get_asset_dependencies
# ]