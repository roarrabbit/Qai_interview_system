"""
AI面试基类 - 提供共同的AI面试功能
"""
import json
import requests
import re
from typing import List, Dict, Optional, AsyncGenerator
from app.config import settings
from app.logger import ai_logger


def get_ai_config_from_db():
    """从数据库获取AI配置，如果不存在则使用默认配置"""
    try:
        from app.database import SessionLocal
        from app.models import SystemConfig
        
        db = SessionLocal()
        try:
            configs = db.query(SystemConfig).filter(
                SystemConfig.config_key.in_([
                    'ollama_base_url', 
                    'ollama_model', 
                    'ollama_no_think',
                    'personal_interview_questions',
                    'job_interview_questions'
                ])
            ).all()
            
            config_dict = {c.config_key: c.config_value for c in configs}
            
            return {
                'base_url': config_dict.get('ollama_base_url') or settings.OLLAMA_BASE_URL,
                'model': config_dict.get('ollama_model') or settings.OLLAMA_MODEL,
                'no_think': config_dict.get('ollama_no_think', 'true').lower() == 'true' if 'ollama_no_think' in config_dict else settings.OLLAMA_NO_THINK,
                'personal_interview_questions': int(config_dict.get('personal_interview_questions', 5)),
                'job_interview_questions': int(config_dict.get('job_interview_questions', 7))
            }
        finally:
            db.close()
    except Exception as e:
        ai_logger.warning(f"从数据库获取AI配置失败，使用默认配置: {str(e)}")
        return {
            'base_url': settings.OLLAMA_BASE_URL,
            'model': settings.OLLAMA_MODEL,
            'no_think': settings.OLLAMA_NO_THINK,
            'personal_interview_questions': 5,
            'job_interview_questions': 7
        }


class BaseAIInterviewer:
    """AI面试官基类 - 提供共同的AI调用和评估功能"""

    def __init__(self):
        config = get_ai_config_from_db()
        self.base_url = config['base_url']
        self.model = config['model']
        self.no_think = config['no_think']
        self.personal_interview_questions = config['personal_interview_questions']
        self.job_interview_questions = config['job_interview_questions']

    def reload_config(self):
        """重新加载配置（用于配置更新后）"""
        config = get_ai_config_from_db()
        self.base_url = config['base_url']
        self.model = config['model']
        self.no_think = config['no_think']
        self.personal_interview_questions = config['personal_interview_questions']
        self.job_interview_questions = config['job_interview_questions']
        ai_logger.info(f"AI配置已重新加载: base_url={self.base_url}, model={self.model}, no_think={self.no_think}, personal_q={self.personal_interview_questions}, job_q={self.job_interview_questions}")

    def auto_detect_difficulty(self, job_description: str, required_skills: str) -> str:
        """根据岗位描述和技能要求自动判断面试难度"""
        senior_keywords = [
            '架构师', '技术总监', 'CTO', '首席技术官',
            '高级', '资深', '专家', 'principal',
            '系统架构', '微服务', '高并发', '分布式',
            '团队管理', '技术管理', '技术规划',
            '10年以上', '8年以上',
            '云原生', '大数据', '架构设计',
            'architect', 'senior', 'expert', 'lead'
        ]
        mid_keywords = [
            '中级', '3年以上', '4年以上',
            '熟练', '精通', '独立开发',
            '框架', '数据库设计', '数据库优化',
            'API设计', 'RESTful', '缓存', '消息队列',
            '单元测试', '集成测试', 'Git',
            '性能调优', '问题排查',
            'intermediate', 'mid-level'
        ]
        junior_keywords = [
            '初级', '1年以上', '2年以下', '新人',
            '应届生', '应届毕业生', '实习生',
            '实习', '培训', '培养', '储备',
            '了解', '熟悉', '接触过', '基础',
            '校招', '校园招聘',
            'junior', 'intern', 'trainee', 'beginner'
        ]

        combined_text = f"{job_description} {required_skills}".lower()
        senior_count = sum(1 for kw in senior_keywords if kw.lower() in combined_text)
        mid_count = sum(1 for kw in mid_keywords if kw.lower() in combined_text)
        junior_count = sum(1 for kw in junior_keywords if kw.lower() in combined_text)

        ai_logger.info(f"难度判断 - 高级:{senior_count}, 中级:{mid_count}, 初级:{junior_count}")

        if senior_count >= 2 or '架构' in combined_text or '高级' in combined_text:
            return "高级"
        elif junior_count >= 2 or '应届' in combined_text or '实习' in combined_text:
            return "初级"
        else:
            return "中级"

    def _call_ollama(self, prompt: str, system_prompt: str = "") -> str:
        """调用Ollama API - 非流式"""
        ai_logger.debug(f"调用Ollama API - 模型: {self.model}, no_think: {self.no_think}")

        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": False
            }
            
            if self.no_think:
                payload["think"] = False
            
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("response", "抱歉，我暂时无法回答。")
            else:
                ai_logger.error(f"Ollama API错误: {response.status_code}")
                return "AI服务暂时不可用，请稍后再试。"
        except Exception as e:
            ai_logger.error(f"Ollama调用错误: {str(e)}")
            return "AI服务连接失败，请联系管理员。"

    def _call_ollama_stream(self, prompt: str, system_prompt: str = "") -> AsyncGenerator[str, None]:
        """调用Ollama API - 流式响应"""
        ai_logger.debug(f"调用Ollama流式API - 模型: {self.model}, no_think: {self.no_think}")

        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": True
            }
            
            if self.no_think:
                payload["think"] = False
            
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=120,
                stream=True
            )

            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if 'response' in data:
                                yield data['response']
                            if data.get('done', False):
                                break
                        except json.JSONDecodeError:
                            continue
            else:
                ai_logger.error(f"Ollama API错误: {response.status_code}")
                yield "抱歉，我遇到了一些技术问题，请稍后再试。"
        except Exception as e:
            ai_logger.error(f"Ollama流式调用错误: {str(e)}")
            yield "抱歉，服务暂时不可用，请稍后再试。"

    def _clean_ai_text(self, text: str) -> str:
        """清理AI返回的文本，处理列表格式等问题，输出带编号的格式"""
        import html

        if not text:
            return text

        if isinstance(text, list):
            items = [str(item).strip() for item in text if item]
            if items:
                return '\n'.join([f"{i+1}. {item}" for i, item in enumerate(items)])
            return text

        if isinstance(text, str):
            text = html.unescape(text)
            text = text.strip()

            numbered_pattern = r'(?:^|\n)\s*(?:\d+[.、)]\s*|第\s*\d+\s*[题个章节点]?\s*[：:]\s*)(.+)'
            numbered_items = re.findall(numbered_pattern, text, re.MULTILINE)
            if numbered_items:
                cleaned_items = [item.strip() for item in numbered_items if item.strip()]
                if len(cleaned_items) >= 2:
                    return '\n'.join([f"{i+1}. {item}" for i, item in enumerate(cleaned_items)])

            list_items = []
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                line = re.sub(r'^[-*•]\s*', '', line)
                line = re.sub(r'^\*\s*', '', line)
                if line and not line.startswith('#'):
                    list_items.append(line)

            if len(list_items) >= 2:
                return '\n'.join([f"{i+1}. {item}" for i, item in enumerate(list_items)])

            semicolon_items = re.split(r'[；;]', text)
            semicolon_items = [item.strip() for item in semicolon_items if item.strip() and len(item.strip()) > 2]
            if len(semicolon_items) >= 2:
                return '\n'.join([f"{i+1}. {item}" for i, item in enumerate(semicolon_items)])

        return str(text)

    def _generate_feedback_with_ai(
        self,
        conversation: List[Dict],
        evaluations: List[Dict],
        scores_map: Dict[str, float]
    ) -> tuple:
        """使用AI生成面试反馈（优势、劣势、建议）"""
        qa_summary = []
        for msg in conversation:
            if msg.get('role') == 'interviewer':
                qa_summary.append(f"问：{msg.get('content', '')}")
            elif msg.get('role') in ['candidate', 'user']:
                qa_summary.append(f"答：{msg.get('content', '')}")

        scores_text = "\n".join([f"- {dim}：{score:.1f}/20分" for dim, score in scores_map.items()])

        detailed_evaluations = []
        for i, eval_item in enumerate(evaluations, 1):
            comment = eval_item.get('comment', eval_item.get('brief_comment', '无评语'))
            detailed_evaluations.append(f"第{i}题评价：{comment}")

        system_prompt = """以HR评估专家的思维逻辑，真实客观反馈：分数低→指出问题，不写或少些优势，分数高→肯定优势，同时也要指出问题所在。避免空话。
请直接生成准确且简洁的反馈内容，不需要JSON格式，只使用这种格式。
反馈应包含以下三个部分，用中文冒号分隔：
优势：具体的优势点
劣势：需要改进的地方
建议：针对性的改进建议"""

        prompt = f"""对话：
{chr(10).join(qa_summary[:15])}

评分(满分20)：
{scores_text}

评价：
{chr(10).join(detailed_evaluations[:10])}

任务：分数<10→批评，分数>15→表扬。请直接生成真实反馈。"""

        ai_logger.info("正在使用AI生成个性化面试反馈...")

        response = self._call_ollama(prompt, system_prompt)

        try:
            strengths = "技术基础扎实，学习能力强"
            weaknesses = "部分技术细节有待深入"
            suggestions = "建议继续保持学习热情，加强实战经验"
            
            if response:
                ai_logger.debug(f"AI原始反馈: {response}")
                
                if "优势：" in response:
                    strengths_part = response.split("优势：")[1]
                    if "劣势：" in strengths_part:
                        strengths = strengths_part.split("劣势：")[0].strip()
                        
                        weaknesses_part = strengths_part.split("劣势：")[1]
                        if "建议：" in weaknesses_part:
                            weaknesses = weaknesses_part.split("建议：")[0].strip()
                            suggestions = weaknesses_part.split("建议：")[1].strip()
                        else:
                            weaknesses = weaknesses_part.strip()
                else:
                    strengths = response.strip()
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

    def _calculate_grade(self, avg_score: float) -> str:
        """根据平均分计算等级"""
        avg_score_rounded = round(avg_score, 1)
        if avg_score_rounded >= 15:
            return "A"
        elif avg_score_rounded >= 13:
            return "B"
        elif avg_score_rounded >= 11:
            return "C"
        else:
            return "D"

    def _parse_json_response(self, response: str) -> Optional[Dict]:
        """从AI响应中解析JSON"""
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            ai_logger.error(f"JSON解析错误: {str(e)}")
        return None
