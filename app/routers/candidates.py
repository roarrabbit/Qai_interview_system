from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import User, Candidate
from app.auth import get_current_user
from app.schemas import CandidateResponse

router = APIRouter(prefix="/api/candidates", tags=["候选人"])


@router.get("/me", response_model=CandidateResponse)
def get_current_candidate(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前候选人信息"""
    # 只有候选人可以访问
    if current_user.role != "candidate":
        raise HTTPException(status_code=403, detail="权限不足")

    # 获取候选人信息
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    return candidate


@router.get("/all", response_model=List[CandidateResponse])
def get_all_candidates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取所有候选人列表（HR和管理员可访问）"""
    # 只有HR和管理员可以访问
    if current_user.role not in ["hr", "admin"]:
        raise HTTPException(status_code=403, detail="权限不足")

    # 获取所有候选人
    candidates = db.query(Candidate).all()

    return candidates


@router.get("/{candidate_id}", response_model=CandidateResponse)
def get_candidate_by_id(
    candidate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """通过ID获取候选人详情（HR和管理员可访问）"""
    # 只有HR和管理员可以访问
    if current_user.role not in ["hr", "admin"]:
        raise HTTPException(status_code=403, detail="权限不足")

    # 获取候选人信息
    candidate = db.query(Candidate).filter(
        Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    return candidate


@router.post("/search")
def search_candidates(
    search_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """搜索候选人（HR和管理员可访问）"""
    # 只有HR和管理员可以访问
    if current_user.role not in ["hr", "admin"]:
        raise HTTPException(status_code=403, detail="权限不足")

    # 获取搜索条件
    keyword = search_data.get("keyword", "")
    education = search_data.get("education")
    min_experience = search_data.get("min_experience")

    # 构建查询
    query = db.query(Candidate)

    # 关键词搜索
    if keyword:
        query = query.filter(
            (Candidate.real_name.contains(keyword)) |
            (Candidate.target_job.contains(keyword)) |
            (Candidate.skills.contains(keyword)) |
            (Candidate.experience_summary.contains(keyword))
        )

    # 学历过滤
    if education:
        query = query.filter(Candidate.education == education)

    # 工作经验过滤
    if min_experience:
        # 这里假设工作经验是字符串，如"1-3年"，我们需要解析出最小年限
        # 定义工作经验映射
        experience_map = {
            "应届生": 0,
            "1年以内": 0,
            "1-3年": 1,
            "3-5年": 3,
            "5-10年": 5,
            "10年以上": 10
        }
        
        # 获取最小工作经验年限
        min_years = experience_map.get(min_experience, 0)
        
        # 构建工作经验过滤条件
        conditions = []
        for exp_str, exp_years in experience_map.items():
            if exp_years >= min_years:
                conditions.append(Candidate.work_experience == exp_str)
        
        if conditions:
            from sqlalchemy import or_
            query = query.filter(or_(*conditions))

    # 执行查询
    candidates = query.all()

    return candidates
