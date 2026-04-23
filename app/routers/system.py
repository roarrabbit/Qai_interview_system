from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict
import re
from app.database import get_db
from app.models import SystemConfig, Job, Candidate, Application, Interview

router = APIRouter(prefix="/api/system", tags=["系统"])

# 公开可访问的配置白名单（只返回非敏感信息）
PUBLIC_CONFIG_WHITELIST = [
    'site_name',
    'site_title',
    'homepage_announcement',
    'contact_email',
    'contact_phone',
    'service_hours',
    'business_email',
    'copyright',
    'icp_number',
    'platform_slogan',
    'platform_intro'
]


@router.post("/config")
def get_public_config(db: Session = Depends(get_db)) -> Dict:
    """获取公开的系统配置（仅返回白名单内的非敏感配置）"""
    configs = db.query(SystemConfig).filter(
        SystemConfig.config_key.in_(PUBLIC_CONFIG_WHITELIST)
    ).all()

    config_dict = {}
    for config in configs:
        config_dict[config.config_key] = config.config_value

    return config_dict


@router.get("/config/{config_key}")
def get_config_by_key(config_key: str, db: Session = Depends(get_db)) -> Dict:
    """获取指定配置项（仅限白名单内的配置）"""
    # 防止XSS：验证config_key格式（只允许字母、数字、下划线）
    if not re.match(r'^[a-zA-Z0-9_]+$', config_key):
        raise HTTPException(
            status_code=400,
            detail="Invalid config key format")

    # 只允许访问白名单内的配置
    if config_key not in PUBLIC_CONFIG_WHITELIST:
        raise HTTPException(status_code=403,
                            detail="Access to this config is not allowed")

    config = db.query(SystemConfig).filter(
        SystemConfig.config_key == config_key).first()

    if config:
        return {
            "config_key": config.config_key,
            "config_value": config.config_value
        }

    return {"config_key": config_key, "config_value": None}


@router.post("/stats")
def get_public_stats(db: Session = Depends(get_db)) -> Dict:
    """获取公开统计数据（首页展示，使用POST请求提高安全性）"""
    total_jobs = db.query(
        func.count(
            Job.id)).filter(
        Job.is_active).scalar() or 0
    total_candidates = db.query(func.count(Candidate.id)).scalar() or 0
    total_applications = db.query(func.count(Application.id)).scalar() or 0
    total_interviews = db.query(func.count(Interview.id)).scalar() or 0

    return {
        "total_jobs": total_jobs,
        "total_candidates": total_candidates,
        "total_applications": total_applications,
        "total_interviews": total_interviews
    }
