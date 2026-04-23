"""
智能招聘平台 - 面向计算机行业的智能招聘平台
Version: 0.2.7.8
Developer: MLLR
Development Period: 2025.12 ~ 2026.04
License: Apache License 2.0

Description: 配置管理模块，负责应用配置、数据库连接配置、JWT配置、Ollama配置等核心参数管理。
"""

from pydantic_settings import BaseSettings
from typing import Optional
import os
import logging

# 日志级别配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # 默认INFO级别
DETAILED_LOGGING = os.getenv("DETAILED_LOGGING", "false").lower() == "true"


def get_log_level():
    """获取日志级别"""
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }
    return levels.get(LOG_LEVEL.upper(), logging.INFO)


def setup_logging():
    """配置全局日志"""
    log_format = "%(levelname)s: %(message)s"
    if DETAILED_LOGGING:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=get_log_level(),
        format=log_format,
        force=True
    )

    # 设置第三方库的日志级别（避免过多输出）
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return logging.getLogger(__name__)


class Settings(BaseSettings):
    # 数据库配置
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "root"
    DB_NAME: str = "interview_system"

    # JWT 配置
    SECRET_KEY: str = os.getenv("SECRET_KEY", "xR8mZq3KpL7wT9vBcE2NfJd5HsUoP1FgDi4YvXnAa0Zm")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Ollama 配置
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3.5:9b"

    # 模型调用参数
    OLLAMA_NO_THINK: bool = True  # 默认禁用模型思考过程（no_think模式）

    # 应用配置
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # CORS 配置（生产环境应限制具体域名）
    # 暂时注释，后续需要时再打开
    # CORS_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def DATABASE_URL(self) -> str:
        return f"mysql+mysqlconnector://{
            self.DB_USER}:{
            self.DB_PASSWORD}@{
            self.DB_HOST}:{
                self.DB_PORT}/{
                    self.DB_NAME}"

    # @property
    # def cors_origins_list(self) -> list:
    #     """解析CORSOrigins配置为列表"""
    #     return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    class Config:
        # .env 文件是可选的，不存在时使用上述默认值
        env_file = ".env"
        env_file_encoding = 'utf-8'
        case_sensitive = True
        # 找不到 .env 文件时不报错
        extra = 'ignore'


settings = Settings()
