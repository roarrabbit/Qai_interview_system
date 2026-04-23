from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional
from jose import JWTError, jwt
from app.database import get_db
from app.models import User, Job, Candidate, HRProfile, Application, Interview, InterviewReport
from app.auth import get_current_user
from app.config import settings
from app.utils import translate_role, translate_application_status, translate_interview_status

router = APIRouter(tags=["页面"])
templates = Jinja2Templates(directory="templates")

# 注册自定义过滤器
templates.env.filters['translate_role'] = translate_role
templates.env.filters['translate_application_status'] = translate_application_status
templates.env.filters['translate_interview_status'] = translate_interview_status


def get_optional_user(
        request: Request,
        db: Session = Depends(get_db)) -> Optional[User]:
    """获取当前用户（可选，不强制登录）"""
    token = request.cookies.get("access_token")
    if not token:
        return None

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[
                settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        user = db.query(User).filter(User.username == username).first()
        return user
    except JWTError:
        return None


@router.get("/", response_class=HTMLResponse)
async def home(
        request: Request,
        user: Optional[User] = Depends(get_optional_user)):
    """首页"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user
    })


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页面"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """注册页面"""
    return templates.TemplateResponse("register.html", {"request": request})


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    keyword: str = "",
    location: str = "",
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """岗位列表页面（支持搜索和筛选）"""
    # 构建查询，预加载HR关系
    query = db.query(Job).options(joinedload(Job.hr)).filter(Job.is_active)

    # 应用筛选条件
    if keyword:
        query = query.filter(
            (Job.title.contains(keyword)) |
            (Job.description.contains(keyword)) |
            (Job.required_skills.contains(keyword))
        )

    if location:
        query = query.filter(Job.location == location)

    jobs = query.order_by(Job.created_at.desc()).all()

    # 获取推荐岗位（如果是求职者）
    recommended_jobs = []
    if user and user.role == "candidate":
        from app.recommendation import get_job_recommendations_for_user
        recommendations = get_job_recommendations_for_user(
            db, user.id, top_n=2)
        recommended_jobs = recommendations

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "user": user,
        "jobs": jobs,
        "recommended_jobs": recommended_jobs
    })


@router.get("/talent-hall", response_class=HTMLResponse)
async def talent_hall(
    request: Request,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """人才大厅"""
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # 只有HR和管理员可以访问
    if user.role not in ["hr", "admin"]:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse("talent_hall.html", {
        "request": request,
        "user": user
    })


@router.get("/hr-dashboard", response_class=HTMLResponse)
async def hr_dashboard(
    request: Request,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """HR管理面板"""
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if user.role != 'hr':
        return templates.TemplateResponse(
            "403.html", {"request": request}, status_code=403)

    # 获取HR资料
    hr_profile = db.query(HRProfile).filter(
        HRProfile.user_id == user.id).first()
    if not hr_profile:
        hr_profile = HRProfile(user_id=user.id)
        db.add(hr_profile)
        db.commit()

    return templates.TemplateResponse("hr_dashboard.html", {
        "request": request,
        "user": user,
        "hr_profile": hr_profile
    })


@router.get("/admin-dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """数据面板"""
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if user.role != 'admin':
        return templates.TemplateResponse(
            "403.html", {"request": request}, status_code=403)

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "user": user
    })


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """聊天页面"""
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "user": user
    })


@router.get("/candidate-dashboard", response_class=HTMLResponse)
async def candidate_dashboard(
    request: Request,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """求职者面板"""
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if user.role != 'candidate':
        return templates.TemplateResponse(
            "403.html", {"request": request}, status_code=403)
    
    # 获取候选人信息
    candidate = db.query(Candidate).filter(Candidate.user_id == user.id).first()
    
    # 获取个性化推荐
    from app.recommendation import get_job_recommendations_for_user
    job_recommendations = get_job_recommendations_for_user(db, user.id, top_n=8)
    
    # 获取AI面试最好成绩
    best_interview = None
    best_overall_grade = None
    best_grades = []
    
    # 获取候选人的所有面试
    interviews = db.query(Interview).join(InterviewReport).filter(
        Interview.candidate_id == candidate.id,
        Interview.status == "completed"
    ).order_by(Interview.completed_at.desc()).all()
    
    if interviews:
        # 面试评级顺序（用于排序）
        interview_grade_order = {
            'S': 5,
            'A+': 4,
            'A': 3,
            'A-': 2,
            'B+': 1,
            'B': 0
        }
        
        # 按综合评级排序，获取最好的一次
        best_interview = sorted(
            interviews,
            key=lambda x: interview_grade_order.get(x.report.overall_grade, 0),
            reverse=True
        )[0]
        
        best_overall_grade = best_interview.report.overall_grade
        best_grades = {
            "domain_insight": best_interview.report.domain_insight_score,
            "team_collaboration": best_interview.report.team_collaboration_score,
            "technical_vision": best_interview.report.technical_vision_score,
            "practical_ability": best_interview.report.practical_ability_score,
            "architecture_design": best_interview.report.architecture_design_score,
            "authenticity": best_interview.report.authenticity_score
        }

    # 获取候选人的所有申请，预加载job和hr关系
    applications = db.query(Application).options(
        joinedload(Application.job).joinedload(Job.hr)
    ).filter(
        Application.candidate_id == candidate.id
    ).all()
    
    # 按状态优先级排序：面试邀约 > 线下面试 > 成功入职 > 待处理 > 已查看 > 已拒绝
    status_priority = {
        'interview_invited': 5,
        'face_to_face_interview': 4,
        'successfully_joined': 3,
        'pending': 2,
        'reviewed': 1,
        'rejected': 0
    }
    
    # 排序：先按状态优先级，再按申请时间倒序
    applications.sort(
        key=lambda x: (status_priority.get(x.status, 0), x.created_at),
        reverse=True
    )
    
    # 获取所有待面试的面试
    pending_interviews = db.query(Interview).filter(
        Interview.candidate_id == candidate.id,
        Interview.status == "pending"
    ).all()

    # 获取所有AI面试
    all_interviews = db.query(Interview).filter(
        Interview.candidate_id == candidate.id
    ).all()

    return templates.TemplateResponse("candidate_dashboard.html", {
        "request": request,
        "user": user,
        "candidate": candidate,
        "job_recommendations": job_recommendations,
        "best_interview": best_interview,
        "best_overall_grade": best_overall_grade,
        "best_grades": best_grades,
        "applications": applications,
        "interviews": pending_interviews,
        "all_interviews": all_interviews
    })





@router.get("/my-jobs", response_class=HTMLResponse)
async def my_jobs_page(
    request: Request,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """重定向到个人中心（发布岗位功能已统一到个人中心）"""
    if not user or user.role != "hr":
        return RedirectResponse(url="/login", status_code=302)

    return RedirectResponse(url="/profile", status_code=302)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: str,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """岗位详情页面"""
    # 验证 job_id 是否为有效的整数
    if not job_id.isdigit():
        return templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404)
    
    # 转换为整数
    job_id_int = int(job_id)
    
    job = db.query(Job).filter(Job.id == job_id_int).first()
    if not job:
        return templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404)

    # 检查是否已投递
    has_applied = False
    if user and user.role == "candidate":
        application = db.query(Application).filter(
            Application.job_id == job_id,
            Application.candidate_id == user.id
        ).first()
        has_applied = application is not None

    # 获取推荐候选人（如果是HR且是自己的岗位）
    recommended_candidates = []
    if user and user.role == "hr" and job.hr_id == user.id:
        from app.recommendation import get_candidate_recommendations_for_job
        recommendations = get_candidate_recommendations_for_job(
            db, job_id, top_n=5)
        recommended_candidates = recommendations

    # 获取HR的用户ID
    hr_profile = db.query(HRProfile).filter(HRProfile.id == job.hr_id).first()
    hr_user_id = hr_profile.user_id if hr_profile else None

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "user": user,
        "job": job,
        "has_applied": has_applied,
        "recommended_candidates": recommended_candidates,
        "hr_user_id": hr_user_id
    })


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """个人中心"""
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if user.role == "candidate":
        candidate = db.query(Candidate).filter(
            Candidate.user_id == user.id).first()
        if not candidate:
            raise HTTPException(status_code=404, detail="求职者信息不存在")
        interviews = db.query(Interview).filter(
            Interview.candidate_id == candidate.id).order_by(
            Interview.started_at.desc()).all()
        applications = db.query(Application).options(
            joinedload(Application.job).joinedload(Job.hr)
        ).filter(
            Application.candidate_id == candidate.id
        ).all()
        
        # 按状态优先级排序：面试邀约 > 线下面试 > 成功入职 > 待处理 > 已查看 > 已拒绝
        status_priority = {
            'interview_invited': 5,
            'face_to_face_interview': 4,
            'successfully_joined': 3,
            'pending': 2,
            'reviewed': 1,
            'rejected': 0
        }
        
        # 排序：先按状态优先级，再按申请时间倒序
        applications.sort(
            key=lambda x: (status_priority.get(x.status, 0), x.created_at),
            reverse=True
        )

        return templates.TemplateResponse("profile_candidate.html", {
            "request": request,
            "user": user,
            "candidate": candidate,
            "interviews": interviews,
            "applications": applications
        })
    elif user.role == "hr":
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == user.id).first()
        if not hr_profile:
            raise HTTPException(status_code=404, detail="HR信息不存在")
        jobs = db.query(Job).filter(
            Job.hr_id == hr_profile.id).order_by(
            Job.created_at.desc()).all()

        return templates.TemplateResponse("profile_hr.html", {
            "request": request,
            "user": user,
            "hr_profile": hr_profile,
            "jobs": jobs
        })
    else:
        return templates.TemplateResponse("profile_admin.html", {
            "request": request,
            "user": user
        })


@router.get("/admin", response_class=HTMLResponse)
async def admin_console(
    request: Request,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """数据面板"""
    if not user or user.role != "admin":
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("profile_admin.html", {
        "request": request,
        "user": user
    })


@router.get("/interview/{interview_id}", response_class=HTMLResponse)
async def interview_page(
    request: Request,
    interview_id: int,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """面试页面 - 对话式面试界面"""
    if not user or user.role != "candidate":
        return RedirectResponse(url="/login", status_code=302)

    candidate = db.query(Candidate).filter(
        Candidate.user_id == user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        return templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("conversation_interview.html", {
        "request": request,
        "user": user,
        "interview": interview
    })


@router.get("/interview/{interview_id}/report", response_class=HTMLResponse)
async def interview_report_page(
    request: Request,
    interview_id: int,
    user: User = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """面试报告页面"""
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    interview = None
    
    if user.role == "candidate":
        # 获取候选人信息
        candidate = db.query(Candidate).filter(
            Candidate.user_id == user.id).first()
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人信息不存在")

        # 候选人只能查看自己的面试报告
        interview = db.query(Interview).filter(
            Interview.id == interview_id,
            Interview.candidate_id == candidate.id
        ).first()
    elif user.role == "hr":
        # HR可以查看关联到自己岗位的面试报告
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == user.id).first()
        if not hr_profile:
            raise HTTPException(status_code=404, detail="HR信息不存在")
        
        # 获取面试信息，通过岗位关联到HR
        interview = db.query(Interview).join(Job).filter(
            Interview.id == interview_id,
            Job.hr_id == hr_profile.id
        ).first()
    else:
        # 其他角色不允许访问
        return RedirectResponse(url="/login", status_code=302)

    if not interview:
        return templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404)

    report = db.query(InterviewReport).filter(
        InterviewReport.interview_id == interview_id).first()
    
    # 获取岗位和HR信息
    job_info = None
    hr_info = None
    
    if interview.job_id:
        # 获取岗位信息
        job = db.query(Job).filter(Job.id == interview.job_id).first()
        if job:
            job_info = {
                "title": job.title
            }
            
            # 获取HR资料
            hr_profile = db.query(HRProfile).filter(HRProfile.id == job.hr_id).first()
            if hr_profile:
                # 获取HR用户信息
                hr_user = db.query(User).filter(User.id == hr_profile.user_id).first()
                if hr_user:
                    hr_info = {
                        "name": hr_user.username
                    }

    return templates.TemplateResponse("interview_report.html", {
        "request": request,
        "user": user,
        "interview": interview,
        "report": report,
        "job_info": job_info,
        "hr_info": hr_info
    })


@router.get("/logout")
async def logout():
    """登出"""
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token")
    return response
