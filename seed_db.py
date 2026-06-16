import asyncio
from sqlalchemy.future import select

from src.db.session import AsyncSessionLocal
from src.db.models import Tenant, User, Device, Incident, CMDBRelation

async def seed_data():
    print("開始注入 Demo 情境專用測試資料 (Scenario-Driven Seeding)...")
    
    async with AsyncSessionLocal() as session:
        # 【防呆機制】確認租戶是否存在
        result = await session.execute(select(Tenant).filter_by(name="GlobalTech 半導體 POC 環境"))
        if result.scalars().first():
            print("⚠️ 測試資料已存在，取消本次注入作業。")
            return

        # ==========================================
        # 1. 建立企業租戶
        # ==========================================
        tenant = Tenant(name="GlobalTech 半導體 POC 環境")
        session.add(tenant)
        
        # ==========================================
        # 2. 建立精簡且具備代表性的組織架構
        # ==========================================
        # 主管階層 (HITL 審批者)
        it_director = User(tenant=tenant, email="alice.chen@globaltech.com", hashed_password="mock", full_name="Alice Chen", role="admin", account_status="Active", department="IT 資訊處", title="處長")
        rd_manager = User(tenant=tenant, email="david.wu@globaltech.com", hashed_password="mock", full_name="David Wu", role="employee", account_status="Active", department="研發部", title="經理")
        qa_manager = User(tenant=tenant, email="sarah.lin@globaltech.com", hashed_password="mock", full_name="Sarah Lin", role="employee", account_status="Active", department="品保部", title="經理")
        
        # 員工階層 (故障情境主角)
        # 情境 A主角：需要清理快取，且刻意配發多台設備測試 Agent 釐清能力
        bob_rd = User(tenant=tenant, email="bob.lee@globaltech.com", hashed_password="mock", full_name="Bob Lee", role="employee", account_status="Active", department="研發部", title="韌體工程師", manager=rd_manager)
        
        # 情境 B主角：帳號被鎖定，需要 Agent 查證並解鎖
        charlie_qa = User(tenant=tenant, email="charlie.chang@globaltech.com", hashed_password="mock", full_name="Charlie Chang", role="employee", account_status="Locked", department="品保部", title="測試工程師", manager=qa_manager)
        
        session.add_all([it_director, rd_manager, qa_manager, bob_rd, charlie_qa])

        # ==========================================
        # 3. 建立設備資產 (刻意製造多設備情境)
        # ==========================================
        # Bob 的第一台設備：筆電 (容量不足 150MB)
        bob_laptop = Device(tenant=tenant, device_id="NB-RD-BOB-01", owner=bob_rd, os_version="Windows 11", compliance_status="Compliant", disk_space_mb=150)
        # Bob 的第二台設備：測試用手機 (容量充足 50GB)
        bob_mobile = Device(tenant=tenant, device_id="MOB-RD-BOB-02", owner=bob_rd, os_version="Android 14", compliance_status="Compliant", disk_space_mb=51200)
        
        # IT 管轄的核心伺服器 (Guardrails 阻擋抹除測試)
        server_core = Device(tenant=tenant, device_id="SRV-PROD-01", owner=it_director, os_version="Ubuntu 22.04 LTS", compliance_status="Compliant", disk_space_mb=500000)
        
        session.add_all([bob_laptop, bob_mobile, server_core])

        # ==========================================
        # 4. 建立 ITSM 工單與 CMDB 關聯
        # ==========================================
        incident_lockout = Incident(tenant=tenant, ticket_id="INC-2026-001", user=charlie_qa, status="Open", issue_description="User reported VPN login failed multiple times.")
        relation = CMDBRelation(tenant=tenant, asset_id="SRV-PROD-01", dependency_id="HR-Payroll-System", relation_type="Hosts")
        
        session.add_all([incident_lockout, relation])

        # ==========================================
        # 提交寫入
        # ==========================================
        try:
            await session.commit()
            print("✅ 專為 Demo 設計的情境資料已成功寫入！")
            print(f"👉 準備好的劇本靶子：\n 1. Bob Lee (多設備, 其中筆電容量不足)\n 2. Charlie Chang (帳號 Locked)\n 3. SRV-PROD-01 (乘載重要系統的伺服器)")
        except Exception as e:
            await session.rollback()
            print(f"❌ 寫入發生錯誤：{str(e)}")

if __name__ == "__main__":
    asyncio.run(seed_data())