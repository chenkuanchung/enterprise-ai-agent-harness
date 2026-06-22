import json
from mcp.server.fastmcp import FastMCP
from sqlalchemy.future import select

# 引入資料庫連線與模型
from src.db.session import AsyncSessionLocal
from src.db.models import User, Device, AuditLog, CMDBRelation, Incident, ChatThread, ApprovalStep
from src.core.config.settings import settings
import uuid
from enum import Enum
from typing import Optional
from sqlalchemy import asc

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
async def get_my_devices(email: str) -> str:
    """查詢該員工名下擁有哪些 IT 設備與編號。當使用者沒有提供設備編號時，優先呼叫此工具查詢。"""
    async with AsyncSessionLocal() as session:
        try:
            # 1. 先找出這位使用者的 ID
            user_res = await session.execute(select(User).filter_by(email=email))
            user = user_res.scalars().first()
            if not user:
                return format_error(f"找不到信箱為 '{email}' 的員工紀錄。")
            
            # 2. 找出他名下的所有設備
            devices_res = await session.execute(select(Device).filter_by(owner_id=user.id))
            devices = devices_res.scalars().all()
            
            if not devices:
                return format_success({"message": "您名下目前沒有登記任何 IT 設備。"})
                
            # 3. 整理設備清單回傳給 AI
            dev_list = [
                {"device_id": d.device_id, "os_version": d.os_version} 
                for d in devices
            ]
            return format_success({"devices": dev_list})
        except Exception as e:
            return format_error(f"查詢設備失敗: {str(e)}")

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
    - status: 必須是以下六種狀態之一：
        1. 'Open' (新開單 / 處理中)
        2. 'Pending_Approval' (等待主管與 IT 簽核)
        3. 'Resolved' (技術問題已解決，等待使用者確認)
        4. 'Closed' (完全結案)
        5. 'Cancelled' (需求取消或作廢)
        6. 'Reopened' (使用者反應問題未解決，退回重新處理)
    - resolution_notes: 處理紀錄或備註。
    注意：若涉及需授權之高風險操作或設備抹除，必須先將狀態改為 'Pending_Approval' 以觸發 BPM 流程。
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
            
            # === Phase 2: 自動建立主管通知 Thread ===
            if status == "Pending_Approval":
                # 1. 找出申請人與其直屬主管
                user_res = await session.execute(select(User).filter_by(id=inc_obj.user_id))
                applicant = user_res.scalars().first()
                
                if applicant and applicant.manager_id:
                    thread_title = f"[系統通知] 待簽核工單 {ticket_id}"
                    
                    # 2. 檢查是否已經建過這個通知，防止重複發送
                    existing_thread = await session.execute(
                        select(ChatThread).filter_by(user_id=applicant.manager_id, title=thread_title)
                    )
                    
                    if not existing_thread.scalars().first():
                        # 3. 建立新的對話房間給主管
                        new_thread = ChatThread(
                            thread_id=f"sys-notify-{ticket_id}",
                            tenant_id=inc_obj.tenant_id,
                            user_id=applicant.manager_id,
                            title=thread_title
                        )
                        session.add(new_thread)
            
            await session.commit()
            
            # 若為 Pending_Approval，回傳給 Agent 的訊息可以順便告訴它主管已收到通知
            msg = "工單狀態已更新。"
            if status == "Pending_Approval":
                msg += "已自動在後台建立系統通知發送給簽核主管。"
                
            return format_success({"ticket_id": ticket_id, "new_status": status, "message": msg})
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
        
# ==========================================
# 企業級 BPM 簽核引擎與工具 (BPM Engine)
# ==========================================

async def _calculate_chain(session, user: User, tier: int) -> list:
    """[企業實務版] 支援「越級簽核 / 彈性遞補」的雙軌簽核名單 (包含 Tier 4 最高層級)"""
    chain = []
    step = 1

    # ==========================================
    # 軌道一：User 端 (業務需求核准)
    # 邏輯：順著 manager_id 往上爬
    # ==========================================
    if tier >= 2:
        if user.manager_id:
            user_mgr = await session.execute(select(User).filter_by(id=user.manager_id))
            mgr = user_mgr.scalars().first()
            if mgr:
                chain.append({"step": step, "role_type": "User 端直屬/最高主管", "approver": mgr})
                step += 1
            else:
                raise Exception("無法生成簽核鏈：資料庫遺失您的主管資料。")
        else:
            # 申請人無主管 (本身已是最高層)
            chain.append({"step": step, "role_type": "User 端 (系統判定免簽/最高層)", "approver": user})
            step += 1

    # ==========================================
    # 軌道二：IT 端 (技術、資安與高階決行)
    # 邏輯：使用業務頭銜，支援找不到人時往上找，並嚴格去重
    # ==========================================
    
    # 定義職級尋找順序 (權限由小到大)
    async def find_it_approver(preferred_roles: list) -> User:
        for role in preferred_roles:
            res = await session.execute(select(User).filter_by(role=role))
            approver = res.scalars().first()
            if approver:
                return approver
        return None

    if tier >= 2:
        it_mgr = await find_it_approver(["it_manager", "it_director"])
        if it_mgr:
            chain.append({"step": step, "role_type": "IT 維運審查", "approver": it_mgr})
            step += 1
        else:
            raise Exception("系統異常：找不到任何 IT 經理或處長來執行 Tier 2 簽核。")

    if tier >= 3:
        it_director = await find_it_approver(["it_director", "vp_it", "cio"])
        if it_director:
            # 【去重邏輯】如果上一關代簽的主管與此關相同，免重複簽核
            last_approver = chain[-1]["approver"]
            if last_approver.id != it_director.id:
                chain.append({"step": step, "role_type": "IT 處長/高階資安審查", "approver": it_director})
                step += 1
        else:
            raise Exception("系統異常：找不到具備 IT 處長 (it_director) 級別以上之主管來執行 Tier 3 簽核。")

    # ==========================================
    # 軌道三：C-Level 企業高階決行 (Tier 4 專屬)
    # ==========================================
    if tier >= 4:
        # 1. 副總裁 (VP) 會簽
        vp = await find_it_approver(["vp", "vp_it", "cio"])
        if vp:
            last_approver = chain[-1]["approver"]
            if last_approver.id != vp.id:
                chain.append({"step": step, "role_type": "副總 (VP) 決策審查", "approver": vp})
                step += 1
        else:
            raise Exception("系統異常：Tier 4 極高風險專案必須由 副總(VP) 級別以上主管簽核，但系統查無此角色。")

        # 2. 總經理 (GM) 會簽
        gm = await find_it_approver(["gm", "ceo"])
        if gm:
            last_approver = chain[-1]["approver"]
            if last_approver.id != gm.id:
                chain.append({"step": step, "role_type": "總經理 (GM) 決策審查", "approver": gm})
                step += 1
        else:
            raise Exception("系統異常：Tier 4 極高風險專案必須由 總經理(GM) 簽核，但系統查無此角色。")

        # 3. 董事長 (Chairman) 最終決行
        chairman = await find_it_approver(["chairman"])
        if chairman:
            last_approver = chain[-1]["approver"]
            if last_approver.id != chairman.id:
                chain.append({"step": step, "role_type": "董事長 (Chairman) 最終決行", "approver": chairman})
                step += 1
        else:
            raise Exception("系統異常：Tier 4 極高風險專案必須由 董事長(Chairman) 最終決行，但系統查無此角色。")

    return chain

@mcp.tool()
async def evaluate_approval_chain(email: str, tier: int) -> str:
    """
    [預覽工具] 查詢該風險等級 (Tier) 需要的簽核鏈。開單前必呼叫。
    """
    if tier <= 1:
        return format_success({"message": "Tier 1 低風險，免簽核，可直接處理。"})
        
    async with AsyncSessionLocal() as session:
        try:
            user_res = await session.execute(select(User).filter_by(email=email))
            user = user_res.scalars().first()
            if not user:
                return format_error("找不到申請人。")
                
            chain = await _calculate_chain(session, user, tier)
            approver_names = " ➡️ ".join([f"{c['approver'].full_name}({c['role_type']})" for c in chain])
            
            return format_success({
                "message": f"此申請需經過 {len(chain)} 關簽核。流程為：{approver_names}。請詢問使用者是否確認送簽？"
            })
        except Exception as e:
            return format_error(f"查詢失敗: {str(e)}")

@mcp.tool()
async def submit_for_approval(ticket_id: str, email: str, tier: int) -> str:
    """
    [開單工具] 使用者確認後，將工單正式送入 BPM 簽核流程。
    """
    if tier <= 1:
        return format_error("Tier 1 無需送簽，請直接呼叫 update_ticket_status 結案。")

    async with AsyncSessionLocal() as session:
        try:
            # 1. 取得工單與使用者
            inc_res = await session.execute(select(Incident).filter_by(ticket_id=ticket_id))
            incident = inc_res.scalars().first()
            user_res = await session.execute(select(User).filter_by(email=email))
            user = user_res.scalars().first()
            
            if not incident or not user:
                return format_error("工單或使用者不存在。")

            # 2. 由後端程式碼「重新計算」簽核名單 (零信任，不接受 AI 傳入名單)
            chain = await _calculate_chain(session, user, tier)
            
            # 3. 寫入 ApprovalStep 資料表
            for c in chain:
                step = ApprovalStep(
                    tenant_id=incident.tenant_id,
                    incident_id=incident.id,
                    step_order=c["step"],
                    role_type=c["role_type"],
                    approver_id=c["approver"].id,
                    status="Pending" if c["step"] == 1 else "Waiting" # 第一關設為 Pending，其餘等待中
                )
                session.add(step)
            
            # 4. 更新工單狀態與建立第一關的系統通知
            incident.status = "Pending_Approval"
            
            first_approver = chain[0]["approver"]
            thread_title = f"[系統通知] 待簽核工單 {ticket_id}"
            new_thread = ChatThread(
                thread_id=f"sys-notify-{ticket_id}-{uuid.uuid4().hex[:6]}",
                tenant_id=incident.tenant_id,
                user_id=first_approver.id,
                title=thread_title
            )
            session.add(new_thread)
            
            await session.commit()
            return format_success({"message": f"工單已成功送簽。已自動通知第一關主管：{first_approver.full_name}。"})
            
        except Exception as e:
            await session.rollback()
            return format_error(f"送簽失敗: {str(e)}")

@mcp.tool()
async def get_approval_status(ticket_id: str) -> str:
    """[審批輔助工具] 查詢特定工單目前的詳細內容與「完整簽核進度與名單 (Approval Steps)」。用於主管審批前調閱上下文。"""
    async with AsyncSessionLocal() as session:
        try:
            # 1. 取得工單與申請人
            inc_res = await session.execute(select(Incident).filter_by(ticket_id=ticket_id))
            incident = inc_res.scalars().first()
            if not incident:
                return format_error("查無此工單。")

            user_res = await session.execute(select(User).filter_by(id=incident.user_id))
            applicant = user_res.scalars().first()
            applicant_name = applicant.full_name if applicant else "未知申請人"

            # 2. 取得簽核關卡
            steps_res = await session.execute(
                select(ApprovalStep)
                .filter_by(incident_id=incident.id)
                .order_by(asc(ApprovalStep.step_order))
            )
            steps = steps_res.scalars().all()

            if not steps:
                return format_success({
                    "ticket_id": ticket_id, "applicant": applicant_name, 
                    "description": incident.issue_description, "message": "此工單無簽核關卡設定。"
                })

            # 3. 整理簽核鏈
            chain = []
            for s in steps:
                approver_res = await session.execute(select(User).filter_by(id=s.approver_id))
                approver = approver_res.scalars().first()
                chain.append({
                    "step": s.step_order,
                    "role": s.role_type,
                    "approver": approver.full_name if approver else "未知",
                    "status": s.status,
                    "comments": s.comments or ""
                })

            return format_success({
                "ticket_id": ticket_id,
                "applicant": applicant_name,
                "description": incident.issue_description,
                "current_status": incident.status,
                "approval_chain": chain
            })
        except Exception as e:
            return format_error(f"查詢簽核狀態失敗: {str(e)}")

@mcp.tool()
async def process_approval(ticket_id: str, action: str, comments: str = "") -> str:
    """
    [審批工具] 處理簽核動作。
    action 支援: 'approve' (同意), 'reject_previous' (退回前一關), 'reject_applicant' (退回申請人)
    """
    async with AsyncSessionLocal() as session:
        try:
            inc_res = await session.execute(select(Incident).filter_by(ticket_id=ticket_id))
            incident = inc_res.scalars().first()
            if not incident:
                return format_error("找不到該工單。")

            # 找出目前卡住的「那一關」
            step_res = await session.execute(
                select(ApprovalStep)
                .filter_by(incident_id=incident.id, status="Pending")
                .order_by(asc(ApprovalStep.step_order))
                .with_for_update()
            )
            current_step = step_res.scalars().first()
            
            if not current_step:
                return format_error("此工單目前沒有等待您簽核的關卡。")

            if action == "approve":
                current_step.status = "Approved"
                current_step.comments = comments
                
                # 尋找下一關
                next_step_res = await session.execute(
                    select(ApprovalStep)
                    .filter_by(incident_id=incident.id, step_order=current_step.step_order + 1)
                )
                next_step = next_step_res.scalars().first()
                
                if next_step:
                    next_step.status = "Pending"
                    msg = "已核准。流程將進入下一關。"
                else:
                    incident.status = "Approved" # 全部簽完
                    msg = "已核准。此工單的所有簽核皆已完成，可開始執行維運操作。"

            # 退回前一關的邏輯
            elif action == "reject_previous":
                if current_step.step_order > 1:
                    # 找出前一關
                    prev_step_res = await session.execute(
                        select(ApprovalStep)
                        .filter_by(incident_id=incident.id, step_order=current_step.step_order - 1)
                    )
                    prev_step = prev_step_res.scalars().first()
                    
                    if prev_step:
                        # 將前一關狀態改回 Pending，目前這關改為 Waiting
                        prev_step.status = "Pending"
                        current_step.status = "Waiting"
                        current_step.comments = comments
                        msg = "已將工單退回給前一關主管重新審核。"
                    else:
                        return format_error("找不到前一關的紀錄，無法退回。")
                else:
                    return format_error("目前已經是第一關，無法再退回前一關。若要退件，請選擇 '退回申請人'。")

            elif action == "reject_applicant":
                current_step.status = "Rejected"
                current_step.comments = comments
                incident.status = "Open" # 退回原點
                msg = "已退回給申請人。"
                
            await session.commit()
            return format_success({"message": msg})
            
        except Exception as e:
            await session.rollback()
            return format_error(f"操作失敗: {str(e)}")

# ==========================================
# 企業級強型別定義
# ==========================================
class TicketStatus(str, Enum):
    OPEN = "Open"
    PENDING_APPROVAL = "Pending_Approval"
    RESOLVED = "Resolved"
    CLOSED = "Closed"
    CANCELLED = "Cancelled"
    REOPENED = "Reopened"

# ==========================================
# 透過 MCP 協定暴露的通用查詢工具
# ==========================================
@mcp.tool()
async def query_tickets(
    status: Optional[TicketStatus] = None,
    assignee_email: Optional[str] = None,
    limit: int = 10
) -> str:
    """
    [核心通用工具] 根據條件查詢 ITSM 工單清單。
    
    使用情境指引：
    1. 當主管詢問「我有待簽核的工單嗎？」：傳入 status="Pending_Approval"。若有指定主管信箱，可傳入 assignee_email。
    2. 當使用者詢問「我目前處理中的工單？」：傳入 status="Open" 與該使用者的 assignee_email。
    """
    async with AsyncSessionLocal() as session:
        try:
            # 建構動態查詢條件
            query = select(Incident)
            
            if status:
                query = query.filter_by(status=status.value)
                
            # 若未來 Incident 表加入 assignee_id，可在此處轉換 email 並加入 filter
            # if assignee_email:
            #     user_res = await session.execute(select(User).filter_by(email=assignee_email))
            #     user = user_res.scalars().first()
            #     if user:
            #         query = query.filter_by(assignee_id=user.id)
            
            query = query.limit(limit)
            result = await session.execute(query)
            tickets = result.scalars().all()
            
            if not tickets:
                return format_success({"message": "依據您的條件，目前查無任何工單。"})
            
            # 整理回傳格式
            ticket_list = [
                {
                    "ticket_id": t.ticket_id, 
                    "status": t.status,
                    "issue_description": t.issue_description, 
                    "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S")
                } 
                for t in tickets
            ]
            return format_success({"tickets": ticket_list, "count": len(ticket_list)})
            
        except Exception as e:
            return format_error(f"工單查詢異常: {str(e)}")

if __name__ == "__main__":
    # 使用 FastMCP 內建的 SSE 傳輸層啟動伺服器
    mcp.run(transport="sse")