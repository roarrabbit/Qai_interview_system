"""
Description: 新版流式AI对话面试官模块
"""
import json
import requests
import re
from typing import List, Dict, Optional, AsyncGenerator
from datetime import datetime
from app.config import settings
from app.logger import ai_logger
from app.ai_base import BaseAIInterviewer


class AIInterviewer(BaseAIInterviewer):
    """AI面试官 - 基于Ollama的多轮对话面试"""

    def __init__(self):
        super().__init__()

    def generate_interview_questions(
        self,
        job_title: str,
        difficulty: str,
        candidate_info: Dict,
        num_questions: int = 5,
        job_info: Dict = None
    ) -> List[str]:
        """生成面试问题 - 根据难度和6个评估维度生成不同深度的问题

        Args:
            job_title: 岗位标题
            difficulty: 面试难度（初级/中级/高级）
            candidate_info: 候选人信息（仅作参考）
            num_questions: 问题数量
            job_info: 岗位详细信息（优先使用，用于定制化出题）
        """
        import asyncio
        # 同步调用异步方法
        response = asyncio.run(self._generate_questions_sync(job_title, difficulty, candidate_info, num_questions, job_info))
        return response

    async def _generate_questions_sync(
        self,
        job_title: str,
        difficulty: str,
        candidate_info: Dict,
        num_questions: int = 5,
        job_info: Dict = None
    ) -> List[str]:
        """同步生成面试问题的异步实现"""
        # 构建提示词
        system_prompt, prompt = self._build_question_prompt(job_title, difficulty, candidate_info, num_questions, job_info)
        
        # 收集完整响应
        full_response = ""
        async for chunk in self._call_ollama_stream(prompt, system_prompt):
            full_response += chunk
        
        # 解析问题
        questions = self._parse_questions(full_response, num_questions)
        
        # 记录生成的问题
        ai_logger.info(f"成功生成{len(questions)}个面试问题")
        for i, q in enumerate(questions, 1):
            ai_logger.debug(f"问题{i}: {q[:50]}...")
        
        return questions

    async def generate_interview_questions_stream(
        self,
        job_title: str,
        difficulty: str,
        candidate_info: Dict,
        num_questions: int = 5,
        job_info: Dict = None
    ) -> AsyncGenerator[str, None]:
        """流式生成面试问题 - 实时返回生成过程

        Args:
            job_title: 岗位标题
            difficulty: 面试难度（初级/中级/高级）
            candidate_info: 候选人信息（仅作参考）
            num_questions: 问题数量
            job_info: 岗位详细信息（优先使用，用于定制化出题）
        """
        # 构建提示词
        system_prompt, prompt = self._build_question_prompt(job_title, difficulty, candidate_info, num_questions, job_info)
        
        # 流式返回生成过程
        async for chunk in self._call_ollama_stream(prompt, system_prompt):
            yield chunk

    def _build_question_prompt(
        self,
        job_title: str,
        difficulty: str,
        candidate_info: Dict,
        num_questions: int,
        job_info: Dict = None
    ) -> tuple:
        """构建问题生成的提示词"""
        # 根据难度设置不同的提示词和要求
        if difficulty == "初级":
            difficulty_desc = "基础入门级别"
            system_prompt = """请模拟技术面试官的思维逻辑，以面试初级开发者的视角，围绕6维度出题，用中文。"""

        elif difficulty == "中级":
            difficulty_desc = "中级水平"
            system_prompt = """请模拟资深技术面试官的思维逻辑，以面试中级开发者（1-3年经验）的视角，围绕6维度出题。用中文。"""

        else:  # 高级
            difficulty_desc = "高级水平"
            system_prompt = """请模拟技术总监的思维逻辑，以面试高级开发者/架构师的视角，围绕6维度出题。用中文。"""

        # 构建Prompt - 优先使用岗位信息，其次才是候选人信息
        if job_info:
            # 从岗位卡片启动：基于岗位需求出题
            prompt = f"""岗位：{job_info.get('title', job_title)}
描述：{job_info.get('description', '未提供')[:200]}
要求：{job_info.get('requirements', '未提供')[:150]}
技能：{job_info.get('required_skills', '未提供')}

生成{num_questions}个{difficulty}难度面试题，覆盖6维度（专业领域深度洞察、团队协作与技术推动、技术深度与前瞻视野、技术基础与实践能力、系统架构设计思维、项目经历）。严格按格式输出：
1. 问题1
2. 问题2
...
只输出编号问题，无其他文字。"""
        else:
            # 从个人中心启动：基于候选人背景出题
            prompt = f"""岗位：{job_title}
候选人技能：{candidate_info.get('skills', '未提供')}
求职意向：{candidate_info.get('target_job', '未提供')}

生成{num_questions}个{difficulty}难度面试题，需要覆盖6维度（专业领域深度洞察、团队协作与技术推动、技术深度与前瞻视野、技术基础与实践能力、系统架构设计思维、项目经历）。严格按格式输出：
1. 问题1
2. 问题2
...
只输出编号与问题，无其他文字。"""
        
        return system_prompt, prompt

    def _parse_questions(self, response: str, num_questions: int) -> List[str]:
        """解析生成的面试问题"""
        questions = []

        # 按行分割
        lines = response.strip().split('\n')

        for line in lines:
            line = line.strip()

            # 跳过空行和无关内容
            if not line:
                continue

            # 跳过标题行（包含"面试问题"、"评估维度"等关键词）
            if any(
                keyword in line for keyword in [
                    '面试问题',
                    '评估维度',
                    '以下是',
                    '难度',
                    '：',
                    '————']):
                if not re.match(r'^\d+[\.\)、]', line):  # 不是编号开头的行
                    continue

            # 提取问题（移除编号）
            # 匹配格式： "1. 问题", "1) 问题", "1、问题", "第1题：问题" 等
            match = re.match(r'^(?:\d+[\.\)、]|第\d+[题个][:：]?)\s*(.+)$', line)
            if match:
                question_text = match.group(1).strip()
                # 移除问题两侧的方括号（如果有）
                if question_text.startswith('[') and question_text.endswith(']'):
                    question_text = question_text[1:-1]
                # 确保问题有实质内容（至少10个字符）
                if len(question_text) >= 10:
                    questions.append(question_text)

        return questions[:num_questions]

    def _get_backup_questions(
            self,
            job_title: str,
            difficulty: str) -> List[str]:
        """获取后备问题（当AI生成失败时使用）"""
        if difficulty == "初级":
            return [
                f"请简单介绍一下你对{job_title}岗位的理解。",
                f"你学习过哪些与{job_title}相关的技术或课程？",
                "请介绍一个你参与过的项目或实践经历。",
                "你认为做好这个岗位需要具备哪些基本能力？",
                "你为什么对这个岗位感兴趣？"
            ]
        elif difficulty == "中级":
            return [
                f"请介绍一下你在{job_title}方面最有成就感的项目。",
                f"作为{job_title}，你在项目中通常负责哪些工作？",
                "请描述一次你解决技术难题的经历，包括问题和解决方案。",
                "你如何保证代码质量和项目进度？",
                "你对这个岗位的技术栈有哪些了解和实践？"
            ]
        else:  # 高级
            return [
                f"请从架构角度谈谈你对{job_title}相关系统的设计思路。",
                "请分享一个你主导的复杂项目，包括技术选型和决策过程。",
                "在大规模系统中，你如何进行性能优化和问题排查？",
                "请谈谈你对技术团队管理和技术规划的理解。",
                "面对新技术，你如何评估其适用性并推动团队采用？"
            ]

    def evaluate_answer(
        self,
        question: str,
        answer: str,
        job_context: Dict
    ) -> Dict:
        """评估单个问题的回答 - 使用新的6维度评估体系"""
        import asyncio
        # 同步调用异步方法
        evaluation = asyncio.run(self._evaluate_answer_async(question, answer, job_context))
        return evaluation

    async def _evaluate_answer_async(
        self,
        question: str,
        answer: str,
        job_context: Dict
    ) -> Dict:
        """异步评估单个问题的回答"""
        ai_logger.debug(f"开始评估回答 - 问题: {question}, 回答: {answer}")

        system_prompt = """请模拟技术面试官的思维逻辑。围绕6维度评分，6维度评分0-20分。评分标准：
0–3分：答非所问、明显敷衍、无实质内容或完全偏离主题。
4–8分：内容与问题弱相关，表述空洞，缺乏具体信息或技术细节。
9–12分：回答简短但切题，有基本要点，但缺乏展开、深度或实例支撑。
13–15分：内容切题、逻辑通顺，包含有效技术信息，但未深入或缺少案例。
16–20分：回答深入透彻，逻辑严密，结合具体项目/场景/数据，并体现技术判断或反思，具有说服力。

维度定义：
domain_insight(专业领域深度洞察)：对专业知识的深入理解、技术细节的掌握程度
team_collaboration(团队协作与技术推动)：团队合作经验、沟通协调能力、推动技术的能力
technical_vision(技术深度与前瞻视野)：技术广度、对新技术的了解、技术发展趋势的把握
practical_ability(技术基础与实践能力)：基础技术能力、实际项目操作经验、问题解决能力
architecture_design(系统架构设计思维)：架构设计能力、系统设计思路、技术选型能力
authenticity(项目经历)：项目经验的真实性、参与度、贡献度
返回JSON。"""

        prompt = f"""岗位：{job_context.get('job_title', '未知岗位')}
问：{question}
答：{answer}

严格评分：答非所问/敷衍→0-5分，认真但浅→9-12分，详实→13+分

JSON格式：
{{
    "domain_insight": 分数,
    "team_collaboration": 分数,
    "technical_vision": 分数,
    "practical_ability": 分数,
    "architecture_design": 分数,
    "authenticity": 分数,
    "comment": "简短评语"
}}"""

        # 收集完整响应
        full_response = ""
        async for chunk in self._call_ollama_stream(prompt, system_prompt):
            full_response += chunk

        # 尝试解析JSON
        try:
            # 提取JSON部分
            json_match = re.search(r'\{.*\}', full_response, re.DOTALL)
            if json_match:
                evaluation = json.loads(json_match.group())
                ai_logger.debug(f"评估结果: {evaluation}")
                return evaluation
        except Exception as e:
            ai_logger.error(f"评估结果解析错误: {str(e)}")

        # 默认评分（AI解析失败时的低分，避免给无效回答高分）
        return {
            "domain_insight": 5,
            "team_collaboration": 5,
            "technical_vision": 5,
            "practical_ability": 5,
            "architecture_design": 5,
            "authenticity": 5,
            "comment": "回答质量不足，建议提供更详实的内容和具体案例。"
        }

    def _generate_feedback_with_ai(
        self,
        conversation: List[Dict],
        evaluations: List[Dict],
        scores_map: Dict[str, float]
    ) -> tuple:
        """使用AI生成面试反馈（优势、劣势、建议）"""
        import asyncio
        # 同步调用异步方法
        feedback = asyncio.run(self._generate_feedback_with_ai_async(conversation, evaluations, scores_map))
        return feedback

    async def _generate_feedback_with_ai_async(
        self,
        conversation: List[Dict],
        evaluations: List[Dict],
        scores_map: Dict[str, float]
    ) -> tuple:
        """异步使用AI生成面试反馈"""

        # 构建对话摘要
        qa_summary = []
        for msg in conversation:
            if msg.get('role') == 'interviewer':
                qa_summary.append(f"问：{msg.get('content', '')}")
            elif msg.get('role') in ['candidate', 'user']:
                qa_summary.append(f"答：{msg.get('content', '')}")

        # 构建评分摘要
        scores_text = "\n".join(
            [f"- {dim}：{score:.1f}/20分" for dim, score in scores_map.items()])

        # 构建详细评估摘要
        detailed_evaluations = []
        for i, eval_item in enumerate(evaluations, 1):
            comment = eval_item.get('comment', '无评语')
            detailed_evaluations.append(f"第{i}题评价：{comment}")

        system_prompt = """以HR评估专家的思维逻辑，真实客观反馈：分数低→指出问题，不写或少些优势，分数高→肯定优势，同时也要指出问题所在。避免空话。
请直接生成准确且简洁的反馈内容，不需要JSON格式，只使用这种格式。
反馈应包含以下三个部分，用中文冒号分隔：
优势：具体的优势点
劣势：需要改进的地方
建议：针对性的改进建议

例如：
优势：技术基础扎实，有丰富的项目经验；沟通能力强，能够清晰表达技术方案
劣势：对新技术的了解不够深入；架构设计能力有待提升
建议：加强对前沿技术的学习；尝试参与更大规模项目的架构设计"""

        prompt = f"""对话：
{chr(10).join(qa_summary[:15])}

评分(满分20)：
{scores_text}

评价：
{chr(10).join(detailed_evaluations[:10])}

任务：分数<10→批评，分数>15→表扬。请直接生成真实反馈。"""

        ai_logger.info("正在使用AI生成个性化面试反馈...")

        # 收集完整响应
        full_response = ""
        async for chunk in self._call_ollama_stream(prompt, system_prompt):
            full_response += chunk

        # 尝试从AI输出中提取三个部分
        try:
            strengths = "技术基础扎实，学习能力强"
            weaknesses = "部分技术细节有待深入"
            suggestions = "建议继续保持学习热情，加强实战经验"
            
            # 直接使用AI的输出
            if full_response:
                ai_logger.debug(f"AI原始反馈: {full_response}")
                
                # 尝试按部分提取
                if "优势：" in full_response:
                    strengths_part = full_response.split("优势：")[1]
                    if "劣势：" in strengths_part:
                        strengths = strengths_part.split("劣势：")[0].strip()
                        
                        weaknesses_part = strengths_part.split("劣势：")[1]
                        if "建议：" in weaknesses_part:
                            weaknesses = weaknesses_part.split("建议：")[0].strip()
                            suggestions = weaknesses_part.split("建议：")[1].strip()
                        else:
                            weaknesses = weaknesses_part.strip()
                else:
                    # 如果没有按格式输出，直接使用整个响应作为优势，其他字段留空
                    strengths = full_response.strip()
                    weaknesses = ""
                    suggestions = ""

            ai_logger.debug("AI反馈生成成功")
            return (
                self._clean_ai_text(strengths),
                self._clean_ai_text(weaknesses),
                self._clean_ai_text(suggestions)
            )
        except Exception as e:
            ai_logger.error(f"AI反馈处理失败: {str(e)}")
            return (
                self._clean_ai_text(strengths),
                self._clean_ai_text(weaknesses),
                self._clean_ai_text(suggestions)
            )

    def _generate_fallback_feedback(
            self, scores_map: Dict[str, float]) -> tuple:
        """备选方案：基于分数生成反馈"""
        strengths = []
        weaknesses = []
        suggestions = []

        # 计算平均分
        avg_score = sum(scores_map.values()) / len(scores_map)

        # 如果整体表现很差（平均分<10），给出严厉但客观的反馈
        if avg_score < 10:
            weaknesses.append("回答质量整体偏低，多数问题未能深入展开")
            weaknesses.append("回答缺乏具体案例和技术细节")
            suggestions.append("建议重新梳理技术知识体系，加强基础学习")
            suggestions.append("面试时应认真审题，提供详实有据的回答")
            suggestions.append("建议积累实际项目经验，而非停留在理论层面")
            # 即使表现差，也找一些能肯定的地方
            if avg_score >= 5:
                strengths.append("展现了一定的学习意愿")
            else:
                strengths.append("建议端正面试态度，认真对待每个问题")
            return "；".join(strengths), "；".join(
                weaknesses), "；".join(suggestions)

        # 基于20分制生成具体的优势描述（提高门槛）
        if scores_map["专业领域深度洞察"] >= 15:
            strengths.append("专业领域理解深刻，技术栈扎实")
        if scores_map["团队协作与技术推动"] >= 15:
            strengths.append("团队协作能力强，沟通表达清晰")
        if scores_map["技术深度与前瞻视野"] >= 15:
            strengths.append("技术视野广阔，对新技术有独到见解")
        if scores_map["技术基础与实践能力"] >= 15:
            strengths.append("实践能力强，有丰富的项目经验")
        if scores_map["系统架构设计思维"] >= 15:
            strengths.append("系统设计能力优秀，架构思维清晰")
        if scores_map["项目经历"] >= 15:
            strengths.append("项目经历丰富，能提供详细技术细节")

        # 基于20分制生成具体的待改进项和建议（降低门槛，更容易指出问题）
        if scores_map["专业领域深度洞察"] < 14:
            weaknesses.append("专业领域深度有待加强")
            suggestions.append("建议系统学习相关技术栈的核心原理和底层实现")
        if scores_map["团队协作与技术推动"] < 14:
            weaknesses.append("团队协作经验相对不足")
            suggestions.append("建议多参与团队项目，提升沟通协作能力")
        if scores_map["技术深度与前瞻视野"] < 14:
            weaknesses.append("技术视野可以更广一些")
            suggestions.append("建议关注技术发展趋势，学习云原生、微服务等新技术")
        if scores_map["技术基础与实践能力"] < 14:
            weaknesses.append("实践经验需要进一步积累")
            suggestions.append("建议多做项目实践，在实战中提升能力")
        if scores_map["系统架构设计思维"] < 14:
            weaknesses.append("架构设计思维有待提升")
            suggestions.append("建议学习分布式系统设计和高并发架构知识")
        if scores_map["项目经历"] < 14:
            weaknesses.append("项目经历描述不够详细，缺乏技术深度")
            suggestions.append("建议在介绍项目时增加技术细节、实现方案和遇到的挑战")

        # 如果表现优秀，给予鼓励性反馈
        if not strengths:
            if avg_score >= 14:
                strengths.append("整体表现良好，基础扎实")
            else:
                strengths.append("展现了一定的技术基础")
        if not weaknesses:
            weaknesses.append("各维度表现均衡，可继续提升深度")
        if not suggestions:
            suggestions.append("建议继续保持学习热情，深化技术积累")

        return "；".join(strengths), "；".join(weaknesses), "；".join(suggestions)


# 全局AI面试官实例
ai_interviewer = AIInterviewer()



