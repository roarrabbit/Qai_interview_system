from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.database import get_db
from app.models import User, Candidate, HRProfile, Job, Application, Interview, InterviewReport, SystemConfig, Message
from app.schemas import UserListResponse, JobResponse, ApplicationResponse
from app.auth import get_current_admin, get_password_hash
from app.security import validate_password_strength
import requests

router = APIRouter(prefix="/api/admin", tags=["管理员"])

# ==================== 数据概览 ====================


@router.post("/dashboard-overview")
def get_dashboard_overview(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> Dict:
    """获取数据面板概览数据"""
    # 统计用户数
    total_users = db.query(User).count()
    total_candidates = db.query(User).filter(User.role == 'candidate').count()
    total_hrs = db.query(User).filter(User.role == 'hr').count()

    # 统计岗位数
    total_jobs = db.query(Job).count()
    active_jobs = db.query(Job).filter(Job.is_active).count()

    # 统计申请数
    total_applications = db.query(Application).count()
    pending_applications = db.query(Application).filter(
        Application.status == 'pending').count()

    # 统计面试数
    total_interviews = db.query(Interview).count()
    completed_interviews = db.query(Interview).filter(
        Interview.status == '已完成').count()

    # 统计消息数
    total_messages = db.query(Message).count()

    return {
        "total_users": total_users,
        "total_candidates": total_candidates,
        "total_hrs": total_hrs,
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "total_applications": total_applications,
        "pending_applications": pending_applications,
        "total_interviews": total_interviews,
        "completed_interviews": completed_interviews,
        "total_messages": total_messages
    }

# ==================== 系统配置管理 ====================


@router.post("/config")
def get_system_config(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> List[Dict]:
    """获取所有系统配置（使用POST请求提高安全性）"""
    configs = db.query(SystemConfig).all()
    return [
        {
            "id": c.id,
            "config_key": c.config_key,
            "config_value": c.config_value,
            "description": c.description,
            "updated_at": c.updated_at
        }
        for c in configs
    ]


@router.get("/log-level")
def get_current_log_level(
    current_user: User = Depends(get_current_admin)
) -> Dict:
    """获取当前日志级别"""
    from app.logger import get_log_level_name, LOG_LEVELS
    return {
        "current_level": get_log_level_name(),
        "available_levels": list(LOG_LEVELS.keys())
    }


@router.put("/config/{config_key}")
def update_system_config(
    config_key: str,
    config_data: dict,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """更新系统配置"""
    config_value = config_data.get('config_value')
    if config_value is None:
        raise HTTPException(status_code=400, detail="配置值不能为空")

    config = db.query(SystemConfig).filter(
        SystemConfig.config_key == config_key).first()
    
    old_value = config.config_value if config else ""
    
    if not config:
        config = SystemConfig(
            config_key=config_key,
            config_value=str(config_value))
        db.add(config)
    else:
        config.config_value = str(config_value)  # type: ignore

    db.commit()
    db.refresh(config)
    
    from app.logger import log_config_updated
    log_config_updated(config_key, old_value, str(config_value), current_user.username)
    
    if config_key in ['ollama_base_url', 'ollama_model', 'ollama_no_think', 'personal_interview_questions', 'job_interview_questions']:
        try:
            from app.ai_interview import ai_interviewer
            from app.ai_conversation import ai_conversation_interviewer
            ai_interviewer.reload_config()
            ai_conversation_interviewer.reload_config()
        except Exception as e:
            import logging
            logging.warning(f"重新加载AI配置失败: {str(e)}")
    
    if config_key == 'log_level':
        try:
            from app.logger import set_log_level
            set_log_level(str(config_value))
        except Exception as e:
            import logging
            logging.warning(f"设置日志级别失败: {str(e)}")
    
    return {"message": "配置已更新", "config": config}

# ==================== 用户信息管理 ====================


@router.put("/users/{user_id}")
def update_user_info(
    user_id: int,
    username: Optional[str] = None,
    role: Optional[str] = None,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """更新用户基本信息"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if username:
        # 检查用户名是否已存在
        existing = db.query(User).filter(
            User.username == username,
            User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")
        user.username = username  # type: ignore

    if role and role in ["candidate", "hr", "admin"]:
        user.role = role  # type: ignore

    db.commit()
    return {"message": "用户信息已更新"}


@router.get("/candidates/{candidate_id}")
def get_candidate_info(
    candidate_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取求职者详细信息"""
    candidate = db.query(Candidate).filter(
        Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="求职者不存在")

    return {
        "id": candidate.id,
        "user_id": candidate.user_id,
        "real_name": candidate.real_name,
        "gender": candidate.gender,
        "phone": candidate.phone,
        "email": candidate.email,
        "skills": candidate.skills,
        "target_job": candidate.target_job,
        "experience_summary": candidate.experience_summary,
        "job_status": candidate.job_status
    }


@router.put("/candidates/{candidate_id}")
def update_candidate_info(
    candidate_id: int,
    data: dict,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """更新求职者详细信息"""
    candidate = db.query(Candidate).filter(
        Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="求职者不存在")

    allowed_fields = [
        'real_name',
        'gender',
        'phone',
        'email',
        'skills',
        'target_job',
        'experience_summary',
        'job_status']
    for field in allowed_fields:
        if field in data:
            value = data[field]
            if field == 'skills' and value:
                value = value.replace('、', ',').replace('，', ',')
            setattr(candidate, field, value)

    db.commit()
    return {"message": "求职者信息已更新"}


@router.put("/hr-profiles/{hr_id}")
def update_hr_info(
    hr_id: int,
    data: dict,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """更新HR详细信息"""
    hr_profile = db.query(HRProfile).filter(HRProfile.id == hr_id).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="HR信息不存在")

    # 更新字段
    allowed_fields = ['real_name', 'company_name', 'company_size', 'phone', 'email']
    for field in allowed_fields:
        if field in data:
            setattr(hr_profile, field, data[field])

    db.commit()
    return {"message": "HR信息已更新"}


@router.put("/jobs/{job_id}")
def admin_update_job(
    job_id: int,
    data: dict,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理员更新岗位信息"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")

    # 更新字段
    allowed_fields = [
        'title',
        'description',
        'required_skills',
        'salary_range',
        'location',
        'industry',
        'is_active']
    for field in allowed_fields:
        if field in data:
            setattr(job, field, data[field])

    db.commit()
    return {"message": "岗位信息已更新"}


@router.delete("/hr-profiles/{hr_id}")
def admin_delete_hr(
    hr_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理员删除招聘者（同时删除用户账号）"""
    hr_profile = db.query(HRProfile).filter(HRProfile.id == hr_id).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="招聘者不存在")

    # 获取关联的用户账号
    user_id = hr_profile.user_id

    # 先删除HR profile记录（由于外键关联，会自动处理相关记录）
    db.delete(hr_profile)
    db.commit()

    # 再删除用户账号
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()

    return {"message": "招聘者及其账号已删除"}


@router.delete("/candidates/{candidate_id}")
def admin_delete_candidate(
    candidate_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理员删除求职者（同时删除用户账号）"""
    candidate = db.query(Candidate).filter(
        Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="求职者不存在")

    # 获取关联的用户账号
    user_id = candidate.user_id

    # 先删除candidate记录（由于外键关联，会自动处理相关记录）
    db.delete(candidate)
    db.commit()

    # 再删除用户账号
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()

    return {"message": "求职者及其账号已删除"}

# ==================== 数据统计 ====================


@router.get("/dashboard")
def get_dashboard_data(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> Dict:
    """获取管理员仪表盘数据"""

    # 用户统计
    total_users = db.query(User).count()
    candidate_count = db.query(User).filter(User.role == "candidate").count()
    hr_count = db.query(User).filter(User.role == "hr").count()

    # 岗位统计
    total_jobs = db.query(Job).count()
    active_jobs = db.query(Job).filter(Job.is_active).count()

    # 投递统计
    total_applications = db.query(Application).count()
    pending_applications = db.query(Application).filter(
        Application.status == "pending").count()

    # 面试统计
    total_interviews = db.query(Interview).count()
    completed_interviews = db.query(Interview).filter(
        Interview.status == "已完成").count()

    # 达成沟通次数（消息总数）
    total_messages = db.query(Message).count()

    # 最近7天新用户
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    new_users_7days = db.query(User).filter(
        User.created_at >= seven_days_ago).count()

    # 最近7天新岗位
    new_jobs_7days = db.query(Job).filter(
        Job.created_at >= seven_days_ago).count()

    return {
        "users": {
            "total": total_users,
            "candidates": candidate_count,
            "hrs": hr_count,
            "new_7days": new_users_7days
        },
        "jobs": {
            "total": total_jobs,
            "active": active_jobs,
            "inactive": total_jobs - active_jobs,
            "new_7days": new_jobs_7days
        },
        "applications": {
            "total": total_applications,
            "pending": pending_applications,
            "processed": total_applications - pending_applications
        },
        "messages": {
            "total": total_messages
        },
        "interviews": {
            "total": total_interviews,
            "completed": completed_interviews,
            "in_progress": total_interviews - completed_interviews
        }
    }


@router.get("/statistics/users-by-date")
def get_users_by_date(
    days: int = 30,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> Dict:
    """获取用户注册趋势（按日期）"""

    start_date = datetime.utcnow() - timedelta(days=days)

    # 按日期分组统计
    results = db.query(
        func.date(User.created_at).label('date'),
        func.count(User.id).label('count')
    ).filter(
        User.created_at >= start_date
    ).group_by(
        func.date(User.created_at)
    ).order_by('date').all()

    dates = []
    counts = []
    for result in results:
        dates.append(result.date.strftime('%Y-%m-%d'))
        counts.append(result.count)

    return {
        "dates": dates,
        "counts": counts
    }


@router.get("/statistics/applications-status")
def get_applications_status(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> Dict:
    """获取申请状态分布"""

    results = db.query(
        Application.status,
        func.count(Application.id).label('count')
    ).group_by(Application.status).all()

    status_map = {
        "pending": "待处理",
        "reviewed": "已查看",
        "interviewed": "已面试",
        "rejected": "已拒绝",
        "accepted": "已录用"
    }

    labels = []
    counts = []
    for result in results:
        labels.append(status_map.get(result.status, result.status))
        counts.append(result.count)

    return {
        "labels": labels,
        "counts": counts
    }


@router.get("/statistics/interview-grades")
def get_interview_grades(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> Dict:
    """获取面试评级分布"""

    results = db.query(
        InterviewReport.overall_grade,
        func.count(InterviewReport.id).label('count')
    ).group_by(InterviewReport.overall_grade).all()

    grades = ['A', 'B', 'C', 'D']
    grade_counts = {grade: 0 for grade in grades}

    for result in results:
        if result.overall_grade in grade_counts:
            grade_counts[result.overall_grade] = int(result.count)  # type: ignore

    return {
        "labels": grades,
        "counts": [grade_counts[g] for g in grades]
    }


@router.get("/statistics/top-skills")
def get_top_skills(
    limit: int = 10,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> Dict:
    """获取热门技能TOP10"""

    candidates = db.query(Candidate).filter(Candidate.skills.isnot(None)).all()

    skill_counts = {}
    for candidate in candidates:
        if candidate.skills is not None:
            skills = [s.strip().lower() for s in candidate.skills.split(',')]
            for skill in skills:
                if skill:
                    skill_counts[skill] = skill_counts.get(skill, 0) + 1

    # 排序并取前N个
    sorted_skills = sorted(
        skill_counts.items(),
        key=lambda x: x[1],
        reverse=True)[
        :limit]

    skills = [item[0] for item in sorted_skills]
    counts = [item[1] for item in sorted_skills]

    return {
        "skills": skills,
        "counts": counts
    }


@router.get("/statistics/jobs-by-location")
def get_jobs_by_location(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> Dict:
    """获取岗位地域分布"""

    results = db.query(
        Job.location,
        func.count(Job.id).label('count')
    ).filter(
        Job.location.isnot(None)
    ).group_by(Job.location).all()

    locations = []
    counts = []
    for result in results:
        if result.location:
            locations.append(result.location)
            counts.append(result.count)

    return {
        "locations": locations,
        "counts": counts
    }


@router.get("/recent-activities")
def get_recent_activities(
    limit: int = 20,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
) -> List[Dict]:
    """获取最近活动记录"""

    activities = []

    # 最近注册的用户
    recent_users = db.query(User).order_by(
        User.created_at.desc()).limit(5).all()
    for user in recent_users:
        activities.append({
            "type": "user_register",
            "description": f"新用户 {user.username} 注册（{user.role}）",
            "time": user.created_at
        })

    # 最近发布的岗位
    recent_jobs = db.query(Job).order_by(Job.created_at.desc()).limit(5).all()
    for job in recent_jobs:
        activities.append({
            "type": "job_created",
            "description": f"新岗位发布：{job.title}",
            "time": job.created_at
        })

    # 最近的投递
    recent_apps = db.query(Application).order_by(
        Application.created_at.desc()).limit(5).all()
    for app in recent_apps:
        activities.append({
            "type": "application",
            "description": f"求职者投递了岗位（ID: {app.job_id}）",
            "time": app.created_at
        })

    # 最近完成的面试
    recent_interviews = db.query(Interview).filter(
        Interview.status == "已完成"
    ).order_by(Interview.completed_at.desc()).limit(5).all()
    for interview in recent_interviews:
        activities.append({
            "type": "interview_completed",
            "description": f"面试完成：{interview.interview_type}",
            "time": interview.completed_at
        })

    # 按时间排序
    activities.sort(key=lambda x: x["time"], reverse=True)

    return activities[:limit]


@router.get("/users")
def get_all_users(
    skip: int = 0,
    limit: int = 50,
    role: Optional[str] = None,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取所有用户列表"""
    query = db.query(User)

    if role:
        query = query.filter(User.role == role)

    users = query.offset(skip).limit(limit).all()
    total = query.count()

    return {
        "users": [UserListResponse.model_validate(u) for u in users],
        "total": total
    }


@router.get("/hrs")
def get_all_hrs(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取所有招聘者列表"""
    hrs = db.query(HRProfile).offset(skip).limit(limit).all()
    total = db.query(HRProfile).count()

    # 关联用户信息
    result = []
    for hr in hrs:
        user = db.query(User).filter(User.id == hr.user_id).first()
        result.append({
            "id": hr.id,
            "user_id": hr.user_id,
            "company_name": hr.company_name,
            "industry": hr.industry,
            "contact_person": hr.contact_person,
            "contact_phone": hr.contact_phone,
            "contact_email": hr.contact_email,
            "user": {
                "username": user.username if user else "未知",
                "created_at": user.created_at if user else None
            }
        })

    return result


@router.get("/jobs")
def get_all_jobs(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取所有岗位列表"""
    jobs = db.query(Job).offset(skip).limit(limit).all()
    total = db.query(Job).count()

    return {
        "jobs": [JobResponse.model_validate(j) for j in jobs],
        "total": total
    }


@router.get("/applications")
def get_all_applications(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取所有申请列表"""
    applications = db.query(Application).offset(skip).limit(limit).all()
    total = db.query(Application).count()

    return {
        "applications": [ApplicationResponse.model_validate(a) for a in applications],
        "total": total
    }


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """删除用户（管理员）"""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    db.delete(user)
    db.commit()

    return {"message": "用户已删除"}


@router.post("/users/{user_id}/change-password")
def admin_change_user_password(
    user_id: int,
    new_password: str = Form(...),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理员修改用户密码"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 验证新密码强度
    validate_password_strength(new_password)

    # 更新密码
    user.password_hash = get_password_hash(new_password)  # type: ignore
    db.commit()

    return {"message": f"用户 {user.username} 的密码已修改"}


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """删除岗位（管理员）"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")

    db.delete(job)
    db.commit()

    return {"message": "岗位已删除"}

# ==================== 统计图表数据 ====================


@router.get("/statistics/users-trend")
def get_users_trend(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取用户注册趋势（最近30天）"""
    today = datetime.now().date()
    dates = []
    counts = []

    for i in range(29, -1, -1):
        date = today - timedelta(days=i)
        count = db.query(User).filter(
            func.date(User.created_at) == date
        ).count()
        dates.append(date.strftime('%m/%d'))
        counts.append(count)

    return {"dates": dates, "counts": counts}


@router.get("/statistics/grades-distribution")
def get_grades_distribution(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取AI面试评级分布"""
    # 数据库中存储的是A/B/C/D
    grade_mapping = {'A': '优秀', 'B': '良好', 'C': '一般', 'D': '较差'}
    grades_display = []
    counts = []

    for db_grade, display_grade in grade_mapping.items():
        count = db.query(InterviewReport).filter(
            InterviewReport.overall_grade == db_grade
        ).count()
        grades_display.append(display_grade)
        counts.append(count)

    return {"grades": grades_display, "counts": counts}


@router.get("/statistics/applications-distribution")
def get_applications_distribution(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取申请状态分布"""
    status_map = {
        '待处理': '待处理',
        '已查看': '已查看',
        '面试邀约': '已面试',
        '线下面试': '线下面试',
        '成功入职': '已通过',
        '已拒绝': '已拒绝'
    }

    statuses = []
    counts = []

    for status_key, status_label in status_map.items():
        count = db.query(Application).filter(
            Application.status == status_key
        ).count()
        statuses.append(status_label)
        counts.append(count)

    return {"statuses": statuses, "counts": counts}





@router.get("/online-users")
def get_online_users_count(
    current_user: User = Depends(get_current_admin)
):
    """获取当前在线用户数"""
    from app.security import online_users, cleanup_offline_users

    # 清理离线用户
    cleanup_offline_users()

    return {
        "count": len(online_users),
        "users": list(online_users.keys())
    }


@router.get("/logs")
def get_system_logs(
    current_user: User = Depends(get_current_admin)
):
    """获取系统日志（从system.log文件读取）"""
    import os
    from datetime import datetime
    
    logs = []
    log_file_path = "logs/system.log"
    
    try:
        # 检查日志文件是否存在
        if os.path.exists(log_file_path):
            # 读取日志文件
            with open(log_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 解析日志文件的每一行
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    # 解析日志格式：2026-01-21 12:34:56 - INFO - 操作内容
                    parts = line.split(' - ', 2)
                    if len(parts) == 3:
                        timestamp_str, level, message = parts
                        # 解析时间戳
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        
                        logs.append({
                            "level": level.lower(),
                            "message": message,
                            "created_at": timestamp
                        })
                except Exception as e:
                    # 解析失败的行跳过
                    pass
        else:
            # 日志文件不存在，返回提示信息
            logs.append({
                "level": "info",
                "message": "系统日志文件不存在",
                "created_at": datetime.utcnow()
            })
    except Exception as e:
        # 读取文件失败，返回错误信息
        logs.append({
            "level": "error",
            "message": f"读取日志文件失败：{str(e)}",
            "created_at": datetime.utcnow()
        })
    
    # 按时间排序，返回最新的20条日志
    logs.sort(key=lambda x: x["created_at"], reverse=True)
    
    return logs[:20]


@router.get("/system-health")
def get_system_health(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取系统健康状态（AI服务、数据库连接）"""
    health_status = {
        "ai_service": {"status": "offline", "message": ""},
        "database": {"status": "offline", "message": ""}
    }

    # 检查AI服务（Ollama）
    try:
        # 从系统配置中获取 Ollama URL，如果没有则使用默认值
        from app.config import settings
        ollama_url = getattr(
            settings,
            'OLLAMA_BASE_URL',
            'http://localhost:11434')

        response = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if response.status_code == 200:
            health_status["ai_service"] = {
                "status": "online", "message": "AI服务正常"}
        else:
            health_status["ai_service"] = {
                "status": "offline",
                "message": f"AI服务异常 (状态码: {
                    response.status_code})"}
    except Exception as e:
        health_status["ai_service"] = {
            "status": "offline",
            "message": f"无法连接AI服务: {
                str(e)}"}

    # 检查数据库连接
    try:
        db.execute(func.now())
        health_status["database"] = {"status": "online", "message": "数据库连接正常"}
    except Exception as e:
        health_status["database"] = {
            "status": "offline",
            "message": f"数据库连接失败: {
                str(e)}"}

    return health_status


@router.get("/uptime")
def get_uptime(current_user: User = Depends(get_current_admin)):
    """获取服务运行时间"""
    from main import app_start_time

    if app_start_time is None:
        return {"uptime": "未知", "start_time": None}

    uptime_delta = datetime.utcnow() - app_start_time

    days = uptime_delta.days
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # 格式化运行时间
    if days > 0:
        uptime_str = f"{days}天 {hours}小时 {minutes}分钟"
    elif hours > 0:
        uptime_str = f"{hours}小时 {minutes}分钟"
    elif minutes > 0:
        uptime_str = f"{minutes}分钟 {seconds}秒"
    else:
        uptime_str = f"{seconds}秒"

    return {
        "uptime": uptime_str,
        "start_time": app_start_time.isoformat(),
        "uptime_seconds": uptime_delta.total_seconds()
    }

