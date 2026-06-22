import asyncio
from sqlalchemy.future import select
from sqlalchemy import delete
import bcrypt

from src.db.session import AsyncSessionLocal
from src.db.models import Tenant, User, Device, Incident, CMDBRelation, ChatThread, ApprovalStep

# 🔒 使用原生 bcrypt 進行加密
def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_bytes.decode('utf-8')

async def seed_data():
    print("開始注入【企業級 BPM 完整組織架構】測試資料...")
    
    async with AsyncSessionLocal() as session:
        # ==========================================
        # 0. 清理舊資料 (確保組織樹不會發生衝突)
        # ==========================================
        print("🧹 正在清理舊有的測試資料，確保環境乾淨...")
        await session.execute(delete(ApprovalStep))
        await session.execute(delete(ChatThread))
        await session.execute(delete(CMDBRelation))
        await session.execute(delete(Incident))
        await session.execute(delete(Device))
        await session.execute(delete(User))
        await session.execute(delete(Tenant))
        await session.commit()

        # ==========================================
        # 1. 建立租戶
        # ==========================================
        tenant = Tenant(name="GlobalTech 半導體 POC 環境")
        session.add(tenant)
        await session.flush() # flush 以取得 tenant.id
        
        # ==========================================
        # 2. 建立完美對應 Tier 1 ~ Tier 4 的組織架構
        # ==========================================
        print("🏢 正在建立企業組織樹 (包含 C-Level 高管)...")
        
        # 【C-Level 企業高階管理層】 (負責 Tier 4 決行)
        chairman = User(tenant=tenant, email="henry.tsai@globaltech.com", hashed_password=get_password_hash("henry.tsai"), full_name="Henry Tsai", role="chairman", account_status="Active", department="董事會", title="董事長")
        gm = User(tenant=tenant, email="grace.ho@globaltech.com", hashed_password=get_password_hash("grace.ho"), full_name="Grace Ho", role="gm", account_status="Active", department="總經理室", title="總經理", manager=chairman)
        vp_rd = User(tenant=tenant, email="eve.wang@globaltech.com", hashed_password=get_password_hash("eve.wang"), full_name="Eve Wang", role="vp", account_status="Active", department="研發處", title="研發副總", manager=gm)
        
        # 【IT 維運管理層】 (負責 Tier 2, Tier 3 決行)
        # 注意：Alice 正式被正名為 it_director，不再使用不合規的 admin
        it_director = User(tenant=tenant, email="alice.chen@globaltech.com", hashed_password=get_password_hash("alice.chen"), full_name="Alice Chen", role="it_director", account_status="Active", department="IT 資訊處", title="IT 處長", manager=gm)
        it_manager = User(tenant=tenant, email="frank.liu@globaltech.com", hashed_password=get_password_hash("frank.liu"), full_name="Frank Liu", role="it_manager", account_status="Active", department="IT 資訊處", title="IT 經理", manager=it_director)
        
        # 【一般業務端】 (負責發起需求與直屬主管簽核)
        rd_manager = User(tenant=tenant, email="david.wu@globaltech.com", hashed_password=get_password_hash("david.wu"), full_name="David Wu", role="manager", account_status="Active", department="研發部", title="研發經理", manager=vp_rd)
        bob_rd = User(tenant=tenant, email="bob.lee@globaltech.com", hashed_password=get_password_hash("bob.lee"), full_name="Bob Lee", role="employee", account_status="Active", department="研發部", title="韌體工程師", manager=rd_manager)
        
        # 【異常帳號測試用】 (此人被鎖定)
        charlie_qa = User(tenant=tenant, email="charlie.chang@globaltech.com", hashed_password=get_password_hash("charlie.chang"), full_name="Charlie Chang", role="employee", account_status="Locked", department="品保部", title="測試工程師")

        # 批次寫入員工資料
        session.add_all([chairman, gm, vp_rd, it_director, it_manager, rd_manager, bob_rd, charlie_qa])
        await session.flush()

        # ==========================================
        # 3. 建立設備與維運事件 (CMDB)
        # ==========================================
        bob_laptop = Device(tenant=tenant, device_id="NB-RD-BOB-01", owner=bob_rd, os_version="Windows 11", compliance_status="Compliant", disk_space_mb=150)
        bob_mobile = Device(tenant=tenant, device_id="MOB-RD-BOB-02", owner=bob_rd, os_version="Android 14", compliance_status="Compliant", disk_space_mb=51200)
        server_core = Device(tenant=tenant, device_id="SRV-PROD-01", owner=it_director, os_version="Ubuntu 22.04 LTS", compliance_status="Compliant", disk_space_mb=500000)
        
        session.add_all([bob_laptop, bob_mobile, server_core])

        incident_lockout = Incident(tenant=tenant, ticket_id="INC-2026-001", user=charlie_qa, status="Open", issue_description="User reported VPN login failed multiple times.")
        relation = CMDBRelation(tenant=tenant, asset_id="SRV-PROD-01", dependency_id="HR-Payroll-System", relation_type="Hosts")
        
        session.add_all([incident_lockout, relation])

        # 提交所有變更
        try:
            await session.commit()
            print("✅ 完美對應 Tier 1~4 簽核流程的企業級情境資料已成功寫入！")
        except Exception as e:
            await session.rollback()
            print(f"❌ 寫入發生錯誤：{str(e)}")

if __name__ == "__main__":
    asyncio.run(seed_data())