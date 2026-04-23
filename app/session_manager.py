"""
会话管理模块
处理cookie超时、token黑名单和会话清理
"""
from datetime import datetime
from typing import Set, Optional
import threading
from app.logger import system_logger


class SessionManager:
    """单例会话管理器"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(SessionManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Token黑名单（已登出或过期的token）
        self._blacklist: Set[str] = set()
        # Token黑名单清理时间映射
        self._blacklist_cleanup: dict = {}
        # 最后清理时间
        self._last_cleanup = datetime.utcnow()
        self._initialized = True

    def add_to_blacklist(
            self,
            token: str,
            expire_time: Optional[datetime] = None):
        """
        将token添加到黑名单

        Args:
            token: JWT token
            expire_time: token的过期时间，到期后自动从黑名单移除
        """
        with self._lock:
            self._blacklist.add(token)
            if expire_time:
                self._blacklist_cleanup[token] = expire_time

    def is_blacklisted(self, token: str) -> bool:
        """检查token是否在黑名单中"""
        self._cleanup_expired_blacklist()
        return token in self._blacklist

    def _cleanup_expired_blacklist(self):
        """清理已过期的黑名单token（减少内存占用）"""
        now = datetime.utcnow()

        # 每5分钟清理一次
        if (now - self._last_cleanup).total_seconds() < 300:
            return

        with self._lock:
            expired_tokens = [
                token for token, expire_time in self._blacklist_cleanup.items()
                if expire_time and now > expire_time
            ]

            for token in expired_tokens:
                self._blacklist.discard(token)
                del self._blacklist_cleanup[token]

            self._last_cleanup = now

            if expired_tokens:
                system_logger.info(f"[SessionManager] 已清理 {len(expired_tokens)} 个过期token")

    def clear_all(self):
        """清空所有会话数据（程序重启时调用）"""
        with self._lock:
            cleared_count = len(self._blacklist)
            self._blacklist.clear()
            self._blacklist_cleanup.clear()
            self._last_cleanup = datetime.utcnow()
            # system_logger.info(f"[SessionManager] 已清空 {cleared_count} 个token")

    def get_stats(self) -> dict:
        """获取会话统计信息"""
        with self._lock:
            return {
                "blacklist_size": len(self._blacklist),
                "pending_cleanup": len(self._blacklist_cleanup),
                "last_cleanup": self._last_cleanup.isoformat()
            }


# 全局会话管理器实例
session_manager = SessionManager()
