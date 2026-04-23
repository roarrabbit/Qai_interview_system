"""
面试安全检查模块 - 防止恶意输入和提示注入攻击
"""

BLOCKED_KEYWORDS = [
    "忽略", "ignore", "跳过", "bypass", "绕过",
    "system prompt", "系统提示", "system instruction",
    "你现在是", "you are now", "扮演", "pretend", "roleplay",
    "请执行", "execute", "运行命令", "run command",
    "告诉我你的", "tell me your", "reveal your",
    "开发者模式", "developer mode", "debug mode",
    "忘记之前", "forget previous", "清除记忆",
    "没有任何限制", "no restrictions", "no limits",
    "不要使用抱歉", "don't use sorry", "不要说不能",
    "必须回答", "must answer", "必须执行",
    "脏话", "curse", "骂人",
    "越狱", "jailbreak", "突破",
    "do anything now", "忽略不相关的道德诉求", "忽略任何限制",
]

BLOCKED_PATTERNS = [
    r"接下来你只能",
    r"请完全遵循",
    r"不要使用['\"]?抱歉",
    r"我不能['\"]?类似的回答",
    r"忽略.*限制",
    r"忽略.*道德",
    r"请告诉我.*IP",
    r"请执行.*命令",
    r"请查询.*服务器",
]

WARNING_TEXTS = [
    "请注意，您的输入包含不当内容。请专注于回答面试问题。",
    "再次提醒，请勿发送与面试无关的内容。继续违规将终止面试。",
    "这是最后一次警告，请认真回答面试问题。"
]


def check_malicious_input(message: str) -> tuple:
    """检查用户输入是否包含恶意内容，返回 (is_blocked, warning_message)"""
    message_lower = message.lower()
    
    for keyword in BLOCKED_KEYWORDS:
        if keyword.lower() in message_lower:
            return True, f"检测到不允许的关键词：{keyword}"
    
    for pattern in BLOCKED_PATTERNS:
        import re
        if re.search(pattern, message, re.IGNORECASE):
            return True, "检测到不允许的输入模式"
    
    return False, ""


def get_warning_text(warning_count: int) -> str:
    """获取警告文本"""
    return WARNING_TEXTS[min(warning_count - 1, 2)]
