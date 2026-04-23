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
import asyncio

router = APIRouter(prefix="/api/conversation-interview", tags=["对话式面试"])


def generate_report_background(
        interview_id: int,
        candidate_id: int,
        user_id: int,
        conversation: list,
        job_id: int = None):
    """后台任务：生成AI面试报告"""
    db = SessionLocal()
    try:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            ai_logger.error(f"面试不存在: {interview_id}")
            return

        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            ai_logger.error(f"候选人不存在: {candidate_id}")
            return

        job_context = {"job_title": "通用岗位"}
        
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job_context["job_title"] = job.title
                job_context["description"] = job.description or ""
                job_context["required_skills"] = job.required_skills or ""

        ai_logger.info(f"开始生成面试报告 - 面试ID: {interview_id}")
        
        report_data = ai_conversation_interviewer.generate_report_from_conversation(
            conversation, job_context
        )
        
        ai_logger.debug(f"报告数据类型: {type(report_data)}")
        ai_logger.debug(f"报告数据键: {report_data.keys() if isinstance(report_data, dict) else 'N/A'}")
        
        if not isinstance(report_data, dict):
            ai_logger.error(f"报告数据类型错误: {type(report_data)}")
            return

        radar_data = report_data.get("radar_data", [10, 10, 10, 10, 10, 10])
        ai_logger.debug(f"radar_data类型: {type(radar_data)}, 值: {radar_data}")

        # 确保分数是整数
        if isinstance(radar_data, list):
            radar_data = [int(x) if isinstance(x, (int, float)) else 10 for x in radar_data]

        # radar_data 直接传递给 JSON 列，不需要 json.dumps
        report = InterviewReport(
            interview_id=interview_id,
            domain_insight_score=int(report_data.get("domain_insight_score", 10)),
            team_collaboration_score=int(report_data.get("team_collaboration_score", 10)),
            technical_vision_score=int(report_data.get("technical_vision_score", 10)),
            practical_ability_score=int(report_data.get("practical_ability_score", 10)),
            architecture_design_score=int(report_data.get("architecture_design_score", 10)),
            authenticity_score=int(report_data.get("authenticity_score", 10)),
            overall_grade=str(report_data.get("overall_grade", "C")),
            strengths=str(report_data.get("strengths", "暂无")),
            weaknesses=str(report_data.get("weaknesses", "暂无")),
            suggestions=str(report_data.get("suggestions", "暂无")),
            radar_data=radar_data
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        log_ai_report(interview_id, user_id, report_data)

        from app.logger import log_interview_completed
        user = db.query(User).filter(User.id == user_id).first()
        candidate_username = user.username if user else str(user_id)
        job_title = job_context.get('job_title', '通用岗位')
        log_interview_completed(interview_id, candidate_username, job_title, report_data.get('overall_grade', 'C'))
        
        ai_logger.info(f"面试报告生成完成 - 面试ID: {interview_id}, 评级: {report_data.get('overall_grade', 'C')}")

    except Exception as e:
        import traceback
        ai_logger.error(f"报告生成失败: {str(e)}")
        ai_logger.error(f"错误堆栈: {traceback.format_exc()}")
    finally:
        db.close()


@router.post("/", response_model=InterviewResponse)
async def create_conversation_interview(
    interview_data: InterviewCreate,
    current_user: User = Depends(get_current_candidate),
    db: Session = Depends(get_db)
):
    """开始新的对话式面试"""
    candidate = db.query(Candidate).filter(Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="请先完善个人信息")

    job_title = "通用岗位"
    difficulty = "中级"
    job_info = None
    application_id = None

    if interview_data.job_id:
        job = db.query(Job).filter(Job.id == interview_data.job_id).first()
        if job:
            job_title = job.title
            job_description = job.description or ""
            required_skills = job.required_skills or ""
            difficulty = ai_conversation_interviewer.auto_detect_difficulty(job_description, required_skills)
            ai_logger.info(f"面试岗位: {job_title}, 自动判断难度: {difficulty}")

            job_info = {
                "title": job.title,
                "description": job.description or "",
                "required_skills": job.required_skills or "",
                "education_required": job.education_required or "",
                "location": job.location or "",
                "salary_range": job.salary_range or ""
            }

            application = db.query(Application).filter(
                Application.job_id == interview_data.job_id,
                Application.candidate_id == candidate.id
            ).first()

            if application:
                application_id = application.id

    interview_type_value = "对话式-" + difficulty
    
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

    max_questions = interview_data.job_interview_questions if interview_data.job_id else interview_data.personal_interview_questions

    async def generate_stream():
        nonlocal job_info, difficulty
        
        interview = Interview(
            candidate_id=candidate.id,
            job_id=interview_data.job_id,
            application_id=application_id,
            interview_type=interview_type_value,
            conversation=[],
            status=InterviewStatus.IN_PROGRESS.value
        )
        db.add(interview)
        db.commit()
        db.refresh(interview)
        
        interview_id = interview.id
        greeting_chunks = []
        full_greeting = ""
        stream_error = False
        
        try:
            stream = ai_conversation_interviewer.generate_greeting_stream(job_info, candidate_info, max_questions)
            
            for chunk in stream:
                full_greeting += chunk
                greeting_chunks.append(chunk)
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                
        except Exception as e:
            import traceback
            ai_logger.error(f"开场白流式生成失败: {str(e)}")
            ai_logger.error(f"错误堆栈: {traceback.format_exc()}")
            stream_error = True
            yield f"data: {json.dumps({'error': '开场白生成失败，请重试'}, ensure_ascii=False)}\n\n"
        
        if stream_error:
            interview.status = InterviewStatus.CANCELLED.value
            db.commit()
            yield f"data: {json.dumps({'done': True, 'success': False, 'interview_id': interview_id}, ensure_ascii=False)}\n\n"
        else:
            interview.conversation = [
                {
                    "role": "system",
                    "difficulty": difficulty,
                    "job_info": job_info,
                    "candidate_info": candidate_info,
                    "question_count": 1,
                    "is_ended": False,
                    "is_from_job": job_info is not None
                },
                {"role": "interviewer", "content": full_greeting, "timestamp": datetime.now().isoformat()}
            ]
            flag_modified(interview, "conversation")
            db.commit()
            
            log_ai_question(interview.id, candidate.id, full_greeting)
            yield f"data: {json.dumps({'done': True, 'success': True, 'interview_id': interview_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


@router.post("/{interview_id}/message")
async def send_message(
    interview_id: int,
    message_data: dict,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_candidate),
    db: Session = Depends(get_db)
):
    """发送消息并获取AI响应"""
    candidate = db.query(Candidate).filter(Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    from app.utils import get_interview_by_id
    interview = get_interview_by_id(db, interview_id, candidate_id=candidate.id)

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    if interview.status != InterviewStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=400, detail="面试已结束")

    conversation = interview.conversation or []
    system_info = conversation[0] if conversation and conversation[0].get("role") == "system" else None
    if not system_info:
        raise HTTPException(status_code=500, detail="面试数据异常")

    user_message = message_data.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    is_blocked, warning_msg = check_malicious_input(user_message)
    if is_blocked:
        warning_count = system_info.get("warning_count", 0) + 1
        system_info["warning_count"] = warning_count
        conversation[0] = system_info
        flag_modified(interview, "conversation")
        db.commit()
        
        ai_logger.warning(f"恶意输入检测 - 面试ID: {interview_id}, 警告次数: {warning_count}, 原因: {warning_msg}")
        
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
        
        return {
            "response": get_warning_text(warning_count),
            "is_ended": False,
            "question_count": system_info.get("question_count", 0),
            "warning": f"警告 ({warning_count}/3)：{warning_msg}"
        }

    conversation.append({
        "role": "candidate",
        "content": user_message,
        "timestamp": datetime.now().isoformat()
    })
    log_ai_answer(interview.id, candidate.id, user_message)

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
        # 先让AI生成响应
        ai_response = ai_conversation_interviewer.generate_next_response(
            conversation_history=conversation,
            difficulty=difficulty,
            interview_type=interview_type,
            job_info=job_info,
            candidate_info=candidate_info,
            question_count=question_count,
            max_questions=max_questions
        )

        is_ended = ai_conversation_interviewer.is_interview_ended(ai_response)

        # 检查是否是问题，如果是则增加问题计数（只检测AI的响应，不检测用户消息）
        if not is_ended and ("?" in ai_response or "？" in ai_response):
            question_count += 1
            system_info["question_count"] = question_count

    conversation.append({
        "role": "interviewer",
        "content": ai_response,
        "timestamp": datetime.now().isoformat()
    })

    system_info["is_ended"] = is_ended
    conversation[0] = system_info

    interview.conversation = conversation
    flag_modified(interview, "conversation")

    if is_ended:
        interview.status = InterviewStatus.COMPLETED.value
        from app.models import get_local_time
        interview.completed_at = get_local_time()
        db.commit()

        interview_id_to_process = interview.id
        candidate_id_to_process = candidate.id
        user_id_to_process = current_user.id
        job_id_to_process = interview.job_id
        conversation_copy = list(conversation)

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

    log_ai_question(interview.id, candidate.id, ai_response)

    return {
        "response": ai_response,
        "is_ended": is_ended,
        "question_count": question_count
    }


@router.post("/{interview_id}/message/stream")
async def send_message_stream(
    interview_id: int,
    message_data: dict,
    current_user: User = Depends(get_current_candidate),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """发送消息并获取流式AI响应"""
    candidate = db.query(Candidate).filter(Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    from app.utils import get_interview_by_id
    interview = get_interview_by_id(db, interview_id, candidate_id=candidate.id)

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    if interview.status != InterviewStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=400, detail="面试已结束")

    conversation = interview.conversation or []
    system_info = conversation[0] if conversation and conversation[0].get("role") == "system" else None
    if not system_info:
        raise HTTPException(status_code=500, detail="面试数据异常")

    user_message = message_data.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    is_blocked, warning_msg = check_malicious_input(user_message)
    if is_blocked:
        warning_count = system_info.get("warning_count", 0) + 1
        system_info["warning_count"] = warning_count
        conversation[0] = system_info
        flag_modified(interview, "conversation")
        db.commit()
        
        ai_logger.warning(f"恶意输入检测 - 面试ID: {interview_id}, 警告次数: {warning_count}, 原因: {warning_msg}")
        
        async def warning_stream():
            if warning_count >= 3:
                interview.status = InterviewStatus.COMPLETED.value
                from app.models import get_local_time
                interview.completed_at = get_local_time()
                db.commit()
                
                yield f"data: {json.dumps({'chunk': '由于多次发送不当内容，面试已结束。'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'is_ended': True, 'warning': '面试已因违规行为终止'}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'chunk': get_warning_text(warning_count)}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'is_ended': False, 'warning': f'警告 ({warning_count}/3)：{warning_msg}'}, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(warning_stream(), media_type="text/event-stream")

    conversation.append({
        "role": "candidate",
        "content": user_message,
        "timestamp": datetime.now().isoformat()
    })
    log_ai_answer(interview.id, candidate.id, user_message)

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
            
            # 先让AI生成响应
            stream = ai_conversation_interviewer.generate_next_response_stream(
                conversation_history=conversation,
                difficulty=difficulty,
                interview_type=interview_type,
                job_info=job_info,
                candidate_info=candidate_info,
                question_count=question_count,
                max_questions=max_questions
            )

            for chunk in stream:
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"

            is_ended = ai_conversation_interviewer.is_interview_ended(full_response)

            # 检查是否是问题，如果是则增加问题计数（只检测AI的响应，不检测用户消息）
            if not is_ended and ("?" in full_response or "？" in full_response):
                question_count += 1
                system_info["question_count"] = question_count

        conversation.append({
            "role": "interviewer",
            "content": full_response,
            "timestamp": datetime.now().isoformat()
        })

        system_info["is_ended"] = is_ended
        conversation[0] = system_info

        interview.conversation = conversation
        flag_modified(interview, "conversation")

        # 先发送结束消息，让客户端快速收到
        ai_logger.debug(f"准备发送结束消息 - is_ended={is_ended}, question_count={question_count}")
        yield f"data: {json.dumps({'done': True, 'is_ended': is_ended, 'question_count': question_count}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0)

        if is_ended:
            interview.status = InterviewStatus.COMPLETED.value
            from app.models import get_local_time
            interview.completed_at = get_local_time()
            
            # 添加生成报告的后台任务
            interview_id_to_process = interview.id
            candidate_id_to_process = candidate.id
            user_id_to_process = current_user.id
            job_id_to_process = interview.job_id
            conversation_copy = list(conversation)
            
            background_tasks.add_task(
                generate_report_background,
                interview_id=interview_id_to_process,
                candidate_id=candidate_id_to_process,
                user_id=user_id_to_process,
                conversation=conversation_copy,
                job_id=job_id_to_process
            )
            ai_logger.info(f"已添加生成面试报告的后台任务 - 面试ID: {interview_id_to_process}")

        # 后台执行数据库操作和日志记录
        db.commit()
        log_ai_question(interview.id, candidate.id, full_response)

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


@router.get("/{interview_id}")
def get_conversation_interview(
    interview_id: int,
    current_user: User = Depends(get_current_candidate),
    db: Session = Depends(get_db)
):
    """获取对话式面试详情"""
    candidate = db.query(Candidate).filter(Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    conversation = interview.conversation or []
    system_info = conversation[0] if conversation and conversation[0].get("role") == "system" else None

    messages = []
    for msg in conversation:
        if msg.get("role") in ["interviewer", "candidate"]:
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
                "timestamp": msg.get("timestamp")
            })

    is_ended = False
    question_count = 0
    if system_info:
        is_ended = system_info.get("is_ended", False)
        question_count = system_info.get("question_count", 0)

    return {
        "interview": interview,
        "messages": messages,
        "is_ended": is_ended,
        "question_count": question_count,
        "status": interview.status
    }


@router.delete("/{interview_id}")
def delete_conversation_interview(
    interview_id: int,
    current_user: User = Depends(get_current_candidate),
    db: Session = Depends(get_db)
):
    """删除对话式面试记录"""
    candidate = db.query(Candidate).filter(Candidate.user_id == current_user.id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人信息不存在")

    interview = db.query(Interview).filter(
        Interview.id == interview_id,
        Interview.candidate_id == candidate.id
    ).first()

    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    report = db.query(InterviewReport).filter(InterviewReport.interview_id == interview_id).first()
    if report:
        db.delete(report)

    db.delete(interview)
    db.commit()

    return {"message": "面试记录已删除"}
