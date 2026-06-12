# src/db/models.py
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import uuid

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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    """平台使用者 (RBAC 與身分主體)"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    
    # RBAC 核心：角色標籤
    role = Column(String(50), nullable=False, default="employee")

    # IAM 領域：帳號狀態 (對應規格書要求)
    account_status = Column(String(20), nullable=False, default="Active") # Active / Locked

    # 組織架構：部門與職稱
    department = Column(String(100), nullable=True)
    title = Column(String(100), nullable=True)

    # 組織架構：直屬主管 (供 HITL 簽核使用)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    manager = relationship("User", remote_side=[id], backref="subordinates")
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    tenant = relationship("Tenant", back_populates="users")


# ==========================================
# ITOps 維運領域 (IT Operations Domain)
# ==========================================

class Device(Base):
    """端點設備 (MDM 領域)"""
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), unique=True, index=True, nullable=False) # 企業內部的設備編號
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    os_version = Column(String(50), nullable=True)
    compliance_status = Column(String(50), default="Compliant") # Compliant / Non-Compliant
    disk_space_mb = Column(Integer, nullable=True)
    
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 反向關聯：查出該使用者的所有設備
    owner = relationship("User", backref="devices")


class Incident(Base):
    """維運工單 (ITSM 領域)"""
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(String(50), unique=True, index=True, nullable=False) # 例如: INC-001
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    status = Column(String(50), nullable=False, default="Open") # 狀態: Open / Pending / Resolved / Closed
    issue_description = Column(Text, nullable=False)
    resolution_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 反向關聯：查出該使用者開過的所有工單
    user = relationship("User", backref="incidents")


class CMDBRelation(Base):
    """組態相依性 (CMDB 領域)"""
    __tablename__ = "cmdb_relations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(String(100), index=True, nullable=False)
    dependency_id = Column(String(100), index=True, nullable=False)
    relation_type = Column(String(50), nullable=False) # 例如: Depends_On, Hosted_On


class AuditLog(Base):
    """不可篡改之審計日誌 (安全合規領域)"""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    agent_id = Column(String(100), nullable=True)
    
    action = Column(String(255), nullable=False) # 例如: remote_wipe_device
    tool_name = Column(String(100), nullable=False)
    
    # 強烈建議企業級用法：使用 JSONB 儲存彈性的工具參數
    parameters = Column(JSONB, nullable=True) 
    
    status = Column(String(50), nullable=False) # Success / Failed / Pending_Approval
    created_at = Column(DateTime(timezone=True), server_default=func.now())