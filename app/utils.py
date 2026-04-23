"""工具函数模块 - 包含通用查询、格式化和翻译函数"""


def translate_role(role: str) -> str:
    """翻译角色名为中文"""
    role_map = {
        'candidate': '求职者',
        'hr': '招聘者',
        'admin': '管理员'
    }
    return role_map.get(role, role)


def translate_job_status(status: str) -> str:
    """翻译求职状态"""
    status_map = {
        '求职中': '求职中',
        '观望中': '观望中',
        '已有工作': '已有工作'
    }
    return status_map.get(status, status)


def translate_application_status(status: str) -> str:
    """翻译申请状态"""
    # 直接返回中文状态值，因为我们现在在数据库中直接存储中文
    return status


def translate_interview_status(status: str) -> str:
    """翻译面试状态"""
    # 直接返回中文状态值，因为我们现在在数据库中直接存储中文
    return status


def get_interview_by_id(db, interview_id, candidate_id=None, hr_id=None):
    """
    根据面试ID获取面试信息
    
    Args:
        db: 数据库会话
        interview_id: 面试ID
        candidate_id: 候选人ID（可选，用于权限验证）
        hr_id: HR ID（可选，用于权限验证）
    
    Returns:
        Interview对象
    """
    from app.models import Interview
    
    query = db.query(Interview)
    
    if candidate_id:
        query = query.filter(Interview.candidate_id == candidate_id)
    
    if hr_id:
        # 检查HR是否与该面试相关（通过岗位关联）
        query = query.join(Interview.job).filter(Interview.job.has(hr_id=hr_id))
    
    interview = query.filter(Interview.id == interview_id).first()
    return interview


def format_candidate_info(candidate):
    """
    格式化候选人完整信息
    
    Args:
        candidate: 候选人对象
    
    Returns:
        格式化后的候选人信息字典
    """
    return {
        "id": candidate.id,
        "user_id": candidate.user_id,
        "real_name": candidate.real_name,
        "gender": candidate.gender,
        "phone": candidate.phone,
        "email": candidate.email,
        "target_job": candidate.target_job,
        "skills": candidate.skills,
        "job_status": candidate.job_status
    }


def format_candidate_basic_info(candidate):
    """
    格式化候选人基本信息
    
    Args:
        candidate: 候选人对象
    
    Returns:
        格式化后的候选人基本信息字典
    """
    return {
        "id": candidate.id,
        "user_id": candidate.user_id,
        "real_name": candidate.real_name,
        "gender": candidate.gender,
        "phone": candidate.phone,
        "email": candidate.email
    }
