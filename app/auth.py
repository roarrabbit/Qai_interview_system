"""
智能招聘平台 - 面向计算机行业的智能招聘平台
Version: 0.2.7.8
Developer: MLLR
Development Period: 2025.12 ~ 2026.04
License: Apache License 2.0

Description: 认证授权模块，负责用户注册、登录、密码哈希、Token创建、当前用户获取、角色验证等认证授权相关功能。
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import hashlib
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User

# 凭证异常定义
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="无效凭据，请重新登录",
    headers={"WWW-Authenticate": "Bearer"},
)

# OAuth2 密码流（可选）
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login", auto_error=False)

# 延迟导入session_manager以避免循环导入


def get_session_manager():
    from app.session_manager import session_manager
    return session_manager


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return get_password_hash(plain_password) == hashed_password


def get_password_hash(password: str) -> str:
    """生成密码哈希 - 使用SHA256"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def create_access_token(
        data: dict,
        expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM)
    return encoded_jwt


def get_current_user(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    header_token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """获取当前用户（优先从HttpOnly Cookie读取，fallback到Authorization header）
    未登录用户返回None，不抛出异常
    """
    # 优先从cookie读取token（HttpOnly），其次从Authorization header
    token = access_token or header_token

    if not token:
        return None

    # 检查token是否在黑名单中（已登出）
    session_mgr = get_session_manager()
    if session_mgr.is_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[
                settings.ALGORITHM])
        username: str = payload.get("sub")
        exp: int = payload.get("exp")

        if username is None:
            raise credentials_exception

        # 检查token是否过期
        if exp and datetime.utcnow().timestamp() > exp:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception

    # 实现基于活动时间的会话管理
    from app.security import update_user_activity, is_user_online, cleanup_offline_users
    
    # 先清理离线用户（定期执行）
    cleanup_offline_users()
    
    # 先更新用户活动时间，再检查在线状态
    # 这样新登录的用户不会被立即踢下线
    update_user_activity(user.id)
    
    # 检查用户是否在线（5分钟内有活动）
    # 这个检查主要是为了处理token还在有效期但用户长时间未活动的情况
    # 但新登录的用户已经更新了活动时间，所以不会被踢下线
    if not is_user_online(user.id):
        # 用户长时间不活动，将token加入黑名单并强制下线
        session_mgr.add_to_blacklist(token, datetime.fromtimestamp(exp) if exp else None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="长时间未活动，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_current_candidate(
        current_user: Optional[User] = Depends(get_current_user)) -> User:
    """获取当前求职者用户（管理员也可访问）"""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未登录：请先登录")
    if current_user.role not in ["candidate", "admin"]:
        raise HTTPException(status_code=403, detail="权限不足：仅限求职者访问")
    return current_user



def get_current_hr(current_user: Optional[User] = Depends(get_current_user)) -> User:
    """获取当前招聘者用户（管理员也可访问）"""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未登录：请先登录")
    if current_user.role not in ["hr", "admin"]:
        raise HTTPException(status_code=403, detail="权限不足：仅限招聘者访问")
    return current_user



def get_current_admin(current_user: Optional[User] = Depends(get_current_user)) -> User:
    """获取当前管理员用户"""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未登录：请先登录")
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="权限不足：仅限管理员访问")
    return current_user
