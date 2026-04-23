"""
智能招聘平台 - 面向计算机行业的智能招聘平台
Version: 0.2.7.8
Developer: MLLR
Development Period: 2025.12 ~ 2026.04
License: Apache License 2.0

Description: 数据库连接模块，负责创建数据库引擎、会话工厂、获取数据库会话等数据库连接管理功能。
"""

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

# 创建数据库引擎
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)

# 创建会话工厂
@event.listens_for(engine, "connect")
def set_time_zone(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("SET time_zone = '+08:00'")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基类
Base = declarative_base()

# 依赖项：获取数据库会话


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
