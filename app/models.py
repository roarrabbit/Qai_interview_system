"""
智能招聘平台 - 面向计算机行业的智能招聘平台
Version: 0.2.7.8
Developer: MLLR
Development Period: 2025.12 ~ 2026.04
License: Apache License 2.0

Description: 数据模型定义模块，使用SQLAlchemy ORM定义所有数据库表结构，包括用户、候选人、招聘者、岗位、申请、面试、报告等核心实体。
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Enum, ForeignKey, Float, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
import enum
import pytz

# 设置时区为东八区
LOCAL_TZ = pytz.timezone('Asia/Shanghai')

# 获取当前本地时间
def get_local_time():
    return datetime.now(LOCAL_TZ)


class UserRole(str, enum.Enum):
    CANDIDATE = "candidate"
    HR = "hr"
    ADMIN = "admin"


class Gender(str, enum.Enum):
    MALE = "男"
    FEMALE = "女"
    OTHER = "其他"


class JobStatus(str, enum.Enum):
    SEEKING = "求职中"
    OBSERVING = "观望中"
    EMPLOYED = "已有工作"


class ApplicationStatus(str, enum.Enum):
    PENDING = "待处理"
    REVIEWED = "已查看"
    INTERVIEW_INVITED = "面试邀约"
    FACE_TO_FACE = "线下面试"
    SUCCESSFULLY_JOINED = "成功入职"
    REJECTED = "已拒绝"


class InterviewStatus(str, enum.Enum):
    IN_PROGRESS = "进行中"
    COMPLETED = "已完成"
    CANCELLED = "已取消"


class OverallGrade(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, index=True)
    created_at = Column(DateTime, default=get_local_time)
    updated_at = Column(
        DateTime,
        default=get_local_time,
        onupdate=get_local_time)

    # 关系
    candidate = relationship(
        "Candidate",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan")
    hr_profile = relationship(
        "HRProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE"),
        unique=True,
        nullable=False)
    real_name = Column(String(50))
    gender = Column(String(10))
    birth_date = Column(String(50), comment="出生日期")
    phone = Column(String(20))
    email = Column(String(100))
    education = Column(String(50), comment="学历")
    major = Column(String(100), comment="专业")
    work_experience = Column(String(50), comment="工作年限")
    skills = Column(Text, comment="技能标签，逗号分隔")
    target_job = Column(String(100), comment="求职意向岗位", index=True)
    expected_salary = Column(String(50), comment="期望薪资")
    experience_summary = Column(Text, comment="经验摘要")
    self_introduction = Column(Text, comment="个人简介")
    job_status = Column(String(20), default="求职中", comment="求职状态", index=True)
    created_at = Column(DateTime, default=get_local_time)
    updated_at = Column(
        DateTime,
        default=get_local_time,
        onupdate=get_local_time)

    # 创建sql的关联关系
    user = relationship("User", back_populates="candidate")
    applications = relationship(
        "Application",
        back_populates="candidate",
        cascade="all, delete-orphan")
    interviews = relationship(
        "Interview",
        back_populates="candidate",
        cascade="all, delete-orphan")


class HRProfile(Base):
    __tablename__ = "hr_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE"),
        unique=True,
        nullable=False)
    company_name = Column(String(100))
    industry = Column(String(50))
    company_size = Column(String(50), comment="公司规模")
    contact_person = Column(String(50))
    contact_phone = Column(String(20))
    contact_email = Column(String(100))
    company_description = Column(Text)
    created_at = Column(DateTime, default=get_local_time)
    updated_at = Column(
        DateTime,
        default=get_local_time,
        onupdate=get_local_time)

    # 关系
    user = relationship("User", back_populates="hr_profile")
    jobs = relationship(
        "Job",
        back_populates="hr",
        foreign_keys="Job.hr_id",
        cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    hr_id = Column(
        Integer,
        ForeignKey(
            "hr_profiles.id",
            ondelete="CASCADE"),
        nullable=False,
        index=True)
    title = Column(String(100), nullable=False)
    description = Column(Text)
    required_skills = Column(Text, comment="所需技能，逗号分隔")
    salary_range = Column(String(50))
    location = Column(String(50))
    education_required = Column(String(50), comment="学历要求")
    work_experience = Column(String(50), comment="工作经验要求")
    status = Column(String(20), default="active", comment="岗位状态")
    is_active = Column(Boolean, default=True, index=True)
    hiring_count = Column(Integer, default=1, comment="招聘人数")
    created_at = Column(DateTime, default=get_local_time, index=True)
    updated_at = Column(
        DateTime,
        default=get_local_time,
        onupdate=get_local_time)

    # 关系
    hr = relationship("HRProfile", back_populates="jobs")
    applications = relationship(
        "Application",
        back_populates="job",
        cascade="all, delete-orphan")
    interviews = relationship("Interview", back_populates="job")


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(
        Integer,
        ForeignKey(
            "jobs.id",
            ondelete="CASCADE"),
        nullable=False,
        index=True)
    candidate_id = Column(
        Integer,
        ForeignKey(
            "candidates.id",
            ondelete="CASCADE"),
        nullable=False,
        index=True)
    status = Column(String(20), default="待处理", index=True)
    match_score = Column(Float, comment="匹配度分数 0-1", default=0.0)
    
    # 面试邀约相关字段
    interview_location = Column(String(255), comment="面试地点")
    interview_time = Column(DateTime, comment="面试时间")
    interviewer_info = Column(Text, comment="面试官信息")
    interview_notes = Column(Text, comment="面试须知/备注")
    
    # 入职通知相关字段
    offer_sent = Column(Boolean, default=False, comment="是否已发送入职通知")
    offer_accepted = Column(Boolean, default=False, comment="候选人是否接受入职通知")
    
    # 流程追踪字段
    created_at = Column(DateTime, default=get_local_time)
    updated_at = Column(
        DateTime,
        default=get_local_time,
        onupdate=get_local_time)
    interview_invited_at = Column(DateTime, comment="发送面试邀约的时间")
    interview_confirmed_at = Column(DateTime, comment="候选人确认面试的时间")
    interview_completed_at = Column(DateTime, comment="线下面试完成的时间")
    offer_sent_at = Column(DateTime, comment="发送入职通知的时间")

    # 关系
    job = relationship("Job", back_populates="applications")
    candidate = relationship("Candidate", back_populates="applications")


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(
        Integer,
        ForeignKey(
            "candidates.id",
            ondelete="CASCADE"),
        nullable=False,
        index=True)
    job_id = Column(
        Integer,
        ForeignKey(
            "jobs.id",
            ondelete="SET NULL"),
        nullable=True)
    application_id = Column(
        Integer,
        ForeignKey(
            "applications.id",
            ondelete="SET NULL"),
        nullable=True,
        comment="关联申请")
    interview_type = Column(String(50), comment="面试类型/难度")
    conversation = Column(JSON, comment="面试对话记录")
    status = Column(String(20), default="in_progress", index=True)
    started_at = Column(DateTime, default=get_local_time)
    completed_at = Column(DateTime)

    # 关系
    candidate = relationship("Candidate", back_populates="interviews")
    job = relationship("Job", back_populates="interviews")
    application = relationship("Application")
    report = relationship(
        "InterviewReport",
        back_populates="interview",
        uselist=False,
        cascade="all, delete-orphan")


class InterviewReport(Base):
    __tablename__ = "interview_reports"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(
        Integer,
        ForeignKey(
            "interviews.id",
            ondelete="CASCADE"),
        unique=True,
        nullable=False)

    # 新的6维度评分
    domain_insight_score = Column(Integer, comment="专业领域深度洞察 0-100")
    team_collaboration_score = Column(Integer, comment="团队协作与技术推动 0-100")
    technical_vision_score = Column(Integer, comment="技术深度与前瞻视野 0-100")
    practical_ability_score = Column(Integer, comment="技术基础与实践能力 0-100")
    architecture_design_score = Column(Integer, comment="系统架构设计思维 0-100")
    authenticity_score = Column(Integer, comment="项目经历 0-100")

    overall_grade = Column(String(5), comment="综合评级")
    strengths = Column(Text, comment="优势总结")
    weaknesses = Column(Text, comment="待改进项")
    suggestions = Column(Text, comment="改进建议")
    radar_data = Column(JSON, comment="雷达图数据")
    created_at = Column(DateTime, default=get_local_time)

    # 关系
    interview = relationship("Interview", back_populates="report")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(20), nullable=False)
    source_id = Column(Integer, nullable=False, index=True)
    target_type = Column(String(20), nullable=False)
    target_id = Column(Integer, nullable=False, index=True)
    similarity_score = Column(Float, index=True)
    created_at = Column(DateTime, default=get_local_time)


class SystemConfig(Base):
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(50), unique=True, nullable=False, index=True)
    config_value = Column(Text)
    description = Column(String(255))
    updated_at = Column(
        DateTime,
        default=get_local_time,
        onupdate=get_local_time)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE"),
        nullable=False)
    receiver_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE"),
        nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    job_id = Column(
        Integer,
        ForeignKey(
            "jobs.id",
            ondelete="SET NULL"),
        nullable=True,
        comment="关联的岗位ID（求职者咨询岗位时）")
    extra_data = Column(JSON, comment="额外元数据，如候选人信息快照")
    created_at = Column(DateTime, default=get_local_time)

    # 关系
    sender = relationship("User", foreign_keys=[sender_id])
    receiver = relationship("User", foreign_keys=[receiver_id])
    job = relationship("Job")


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False, index=True,
                   comment="日志级别: info/warning/error/success")
    message = Column(Text, nullable=False, comment="日志消息")
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL"),
        nullable=True,
        comment="相关用户ID")
    module = Column(String(50), comment="模块名称")
    created_at = Column(DateTime, default=get_local_time, index=True)

    # 关系
    user = relationship("User", foreign_keys=[user_id])

