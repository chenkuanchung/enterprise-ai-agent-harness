import asyncio
from sqlalchemy.future import select
import bcrypt

from src.db.session import AsyncSessionLocal
from src.db.models import Tenant, User, Device, Incident, CMDBRelation

# 🔒 使用原生 bcrypt 進行加密
def get_password_hash(password: str) -> str:
    # bcrypt 嚴格要求輸入必須是 bytes (utf-8)，產生的 hash 也要解碼回字串存入 DB
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_bytes.decode('utf-8')

async def seed_data():
    print("開始注入 Demo 情境專用測試資料 (啟用 Bcrypt 密碼加密)...")
    
    async with AsyncSessionLocal() as session:
        # 查詢租戶是否存在
        result = await session.execute(select(Tenant).filter_by(name="GlobalTech 半導體 POC 環境"))
        tenant = result.scalars().first()
        
        if tenant:
            print("⚠️ 測試資料已存在，正在執行密碼加密升級作業...")
            users_result = await session.execute(select(User))
            for u in users_result.scalars():
                # 動態產生密碼：信箱的 @ 前綴 (例如 bob.lee)
                raw_password = u.email.split("@")[0]
                u.hashed_password = get_password_hash(raw_password)
            
            await session.commit()
            print("✅ 舊資料的密碼已全部升級為 Bcrypt 加密格式！")
            return

        # ==========================================
        # 以下為全新建立資料的流程
        # ==========================================
        tenant = Tenant(name="GlobalTech 半導體 POC 環境")
        session.add(tenant)
        
        # 建立組織架構，密碼皆動態加密
        it_director = User(tenant=tenant, email="alice.chen@globaltech.com", hashed_password=get_password_hash("alice.chen"), full_name="Alice Chen", role="admin", account_status="Active", department="IT 資訊處", title="處長")
        rd_manager = User(tenant=tenant, email="david.wu@globaltech.com", hashed_password=get_password_hash("david.wu"), full_name="David Wu", role="employee", account_status="Active", department="研發部", title="經理")
        qa_manager = User(tenant=tenant, email="sarah.lin@globaltech.com", hashed_password=get_password_hash("sarah.lin"), full_name="Sarah Lin", role="employee", account_status="Active", department="品保部", title="經理")
        
        bob_rd = User(tenant=tenant, email="bob.lee@globaltech.com", hashed_password=get_password_hash("bob.lee"), full_name="Bob Lee", role="employee", account_status="Active", department="研發部", title="韌體工程師", manager=rd_manager)
        charlie_qa = User(tenant=tenant, email="charlie.chang@globaltech.com", hashed_password=get_password_hash("charlie.chang"), full_name="Charlie Chang", role="employee", account_status="Locked", department="品保部", title="測試工程師", manager=qa_manager)
        
        session.add_all([it_director, rd_manager, qa_manager, bob_rd, charlie_qa])

        # (設備與工單資料與先前相同)
        bob_laptop = Device(tenant=tenant, device_id="NB-RD-BOB-01", owner=bob_rd, os_version="Windows 11", compliance_status="Compliant", disk_space_mb=150)
        bob_mobile = Device(tenant=tenant, device_id="MOB-RD-BOB-02", owner=bob_rd, os_version="Android 14", compliance_status="Compliant", disk_space_mb=51200)
        server_core = Device(tenant=tenant, device_id="SRV-PROD-01", owner=it_director, os_version="Ubuntu 22.04 LTS", compliance_status="Compliant", disk_space_mb=500000)
        
        session.add_all([bob_laptop, bob_mobile, server_core])

        incident_lockout = Incident(tenant=tenant, ticket_id="INC-2026-001", user=charlie_qa, status="Open", issue_description="User reported VPN login failed multiple times.")
        relation = CMDBRelation(tenant=tenant, asset_id="SRV-PROD-01", dependency_id="HR-Payroll-System", relation_type="Hosts")
        
        session.add_all([incident_lockout, relation])

        try:
            await session.commit()
            print("✅ 專為 Demo 設計的情境資料 (含加密密碼) 已成功寫入！")
        except Exception as e:
            await session.rollback()
            print(f"❌ 寫入發生錯誤：{str(e)}")

if __name__ == "__main__":
    asyncio.run(seed_data())