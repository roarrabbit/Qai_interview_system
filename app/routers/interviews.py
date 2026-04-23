# 导入必要的模块和依赖
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import List
from datetime import datetime
from app.database import get_db, SessionLocal
from app.models import Interview, InterviewReport, Job, Candidate, User, Message, HRProfile, SystemConfig, Application, InterviewStatus
from app.schemas import InterviewCreate, InterviewResponse
from app.auth import get_current_user, get_current_candidate
from app.ai_conversation import ai_conversation_interviewer
from app.logger import log_ai_question, log_ai_answer, log_ai_evaluation, log_ai_report, ai_logger
from app.interview_security import check_malicious_input, get_warning_text
import json

# 初始化路由器，设置路由前缀和标签
router = APIRouter(prefix="/api/interviews", tags=["面试"])


# 后台任务：生成AI面试报告
def generate_report_background(
        interview_id: int,         # 面试ID
        candidate_id: int,         # 候选人ID
        user_id: int,              # 用户ID
        conversation: list,        # 对话历史
        job_id: int = None):       # 职位ID（可选）
    """后台任务：生成AI面试报告"""
    # 创建数据库会话
    db = SessionLocal()
    try:
        # 查询面试信息
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            ai_logger.error(f"面试不存在: {interview_id}")
            return

        # 查询候选人信息
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            ai_logger.error(f"候选人不存在: {candidate_id}")
            return

        # 初始化职位上下文信息
        job_context = {"job_title": "通用岗位"}
        
        # 如果提供了职位ID，查询职位信息并更新上下文
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job_context["job_title"] = job.title
                job_context["description"] = job.description or ""
                job_context["required_skills"] = job.required_skills or ""

        # 记录开始生成报告的日志
        ai_logger.info(f"开始生成面试报告 - 面试ID: {interview_id}")
        
        # 调用AI生成面试报告
        report_data = ai_conversation_interviewer.generate_report_from_conversation(
            conversation, job_context
        )

        # 创建面试报告记录
        radar_data = report_data.get("radar_data", [10, 10, 10, 10, 10, 10])
        # 确保分数是整数
        if isinstance(radar_data, list):
            radar_data = [int(x) if isinstance(x, (int, float)) else 10 for x in radar_data]

        report = InterviewReport(
            interview_id=interview_id,
            domain_insight_score=int(report_data.get("domain_insight_score", 10)),
            team_collaboration_score=int(report_data.get("team_collaboration_score", 10)),
            technical_vision_score=int(report_data.get("technical_vision_score", 10)),
            practical_ability_score=int(report_data.get("practical_ability_score", 10)),
            architecture_design_score=int(report_data.get("architecture_design_score", 10)),
            authenticity_score=int(report_data.get("authenticity_score", 10)),
            overall_grade=report_data.get("overall_grade", "C"),
            strengths=report_data.get("strengths", "暂无"),
            weaknesses=report_data.get("weaknesses", "暂无"),
            suggestions=report_data.get("suggestions", "暂无"),
            radar_data=radar_data
        )
        # 保存报告到数据库
        db.add(report)
        db.commit()
        db.refresh(report)

        # 记录AI报告日志
        log_ai_report(interview_id, user_id, report_data)

        # 记录面试完成日志
        from app.logger import log_interview_completed
        user = db.query(User).filter(User.id == user_id).first()
        candidate_username = user.username if user else str(user_id)
        job_title = job_context.get('job_title', '通用岗位')
        log_interview_completed(interview_id, candidate_username, job_title, report_data['overall_grade'])
        
        # 记录报告生成完成的日志
        ai_logger.info(f"面试报告生成完成 - 面试ID: {interview_id}, 评级: {report_data['overall_grade']}")

    except Exception as e:
        # 记录报告生成失败的错误
        ai_logger.error(f"报告生成失败: {str(e)}")
    finally:
        # 关闭数据库会话
        db.close()


# 获取我的面试列表
@router.get("/", response_model=List[InterviewResponse])
def get_my_interviews(
    current_user: User = Depends(get_current_candidate),  # 当前候选人用户
    db: Session = Depends(get_db)  # 数据库会话
):
    """获取我的面试列表"""
    # 查询当前用户对应的候选人信息
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    # 查询该候选人的所有面试，按开始时间倒序排列
    interviews = db.query(Interview).filter(
        Interview.candidate_id == candidate.id
    ).order_by(Interview.started_at.desc()).all()
    return interviews


# 开始新的对话式面试
@router.post("/", response_model=InterviewResponse)
def create_interview(
    interview_data: InterviewCreate,  # 面试创建数据
    current_user: User = Depends(get_current_candidate),  # 当前候选人用户
    db: Session = Depends(get_db)  # 数据库会话
):
    """开始新的对话式面试"""
    # 查询当前用户对应的候选人信息
    candidate = db.query(Candidate).filter(Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="请先完善个人信息")

    # 初始化职位信息和难度
    job_title = "通用岗位"
    difficulty = interview_data.interview_type or "中级"
    job_info = None
    application_id = None

    # 如果提供了职位ID，查询职位信息
    if interview_data.job_id:
        job = db.query(Job).filter(Job.id == interview_data.job_id).first()
        if job:
            job_title = job.title
            job_description = job.description or ""
            required_skills = job.required_skills or ""
            # 自动检测面试难度
            difficulty = ai_conversation_interviewer.auto_detect_difficulty(job_description, required_skills)
            ai_logger.info(f"面试岗位: {job_title}, 自动判断难度: {difficulty}")

            # 构建职位信息
            job_info = {
                "title": job.title,
                "description": job.description or "",
                "required_skills": job.required_skills or "",
                "education_required": job.education_required or "",
                "location": job.location or "",
                "salary_range": job.salary_range or ""
            }

            # 查询是否有相关的职位申请
            application = db.query(Application).filter(
                Application.job_id == interview_data.job_id,
                Application.candidate_id == candidate.id
            ).first()

            if application:
                application_id = application.id

    # 构建面试类型
    interview_type_value = "对话式-" + difficulty
    # 创建面试记录
    interview = Interview(
        candidate_id=candidate.id,
        job_id=interview_data.job_id,
        application_id=application_id,
        interview_type=interview_type_value,
        conversation=[],
        status=InterviewStatus.IN_PROGRESS.value  # 设置为进行中状态
    )
    # 保存面试记录
    db.add(interview)
    db.commit()
    db.refresh(interview)

    # 构建候选人信息
    candidate_info = {
        "real_name": candidate.real_name or "",
        "education": candidate.education or "",
        "major": candidate.major or "",
        "work_experience": candidate.work_experience or "",
        "skills": candidate.skills or "",
        "target_job": candidate.target_job or "",
        "experience_summary": candidate.experience_summary or "",
        "self_introduction": candidate.self_introduction or ""
    }

    # 生成AI面试官的问候语
    greeting = ai_conversation_interviewer.generate_greeting(job_info, candidate_info)

    # 初始化对话历史，包含系统信息和问候语
    # 注意：greeting已经包含第一个技术问题，所以question_count初始化为1
    interview.conversation = [
        {
            "role": "system",  # 系统角色
            "difficulty": difficulty,  # 面试难度
            "job_info": job_info,  # 职位信息
            "candidate_info": candidate_info,  # 候选人信息
            "question_count": 1,  # 问题计数（greeting已包含第一题）
            "is_ended": False  # 面试是否结束
        },
        {"role": "interviewer", "content": greeting, "timestamp": datetime.now().isoformat()}  # 面试官的问候语
    ]
    # 标记conversation字段已修改
    flag_modified(interview, "conversation")
    db.commit()
    db.refresh(interview)

    # 记录AI问题日志
    log_ai_question(interview.id, candidate.id, greeting)

    return interview


# 发送消息并获取AI响应
@router.post("/{interview_id}/message")
async def send_message(
    interview_id: int,  # 面试ID
    message_data: dict,  # 消息数据
    background_tasks: BackgroundTasks,  # 后台任务
    current_user: User = Depends(get_current_candidate),  # 当前候选人用户
    db: Session = Depends(get_db)  # 数据库会话
):
    """发送消息并获取AI响应"""
    # 查询当前用户对应的候选人信息
    candidate = db.query(Candidate).filter(Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    # 查询面试信息
    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    # 检查面试状态
    if interview.status != InterviewStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=400, detail="面试已结束")

    # 获取对话历史
    conversation = interview.conversation or []
    # 获取系统信息
    system_info = conversation[0] if conversation and conversation[0].get("role") == "system" else None
    if not system_info:
        raise HTTPException(status_code=500, detail="面试数据异常")

    # 获取用户消息
    user_message = message_data.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    # 检查恶意输入
    is_blocked, warning_msg = check_malicious_input(user_message)
    if is_blocked:
        # 增加警告计数
        warning_count = system_info.get("warning_count", 0) + 1
        system_info["warning_count"] = warning_count
        conversation[0] = system_info
        # 标记conversation字段已修改
        flag_modified(interview, "conversation")
        db.commit()
        
        # 记录恶意输入警告
        ai_logger.warning(f"恶意输入检测 - 面试ID: {interview_id}, 警告次数: {warning_count}, 原因: {warning_msg}")
        
        # 如果警告次数达到3次，结束面试
        if warning_count >= 3:
            interview.status = InterviewStatus.COMPLETED.value
            from app.models import get_local_time
            interview.completed_at = get_local_time()
            db.commit()
            
            return {
                "response": "由于多次发送不当内容，面试已结束。",
                "is_ended": True,
                "question_count": system_info.get("question_count", 0),
                "warning": "面试已因违规行为终止"
            }
        
        # 返回警告信息
        return {
            "response": get_warning_text(warning_count),
            "is_ended": False,
            "question_count": system_info.get("question_count", 0),
            "warning": f"警告 ({warning_count}/3)：{warning_msg}"
        }

    # 添加用户消息到对话历史
    conversation.append({
        "role": "candidate",
        "content": user_message,
        "timestamp": datetime.now().isoformat()
    })
    # 记录AI回答日志
    log_ai_answer(interview.id, candidate.id, user_message)

    # 获取系统信息中的参数
    difficulty = system_info.get("difficulty", "中级")
    job_info = system_info.get("job_info")
    candidate_info = system_info.get("candidate_info")
    question_count = system_info.get("question_count", 0)
    
    # 判断面试类型并获取对应的配置
    # 优先从interview.job_id判断，确保即使system_info中的job_info丢失也能正确判断
    is_from_job = interview.job_id is not None or job_info is not None
    interview_type = "job_interview" if is_from_job else "personal_interview"
    
    # 从AI面试官实例中获取配置的最大问题数
    max_questions = ai_conversation_interviewer.job_interview_questions if is_from_job else ai_conversation_interviewer.personal_interview_questions
    ai_logger.info(f"使用配置的最大问题数: {max_questions} (岗位面试: {is_from_job}, job_id: {interview.job_id})")

    # 检查是否已经达到最大问题数，如果是则直接结束面试
    if question_count >= max_questions:
        ai_response = "今天的面试就到这里，感谢你的时间，我们会有后续通知。"
        is_ended = True
    else:
        # 生成AI响应
        ai_response = ai_conversation_interviewer.generate_next_response(
            conversation_history=conversation,
            difficulty=difficulty,
            interview_type=interview_type,
            job_info=job_info,
            candidate_info=candidate_info,
            question_count=question_count,
            max_questions=max_questions
        )

        # 检查面试是否结束
        is_ended = ai_conversation_interviewer.is_interview_ended(ai_response)

        # 如果不是结束消息且包含问题，增加问题计数
        if not is_ended and ("?" in ai_response or "？" in ai_response):
            question_count += 1
            system_info["question_count"] = question_count

    # 添加AI响应到对话历史
    conversation.append({
        "role": "interviewer",
        "content": ai_response,
        "timestamp": datetime.now().isoformat()
    })

    # 更新系统信息中的结束状态
    system_info["is_ended"] = is_ended
    conversation[0] = system_info

    # 更新面试的对话历史
    interview.conversation = conversation
    # 标记conversation字段已修改
    flag_modified(interview, "conversation")

    # 如果面试结束，更新状态并生成报告
    if is_ended:
        interview.status = InterviewStatus.COMPLETED.value
        from app.models import get_local_time
        interview.completed_at = get_local_time()
        db.commit()

        # 准备后台任务参数
        interview_id_to_process = interview.id
        candidate_id_to_process = candidate.id
        user_id_to_process = current_user.id
        job_id_to_process = interview.job_id
        conversation_copy = list(conversation)

        # 添加生成报告的后台任务
        background_tasks.add_task(
            generate_report_background,
            interview_id=interview_id_to_process,
            candidate_id=candidate_id_to_process,
            user_id=user_id_to_process,
            conversation=conversation_copy,
            job_id=job_id_to_process
        )
    else:
        db.commit()

    # 记录AI问题日志
    log_ai_question(interview.id, candidate.id, ai_response)

    # 返回响应
    return {
        "response": ai_response,
        "is_ended": is_ended,
        "question_count": question_count
    }


# 发送消息并获取流式AI响应
@router.post("/{interview_id}/message/stream")
async def send_message_stream(
    interview_id: int,  # 面试ID
    message_data: dict,  # 消息数据
    current_user: User = Depends(get_current_candidate),  # 当前候选人用户
    db: Session = Depends(get_db),  # 数据库会话
    background_tasks: BackgroundTasks = BackgroundTasks()  # 后台任务
):
    """发送消息并获取流式AI响应"""
    # 查询当前用户对应的候选人信息
    candidate = db.query(Candidate).filter(Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    # 查询面试信息
    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    # 检查面试状态
    if interview.status != InterviewStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=400, detail="面试已结束")

    # 获取对话历史
    conversation = interview.conversation or []
    # 获取系统信息
    system_info = conversation[0] if conversation and conversation[0].get("role") == "system" else None
    if not system_info:
        raise HTTPException(status_code=500, detail="面试数据异常")

    # 获取用户消息
    user_message = message_data.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    # 检查恶意输入
    is_blocked, warning_msg = check_malicious_input(user_message)
    if is_blocked:
        # 增加警告计数
        warning_count = system_info.get("warning_count", 0) + 1
        system_info["warning_count"] = warning_count
        conversation[0] = system_info
        # 标记conversation字段已修改
        flag_modified(interview, "conversation")
        db.commit()
        
        # 记录恶意输入警告
        ai_logger.warning(f"恶意输入检测 - 面试ID: {interview_id}, 警告次数: {warning_count}, 原因: {warning_msg}")
        
        # 生成警告流响应
        async def warning_stream():
            if warning_count >= 3:
                # 如果警告次数达到3次，结束面试
                interview.status = InterviewStatus.COMPLETED.value
                from app.models import get_local_time
                interview.completed_at = get_local_time()
                db.commit()
                
                # 发送结束消息
                yield f"data: {json.dumps({'chunk': '由于多次发送不当内容，面试已结束。'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'is_ended': True, 'warning': '面试已因违规行为终止'}, ensure_ascii=False)}\n\n"
            else:
                # 发送警告消息
                yield f"data: {json.dumps({'chunk': get_warning_text(warning_count)}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'is_ended': False, 'warning': f'警告 ({warning_count}/3)：{warning_msg}'}, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(warning_stream(), media_type="text/event-stream")

    # 添加用户消息到对话历史
    conversation.append({
        "role": "candidate",
        "content": user_message,
        "timestamp": datetime.now().isoformat()
    })
    # 记录AI回答日志
    log_ai_answer(interview.id, candidate.id, user_message)

    # 获取系统信息中的参数
    difficulty = system_info.get("difficulty", "中级")
    job_info = system_info.get("job_info")
    candidate_info = system_info.get("candidate_info")
    question_count = system_info.get("question_count", 0)
    
    # 判断面试类型并获取对应的配置
    # 优先从interview.job_id判断，确保即使system_info中的job_info丢失也能正确判断
    is_from_job = interview.job_id is not None or job_info is not None
    interview_type = "job_interview" if is_from_job else "personal_interview"
    
    # 从AI面试官实例中获取配置的最大问题数
    max_questions = ai_conversation_interviewer.job_interview_questions if is_from_job else ai_conversation_interviewer.personal_interview_questions
    ai_logger.info(f"使用配置的最大问题数: {max_questions} (岗位面试: {is_from_job}, job_id: {interview.job_id})")

    # 生成流式响应
    async def generate_stream():
        nonlocal question_count
        
        # 检查是否已经达到最大问题数，如果是则直接结束面试
        if question_count >= max_questions:
            full_response = "今天的面试就到这里，感谢你的时间，我们会有后续通知。"
            is_ended = True
            yield f"data: {json.dumps({'chunk': full_response}, ensure_ascii=False)}\n\n"
        else:
            full_response = ""
            is_ended = False
            
            # 生成流式AI响应
            stream = ai_conversation_interviewer.generate_next_response_stream(
                conversation_history=conversation,
                difficulty=difficulty,
                interview_type=interview_type,
                job_info=job_info,
                candidate_info=candidate_info,
                question_count=question_count,
                max_questions=max_questions
            )

            # 流式发送响应
            for chunk in stream:
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"

            # 检查面试是否结束
            is_ended = ai_conversation_interviewer.is_interview_ended(full_response)

            # 如果不是结束消息且包含问题，增加问题计数
            if not is_ended and ("?" in full_response or "？" in full_response):
                question_count += 1
                system_info["question_count"] = question_count

        # 添加AI响应到对话历史
        conversation.append({
            "role": "interviewer",
            "content": full_response,
            "timestamp": datetime.now().isoformat()
        })

        # 更新系统信息中的结束状态
        system_info["is_ended"] = is_ended
        conversation[0] = system_info

        # 更新面试的对话历史
        interview.conversation = conversation
        # 标记conversation字段已修改
        flag_modified(interview, "conversation")

        # 如果面试结束，更新状态并生成报告
        # 先发送结束消息，让客户端快速收到
        yield f"data: {json.dumps({'done': True, 'is_ended': is_ended, 'question_count': question_count}, ensure_ascii=False)}\n\n"

        if is_ended:
            interview.status = InterviewStatus.COMPLETED.value
            from app.models import get_local_time
            interview.completed_at = get_local_time()
            
            # 添加生成报告的后台任务
            interview_id_to_process = interview.id
            candidate_id_to_process = candidate.id
            background_tasks.add_task(
                generate_report_background,
                interview_id=interview_id_to_process,
                candidate_id=candidate_id_to_process,
                job_id=interview.job_id
            )
            ai_logger.info(f"已添加生成面试报告的后台任务 - 面试ID: {interview_id_to_process}")

        # 后台执行数据库操作和日志记录
        db.commit()
        log_ai_question(interview.id, candidate.id, full_response)

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


# 获取面试详情
@router.get("/{interview_id}")
def get_interview(
    interview_id: int,  # 面试ID
    current_user: User = Depends(get_current_candidate),  # 当前候选人用户
    db: Session = Depends(get_db)  # 数据库会话
):
    """获取面试详情"""
    # 查询当前用户对应的候选人信息
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    # 查询面试信息
    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    # 获取对话历史
    conversation = interview.conversation or []
    # 获取系统信息
    system_info = conversation[0] if conversation and conversation[0].get("role") == "system" else None

    # 提取消息列表（只包含面试官和候选人的消息）
    messages = []
    for msg in conversation:
        if msg.get("role") in ["interviewer", "candidate"]:
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
                "timestamp": msg.get("timestamp")
            })

    # 初始化结束状态和问题计数
    is_ended = False
    question_count = 0
    if system_info:
        is_ended = system_info.get("is_ended", False)
        question_count = system_info.get("question_count", 0)

    # 返回面试详情
    return {
        "interview": interview,
        "messages": messages,
        "is_ended": is_ended,
        "question_count": question_count,
        "status": interview.status
    }


# 获取面试报告
@router.get("/{interview_id}/report")
def get_interview_report(
    interview_id: int,  # 面试ID
    current_user: User = Depends(get_current_candidate),  # 当前候选人用户
    db: Session = Depends(get_db)  # 数据库会话
):
    """获取面试报告"""
    # 查询当前用户对应的候选人信息
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    # 查询面试信息
    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    # 查询面试报告
    report = db.query(InterviewReport).filter(
        InterviewReport.interview_id == interview_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    return report


# 将面试报告发送给HR
@router.post("/{interview_id}/send-to-hr")
def send_report_to_hr(
    interview_id: int,  # 面试ID
    current_user: User = Depends(get_current_candidate),  # 当前候选人用户
    db: Session = Depends(get_db)  # 数据库会话
):
    """将面试报告发送给HR"""
    # 查询当前用户对应的候选人信息
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    # 查询面试信息
    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    # 检查面试是否关联了职位
    if not interview.job_id:
        raise HTTPException(status_code=400, detail="该面试未关联职位，无法发送给HR")

    # 查询面试报告
    report = db.query(InterviewReport).filter(
        InterviewReport.interview_id == interview_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="报告尚未生成，请稍后再试")

    # 查询职位信息
    job = db.query(Job).filter(Job.id == interview.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")

    # 查询HR信息
    hr_profile = db.query(HRProfile).filter(HRProfile.id == job.hr_id).first()
    if not hr_profile:
        raise HTTPException(status_code=404, detail="HR信息不存在")

    # 查询HR用户
    hr = db.query(User).filter(User.id == hr_profile.user_id).first()
    if not hr:
        raise HTTPException(status_code=404, detail="HR用户不存在")

    # 获取候选人姓名
    candidate_name = candidate.real_name if candidate.real_name else current_user.username

    # 构建消息内容
    message_content = f"""【AI面试结果通知】<br><br>

• 候选人：{candidate_name}<br>
• 应聘岗位：{job.title}<br>
• 面试评级：{report.overall_grade} 级<br>

• 能力评估（满分20分）：
  专业深度：{report.domain_insight_score}分 - {"优秀" if report.domain_insight_score >= 16 else "良好" if report.domain_insight_score >= 14 else "一般"}<br>
  团队协作：{report.team_collaboration_score}分 - {"优秀" if report.team_collaboration_score >= 16 else "良好" if report.team_collaboration_score >= 14 else "一般"}<br>
  技术视野：{report.technical_vision_score}分 - {"优秀" if report.technical_vision_score >= 16 else "良好" if report.technical_vision_score >= 14 else "一般"}<br>
  实践能力：{report.practical_ability_score}分 - {"优秀" if report.practical_ability_score >= 16 else "良好" if report.practical_ability_score >= 14 else "一般"}<br>
  架构设计：{report.architecture_design_score}分 - {"优秀" if report.architecture_design_score >= 16 else "良好" if report.architecture_design_score >= 14 else "一般"}<br>
  项目经历：{report.authenticity_score}分 - {"优秀" if report.authenticity_score >= 16 else "良好" if report.authenticity_score >= 14 else "一般"}<br>

• 优势亮点：
{report.strengths}<br>

• 完整报告链接：<a href='/interview/{interview_id}/report' target='_blank'>点击查看完整面试报告</a><br><br>

• 候选人已授权查看完整报告，建议安排进一步面试。"""

    # 创建消息记录
    message = Message(
        sender_id=current_user.id,  # 发送者ID
        receiver_id=hr.id,  # 接收者ID（HR）
        content=message_content,  # 消息内容
        is_read=False,  # 未读状态
        job_id=job.id,  # 职位ID
        extra_data=json.dumps({
            "type": "interview_result",  # 消息类型
            "interview_id": interview_id,  # 面试ID
            "report_id": report.id,  # 报告ID
            "candidate_id": candidate.id  # 候选人ID
        }, ensure_ascii=False)  # 额外数据
    )
    # 保存消息到数据库
    db.add(message)
    db.commit()

    # 返回成功消息
    return {
        "message": "报告已成功发送给HR",
        "hr_name": hr.username,
        "job_title": job.title
    }


# 删除面试记录
@router.delete("/{interview_id}")
def delete_interview(
    interview_id: int,  # 面试ID
    current_user: User = Depends(get_current_candidate),  # 当前候选人用户
    db: Session = Depends(get_db)  # 数据库会话
):
    """删除面试记录"""
    # 查询当前用户对应的候选人信息
    candidate = db.query(Candidate).filter(
        Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    # 查询面试信息
    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    # 查询并删除相关的面试报告
    report = db.query(InterviewReport).filter(
        InterviewReport.interview_id == interview_id).first()
    if report:
        db.delete(report)

    # 删除面试记录
    db.delete(interview)
    db.commit()

    return {"message": "面试记录已删除"}
