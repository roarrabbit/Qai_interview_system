"""
系统日志模块 - 包含AI面试日志和系统操作日志
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

os.makedirs("logs", exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}

_current_log_level = LOG_LEVEL.upper()

def get_log_level():
    """获取日志级别"""
    return LOG_LEVELS.get(_current_log_level, logging.INFO)

def get_log_level_name():
    """获取当前日志级别名称"""
    return _current_log_level

def set_log_level(level_name: str):
    """动态设置日志级别
    
    Args:
        level_name: 日志级别名称 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    global _current_log_level
    
    level_name = level_name.upper()
    if level_name not in LOG_LEVELS:
        raise ValueError(f"无效的日志级别: {level_name}，有效值为: {list(LOG_LEVELS.keys())}")
    
    _current_log_level = level_name
    level = LOG_LEVELS[level_name]
    
    ai_logger.setLevel(level)
    for handler in ai_logger.handlers:
        handler.setLevel(level)
    
    system_logger.setLevel(level)
    for handler in system_logger.handlers:
        handler.setLevel(level)
    
    system_logger.info(f"日志级别已切换为: {level_name}")
    return level_name


# 创建日志格式
log_format = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ============ AI面试日志 ============
ai_logger = logging.getLogger('ai_interview')
ai_logger.setLevel(get_log_level())
ai_logger.propagate = False

ai_handler = RotatingFileHandler(
    'logs/ai_interview.log',
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=3,
    encoding='utf-8'
)
ai_handler.setFormatter(log_format)
ai_logger.addHandler(ai_handler)

# ============ 系统日志 ============
system_logger = logging.getLogger('system')
system_logger.setLevel(get_log_level())
system_logger.propagate = False

system_handler = RotatingFileHandler(
    'logs/system.log',
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
system_handler.setFormatter(log_format)
system_logger.addHandler(system_handler)

# ============ AI面试相关日志函数 ============


def log_ai_question(interview_id: int, candidate_id: int, question: str):
    """记录AI提问"""
    question_single_line = question.replace('\n', '\\n').replace('\r', '\\r')
    ai_logger.debug(f"AI提问 - 面试ID: {interview_id}, 求职者ID: {candidate_id}")
    ai_logger.debug(f"问题: {question_single_line}")


def log_ai_answer(interview_id: int, candidate_id: int, answer: str):
    """记录求职者回答"""
    answer_single_line = answer.replace('\n', '\\n').replace('\r', '\\r')
    ai_logger.info(f"求职者回答 - 面试ID: {interview_id}, 求职者ID: {candidate_id}")
    ai_logger.debug(f"回答: {answer_single_line}")


def log_ai_evaluation(interview_id: int, candidate_id: int, evaluation: dict):
    """记录AI评估"""
    ai_logger.info(f"AI评估 - 面试ID: {interview_id}, 求职者ID: {candidate_id}")
    ai_logger.debug(f"评估结果: {evaluation}")


def log_ai_report(interview_id: int, candidate_id: int, report: dict):
    """记录AI面试报告"""
    ai_logger.debug(
        f"AI面试报告生成 - 面试ID: {interview_id}, 求职者ID: {candidate_id}, 评级: {
            report.get(
                'overall_grade',
                'N/A')}")
    report_copy = {k: v for k, v in report.items() if k != 'radar_data'}
    ai_logger.debug(f"完整报告: {report_copy}")

# ============ 系统操作日志函数 ============


def log_platform_startup():
    """平台启动"""
    system_logger.info("平台启动")


def log_platform_shutdown():
    """平台停止"""
    system_logger.warning("平台停止")


def log_user_register(username: str, role: str):
    """用户注册"""
    system_logger.info(f"新用户注册: {username} (角色: {role})")


def log_user_login(username: str, role: str, success: bool = True):
    """用户登录"""
    status = "成功" if success else "失败"
    system_logger.info(f"用户登录: {username} (角色: {role}, 状态: {status})")


def log_admin_login(username: str):
    """管理员登录"""
    system_logger.info(f"管理员登录: {username}")


def log_admin_action(username: str, action: str, details: str = ""):
    """管理员操作"""
    system_logger.info(f"管理员操作: {username} - {action}")
    if details:
        system_logger.debug(f"操作详情: {details}")


def log_job_created(job_title: str, hr_username: str):
    """岗位发布"""
    system_logger.debug(f"新岗位发布: {job_title} (发布者: {hr_username})")


def log_interview_completed(interview_id: int, candidate_username: str, job_title: str, grade: str):
    """面试完成"""
    system_logger.info(f"面试完成: ID={interview_id}, 候选人={candidate_username}, 岗位={job_title}, 评级={grade}")


def log_application_submitted(candidate_username: str, job_title: str):
    """申请提交"""
    system_logger.debug(f"新申请提交: {candidate_username} 申请 {job_title}")


def log_config_updated(config_key: str, old_value: str, new_value: str, admin_username: str):
    """系统配置修改"""
    system_logger.info(f"系统配置修改: {config_key} (修改者: {admin_username})")
    system_logger.debug(f"配置变更: {old_value} -> {new_value}")
