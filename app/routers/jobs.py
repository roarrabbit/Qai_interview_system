from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import distinct
from typing import List, Optional, Dict
from app.database import get_db
from app.models import Job, User, Application, Candidate, HRProfile, Interview
from app.schemas import JobCreate, JobUpdate, JobResponse, JobPublicResponse
from app.auth import get_current_user, get_current_hr
from app.recommendation import get_job_recommendations_for_user, get_candidate_recommendations_for_job
from pydantic import BaseModel

router = APIRouter(prefix="/api/jobs", tags=["岗位"])


class JobSearchParams(BaseModel):
    """岗位搜索参数"""
    keyword: Optional[str] = None
    location: Optional[str] = None


@router.post("/search")
def search_jobs(
    search_params: JobSearchParams = Body(...),
    db: Session = Depends(get_db)
):
    """搜索岗位（使用POST请求提高安全性，不暴露HR联系方式）"""
    query = db.query(Job).options(joinedload(Job.hr)).filter(Job.is_active)

    if search_params.keyword:
        query = query.filter(
            (Job.title.contains(search_params.keyword)) |
            (Job.description.contains(search_params.keyword))
        )
    if search_params.location:
        query = query.filter(Job.location == search_params.location)

    jobs = query.order_by(Job.created_at.desc()).all()

    result = []
    for job in jobs:
        job_dict = {
            "id": job.id,
            "hr_id": job.hr_id,
            "title": job.title,
            "description": job.description,
            "required_skills": job.required_skills,
            "salary_range": job.salary_range,
            "location": job.location,
            "education_required": job.education_required,
            "work_experience": job.work_experience,
            "status": job.status,
            "is_active": job.is_active,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "hr": {
                "id": job.hr.id if job.hr else None,
                "company_name": job.hr.company_name if job.hr else None,
                "industry": job.hr.industry if job.hr else None,
                "company_size": job.hr.company_size if job.hr else None
            }
        }
        result.append(job_dict)

    return result


@router.get("/filters", response_model=Dict)
def get_filter_options(db: Session = Depends(get_db)):
    """获取筛选选项（仅地点）"""
    # 获取所有不重复的地点
    locations = db.query(distinct(Job.location)).filter(
        Job.is_active,
        Job.location.isnot(None),
        Job.location != ''
    ).order_by(Job.location).all()
    locations = [loc[0] for loc in locations if loc[0]]

    return {
        "locations": locations
    }


def _build_job_query(query_params, db):
    """构建岗位查询条件"""
    query = db.query(Job).options(joinedload(Job.hr)).filter(Job.is_active)
    
    if query_params.get("keyword"):
        query = query.filter(
            (Job.title.contains(query_params["keyword"])) | 
            (Job.description.contains(query_params["keyword"]))
        )
    if query_params.get("location"):
        query = query.filter(Job.location == query_params["location"])
    
    return query


@router.get("/", response_model=List[JobPublicResponse])
def get_jobs(
    skip: int = 0,
    limit: int = 100,
    keyword: Optional[str] = None,
    location: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取岗位列表（公开接口，不暴露HR联系方式）"""
    query_params = {
        "keyword": keyword,
        "location": location
    }

    query = _build_job_query(query_params, db)
    jobs = query.order_by(Job.created_at.desc()).offset(skip).limit(limit).all()

    return jobs


@router.get("/my-jobs")
def get_my_jobs(
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取HR发布的所有岗位"""
    if not current_user:
        raise HTTPException(status_code=401, detail="请先登录")
    
    # 使用类型断言确保role被识别为str
    if (current_user.role  # type: ignore
        not in ["hr", "admin"]):
        raise HTTPException(status_code=403, detail="仅HR或管理员可访问")

    if (current_user.role  # type: ignore
        == "admin"):
        # 管理员可以访问所有岗位
        jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    else:
        # HR只能访问自己发布的岗位
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()
        if not hr_profile:
            return []

        # 获取该HR发布的所有岗位
        jobs = db.query(Job).filter(
            Job.hr_id == hr_profile.id).order_by(
            Job.created_at.desc()).all()

    # 统计每个岗位的申请数据
    result = []
    for job in jobs:
        applications = db.query(Application).filter(
            Application.job_id == job.id).all()
        job_dict = {
            "id": job.id,
            "title": job.title,
            "location": job.location,
            "salary_range": job.salary_range,
            "description": job.description,
            "required_skills": job.required_skills,
            "education_required": job.education_required,
            "work_experience": job.work_experience,
            "is_active": job.is_active,
            "status": job.status,
            "hiring_count": job.hiring_count,
            "created_at": job.created_at,
            "application_count": len(applications),
            "pending_count": len([a for a in applications if str(a.status) == '待处理']),
            "accepted_count": len([a for a in applications if str(a.status) == '成功入职']),
            "rejected_count": len([a for a in applications if str(a.status) == '已拒绝']),
            # 统计面试中的数量：已发送面试邀约或正在进行线下面试的数量
            "interview_count": len([a for a in applications if str(a.status) in ['面试邀约', '线下面试']])
        }
        result.append(job_dict)

    return result


@router.get("/recommendations")
def get_recommended_jobs(
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取推荐岗位（未登录用户获取热门岗位，不暴露HR联系方式）"""
    if current_user and str(getattr(current_user, 'role', '')) == "candidate":
        # 已登录求职者获取个性化推荐
        recommendations = get_job_recommendations_for_user(
            db, int(getattr(current_user, 'id', 0)), top_n=2)

        # 手动加载HR信息
        for rec in recommendations:
            job = rec['job']
            hr_profile = db.query(HRProfile).filter(
                HRProfile.id == job.hr_id).first()
            if hr_profile:
                rec['job'].hr = hr_profile

        return recommendations
    else:
        # 未登录用户或其他角色获取热门岗位
        # 获取最新的4个岗位
        jobs = db.query(Job).options(joinedload(Job.hr)).filter(
            Job.is_active
        ).order_by(Job.created_at.desc()).limit(4).all()

        # 转换为与个性化推荐相同的格式，但不暴露HR联系方式
        result = []
        for job in jobs:
            result.append({
                'job': job,
                'score': 1.0  # 热门岗位默认分数
            })

        return result


@router.get("/{job_id}/recommendations")
def get_recommended_candidates(
    job_id: str,
    current_user: User = Depends(get_current_hr),
    db: Session = Depends(get_db)
):
    """获取岗位的推荐候选人（仅HR）"""
    # 验证 job_id 是否为有效的整数
    if not job_id.isdigit():
        raise HTTPException(status_code=404, detail="岗位不存在")
    
    # 转换为整数
    job_id_int = int(job_id)
    
    hr_profile = db.query(HRProfile).filter(
        HRProfile.user_id == current_user.id).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="请先完善HR信息")

    job = db.query(Job).filter(
        Job.id == job_id_int,
        Job.hr_id == hr_profile.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在或无权限")

    recommendations = get_candidate_recommendations_for_job(
        db, job_id_int, top_n=5)
    return recommendations


@router.get("/{job_id}/applications")
def get_job_applications(
    job_id: str,
    current_user: User = Depends(get_current_hr),
    db: Session = Depends(get_db)
):
    """获取岗位的申请列表（仅HR）"""
    # 验证 job_id 是否为有效的整数
    if not job_id.isdigit():
        raise HTTPException(status_code=404, detail="岗位不存在")
    
    # 转换为整数
    job_id_int = int(job_id)
    
    hr_profile = db.query(HRProfile).filter(
        HRProfile.user_id == current_user.id).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="请先完善HR信息")

    job = db.query(Job).filter(
        Job.id == job_id_int,
        Job.hr_id == hr_profile.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在或无权限")

    applications = db.query(Application).filter(
        Application.job_id == job_id_int).all()

    result = []
    for app in applications:
        candidate = db.query(Candidate).filter(
            Candidate.id == app.candidate_id).first()
        result.append({
            "application": app,
            "candidate": candidate
        })

    return result


@router.get("/{job_id}", response_model=JobPublicResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """获取岗位详情（不暴露HR联系方式）"""
    # 验证 job_id 是否为有效的整数
    if not job_id.isdigit():
        raise HTTPException(status_code=404, detail="岗位不存在")
    
    # 转换为整数
    job_id_int = int(job_id)
    
    job = db.query(Job).options(
        joinedload(
            Job.hr)).filter(
        Job.id == job_id_int).first()
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return job


@router.post("/", response_model=JobResponse)
def create_job(
    job_data: JobCreate,
    current_user: User = Depends(get_current_hr),
    db: Session = Depends(get_db)
):
    """发布岗位（仅HR）"""
    hr_profile = db.query(HRProfile).filter(
        HRProfile.user_id == current_user.id).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="请先完善HR信息")

    job_dict = job_data.model_dump()
    if 'hiring_count' in job_dict and job_dict['hiring_count'] < 1:
        job_dict['hiring_count'] = 1
    
    if job_dict.get('required_skills'):
        job_dict['required_skills'] = job_dict['required_skills'].replace('、', ',').replace('，', ',')

    job = Job(**job_dict, hr_id=hr_profile.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    
    from app.logger import log_job_created
    log_job_created(job.title, current_user.username)
    
    return job


@router.put("/{job_id}", response_model=JobResponse)
def update_job(
    job_id: str,
    job_data: JobUpdate,
    current_user: User = Depends(get_current_hr),
    db: Session = Depends(get_db)
):
    """更新岗位（仅HR）"""
    # 验证 job_id 是否为有效的整数
    if not job_id.isdigit():
        raise HTTPException(status_code=404, detail="岗位不存在")
    
    # 转换为整数
    job_id_int = int(job_id)
    
    if str(current_user.role) == "admin":
        job = db.query(Job).filter(Job.id == job_id_int).first()
    else:
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()
        if not hr_profile:
            raise HTTPException(status_code=404, detail="请先完善HR信息")

        job = db.query(Job).filter(
            Job.id == job_id_int,
            Job.hr_id == hr_profile.id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在或无权限")

    update_data = job_data.model_dump(exclude_unset=True)
    
    if 'required_skills' in update_data and update_data['required_skills']:
        update_data['required_skills'] = update_data['required_skills'].replace('、', ',').replace('，', ',')

    for field, value in update_data.items():
        setattr(job, field, value)

    db.commit()
    db.refresh(job)
    return job


@router.delete("/{job_id}")
def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_hr),
    db: Session = Depends(get_db)
):
    """删除岗位（仅HR）"""
    # 验证 job_id 是否为有效的整数
    if not job_id.isdigit():
        raise HTTPException(status_code=404, detail="岗位不存在")
    
    # 转换为整数
    job_id_int = int(job_id)
    
    # 权限检查：只有岗位发布者或管理员可删除
    if str(current_user.role) == "admin":
        # 管理员可以删除任何岗位
        job = db.query(Job).filter(Job.id == job_id_int).first()
    else:
        # HR只能删除自己的岗位
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == current_user.id).first()
        if not hr_profile:
            raise HTTPException(status_code=404, detail="请先完善HR信息")

        job = db.query(Job).filter(
            Job.id == job_id_int,
            Job.hr_id == hr_profile.id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在或无权限")

    db.delete(job)
    db.commit()
    return {"message": "岗位已删除"}
