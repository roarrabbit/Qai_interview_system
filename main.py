"""
智能招聘平台 - 面向计算机行业的智能招聘平台
Version: 0.2.7.8
Developer: MLLR
Development Period: 2025.12 ~ 2026.04
License: Apache License 2.0
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from app.routers import auth, users, jobs, applications, interviews, admin, system, pages, candidates, messages, conversation_interview
from app.config import settings, setup_logging
from app.logger import log_platform_startup, log_platform_shutdown, system_logger
import os
from datetime import datetime

# 配置日志级别
setup_logging()

# 安全响应头中间件


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # 防止点击劫持
        response.headers["X-Frame-Options"] = "DENY"
        # 防止MIME类型嗅探
        response.headers["X-Content-Type-Options"] = "nosniff"
        # 缓存控制
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

        # 增强的内容安全策略（CSP）
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.bootcdn.net https://cdn.staticfile.org",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.bootcdn.net https://cdn.staticfile.org",
            "img-src 'self' data: https:",
            "font-src 'self' https://cdn.jsdelivr.net https://cdn.bootcdn.net https://cdn.staticfile.org",
            "connect-src 'self' https://cdn.jsdelivr.net https://cdn.bootcdn.net https://cdn.staticfile.org",
            "frame-ancestors 'none'",  # 防止Clickjacking
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'"
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # 引用策略
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # 权限策略
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        # 确保Content-Type使用UTF-8 charset
        if "content-type" in response.headers:
            content_type = response.headers["content-type"]
            if "; charset=" not in content_type.lower():
                response.headers["content-type"] = f"{content_type}; charset=utf-8"
        
        return response

# Lifespan事件处理


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    global app_start_time
    app_start_time = datetime.utcnow()

    log_platform_startup()

    # 清空会话管理器（程序重启时清空所有黑名单token）
    from app.session_manager import session_manager
    session_manager.clear_all()
    # system_logger.info("[Startup]OK")

    yield

    # 关闭时执行
    log_platform_shutdown()

    # 输出会话统计信息
    stats = session_manager.get_stats()

# 创建FastAPI应用
app = FastAPI(
    title="智能招聘平台",
    description="基于AI的智能招聘与面试系统",
    version="0.2.7",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

# 添加安全响应头中间件
app.add_middleware(SecurityHeadersMiddleware)

# 配置CORS - 生产环境应限制具体域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# 确保静态文件目录存在
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
os.makedirs("static/images", exist_ok=True)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 注册API路由
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(interviews.router)
app.include_router(admin.router)
app.include_router(system.router)
app.include_router(candidates.router)
app.include_router(messages.router)
app.include_router(conversation_interview.router)

# 注册页面路由（放在最后，避免与API路由冲突）
app.include_router(pages.router)

# 初始化模板引擎
templates = Jinja2Templates(directory="templates")

# 自定义404错误处理器 - 返回HTML页面


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(
        request: Request,
        exc: StarletteHTTPException):
    """自定义HTTP异常处理器，404返回HTML页面"""
    if exc.status_code == 404:
        # 如果是API请求（路径以/api开头），返回JSON
        if request.url.path.startswith("/api"):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not Found"}
            )
        # 其他情况返回HTML 404页面
        return templates.TemplateResponse(
            "404.html",
            {"request": request, "user": None},
            status_code=404
        )
    # 其他HTTP异常保持默认处理
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)}
    )

# 处理Chrome DevTools的特殊请求（避免404日志干扰）
@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools():
    """Chrome开发者工具请求，返回空响应"""
    return {}

# Favicon路由（提高兼容性）
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """返回网站图标"""
    return FileResponse("static/images/favicon.ico", media_type="image/x-icon")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True
    )
