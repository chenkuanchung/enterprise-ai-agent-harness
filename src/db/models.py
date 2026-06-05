# src/db/models.py
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import uuid

# 建立所有 ORM 模型的基底類別
Base = declarative_base()

class Tenant(Base):
    """企業租戶 (多租戶隔離邊界)"""
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 關聯設定：一個租戶底下有多個使用者
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    """平台使用者 (RBAC 權限主體)"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    
    # RBAC 核心：角色標籤 (如 'admin', 'employee', 'guest')
    role = Column(String(50), nullable=False, default="employee")

    # 組織架構：部門與職稱
    department = Column(String(100), nullable=True)  # 例如：'工程部', '人資部'
    title = Column(String(100), nullable=True)       # 例如：'資深工程師', '部門經理'

    # 組織架構：直屬主管 (自我關聯的 Foreign Key)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # SQLAlchemy 關聯設定：建立上下屬關係
    manager = relationship("User", remote_side=[id], backref="subordinates")
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 關聯設定
    tenant = relationship("Tenant", back_populates="users")