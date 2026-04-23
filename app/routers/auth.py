from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import User, Candidate, HRProfile
from app.schemas import UserCreate, UserLogin, Token, UserResponse
from app.auth import verify_password, get_password_hash, create_access_token, get_current_user
from app.config import settings
from app.logger import log_user_register, log_user_login, log_admin_login, system_logger
from app.security import check_login_attempts, record_login_attempt, validate_password_strength, check_ip_rate_limit, record_ip_attempt

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """用户注册"""
    # 验证密码强度
    validate_password_strength(user_data.password)

    # 检查用户名是否已存在，filter添加过滤条件，查找用户名是否存在，并返回第一个匹配项
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 如果用户不存在则创建用户
    user = User(
        username=user_data.username,
        password_hash=get_password_hash(user_data.password),
        role=user_data.role
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 根据角色创建对应的profile
    if user_data.role == "candidate":
        candidate = Candidate(user_id=user.id)
        db.add(candidate)
    elif user_data.role == "hr":
        hr_profile = HRProfile(user_id=user.id)
        db.add(hr_profile)

    db.commit()

    # 记录注册日志
    log_user_register(str(user_data.username), str(user_data.role))

    return user


@router.post("/login", response_model=Token)
def login(
    response: Response,
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """用户登录（自动设置安全的HttpOnly Cookie）"""
    # 检查IP速率限制
    check_ip_rate_limit(request)

    # 检查登录尝试次数
    check_login_attempts(form_data.username)

    user = db.query(User).filter(User.username == form_data.username).first()

    if not user or not verify_password(form_data.password, user.password_hash):
        # 记录登录失败
        record_login_attempt(form_data.username, success=False)
        record_ip_attempt(request, success=False)
        log_user_login(form_data.username, "", success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 记录登录成功
    record_login_attempt(form_data.username, success=True)
    record_ip_attempt(request, success=True)

    # 创建访问令牌
    access_token_expires = timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    # 设置安全的HttpOnly Cookie
    # httponly=True: 防止JavaScript访问，降低XSS风险
    # secure=False: 本地开发环境，生产环境应设为True（需HTTPS）
    # samesite='lax': 防止CSRF攻击
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  # 生产环境改为 True
        samesite='lax',
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/"
    )

    # 记录登录成功日志
    log_user_login(user.username, user.role, success=True)

    # 如果是管理员，额外记录
    if user.role == "admin":
        log_admin_login(user.username)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role
        }
    }


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """用户登出（清除HttpOnly Cookie并加入黑名单）"""
    from app.session_manager import session_manager
    from app.auth import oauth2_scheme
    from jose import jwt
    from app.security import online_users

    # 从cookie中获取token
    token = request.cookies.get("access_token")

    if token:
        try:
            # 解析token获取过期时间
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[
                    settings.ALGORITHM])
            exp = payload.get("exp")
            expire_time = datetime.fromtimestamp(exp) if exp else None

            # 将token加入黑名单
            session_manager.add_to_blacklist(token, expire_time)
            system_logger.info(f"[Logout] Token已加入黑名单，过期时间: {expire_time}")
        except Exception as e:
            system_logger.error(f"[Logout] 解析token失败: {e}")

    # 从在线用户列表中移除
    if current_user and current_user.id in online_users:
        del online_users[current_user.id]
        system_logger.info(f"[Logout] 用户 {current_user.username} 已从在线列表移除")

    # 清除cookie
    response.delete_cookie(
        key="access_token",
        path="/"
    )

    return {"message": "已成功登出"}
