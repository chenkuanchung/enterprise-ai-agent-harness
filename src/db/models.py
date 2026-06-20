# src/db/models.py
import uuid
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

# 建立所有 ORM 模型的基底類別
Base = declarative_base()

# ==========================================
# 核心基礎設施 (Core Infrastructure)
# ==========================================

class Tenant(Base):
    """企業租戶 (多租戶隔離邊界)"""
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    
    # 統一時間戳記
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # 建立雙向關聯
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    """平台使用者 (RBAC 與身分主體)"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 優化：加上 index=True，大幅提升租戶內員工查詢與級聯刪除效能
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    
    # RBAC 核心：角色標籤
    role = Column(String(50), nullable=False, default="employee")

    # IAM 領域：帳號狀態
    account_status = Column(String(20), nullable=False, default="Active")  # Active / Locked

    # 組織架構：部門與職稱
    department = Column(String(100), nullable=True)
    title = Column(String(100), nullable=True)

    # 組織架構：直屬主管 (優化：加上 index=True，供 HITL 快速查找審批鏈)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # 關係宣告
    tenant = relationship("Tenant", back_populates="users")
    manager = relationship("User", remote_side=[id], backref="subordinates")


# ==========================================
# ITOps 維運領域 (IT Operations Domain)
# ==========================================

class Device(Base):
    """端點設備 (MDM 領域)"""
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), unique=True, index=True, nullable=False)  # 企業內部設備編號
    
    # 零信任優化：直接引入租戶邊界，確保跨表合規性
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # 優化：外鍵補上 index=True
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    os_version = Column(String(50), nullable=True)
    compliance_status = Column(String(50), default="Compliant")  # Compliant / Non-Compliant
    disk_space_mb = Column(Integer, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    owner = relationship("User", backref="devices")
    tenant = relationship("Tenant")


class Incident(Base):
    """維運工單 (ITSM 領域)"""
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(String(50), unique=True, index=True, nullable=False)  # 例如: INC-001
    
    # 零信任優化：資料落盤即具租戶標籤
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # 優化：外鍵補上 index=True
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    status = Column(String(50), nullable=False, default="Open")  # Open / Pending_Approval / Resolved / Closed
    issue_description = Column(Text, nullable=False)
    resolution_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", backref="incidents")
    tenant = relationship("Tenant")


class CMDBRelation(Base):
    """組態相依性 (CMDB 領域)"""
    __tablename__ = "cmdb_relations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # 零信任優化：組態關係也應納入租戶邊界，嚴防資訊跨租戶外洩
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    asset_id = Column(String(100), index=True, nullable=False)
    dependency_id = Column(String(100), index=True, nullable=False)
    relation_type = Column(String(50), nullable=False)  # 例如: Depends_On, Hosted_On
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    tenant = relationship("Tenant")


class AuditLog(Base):
    """不可篡改之審計日誌 (安全合規領域)"""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # 零信任優化：安全日誌第一時間綁定租戶，以利進行多租戶獨立審計與法規遵循
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # 優化：外鍵補上 index=True
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    agent_id = Column(String(100), nullable=True)
    action = Column(String(255), nullable=False)  # 例如: remote_wipe_device
    tool_name = Column(String(100), nullable=False)
    
    # 使用 JSONB 儲存變更參數，高度適應各類 MCP 工具的欄位
    parameters = Column(JSONB, nullable=True) 
    
    status = Column(String(50), nullable=False)  # Success / Failed / Pending_Approval
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tenant = relationship("Tenant")


class ChatThread(Base):
    """對話紀錄 (LLMOps 領域：支援歷史對話與主動通知)"""
    __tablename__ = "chat_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(String(100), unique=True, index=True, nullable=False)  # 對應 LangGraph 的 thread_id
    
    # 零信任優化：對話紀錄綁定租戶與員工
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    title = Column(String(255), nullable=False, default="新對話")
    is_active = Column(Boolean, default=True)  # 若使用者刪除對話，則設為 False
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", backref="chat_threads")
    tenant = relationship("Tenant")


class ApprovalStep(Base):
    """BPM 簽核關卡 (記錄每張工單在各層級的審批狀態)"""
    __tablename__ = "approval_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # 關卡順序與角色定義
    step_order = Column(Integer, nullable=False)  # 第幾關 (例如: 1, 2, 3)
    role_type = Column(String(50), nullable=False) # 關卡名稱 (例如: "User 直屬經理", "IT 處長")
    
    # 負責簽核的主管
    approver_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # 狀態: Pending(等待中), Approved(已核准), Rejected(已退回), Skipped(略過)
    status = Column(String(20), nullable=False, default="Pending")
    comments = Column(Text, nullable=True) # 核准備註或退簽理由
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # 建立關聯
    incident = relationship("Incident", backref="approval_steps")
    approver = relationship("User")
    tenant = relationship("Tenant")