"""
智能招聘平台 - 面向计算机行业的智能招聘平台
Version: 0.2.7.8
Developer: MLLR
Development Period: 2025.12 ~ 2026.04
License: Apache License 2.0

Description: Pydantic模式定义模块，定义所有API请求和响应的数据验证模式，包括用户、候选人、招聘者、岗位、申请、面试等数据验证和转换。
"""

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime
import re
import html
from app.models import UserRole, Gender, JobStatus

# 安全工具函数


def sanitize_text(text: str) -> str:
    """清理文本，防止XSS攻击"""
    if not text:
        return text
    # HTML转义特殊字符
    text = html.escape(text)
    # 移除可能的脚本标签
    text = re.sub(r'<script[^>]*>.*?</script>', '',
                  text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<iframe[^>]*>.*?</iframe>', '',
                  text, flags=re.IGNORECASE | re.DOTALL)
    # 移除事件处理属性
    text = re.sub(
        r'\s*on\w+\s*=\s*["\'][^"\']*["\']',
        '',
        text,
        flags=re.IGNORECASE)
    return text.strip()


def validate_text_length(text: str, max_length: int) -> str:
    """验证文本长度"""
    if text and len(text) > max_length:
        raise ValueError('输入内容过长')
    return text


def validate_phone(phone: str) -> str:
    """验证手机号格式"""
    if phone and not re.match(r'^1[3-9]\d{9}$', phone):
        raise ValueError('手机号格式不正确')
    return phone

# 用户相关Schema


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=8, max_length=128, description="密码")
    role: UserRole

    @validator('username')
    def validate_username(cls, v):
        # 用户名长度验证（不在错误消息中暴露具体范围）
        if len(v) < 3 or len(v) > 50:
            raise ValueError('用户名格式不正确')
        # 只允许字母、数字、下划线
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('用户名格式不正确')
        return v

    @validator('password')
    def validate_password(cls, v):
        # 密码长度验证（不在错误消息中暴露具体范围）
        if len(v) < 8 or len(v) > 128:
            raise ValueError('密码强度不足')
        # 必须包含字母和数字
        if not re.search(r'[A-Za-z]', v):
            raise ValueError('密码强度不足')
        if not re.search(r'[0-9]', v):
            raise ValueError('密码强度不足')
        return v


class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
    user: Optional[dict] = None  # 包含用户信息（id, username, role）

# 求职者相关Schema


class CandidateCreate(BaseModel):
    real_name: Optional[str] = Field(None, max_length=50)
    gender: Optional[Gender] = None
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = Field(None, max_length=100)
    skills: Optional[str] = Field(None, max_length=500)
    target_job: Optional[str] = Field(None, max_length=100)
    experience_summary: Optional[str] = Field(None, max_length=2000)
    self_introduction: Optional[str] = Field(None, max_length=2000)
    job_status: Optional[JobStatus] = None

    @validator('real_name', 'target_job', 'skills', 'experience_summary', 'self_introduction')
    def sanitize_fields(cls, v):
        if v:
            return sanitize_text(v)
        return v

    @validator('phone')
    def validate_phone_field(cls, v):
        if v:
            return validate_phone(v)
        return v


class CandidateUpdate(BaseModel):
    real_name: Optional[str] = Field(None, max_length=50)
    gender: Optional[str] = None
    birth_date: Optional[str] = Field(None, max_length=50)  # v0.5新增
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = None  # 改为普通字符串，避免空字符串验证问题
    education: Optional[str] = Field(None, max_length=50)  # v0.5新增
    major: Optional[str] = Field(None, max_length=100)  # v0.5新增
    work_experience: Optional[str] = Field(None, max_length=50)  # v0.5新增
    skills: Optional[str] = Field(None, max_length=500)
    target_job: Optional[str] = Field(None, max_length=100)
    expected_salary: Optional[str] = Field(None, max_length=50)  # v0.5新增
    experience_summary: Optional[str] = Field(None, max_length=2000)
    self_introduction: Optional[str] = Field(None, max_length=2000)
    job_status: Optional[str] = None

    @validator('*', pre=True)
    def empty_str_to_none(cls, v):
        """将空字符串转换为None"""
        if v == '':
            return None
        return v

    @validator('real_name', 'major', 'target_job',
               'skills', 'experience_summary', 'self_introduction')
    def sanitize_fields(cls, v):
        if v:
            return sanitize_text(v)
        return v

    @validator('phone')
    def validate_phone_field(cls, v):
        if v and v.strip():  # 确保不是空白字符串
            return validate_phone(v)
        return v

    @validator('email')
    def validate_email_field(cls, v):
        if v and v.strip():  # 如果有值才验证邮箱格式
            if not re.match(
                r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
                    v):
                raise ValueError('邮箱格式不正确')
        return v

    @validator('gender')
    def validate_gender(cls, v):
        if v and v.strip() and v not in ["男", "女", "其他"]:
            raise ValueError('性别必须是：男、女或其他')
        return v

    @validator('job_status')
    def validate_job_status(cls, v):
        if v and v.strip() and v not in ["求职中", "观望中", "已有工作"]:
            raise ValueError('求职状态必须是：求职中、观望中或已有工作')
        return v


class CandidateResponse(BaseModel):
    id: int
    user_id: int
    real_name: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[str] = None  # v0.5新增
    phone: Optional[str] = None
    email: Optional[str] = None
    education: Optional[str] = None  # v0.5新增
    major: Optional[str] = None  # v0.5新增
    work_experience: Optional[str] = None  # v0.5新增
    skills: Optional[str] = None
    target_job: Optional[str] = None
    expected_salary: Optional[str] = None  # v0.5新增
    experience_summary: Optional[str] = None
    self_introduction: Optional[str] = None
    job_status: Optional[str] = None

    class Config:
        from_attributes = True

# HR相关Schema


class HRProfileCreate(BaseModel):
    company_name: Optional[str] = Field(None, max_length=100)
    industry: Optional[str] = Field(None, max_length=50)
    company_size: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    contact_email: Optional[EmailStr] = None
    company_description: Optional[str] = Field(None, max_length=1000)

    @validator('company_name', 'industry', 'company_size',
               'contact_person', 'company_description')
    def sanitize_fields(cls, v):
        if v:
            return sanitize_text(v)
        return v

    @validator('contact_phone')
    def validate_phone_field(cls, v):
        if v:
            return validate_phone(v)
        return v


class HRProfileUpdate(BaseModel):
    company_name: Optional[str] = Field(None, max_length=100)
    industry: Optional[str] = Field(None, max_length=50)
    company_size: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    contact_email: Optional[EmailStr] = None
    company_description: Optional[str] = Field(None, max_length=1000)

    @validator('company_name', 'industry', 'company_size',
               'contact_person', 'company_description')
    def sanitize_fields(cls, v):
        if v:
            return sanitize_text(v)
        return v

    @validator('contact_phone')
    def validate_phone_field(cls, v):
        if v:
            return validate_phone(v)
        return v


class HRProfileResponse(BaseModel):
    id: int
    user_id: int
    company_name: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    company_description: Optional[str] = None

    class Config:
        from_attributes = True


class HRPublicResponse(BaseModel):
    id: int
    company_name: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None

    class Config:
        from_attributes = True

# 岗位相关Schema


class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    required_skills: Optional[str] = Field(None, max_length=255)
    salary_range: Optional[str] = Field(None, max_length=50)
    location: Optional[str] = Field(None, max_length=50)
    education_required: Optional[str] = Field(None, max_length=50)
    work_experience: Optional[str] = Field(None, max_length=50)
    hiring_count: int = Field(default=1, ge=1)


class JobUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1)
    required_skills: Optional[str] = Field(None, max_length=255)
    salary_range: Optional[str] = Field(None, max_length=50)
    location: Optional[str] = Field(None, max_length=50)
    education_required: Optional[str] = Field(None, max_length=50)
    work_experience: Optional[str] = Field(None, max_length=50)
    hiring_count: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = Field(None)


class JobResponse(BaseModel):
    id: int
    hr_id: int
    title: str
    description: Optional[str]
    required_skills: Optional[str]
    salary_range: Optional[str]
    location: Optional[str]
    education_required: Optional[str]
    work_experience: Optional[str]
    status: str
    is_active: bool
    hiring_count: int
    created_at: datetime
    updated_at: datetime
    hr: Optional[HRProfileResponse] = None

    class Config:
        from_attributes = True


class JobPublicResponse(BaseModel):
    id: int
    hr_id: int
    title: str
    description: Optional[str]
    required_skills: Optional[str]
    salary_range: Optional[str]
    location: Optional[str]
    education_required: Optional[str]
    work_experience: Optional[str]
    status: str
    is_active: bool
    hiring_count: int
    created_at: datetime
    updated_at: datetime
    hr: Optional[HRPublicResponse] = None

    class Config:
        from_attributes = True

# 申请相关Schema


class ApplicationCreate(BaseModel):
    job_id: int


class ApplicationResponse(BaseModel):
    id: int
    job_id: int
    candidate_id: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

# 面试相关Schema


class InterviewCreate(BaseModel):
    job_id: Optional[int] = None
    interview_type: Optional[str] = None


class InterviewResponse(BaseModel):
    id: int
    candidate_id: int
    job_id: Optional[int] = None
    interview_type: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InterviewQuestion(BaseModel):
    question: str


class InterviewAnswer(BaseModel):
    answer: str