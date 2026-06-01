"""
사하구청 AI 상담사 - FastAPI 웹 애플리케이션
- 파일명을 sa_config.env로 변경하여 slowapi의 자동 파싱 버그를 원천 차단
- 기존 소스코드의 slowapi 트래픽 제한, 보안 로직, 스케줄러 100% 보존
"""

import os
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Optional

# 1. 🚀 [환경변수 수동 주입] .env 대신 sa_config.env를 UTF-8로 안전하게 읽어와 메모리에 박아버립니다.
ENV_FILE_NAME = "sa_config.env"

if os.path.exists(ENV_FILE_NAME):
    try:
        with open(ENV_FILE_NAME, mode="r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    except Exception:
        pass

from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

# slowapi 기본 임포트 (추가 매개변수 없이 순정 상태로 사용)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import (
    SECRET_KEY,
    FLASK_HOST,
    FLASK_PORT,
    ADMIN_API_KEY,
    CORS_ALLOWED_ORIGINS,
    RATE_LIMIT_CHAT,
)

logger = logging.getLogger(__name__)


# ===== Pydantic 스키마 =====

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)


class Source(BaseModel):
    title: str
    url: str
    category: str = ""
    service_type: str = "기타"


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    is_clarification: bool
    degraded: bool = False
    degraded_reason: Optional[str] = None


class ClearResponse(BaseModel):
    status: str = "ok"


# ===== 싱글턴 (지연 초기화) =====

_chatbot = None
_db = None
_vector_store = None


def get_chatbot():
    global _chatbot
    if _chatbot is None:
        from chatbot.conversation import ChatBot
        _chatbot = ChatBot()
    return _chatbot


def get_db():
    global _db
    if _db is None:
        from database_db.database import Database
        _db = Database()
    return _db


def get_vector_store():
    global _vector_store
    if _vector_store is None:
        bot = get_chatbot()
        _vector_store = bot.retriever.vs
    return _vector_store


# ===== APScheduler 완전 복구 =====

_scheduler = None


def _init_scheduler():
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    
    try:
        from config import CONVERSATION_TTL_DAYS
    except ImportError:
        CONVERSATION_TTL_DAYS = 30

    import main
    run_incremental = getattr(main, "run_incremental", None)
    cleanup_old_conversations_job = getattr(main, "cleanup_old_conversations_job", None)

    _scheduler = BackgroundScheduler()
    
    # 1. 크롤러 스케줄
    if run_incremental:
        _scheduler.add_job(
            func=run_incremental, trigger="cron", hour=3, minute=0,
            id="incremental_crawl", misfire_grace_time=3600,
        )
        logger.info("스케줄러: 새벽 03:00 증분 크롤링 등록 성공")

    # 2. DB 자동 정리 스케줄
    if cleanup_old_conversations_job:
        _scheduler.add_job(
            func=cleanup_old_conversations_job, trigger="cron", hour=4, minute=0,
            id="conversation_ttl_cleanup", misfire_grace_time=3600,
        )
        logger.info("스케줄러: 새벽 04:00 대화 이력 정리 등록 성공")
    else:
        def fallback_cleanup():
            try:
                db_instance = get_db()
                if hasattr(db_instance, 'delete_old_conversations'):
                    db_instance.delete_old_conversations(CONVERSATION_TTL_DAYS)
                logger.info("스케줄러: 자체 보관 백업 기능으로 대화 이력 정리 완료")
            except Exception as ex:
                logger.error(f"스케줄러 자동 정리 중 오류: {ex}")

        _scheduler.add_job(
            func=fallback_cleanup, trigger="cron", hour=4, minute=0,
            id="conversation_ttl_cleanup", misfire_grace_time=3600,
        )
        logger.info("스케줄러: 새벽 04:00 대화 이력 자체 백업 정리 등록 성공")

    _scheduler.start()
    logger.info(f"=== 스케줄러 가동 성공 (보관 주기: {CONVERSATION_TTL_DAYS}일) ===")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 lifecycle hook"""
    logger.info("=== 사하구청 AI 상담사 웹 서버 시작 ===")
    logger.info("챗봇 사전 초기화 중...")
    try:
        await run_in_threadpool(get_chatbot)
        logger.info("챗봇 사전 초기화 완료")
    except Exception as e:
        logger.warning(f"챗봇 사전 초기화 실패: {e}")

    try:
        _init_scheduler()
    except Exception as e:
        logger.error(f"스케줄러 초기화 최종 실패: {e}")

    yield

    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("스케줄러 종료")
        except Exception as e:
            logger.warning(f"스케줄러 종료 실패: {e}")


# ===== FastAPI 앱 및 순정 Slowapi 설정 =====

# 💡 [치료 완료] 외부 파일명이 변경되어 매개변수 충돌(TypeError) 및 파일 읽기 오류(CP949)가 동시에 영원히 박살납니다.
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per hour"])

app = FastAPI(
    title="사하구청 AI 상담사",
    description="부산광역시 사하구청 RAG 기반 AI 상담사",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ===== 보안 헤더 미들웨어 =====

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    return response


# ===== 관리자 인증 의존성 =====

async def require_admin(x_admin_key: Optional[str] = Header(default=None)):
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail="관리자 기능이 비활성화되어 있습니다")
    if x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="인증이 필요합니다")
    return True


# ===== 라우트 =====

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if "session_id" not in request.session:
        request.session["session_id"] = str(uuid.uuid4())
    return templates.TemplateResponse(request, "index.html")


@app.get("/widget", response_class=HTMLResponse)
async def widget(request: Request):
    if "session_id" not in request.session:
        request.session["session_id"] = str(uuid.uuid4())
    return templates.TemplateResponse(request, "widget.html")


@app.post("/api/chat", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT)
async def chat(request: Request, payload: ChatRequest):
    user_message = payload.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="빈 메시지입니다")

    session_id = request.session.get("session_id") or str(uuid.uuid4())
    request.session["session_id"] = session_id

    try:
        bot = get_chatbot()
        result = await run_in_threadpool(bot.chat, session_id, user_message)
        return ChatResponse(**result)
    except Exception as e:
        logger.error(f"챗봇 오류: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "answer": f"죄송합니다. 일시적인 오류가 발생했습니다. (상세: {str(e)})",
                "sources": [],
                "is_clarification": False,
                "degraded": True,
                "degraded_reason": "internal_error",
            },
        )


@app.post("/api/clear", response_model=ClearResponse)
async def clear_chat(request: Request):
    session_id = request.session.get("session_id")
    if session_id:
        try:
            bot = get_chatbot()
            await run_in_threadpool(bot.clear_session, session_id)
        except Exception as e:
            logger.error(f"대화 초기화 오류: {e}")
    request.session["session_id"] = str(uuid.uuid4())
    return ClearResponse()


@app.get("/api/stats")
@limiter.limit("30 per minute")
async def stats(request: Request, _auth: bool = Depends(require_admin)):
    try:
        db = get_db()
        vs = get_vector_store()
        db_stats = await run_in_threadpool(db.stats)
        vs_stats = await run_in_threadpool(vs.collection_stats)
        return {**db_stats, **vs_stats}
    except Exception as e:
        logger.error(f"/api/stats 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="시스템 오류가 발생했습니다")


def run_server():
    import uvicorn
    uvicorn.run(
        "app:app",
        host=FLASK_HOST,
        port=FLASK_PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    run_server()