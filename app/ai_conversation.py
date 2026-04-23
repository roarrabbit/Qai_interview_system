"""
Description: 弃用的旧版AI对话面试官模块
"""
import json
import requests
import re
from typing import List, Dict, Optional, AsyncGenerator
from datetime import datetime
from app.config import settings
from app.logger import ai_logger
from app.ai_base import BaseAIInterviewer


class AIConversationInterviewer(BaseAIInterviewer):
    """AI对话面试官 - 支持流式对话的交互式面试"""

    def __init__(self):
        super().__init__()

    def _get_system_prompt(self, difficulty: str, interview_type: str = "job_interview", job_info: Dict = None, candidate_info: Dict = None, max_questions: int = None) -> str:
        """获取系统提示词 - 自然对话风格"""
        difficulty_prompts = {
            "初级": """你是一位温和友好的技术面试官，正在面试一位初级开发者。
你的风格是：
- 亲切自然，像在和同事聊天一样
- 用简单易懂的语言提问，避免过于专业的术语
- 对候选人的回答给予鼓励和引导
- 关注基础知识的掌握和学习能力
- 每次只问一个问题，等待回答后再继续""",
            "中级": """你是一位经验丰富的技术面试官，正在面试一位有1-3年经验的开发者。
你的风格是：
- 专业但不刻板，保持自然对话的氛围
- 关注实际项目经验和技术深度
- 会根据回答进行适当的追问和引导
- 考察问题解决能力和技术视野
- 每次只问一个问题，等待回答后再继续""",
            "高级": """你是一位资深的技术专家/架构师，正在面试一位高级开发者或架构师候选人。
你的风格是：
- 深入探讨技术细节和架构设计
- 关注系统思维和技术决策能力
- 会进行深度追问，考察技术深度
- 考察团队管理和技术推动能力
- 每次只问一个问题，等待回答后再继续"""
        }

        base_prompt = difficulty_prompts.get(difficulty, difficulty_prompts["中级"])
        
        if max_questions is None:
            max_questions = self.job_interview_questions if interview_type == "job_interview" else self.personal_interview_questions

        candidate_detail = ""
        missing_info = []
        
        if candidate_info:
            info_parts = []
            if candidate_info.get('real_name'):
                info_parts.append(f"- 姓名：{candidate_info.get('real_name')}")
            else:
                missing_info.append("姓名")
            
            if candidate_info.get('education'):
                info_parts.append(f"- 学历：{candidate_info.get('education')}")
            else:
                missing_info.append("学历")
            
            if candidate_info.get('major'):
                info_parts.append(f"- 专业：{candidate_info.get('major')}")
            else:
                missing_info.append("专业")
            
            if candidate_info.get('work_experience'):
                info_parts.append(f"- 工作年限：{candidate_info.get('work_experience')}")
            else:
                missing_info.append("工作年限")
            
            if candidate_info.get('skills'):
                info_parts.append(f"- 技能标签：{candidate_info.get('skills')}")
            else:
                missing_info.append("技能")
            
            if candidate_info.get('target_job'):
                info_parts.append(f"- 求职意向：{candidate_info.get('target_job')}")
            
            if candidate_info.get('experience_summary'):
                info_parts.append(f"- 经验摘要：{candidate_info.get('experience_summary')}")
            
            if candidate_info.get('self_introduction'):
                info_parts.append(f"- 个人简介：{candidate_info.get('self_introduction')}")
            
            if info_parts:
                candidate_detail = f"""
候选人已登记的个人信息：
{chr(10).join(info_parts)}
"""
            if missing_info:
                candidate_detail += f"""
候选人未填写的个人信息：{', '.join(missing_info)}
（如果这些信息对面试评估重要，可以适当追问）
"""

        context_info = ""
        if job_info:
            context_info = f"""
当前面试的岗位信息：
- 岗位名称：{job_info.get('title', '技术岗位')}
- 岗位描述：{job_info.get('description', '')[:300]}
- 技能要求：{job_info.get('required_skills', '未指定')}
"""
        
        context_info += candidate_detail

        return f"""{base_prompt}

{context_info}

重要规则：
1. 你必须模拟真实的面试对话，每次只说一句话或问一个问题
2. 用自然的口语化表达，避免书面语和机械感
3. 根据候选人的回答灵活调整后续问题
4. 如果回答很好，可以给予肯定；如果回答有问题，可以适当引导
5. 面试大约需要问{max_questions}个问题，需覆盖六大评估维度：①专业领域深度 ②团队协作与技术推动 ③技术视野与前瞻思维 ④技术基础与实践能力 ⑤系统架构设计思维 ⑥项目经历真实性
6. 当你觉得面试可以结束时，说"今天的面试就到这里，感谢你的时间，我们会有后续通知。"
7. 永远不要一次性输出多个问题
8. 保持对话的连贯性，记住之前的对话内容
9. 候选人的个人信息已在上方提供，如果关键信息缺失（如工作年限、技能等），可以在面试中适当追问
10. 开场白要简洁，直接进入第一个技术问题，不要要求候选人重复介绍已登记的信息"""

    def generate_greeting(self, job_info: Dict = None, candidate_info: Dict = None, max_questions: int = None) -> str:
        """生成开场白 - 直接开始第一个技术问题"""
        if max_questions is None:
            max_questions = self.job_interview_questions if job_info else self.personal_interview_questions
        
        if job_info:
            job_title = job_info.get('title', '这个岗位')
            required_skills = job_info.get('required_skills', '')
            prompt = f"""请生成一个简洁的面试开场白并直接提出第一个技术问题。
应聘岗位：{job_title}
技能要求：{required_skills}

要求：
- 简短问候后直接进入第一个技术问题
- 不要要求候选人自我介绍
- 第一个问题要结合岗位要求，覆盖六大评估维度：专业领域深度、团队协作、技术视野、实践能力、架构设计、项目真实性
- 只输出内容本身，不要有其他说明"""
        else:
            target_job = candidate_info.get('target_job', '技术岗位') if candidate_info else '技术岗位'
            skills = candidate_info.get('skills', '') if candidate_info else ''
            prompt = f"""请生成一个简洁的面试开场白并直接提出第一个技术问题。
候选人应聘方向：{target_job}
候选人技能：{skills}

要求：
- 简短问候后直接进入第一个技术问题
- 不要要求候选人自我介绍
- 第一个问题要结合候选人的技能方向，覆盖六大评估维度：专业领域深度、团队协作、技术视野、实践能力、架构设计、项目真实性
- 只输出内容本身，不要有其他说明"""

        system_prompt = "你是一位专业的面试官。请简洁开场并直接开始技术面试，不要要求自我介绍。"
        greeting = self._call_ollama(prompt, system_prompt)
        return greeting.strip()

    def generate_greeting_stream(self, job_info: Dict = None, candidate_info: Dict = None, max_questions: int = None) -> AsyncGenerator[str, None]:
        """流式生成开场白 - 直接开始第一个技术问题"""
        if max_questions is None:
            max_questions = self.job_interview_questions if job_info else self.personal_interview_questions
        
        if job_info:
            job_title = job_info.get('title', '这个岗位')
            required_skills = job_info.get('required_skills', '')
            prompt = f"""请生成一个简洁的面试开场白并直接提出第一个技术问题。
应聘岗位：{job_title}
技能要求：{required_skills}

要求：
- 简短问候后直接进入第一个技术问题，只问一个问题
- 不要要求候选人自我介绍
- 第一个问题要结合岗位要求，覆盖六大评估维度：专业领域深度、团队协作、技术视野、实践能力、架构设计、项目真实性
- 只输出内容本身，不要有其他说明"""
        else:
            target_job = candidate_info.get('target_job', '技术岗位') if candidate_info else '技术岗位'
            skills = candidate_info.get('skills', '') if candidate_info else ''
            prompt = f"""请生成一个简洁的面试开场白并直接提出第一个技术问题。
候选人应聘方向：{target_job}
候选人技能：{skills}

要求：
- 简短问候后直接进入第一个技术问题，只问一个问题
- 不要要求候选人自我介绍
- 第一个问题要结合候选人的技能方向，覆盖六大评估维度：专业领域深度、团队协作、技术视野、实践能力、架构设计、项目真实性
- 只输出内容本身，不要有其他说明"""

        system_prompt = "你是一位专业的面试官。请简洁开场并直接开始技术面试，不要要求自我介绍。"
        return self._call_ollama_stream(prompt, system_prompt)

    def generate_next_response(
        self,
        conversation_history: List[Dict],
        difficulty: str,
        interview_type: str = "job_interview",
        job_info: Dict = None,
        candidate_info: Dict = None,
        question_count: int = 0,
        max_questions: int = None
    ) -> str:
        """根据对话历史生成下一个响应（问题或结束语）"""
        if max_questions is None:
            max_questions = self.job_interview_questions if interview_type == "job_interview" else self.personal_interview_questions
        
        system_prompt = self._get_system_prompt(difficulty, interview_type, job_info, candidate_info, max_questions)

        conversation_text = ""
        for msg in conversation_history:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role == 'interviewer':
                conversation_text += f"面试官：{content}\n"
            elif role == 'candidate':
                conversation_text += f"候选人：{content}\n"

        prompt = f"""以下是之前的对话记录：
{conversation_text}

你已经问了{question_count}个问题，最多问{max_questions}个问题。
请根据对话内容，自然地继续对话。可以是：
- 对上一个回答的简短反馈（如果回答值得评论）
- 下一个问题（如果还有问题要问）
- 面试结束语（如果觉得已经问够了，或者候选人的回答已经足够说明问题）

记住：
1. 只说一句话或问一个问题
2. 保持自然对话的风格
3. 不要一次性输出多个问题"""

        response = self._call_ollama(prompt, system_prompt)
        return response.strip()

    def generate_next_response_stream(
        self,
        conversation_history: List[Dict],
        difficulty: str,
        interview_type: str = "job_interview",
        job_info: Dict = None,
        candidate_info: Dict = None,
        question_count: int = 0,
        max_questions: int = None
    ):
        """流式生成下一个响应"""
        if max_questions is None:
            max_questions = self.job_interview_questions if interview_type == "job_interview" else self.personal_interview_questions
        
        system_prompt = self._get_system_prompt(difficulty, interview_type, job_info, candidate_info, max_questions)

        conversation_text = ""
        for msg in conversation_history:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role == 'interviewer':
                conversation_text += f"面试官：{content}\n"
            elif role == 'candidate':
                conversation_text += f"候选人：{content}\n"

        prompt = f"""以下是之前的对话记录：
{conversation_text}

你已经问了{question_count}个问题，最多问{max_questions}个问题。
请根据对话内容，自然地继续对话。可以是：
- 对上一个回答的简短反馈（如果回答值得评论）
- 下一个问题（如果还有问题要问）
- 面试结束语（如果觉得已经问够了，或者候选人的回答已经足够说明问题）

记住：
1. 只说一句话或问一个问题
2. 保持自然对话的风格
3. 不要一次性输出多个问题"""

        return self._call_ollama_stream(prompt, system_prompt)

    def generate_report_from_conversation(self, conversation: List[Dict], job_context: Dict) -> Dict:
        """从对话记录直接生成完整报告 - 一次性AI调用"""
        qa_pairs = []
        for i, msg in enumerate(conversation):
            if msg.get('role') == 'interviewer' and msg.get('content'):
                answer = ""
                if i + 1 < len(conversation) and conversation[i + 1].get('role') == 'candidate':
                    answer = conversation[i + 1].get('content', '')
                qa_pairs.append({
                    "question": msg.get('content'),
                    "answer": answer if answer else "（未回答）"
                })

        qa_text = "\n\n".join([
            f"问题{i+1}：{qa['question']}\n回答：{qa['answer']}"
            for i, qa in enumerate(qa_pairs)
        ])

        system_prompt = """你是一位专业的面试评估专家。请对整场面试进行全面评估。

评估维度说明（每个维度0-20分）：
1. 专业领域深度洞察：对专业知识的深入理解、技术细节的掌握程度
2. 团队协作与技术推动：团队合作经验、沟通协调能力、技术分享与推动
3. 技术深度与前瞻视野：技术广度、对新技术的了解、技术趋势把握
4. 技术基础与实践能力：基础技术能力、实际项目操作经验、代码质量
5. 系统架构设计思维：架构设计能力、系统设计思路、性能优化思维
6. 项目经历真实性：项目经验的真实性、参与度、贡献度

评分标准：
- 0-5分：表现很差或未涉及
- 6-10分：表现一般，有基本了解
- 11-15分：表现良好，有实际经验
- 16-20分：表现优秀，有深入见解

请返回JSON格式：
{
    "domain_insight": 分数,
    "team_collaboration": 分数,
    "technical_vision": 分数,
    "practical_ability": 分数,
    "architecture_design": 分数,
    "authenticity": 分数,
    "overall_grade": "A/B/C/D",
    "strengths": "优势总结（2-3点）",
    "weaknesses": "待改进项（2-3点）",
    "suggestions": "改进建议（2-3点）",
    "summary": "面试总结（一句话）"
}

评级标准：
- A（优秀）：平均分≥15
- B（良好）：平均分≥13
- C（及格）：平均分≥11
- D（不及格）：平均分<11"""

        prompt = f"""岗位：{job_context.get('job_title', '技术岗位')}

面试对话记录：
{qa_text}

请根据以上面试对话，对候选人进行全面评估，给出各维度评分和反馈。"""

        response = self._call_ollama(prompt, system_prompt)

        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                
                for key in ['domain_insight', 'team_collaboration', 'technical_vision', 
                           'practical_ability', 'architecture_design', 'authenticity']:
                    if key not in result:
                        result[key] = 10
                    else:
                        result[key] = max(0, min(20, int(result[key])))
                
                scores = [
                    result.get('domain_insight', 10),
                    result.get('team_collaboration', 10),
                    result.get('technical_vision', 10),
                    result.get('practical_ability', 10),
                    result.get('architecture_design', 10),
                    result.get('authenticity', 10)
                ]
                avg_score = sum(scores) / 6
                
                if not result.get('overall_grade'):
                    if avg_score >= 15:
                        result['overall_grade'] = "A"
                    elif avg_score >= 13:
                        result['overall_grade'] = "B"
                    elif avg_score >= 11:
                        result['overall_grade'] = "C"
                    else:
                        result['overall_grade'] = "D"
                
                result['radar_data'] = scores
                
                for field in ['strengths', 'weaknesses', 'suggestions']:
                    if not result.get(field):
                        result[field] = "暂无"
                    else:
                        result[field] = self._clean_ai_text(result[field])
                
                result['domain_insight_score'] = result.pop('domain_insight', 10)
                result['team_collaboration_score'] = result.pop('team_collaboration', 10)
                result['technical_vision_score'] = result.pop('technical_vision', 10)
                result['practical_ability_score'] = result.pop('practical_ability', 10)
                result['architecture_design_score'] = result.pop('architecture_design', 10)
                result['authenticity_score'] = result.pop('authenticity', 10)
                
                # 确保包含 summary 字段
                if 'summary' not in result:
                    result['summary'] = "面试表现一般"
                
                return result
        except Exception as e:
            ai_logger.error(f"报告生成解析错误: {str(e)}")
            ai_logger.error(f"AI返回内容: {response[:500] if response else 'Empty'}")

        return {
            "domain_insight_score": 10,
            "team_collaboration_score": 10,
            "technical_vision_score": 10,
            "practical_ability_score": 10,
            "architecture_design_score": 10,
            "authenticity_score": 10,
            "overall_grade": "C",
            "strengths": self._clean_ai_text("技术基础一般"),
            "weaknesses": self._clean_ai_text("需要进一步提升"),
            "suggestions": self._clean_ai_text("建议加强学习和实践"),
            "radar_data": [10, 10, 10, 10, 10, 10],
            "summary": "面试表现一般"
        }

    def is_interview_ended(self, response: str) -> bool:
        """判断面试是否结束"""
        end_keywords = [
            "面试就到这里",
            "今天的面试",
            "感谢你的时间",
            "我们会有后续通知",
            "面试结束"
        ]
        return any(keyword in response for keyword in end_keywords)


ai_conversation_interviewer = AIConversationInterviewer()
