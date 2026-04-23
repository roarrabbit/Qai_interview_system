from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import json
from app.database import get_db
from app.models import Application, Job, User, Candidate, HRProfile, Message, get_local_time
from app.schemas import ApplicationCreate, ApplicationResponse
from app.auth import get_current_user, get_current_candidate
from app.recommendation import recommendation_engine
from app.logger import system_logger

router = APIRouter(prefix="/api/applications", tags=["申请"])


@router.post("/hr")
def get_hr_applications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取HR收到的申请列表（包含完整的候选人和职位信息）- 使用POST提高安全性"""
    if current_user.role not in ["hr", "admin"]:
        raise HTTPException(status_code=403, detail="仅HR或管理员可访问")

    # 检查当前用户角色是否为admin
    is_admin = str(current_user.role) == "admin"
    if is_admin:
        # 管理员可以访问所有申请
        applications = db.query(Application).order_by(Application.created_at.desc()).all()
    else:
        # HR只能访问自己发布的岗位的申请
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()
        if not hr_profile:
            raise HTTPException(status_code=404, detail="HR信息不存在")

        # 获取HR发布的所有岗位的ID
        job_ids = db.query(Job.id).filter(Job.hr_id == hr_profile.id).all()
        job_ids = [job_id[0] for job_id in job_ids]

        # 获取这些岗位收到的申请
        applications = db.query(Application).filter(
            Application.job_id.in_(job_ids)
        ).order_by(Application.created_at.desc()).all()

    # 组装返回数据，包含完整的候选人和职位信息
    from app.models import Interview, InterviewReport

    result = []
    for app in applications:
        candidate = db.query(Candidate).filter(
            Candidate.id == app.candidate_id).first()
        candidate_user = db.query(User).filter(
            User.id == candidate.user_id).first() if candidate else None
        job = db.query(Job).filter(Job.id == app.job_id).first()

        # 获取面试评分（如果存在）
        interview_grade = None
        # 1. 首先尝试获取与该申请直接关联的面试
        interview = db.query(Interview).filter(
            Interview.application_id == app.id,
            Interview.status == "已完成"
        ).first()
        
        # 2. 如果没有关联面试，尝试获取该候选人的最新完成的面试
        if not interview:
            interview = db.query(Interview).filter(
                Interview.candidate_id == app.candidate_id,
                Interview.status == "已完成"
            ).order_by(Interview.completed_at.desc()).first()
        
        if interview:
            report = db.query(InterviewReport).filter(
                InterviewReport.interview_id == interview.id
            ).first()
            if report:
                interview_grade = report.overall_grade

        # 重新计算匹配度，确保与智能推荐一致
        try:
            candidate_keywords = recommendation_engine._get_candidate_keywords(candidate)
            job_keywords = recommendation_engine._get_job_keywords(job)
            match_similarity = recommendation_engine._calculate_keyword_match(candidate_keywords, job_keywords)
            match_percentage = recommendation_engine.calculate_match_percentage(match_similarity)
        except Exception as e:
            # 如果计算失败，使用存储的匹配度
            raw_score = app.match_score or 0
            # 确保raw_score是Python原生类型
            raw_score_value = float(raw_score)  # type: ignore
            match_percentage = int(raw_score_value) if isinstance(raw_score_value, int) or raw_score_value > 1 else int(raw_score_value * 100)

        # 转换旧的英文状态值为中文
        status_map = {
            'pending': '待处理',
            'reviewed': '已查看',
            'interview_invited': '面试邀约',
            'face_to_face': '线下面试',
            'successfully_joined': '成功入职',
            'rejected': '已拒绝'
        }
        current_status = str(app.status)
        if current_status in status_map:
            current_status = status_map[current_status]
        
        result.append({
            "id": app.id,
            "job_id": app.job_id,
            "candidate_id": app.candidate_id,
            "status": current_status,
            "match_score": match_percentage,  # 匹配度百分比
            "interview_grade": interview_grade,  # AI面试评分（A/B/C/D 或 None）
            "offer_sent": app.offer_sent,  # 是否已发送入职邀请
            "created_at": app.created_at.isoformat(),
            "candidate": {
                "id": candidate.id,
                "user_id": candidate.user_id,
                "real_name": candidate.real_name,
                "gender": candidate.gender,
                "phone": candidate.phone,
                "email": candidate.email,
                "target_job": candidate.target_job,
                "skills": candidate.skills,
                "job_status": candidate.job_status
            } if candidate else None,
            "job": {
                    "id": job.id,
                    "title": job.title,
                    "location": job.location,
                    "salary_range": job.salary_range
                } if job else None
        })

    return result


@router.get("/", response_model=List[ApplicationResponse])
def get_my_applications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户的申请列表"""
    if str(current_user.role) == "candidate":
        # 候选人只能查看自己的申请
        candidate = db.query(Candidate).filter(
            Candidate.user_id == current_user.id).first()
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人信息不存在")

        applications = db.query(Application).filter(
            Application.candidate_id == candidate.id
        ).order_by(Application.created_at.desc()).all()
        return applications
    else:
        # 管理员和HR不应该使用这个端点获取申请
        # 管理员应该使用 /api/admin/applications 端点
        # HR应该使用 /api/applications/hr 端点
        return []


@router.post("/", response_model=ApplicationResponse)
def create_application(
    app_data: ApplicationCreate,
    current_user: User = Depends(get_current_candidate),
    db: Session = Depends(get_db)
):
    """投递简历"""
    # 获取候选人信息
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    # 检查岗位是否存在
    job = db.query(Job).filter(
        Job.id == app_data.job_id,
        Job.is_active).first()
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在或已关闭")

    # 检查是否已投递
    existing = db.query(Application).filter(
        Application.job_id == app_data.job_id,
        Application.candidate_id == candidate.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="已投递过该岗位")

    # 计算匹配度
    candidate_keywords = recommendation_engine._get_candidate_keywords(
        candidate)
    job_keywords = recommendation_engine._get_job_keywords(job)
    match_similarity = recommendation_engine._calculate_keyword_match(
        candidate_keywords, job_keywords)

    # 创建申请
    application = Application(
        job_id=app_data.job_id,
        candidate_id=candidate.id,
        match_score=match_similarity  # 保存匹配度分数
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    # 记录申请提交日志
    from app.logger import log_application_submitted
    candidate_name = candidate.real_name or current_user.username
    job_title = job.title
    log_application_submitted(candidate_name, job_title)

    # 功能1：自动发送通知消息给HR（仅HR可见，求职者看不到）
    try:
        # 获取HR信息
        hr_profile = db.query(HRProfile).filter(
            HRProfile.id == job.hr_id).first()
        if hr_profile:
            # 构建通知消息内容
            candidate_name = candidate.real_name or current_user.username
            message_content = f"""【新申请通知】<br><br>

求职者 {candidate_name} 投递了简历到岗位：{job.title}<br>

• 基本信息：<br>
• 姓名：{candidate.real_name or '未填写'}<br>
• 联系方式：{candidate.phone or '未填写'} / {candidate.email or '未填写'}<br>
• 学历：{candidate.education if hasattr(candidate, 'education') else '未填写'} - {candidate.major if hasattr(candidate, 'major') else '未填写'}<br>
• 工作经验：{candidate.work_experience if hasattr(candidate, 'work_experience') else '未填写'}<br>

• 技能与意向：<br>
• 技能：{candidate.skills or '未填写'}<br>
• 求职意向：{candidate.target_job or '未填写'}<br>
• 期望薪资：{candidate.expected_salary if hasattr(candidate, 'expected_salary') else '未填写'}<br>
"""

            # 创建消息记录（保持聊天界面逻辑，但标记为系统通知）
            message = Message(
                sender_id=current_user.id,  # 发送者是求职者（保持聊天界面逻辑）
                receiver_id=hr_profile.user_id,  # 接收者是HR
                content=message_content,
                is_read=False,
                job_id=job.id,
                extra_data=json.dumps({
                    "type": "application_notification",
                    "is_system_notification": True,  # 标记为系统通知，求职者看不到
                    "application_id": application.id,
                    "candidate_id": candidate.id,
                    "candidate_snapshot": {
                        "real_name": candidate.real_name,
                        "phone": candidate.phone,
                        "email": candidate.email,
                        "skills": candidate.skills,
                        "target_job": candidate.target_job,
                        "job_status": candidate.job_status
                    }
                }, ensure_ascii=False)
            )
            db.add(message)
            db.commit()
    except Exception as e:
        # 发送消息失败不影响主流程
        system_logger.error(f"发送通知消息失败: {str(e)}")

    return application


@router.get("/{application_id}")
def get_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取申请详情"""
    from app.models import Interview, InterviewReport

    application = db.query(Application).filter(
        Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")

    # 权限检查：申请人、岗位发布者或管理员可查看
    if str(current_user.role) != "admin":
        job = db.query(Job).filter(Job.id == application.job_id).first()
        candidate = db.query(Candidate).filter(
            Candidate.user_id == current_user.id).first()
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()

        is_applicant = False
        if candidate:
            is_applicant = bool(int(application.candidate_id) == int(candidate.id))  # type: ignore
        
        is_hr = False
        if hr_profile and job:
            is_hr = bool(int(job.hr_id) == int(hr_profile.id))  # type: ignore

        if not (is_applicant or is_hr):
            raise HTTPException(status_code=403, detail="无权限查看")

    # 获取面试评分（如果存在）
    interview_grade = None
    # 1. 首先尝试获取与该申请直接关联的面试
    interview = db.query(Interview).filter(
        Interview.application_id == application.id,
        Interview.status == "已完成"   
    ).first()
    
    # 2. 如果没有关联面试，尝试获取该候选人的最新完成的面试
    if not interview:
        interview = db.query(Interview).filter(
            Interview.candidate_id == application.candidate_id,
            Interview.status == "已完成"   
        ).order_by(Interview.completed_at.desc()).first()
    
    if interview:
        report = db.query(InterviewReport).filter(
            InterviewReport.interview_id == interview.id
        ).first()
        if report:
            interview_grade = report.overall_grade

    # 计算匹配度百分比（兼容旧数据：如果>1说明是整数格式，直接使用；否则是0-1小数格式，需要乘100）
    raw_score = application.match_score or 0
    # 确保raw_score是Python原生类型
    raw_score_value = float(raw_score)  # type: ignore
    match_percentage = int(
        raw_score_value) if isinstance(raw_score_value, int) or raw_score_value > 1 else int(raw_score_value * 100)

    return {
        "id": application.id,
        "job_id": application.job_id,
        "candidate_id": application.candidate_id,
        "status": application.status,
        "match_score": match_percentage,
        "interview_grade": interview_grade,
        "interview_location": application.interview_location,
        "interview_time": application.interview_time.isoformat() if isinstance(application.interview_time, datetime) else None,
        "interviewer_info": application.interviewer_info,
        "interview_notes": application.interview_notes,
        "created_at": application.created_at.isoformat(),
        "updated_at": application.updated_at.isoformat()
    }


@router.put("/{application_id}/status")
def update_application_status(
    application_id: int,
    status_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新申请状态（仅HR）"""

    application = db.query(Application).filter(
        Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")

    # 检查权限
    if str(current_user.role) != "admin":
        # 非管理员只能修改自己发布的岗位的申请
        job = db.query(Job).filter(Job.id == application.job_id).first()
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()

        if not hr_profile:
            raise HTTPException(status_code=403, detail="无权限")
        if not job:
            raise HTTPException(status_code=404, detail="岗位不存在")
        if int(job.hr_id) != int(hr_profile.id):  # type: ignore
            raise HTTPException(status_code=403, detail="无权限")

    status = status_data.get('status')
    if not status:
        raise HTTPException(status_code=400, detail="状态参数缺失")

    old_status = application.status
    
    # 状态流转规则检查
    valid_transitions = {
        "待处理": ["已查看", "已拒绝", "面试邀约"],
        "已查看": ["已拒绝", "面试邀约"],
        "面试邀约": ["已拒绝", "线下面试"],
        "线下面试": ["已拒绝", "成功入职"],
        "成功入职": []  # 最终状态，无法再转换
    }
    
    # 确保old_status和status是Python字符串，不是SQLAlchemy Column对象
    old_status_str = str(old_status)
    status_str = str(status)
    
    if old_status_str not in valid_transitions or status_str not in valid_transitions[old_status_str]:
        raise HTTPException(status_code=400, detail=f"无效的状态转换：{old_status} -> {status}")

    application.status = status  # type: ignore
    
    # 更新相应的时间戳
    if status == "面试邀约":
        application.interview_invited_at = get_local_time()  # type: ignore
    elif status == "线下面试":
        application.interview_confirmed_at = get_local_time()  # type: ignore
    elif status == "成功入职":
        application.interview_completed_at = get_local_time()  # type: ignore
        application.offer_accepted = True  # type: ignore
    
    # 当申请被拒绝时，发送拒绝通知
    if status == "已拒绝" and old_status_str != "已拒绝":
        # 获取候选人信息
        candidate = db.query(Candidate).filter(
            Candidate.id == application.candidate_id).first()
        # 获取岗位信息
        job = db.query(Job).filter(Job.id == application.job_id).first()
        if candidate:
            # 获取候选人的用户信息
            candidate_user = db.query(User).filter(
                User.id == candidate.user_id).first()
            if candidate_user and job:
                # 构建拒绝消息
                message_content = f"【申请拒绝通知】<br><br>很遗憾，您申请的\"{job.title}\"职位未能通过筛选。<br><br>感谢您对我们公司的关注，祝您求职顺利！"
                
                # 创建消息
                from app.models import Message
                new_message = Message(
                    sender_id=current_user.id,
                    receiver_id=candidate_user.id,
                    content=message_content,
                    job_id=job.id,
                    extra_data=json.dumps({
                        "type": "application_notification",
                        "application_id": application.id,
                        "status": "rejected"
                    }, ensure_ascii=False)
                )
                db.add(new_message)
    
    db.commit()
    db.refresh(application)

    return {"message": "状态已更新", "status": status}


@router.post("/{application_id}/offline-interview")
def send_offline_interview_invitation(
    application_id: int,
    invitation_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """发送线下面试邀约（仅HR）"""
    
    application = db.query(Application).filter(
        Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")

    # 检查权限
    if str(current_user.role) != "admin":
        job = db.query(Job).filter(Job.id == application.job_id).first()
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()

        if not hr_profile:
            raise HTTPException(status_code=403, detail="无权限")
        if job and int(job.hr_id) != int(hr_profile.id):  # type: ignore
            raise HTTPException(status_code=403, detail="无权限")
    
    # 获取必要的邀约信息
    location = invitation_data.get('location')
    date_time = invitation_data.get('date_time')
    interviewer_info = invitation_data.get('interviewer_info', '')
    notes = invitation_data.get('notes', '')
    
    if not location or not date_time:
        raise HTTPException(status_code=400, detail="面试地点和时间为必填字段")
    
    # 更新申请记录
    from datetime import datetime as dt
    try:
        interview_time = dt.fromisoformat(date_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的日期时间格式")
    
    # 状态流转检查
    if application.status not in ['待处理', '已查看']:
        raise HTTPException(status_code=400, detail=f"当前状态({application.status})无法发送面试邀约")
    
    # 更新申请信息
    from datetime import datetime
    application.interview_location = location  # type: ignore
    application.interview_time = interview_time  # type: ignore
    application.interviewer_info = interviewer_info  # type: ignore
    application.interview_notes = notes  # type: ignore
    application.status = "面试邀约"  # type: ignore
    application.interview_invited_at = datetime.utcnow()  # type: ignore
    
    # 发送面试邀约消息给候选人
    candidate = db.query(Candidate).filter(
        Candidate.id == application.candidate_id).first()
    if candidate:
        candidate_user = db.query(User).filter(
            User.id == candidate.user_id).first()
        if candidate_user:
            # 获取岗位信息
            job = db.query(Job).filter(Job.id == application.job_id).first()
            # 构建邀约消息
            message_content = f"【线下面试邀约】<br><br>"
            message_content += f"您好，{candidate.real_name or current_user.username}！<br>"
            message_content += f"我们邀请您参加\"{job.title if job else '未知岗位'}\"职位的线下面试。<br><br>"
            message_content += f"• 面试地点：{location}<br>"
            message_content += f"• 面试时间：{interview_time.strftime('%Y-%m-%d %H:%M')}<br>"
            if interviewer_info:
                message_content += f"• 面试官：{interviewer_info}<br>"
            if notes:
                message_content += f"• 面试须知：<br>{notes.replace('\n', '<br>')}<br>"
            message_content += f"<br>请在【我的申请】中确认是否参加面试。<br>"
            message_content += f"期待您的到来！"
            
            # 创建消息
            from app.models import Message
            new_message = Message(
                sender_id=current_user.id,
                receiver_id=candidate_user.id,
                content=message_content,
                job_id=job.id if job else None,
                extra_data=json.dumps({
                    "type": "interview_invitation",
                    "application_id": application.id,
                    "interview_time": interview_time.isoformat()
                }, ensure_ascii=False)
            )
            db.add(new_message)
    
    db.commit()
    db.refresh(application)
    
    return {"message": "线下面试邀约已发送", "application_id": application.id, "status": "interview_invited"}


@router.post("/{application_id}/confirm-interview")
def confirm_interview(
    application_id: int,
    confirm_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """候选人确认面试邀约"""
    
    application = db.query(Application).filter(
        Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")
    
    # 权限检查：只能是候选人自己确认
    candidate = db.query(Candidate).filter(
        Candidate.id == application.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=403, detail="无权限")
    if candidate and int(candidate.user_id) != int(current_user.id):  # type: ignore
        raise HTTPException(status_code=403, detail="无权限")
    
    # 获取候选人用户信息
    candidate_user = db.query(User).filter(
        User.id == candidate.user_id).first()
    
    # 状态检查
    if str(application.status) != "面试邀约":
        raise HTTPException(status_code=400, detail="当前状态无法确认面试")
    
    # 更新申请状态
    from datetime import datetime
    application.status = "线下面试"  # type: ignore
    application.interview_confirmed_at = datetime.utcnow()  # type: ignore
    
    # 发送确认通知给HR
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if job:
        hr_profile = db.query(HRProfile).filter(
            HRProfile.id == job.hr_id).first()
        if hr_profile:
            hr_user = db.query(User).filter(
                User.id == hr_profile.user_id).first()
            if hr_user:
                message_content = f"【面试确认通知】<br><br>"
                message_content += f"候选人 {candidate.real_name or current_user.username} 已确认参加\"{job.title}\"职位的线下面试。<br><br>"
                message_content += f"• 面试地点：{application.interview_location}<br>"
                message_content += f"• 面试时间：{application.interview_time.strftime('%Y-%m-%d %H:%M')}<br>"
                
                new_message = Message(
                    sender_id=current_user.id,
                    receiver_id=hr_user.id,
                    content=message_content,
                    job_id=job.id,
                    extra_data=json.dumps({
                        "type": "interview_confirmation",
                        "application_id": application.id
                    }, ensure_ascii=False)
                )
                db.add(new_message)
    
    # 发送入职相关通知给候选人
    if candidate and candidate_user:
        job = db.query(Job).filter(Job.id == application.job_id).first()
        if job:
            hr_profile = db.query(HRProfile).filter(HRProfile.id == job.hr_id).first()
            if hr_profile:
                hr_user = db.query(User).filter(User.id == hr_profile.user_id).first()
                message_content = f"【面试确认成功】<br><br>"
                message_content += f"您好，{candidate.real_name or candidate_user.username}！<br><br>"
                message_content += f'您已成功确认参加"{job.title}"职位的线下面试。<br><br>'
                message_content += f"• 面试地点：{application.interview_location}<br>"
                message_content += f"• 面试时间：{application.interview_time.strftime('%Y-%m-%d %H:%M')}<br>"
                message_content += f"• 面试官：{application.interviewer_info}<br><br>"
                message_content += f"面试通过后，我们将向您发送正式的入职通知。具体入职细节请联系HR。<br>"
                message_content += f"期待您的精彩表现！"
                
                new_message = Message(
                    sender_id=hr_user.id if hr_user else 1,  # 如果HR用户不存在，使用系统用户ID
                    receiver_id=candidate_user.id,
                    content=message_content,
                    job_id=job.id,
                    extra_data=json.dumps({
                        "type": "interview_confirmation_notice",
                        "application_id": application.id
                    }, ensure_ascii=False)
                )
                db.add(new_message)
    
    db.commit()
    db.refresh(application)
    
    return {"message": "面试已确认", "status": "线下面试"}


@router.post("/{application_id}/send-offer")
def send_offer(
    application_id: int,
    offer_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """HR发送入职通知"""
    
    application = db.query(Application).filter(
        Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")
    
    # 权限检查
    if str(current_user.role) != "admin":
        job = db.query(Job).filter(Job.id == application.job_id).first()
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()
        
        if not hr_profile:
            raise HTTPException(status_code=403, detail="无权限")
        if job and int(job.hr_id) != int(hr_profile.id):  # type: ignore
            raise HTTPException(status_code=403, detail="无权限")
    
    # 状态检查
    if str(application.status) != "线下面试":
        raise HTTPException(status_code=400, detail="当前状态无法发送入职通知")
    
    # 更新申请状态
    from datetime import datetime
    application.offer_sent = True  # type: ignore
    application.offer_sent_at = datetime.utcnow()  # type: ignore
    
    # 发送入职通知给候选人
    candidate = db.query(Candidate).filter(
        Candidate.id == application.candidate_id).first()
    if candidate:
        candidate_user = db.query(User).filter(
            User.id == candidate.user_id).first()
        # 获取岗位信息
        job = db.query(Job).filter(Job.id == application.job_id).first()
        if candidate_user and job:
            message_content = f"【面试成功 - 正式入职邀请】<br><br>"
            message_content += f"尊敬的 {candidate.real_name or candidate_user.username} 先生/女士：<br><br>"
            message_content += f"恭喜您！经过严格的面试流程，您已成功通过\"{job.title}\"职位的线下面试。<br><br>"
            message_content += f"我们非常高兴地正式向您发出入职邀请，诚挚欢迎您加入我们的团队！<br><br>"
            message_content += f"• 入职岗位：{job.title}<br>"
            message_content += f"• 所属公司：{job.hr.company_name or '未知公司'}<br>"
            message_content += f"• 工作地点：{job.location}<br><br>"
            message_content += f"<strong>重要提示：</strong><br>"
            message_content += f"1. 请在【我的申请】中确认是否接受入职邀请<br>"
            message_content += f"2. 具体入职时间、薪资待遇及所需材料等详情，请直接联系HR<br>"
            message_content += f"3. 如有任何疑问，欢迎随时与我们沟通<br><br>"
            message_content += f"期待您的加入，一起创造更美好的未来！<br>"
            message_content += f"{job.hr.company_name or '招聘团队'} 敬上"
            
            new_message = Message(
                sender_id=current_user.id,
                receiver_id=candidate_user.id,
                content=message_content,
                job_id=job.id,
                extra_data=json.dumps({
                    "type": "offer_notification",
                    "application_id": application.id
                }, ensure_ascii=False)
            )
            db.add(new_message)
    
    db.commit()
    db.refresh(application)
    
    return {"message": "面试成功 - 入职通知已发送", "status": "offer_sent"}


@router.post("/{application_id}/accept-offer")
def accept_offer(
    application_id: int,
    accept_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """候选人接受入职通知"""
    
    application = db.query(Application).filter(
        Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")
    
    # 权限检查
    candidate = db.query(Candidate).filter(
        Candidate.id == application.candidate_id).first()
    if not candidate or int(candidate.user_id) != int(current_user.id):  # type: ignore
        raise HTTPException(status_code=403, detail="无权限")
    
    # 状态检查
    if str(application.status) != "线下面试" or not bool(application.offer_sent):
        raise HTTPException(status_code=400, detail="当前状态无法接受入职邀请")
    
    # 更新申请状态
    from datetime import datetime
    application.offer_accepted = True  # type: ignore
    application.status = "成功入职"  # type: ignore
    application.interview_completed_at = datetime.utcnow()  # type: ignore
    
    # 发送成功入职通知给HR
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if job:
        hr_profile = db.query(HRProfile).filter(
            HRProfile.id == job.hr_id).first()
        if hr_profile:
            hr_user = db.query(User).filter(
                User.id == hr_profile.user_id).first()
            if hr_user:
                message_content = f"【确认入职通知】<br><br>"
                message_content += f"候选人 {candidate.real_name or current_user.username} 已接受\"{job.title}\"职位的入职邀请！<br><br>"
                message_content += f"• 申请ID：{application.id}<br>"
                message_content += f"• 岗位：{job.title}<br>"
                message_content += f"• 入职时间：{datetime.utcnow().strftime('%Y-%m-%d')}<br>"
                
                new_message = Message(
                    sender_id=current_user.id,
                    receiver_id=hr_user.id,
                    content=message_content,
                    job_id=job.id,
                    extra_data=json.dumps({
                        "type": "onboarding_completed",
                        "application_id": application.id
                    }, ensure_ascii=False)
                )
                db.add(new_message)
    
    db.commit()
    db.refresh(application)
    
    return {"message": "已成功接受入职邀请", "status": "successfully_joined"}


@router.get("/{application_id}/candidate-detail")
def get_candidate_detail(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """功能2：获取候选人完整资料（仅HR）"""
    application = db.query(Application).filter(
        Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="申请不存在")

    # 检查权限
    if str(current_user.role) != "admin":
        # 非管理员只能查看自己发布的岗位的候选人详情
        job = db.query(Job).filter(Job.id == application.job_id).first()
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()

        if not hr_profile or not job or int(job.hr_id) != int(hr_profile.id):  # type: ignore
            raise HTTPException(status_code=403, detail="无权限")

    # 获取候选人完整信息
    candidate = db.query(Candidate).filter(
        Candidate.id == application.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    candidate_user = db.query(User).filter(
        User.id == candidate.user_id).first()

    return {
        "id": candidate.id,
        "user_id": candidate.user_id,
        "username": candidate_user.username if candidate_user else None,
        "real_name": candidate.real_name,
        "gender": candidate.gender,
        "birth_date": candidate.birth_date,
        "phone": candidate.phone,
        "email": candidate.email,
        "education": candidate.education,
        "major": candidate.major,
        "work_experience": candidate.work_experience,
        "skills": candidate.skills,
        "target_job": candidate.target_job,
        "expected_salary": candidate.expected_salary,
        "experience_summary": candidate.experience_summary,
        "job_status": candidate.job_status,
        "created_at": candidate.created_at.isoformat() if isinstance(candidate.created_at, datetime) else None,
        "updated_at": candidate.updated_at.isoformat() if isinstance(candidate.updated_at, datetime) else None}


@router.post("/invite")
def send_job_invitation(
    invitation_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """发送岗位邀约（HR向候选人发送岗位邀请）"""
    if str(current_user.role) != "hr":
        raise HTTPException(status_code=403, detail="仅HR可发送岗位邀约")
    
    # 获取邀请数据
    candidate_id = invitation_data.get("candidate_id")
    job_id = invitation_data.get("job_id")
    message = invitation_data.get("message", "")
    
    if not candidate_id or not job_id:
        raise HTTPException(status_code=400, detail="候选人ID和岗位ID不能为空")
    
    # 检查HR是否有权限发送该岗位的邀请（必须是自己创建的岗位）
    hr_profile = db.query(HRProfile).filter(
        HRProfile.user_id == current_user.id
    ).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="HR信息不存在")
    
    job = db.query(Job).filter(
        Job.id == job_id,
        Job.hr_id == hr_profile.id
    ).first()
    if not job:
        raise HTTPException(status_code=403, detail="您没有权限发送该岗位的邀请")
    
    # 检查候选人是否存在
    candidate = db.query(Candidate).filter(
        Candidate.id == candidate_id
    ).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")
    
    # 检查候选人的用户信息
    candidate_user = db.query(User).filter(
        User.id == candidate.user_id
    ).first()
    if not candidate_user:
        raise HTTPException(status_code=404, detail="候选人用户信息不存在")
    
    # 构建邀约消息
    invitation_content = f"【岗位邀约通知】<br><br>"
    invitation_content += f"您好，{candidate.real_name or candidate_user.username}！<br>"
    invitation_content += f"我们邀请您申请我们的岗位：{job.title}<br>"
    invitation_content += f"• 工作地点：{job.location}<br>"
    invitation_content += f"• 薪资范围：{job.salary_range}<br><br>"
    
    if message:
        invitation_content += f"HR留言：{message}<br>"
    
    invitation_content += f"请<a href='../jobs/{job.id}' target='_blank'>点击查看</a>岗位详情并申请。<br><br>"
    invitation_content += f"期待您的加入！"
    
    # 创建消息记录
    new_message = Message(
        sender_id=current_user.id,  # 发送者是HR
        receiver_id=candidate_user.id,  # 接收者是候选人
        content=invitation_content,
        is_read=False,
        job_id=job.id,
        extra_data=json.dumps({
            "type": "job_invitation",
            "candidate_id": candidate_id,
            "job_id": job_id,
            "invitation_message": message
        }, ensure_ascii=False)
    )
    db.add(new_message)
    db.commit()
    
    return {
        "message": "岗位邀约发送成功",
        "candidate_name": candidate.real_name or candidate_user.username,
        "job_title": job.title
    }
