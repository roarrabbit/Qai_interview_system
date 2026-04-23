from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, text
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app.models import User
from app.auth import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/api/messages", tags=["消息"])


class MessageCreate(BaseModel):
    receiver_id: int
    content: str
    job_id: Optional[int] = None
    metadata: Optional[dict] = None


class MessageResponse(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    content: str
    is_read: bool
    created_at: datetime
    sender_name: str

    class Config:
        from_attributes = True


class ConversationUser(BaseModel):
    user_id: int
    username: str
    role: str
    last_message: str
    last_message_time: datetime
    unread_count: int


def _get_conversation_users(current_user_id, db):
    """获取所有与当前用户有对话的用户ID"""
    from app.models import Message
    from sqlalchemy import text
    
    query = text(f"""
    SELECT DISTINCT
        CASE
            WHEN sender_id = {current_user_id} THEN receiver_id
            ELSE sender_id
        END as other_user_id
    FROM messages
    WHERE sender_id = {current_user_id} OR receiver_id = {current_user_id}
    """)
    
    result = db.execute(query).fetchall()
    return [row[0] for row in result]


def _get_last_message(current_user_id, other_user_id, db):
    """获取两个用户之间的最后一条消息"""
    from app.models import Message
    from sqlalchemy import or_, and_
    
    return db.query(Message).filter(
        or_(
            and_(Message.sender_id == current_user_id, 
                 Message.receiver_id == other_user_id),
            and_(Message.sender_id == other_user_id, 
                 Message.receiver_id == current_user_id)
        )
    ).order_by(Message.created_at.desc()).first()


def _get_unread_count(current_user_id, other_user_id, db):
    """获取当前用户未读消息数"""
    from app.models import Message
    
    return db.query(Message).filter(
        Message.sender_id == other_user_id,
        Message.receiver_id == current_user_id,
        not Message.is_read
    ).count()


def _get_user_display_info(other_user, db):
    """获取用户的显示信息"""
    from app.models import Candidate, HRProfile
    
    display_name = other_user.username
    company_name = ""
    job_title = ""
    
    if other_user.role == 'hr':
        hr_profile = db.query(HRProfile).filter(
            HRProfile.user_id == other_user.id).first()
        if hr_profile:
            display_name = hr_profile.contact_person or other_user.username
            company_name = hr_profile.company_name or ""
    elif other_user.role == 'candidate':
        candidate = db.query(Candidate).filter(
            Candidate.user_id == other_user.id).first()
        if candidate:
            display_name = candidate.real_name or other_user.username
            job_title = candidate.target_job or ""
    
    return display_name, company_name, job_title


@router.get("/conversations")
def get_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取所有对话列表"""
    from app.security import is_user_online
    
    other_user_ids = _get_conversation_users(current_user.id, db)
    conversations = []
    
    for other_user_id in other_user_ids:
        other_user = db.query(User).filter(User.id == other_user_id).first()
        if not other_user:
            continue
        
        last_msg = _get_last_message(current_user.id, other_user_id, db)
        unread_count = _get_unread_count(current_user.id, other_user_id, db)
        display_name, company_name, job_title = _get_user_display_info(other_user, db)
        
        # 从消息中获取job_id
        job_id = last_msg.job_id if last_msg and last_msg.job_id else None
        
        # 检查用户在线状态
        user_is_online = is_user_online(other_user_id)
        
        conversations.append({
            "id": other_user_id,  # 这里改为other_user_id以便前端使用
            "other_user_id": other_user_id,
            "other_user_name": display_name,
            "username": other_user.username,
            "role": other_user.role,
            "last_message": last_msg.content if last_msg else "",
            "last_message_time": last_msg.created_at if last_msg else None,
            "unread_count": unread_count,
            "company_name": company_name,
            "job_title": job_title,
            "is_online": user_is_online,
            "job_id": job_id
        })
    
    # 按最后消息时间倒序排序
    conversations.sort(
        key=lambda x: x["last_message_time"] if x["last_message_time"] else datetime.min,
        reverse=True)

    return conversations


@router.get("/{user_id}", response_model=List[MessageResponse])
def get_messages(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取与某用户的聊天记录"""
    from app.models import Message

    # 查询双方的消息
    messages = db.query(Message).filter(
        or_(
            and_(
                Message.sender_id == current_user.id,
                Message.receiver_id == user_id),
            and_(
                Message.sender_id == user_id,
                Message.receiver_id == current_user.id))).order_by(
        Message.created_at.asc()).all()

    # 标记对方发来的消息为已读
    db.query(Message).filter(
        Message.sender_id == user_id,
        Message.receiver_id == current_user.id,
        not Message.is_read
    ).update({"is_read": True})
    db.commit()

    # 获取发送者用户名
    result = []
    for msg in messages:
        sender = db.query(User).filter(User.id == msg.sender_id).first()
        result.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "content": msg.content,
            "is_read": msg.is_read,
            "created_at": msg.created_at,
            "sender_name": sender.username if sender else "未知"
        })

    return result


@router.post("/", response_model=MessageResponse)
def send_message(
    message_data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """发送消息"""
    from app.models import Message, Candidate, Job

    # 验证接收者存在
    receiver = db.query(User).filter(
        User.id == message_data.receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="接收者不存在")

    # 如果是候选人发送的消息且包含job_id，自动添加候选人信息到extra_data
    extra_data = message_data.metadata or {}
    if message_data.job_id and current_user.role == 'candidate':
        candidate = db.query(Candidate).filter(
            Candidate.user_id == current_user.id).first()
        job = db.query(Job).filter(Job.id == message_data.job_id).first()
        if candidate and job:
            extra_data = {
                "candidate_info": {
                    "real_name": candidate.real_name,
                    "phone": candidate.phone,
                    "email": candidate.email,
                    "target_job": candidate.target_job,
                    "skills": candidate.skills,
                    "job_status": candidate.job_status
                },
                "job_info": {
                    "id": job.id,
                    "title": job.title,
                    "location": job.location,
                    "salary_range": job.salary_range
                }
            }

    # 创建消息
    message = Message(
        sender_id=current_user.id,
        receiver_id=message_data.receiver_id,
        content=message_data.content,
        job_id=message_data.job_id,
        extra_data=extra_data if extra_data else None
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return {
        "id": message.id,
        "sender_id": message.sender_id,
        "receiver_id": message.receiver_id,
        "content": message.content,
        "is_read": message.is_read,
        "created_at": message.created_at,
        "sender_name": current_user.username
    }


@router.get("/unread/count")
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取未读消息数"""
    from app.models import Message

    count = db.query(Message).filter(
        Message.receiver_id == current_user.id,
        not Message.is_read
    ).count()

    return {"unread_count": count}


@router.get("/{user_id}/metadata")
def get_conversation_metadata(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取对话的元数据（岗位和候选人信息）"""
    from app.models import Message, Candidate, Job

    # 查找这个对话中第一条带job_id的消息
    message = db.query(Message).filter(
        or_(
            and_(
                Message.sender_id == user_id,
                Message.receiver_id == current_user.id),
            and_(
                Message.sender_id == current_user.id,
                Message.receiver_id == user_id)),
        Message.job_id.isnot(None)).order_by(
        Message.created_at.asc()).first()

    if not message:
        return {}

    result = {}

    # 获取岗位信息
    if message.job_id:
        job = db.query(Job).filter(Job.id == message.job_id).first()
        if job:
            result["job_info"] = {
                "id": job.id,
                "title": job.title,
                "location": job.location,
                "salary_range": job.salary_range
            }

    # 获取候选人信息（如果对话对象是候选人）
    candidate = db.query(Candidate).filter(
        Candidate.user_id == user_id).first()
    if candidate:
        result["candidate_info"] = {
            "id": candidate.id,
            "real_name": candidate.real_name,
            "phone": candidate.phone,
            "email": candidate.email,
            "target_job": candidate.target_job,
            "skills": candidate.skills,
            "job_status": candidate.job_status
        }

    return result
