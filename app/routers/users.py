from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Candidate, HRProfile
from app.schemas import (
    UserResponse, CandidateUpdate, CandidateResponse,
    HRProfileUpdate, HRProfileResponse
)
from app.auth import get_current_user, get_current_candidate, get_current_hr, verify_password, get_password_hash
from app.security import validate_password_strength

router = APIRouter(prefix="/api/users", tags=["用户"])


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user


@router.get("/available-contacts")
def get_available_contacts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取可以联系的用户列表（用于新建对话）"""
    # 根据当前用户角色返回不同的联系人列表
    if current_user.role == 'candidate':
        # 求职者可以联系所有HR
        users = db.query(User).filter(
            User.role == 'hr',
            User.id != current_user.id).all()
    elif current_user.role == 'hr':
        # HR可以联系所有求职者
        users = db.query(User).filter(
            User.role == 'candidate',
            User.id != current_user.id).all()
    else:
        # 管理员可以联系所有人
        users = db.query(User).filter(User.id != current_user.id).all()

    # 获取详细信息
    result = []
    for u in users:
        display_name = u.username
        company_or_job = ""

        if u.role == 'hr':
            hr_profile = db.query(HRProfile).filter(
                HRProfile.user_id == u.id).first()
            if hr_profile:
                display_name = hr_profile.contact_person or u.username
                company_or_job = hr_profile.company_name or ""
        elif u.role == 'candidate':
            candidate = db.query(Candidate).filter(
                Candidate.user_id == u.id).first()
            if candidate:
                display_name = candidate.real_name or u.username
                company_or_job = candidate.target_job or ""

        result.append({
            "id": u.id,
            "username": u.username,
            "display_name": display_name,
            "role": u.role,
            "company_or_job": company_or_job
        })

    return result


@router.get("/candidate/profile", response_model=CandidateResponse)
def get_candidate_profile(
        current_user: User = Depends(get_current_candidate),
        db: Session = Depends(get_db)):
    """获取求职者信息"""
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="求职者信息不存在")
    return candidate


@router.put("/candidate/profile", response_model=CandidateResponse)
def update_candidate_profile(
    profile_data: CandidateUpdate,
    current_user: User = Depends(get_current_candidate),
    db: Session = Depends(get_db)
):
    """更新求职者信息"""
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="求职者信息不存在")

    update_data = profile_data.model_dump(exclude_unset=True)
    
    if 'skills' in update_data and update_data['skills']:
        update_data['skills'] = update_data['skills'].replace('、', ',').replace('，', ',')

    for field, value in update_data.items():
        setattr(candidate, field, value)

    db.commit()
    db.refresh(candidate)
    return candidate


@router.get("/hr/profile", response_model=HRProfileResponse)
def get_hr_profile(
        current_user: User = Depends(get_current_hr),
        db: Session = Depends(get_db)):
    """获取HR信息"""
    hr_profile = db.query(HRProfile).filter(
        HRProfile.user_id == current_user.id).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="HR信息不存在")
    return hr_profile


@router.put("/hr/profile", response_model=HRProfileResponse)
def update_hr_profile(
    profile_data: HRProfileUpdate,
    current_user: User = Depends(get_current_hr),
    db: Session = Depends(get_db)
):
    """更新HR信息"""
    hr_profile = db.query(HRProfile).filter(
        HRProfile.user_id == current_user.id).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="HR信息不存在")

    # 更新字段
    for field, value in profile_data.model_dump(exclude_unset=True).items():
        setattr(hr_profile, field, value)

    db.commit()
    db.refresh(hr_profile)
    return hr_profile


@router.post("/change-password")
def change_password(
    old_password: str = Form(...),
    new_password: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """修改当前用户密码"""
    # 验证旧密码
    if not verify_password(old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")

    # 验证新密码强度
    validate_password_strength(new_password)

    # 更新密码
    current_user.password_hash = get_password_hash(new_password)
    db.commit()

    return {"message": "密码修改成功"}
