"""
智能招聘平台 - 面向计算机行业的智能招聘平台
Version: 0.2.7.8
Developer: MLLR
Development Period: 2025.12 ~ 2026.04
License: Apache License 2.0

Description: 安全机制模块，负责登录尝试限制、IP速率限制、用户在线状态跟踪、密码强度验证等安全相关功能。
"""
from datetime import datetime, timedelta
from typing import Dict
from fastapi import HTTPException, Request
import re
import hashlib

# 登录失败记录 {username: {'count': int, 'last_attempt': datetime}}
login_attempts: Dict[str, Dict] = {}

# IP登录失败记录 {ip: {'count': int, 'last_attempt': datetime}}
ip_login_attempts: Dict[str, Dict] = {}

# 在线用户跟踪 {user_id: last_activity_time}
online_users: Dict[int, datetime] = {}

# 在线状态超时时间（5分钟无活动则认为离线）
ONLINE_TIMEOUT = timedelta(minutes=5)

# IP速率限制配置
IP_RATE_LIMIT_MAX = 10
IP_RATE_LIMIT_WINDOW = timedelta(minutes=1)


def update_user_activity(user_id: int) -> None:
    """更新用户活动时间"""
    online_users[user_id] = datetime.utcnow()


def is_user_online(user_id: int) -> bool:
    """检查用户是否在线（5分钟内有活动）"""
    if user_id not in online_users:
        # 如果用户不在在线列表中，默认认为离线
        return False

    last_activity = online_users[user_id]
    time_since_activity = datetime.utcnow() - last_activity
    return time_since_activity < ONLINE_TIMEOUT


def cleanup_offline_users() -> None:
    """清理离线用户（超过5分钟无活动）"""
    now = datetime.utcnow()
    offline_users = [
        user_id for user_id, last_activity in online_users.items()
        if now - last_activity >= ONLINE_TIMEOUT
    ]
    for user_id in offline_users:
        del online_users[user_id]


# 配置
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


def get_client_ip(request: Request) -> str:
    """获取客户端真实IP地址"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    return hashlib.md5(ip.encode()).hexdigest()[:16]


def check_ip_rate_limit(request: Request) -> None:
    """检查IP速率限制（每分钟最多10次登录尝试）"""
    ip = get_client_ip(request)

    if ip in ip_login_attempts:
        attempt = ip_login_attempts[ip]
        time_since_last = datetime.utcnow() - attempt['last_attempt']

        if time_since_last < IP_RATE_LIMIT_WINDOW:
            if attempt['count'] >= IP_RATE_LIMIT_MAX:
                remaining = IP_RATE_LIMIT_WINDOW - time_since_last
                seconds = int(remaining.total_seconds())
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁，请在{seconds}秒后重试"
                )
            else:
                attempt['count'] += 1
        else:
            ip_login_attempts[ip] = {'count': 1, 'last_attempt': datetime.utcnow()}
    else:
        ip_login_attempts[ip] = {'count': 1, 'last_attempt': datetime.utcnow()}


def record_ip_attempt(request: Request, success: bool) -> None:
    """记录IP登录尝试"""
    ip = get_client_ip(request)

    if success:
        if ip in ip_login_attempts:
            del ip_login_attempts[ip]
    else:
        if ip in ip_login_attempts:
            ip_login_attempts[ip]['count'] += 1
            ip_login_attempts[ip]['last_attempt'] = datetime.utcnow()
        else:
            ip_login_attempts[ip] = {'count': 1, 'last_attempt': datetime.utcnow()}


def check_login_attempts(username: str) -> None:
    """检查登录尝试次数，如果超过限制则抛出异常"""
    if username in login_attempts:
        attempt = login_attempts[username]

        # 检查是否在锁定期内
        if attempt['count'] >= MAX_LOGIN_ATTEMPTS:
            time_since_last = datetime.utcnow() - attempt['last_attempt']
            if time_since_last < LOCKOUT_DURATION:
                remaining = LOCKOUT_DURATION - time_since_last
                minutes = int(remaining.total_seconds() / 60)
                raise HTTPException(
                    status_code=429,
                    detail=f"登录尝试次数过多，请在{minutes}分钟后重试"
                )
            else:
                # 锁定期已过，重置计数
                login_attempts[username] = {
                    'count': 0, 'last_attempt': datetime.utcnow()}


def record_login_attempt(username: str, success: bool) -> None:
    """记录登录尝试"""
    if success:
        # 登录成功，清除记录
        if username in login_attempts:
            del login_attempts[username]
    else:
        # 登录失败，增加计数
        if username not in login_attempts:
            login_attempts[username] = {
                'count': 1, 'last_attempt': datetime.utcnow()}
        else:
            login_attempts[username]['count'] += 1
            login_attempts[username]['last_attempt'] = datetime.utcnow()


def validate_password_strength(password: str) -> None:
    """验证密码强度"""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码长度至少8个字符")

    if len(password) > 128:
        raise HTTPException(status_code=400, detail="密码长度不能超过128个字符")

    # 更严格的密码策略
    if not re.search(r'[A-Z]', password):
        raise HTTPException(status_code=400, detail="密码必须包含至少一个大写字母")
    if not re.search(r'[a-z]', password):
        raise HTTPException(status_code=400, detail="密码必须包含至少一个小写字母")
    if not re.search(r'[0-9]', password):
        raise HTTPException(status_code=400, detail="密码必须包含至少一个数字")
