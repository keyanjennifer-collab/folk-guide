"""FastAPI 应用入口：装配登录、档案、每日建议及后台路由。"""

import asyncio
from asyncio import CancelledError
from contextlib import asynccontextmanager
from contextlib import suppress
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import create_token, current_user
from .ai_routes import router as ai_router
from .ai_service import quota_for_user
from .calendar_service import apply_calendar_calculation, calculate_birth_calendar
from .config import get_settings, validate_runtime_settings
from .database import Base, SessionLocal, engine, get_db
from .daily_color_cache_service import warm_personal_color_cache, warm_public_color_cache
from .daily_color_rule_routes import router as daily_color_rule_router
from .daily_update_routes import router as daily_update_router
from .daily_update_service import daily_cache_scheduler_loop
from .migrations import migrate_development_schema
from .models import AIConversation, AIConversationMessage, AIDeletedUsage, AIServiceGrant, BirthProfile, ChatMessage, DailyGuidance, User, ZiweiChartRecord, ZiweiCompatibilityRecord
from .profile_service import profile_output
from .public_guide_routes import router as public_guide_router
from .knowledge_routes import router as knowledge_router
from .order_routes import Order, router as order_router
from .schemas import (
    BirthProfileInput,
    BirthProfileOutput,
    CalendarConversionOutput,
    ChatRequest,
    ChatResponse,
    DailyGuidanceOutput,
    LoginRequest,
    TokenResponse,
    CurrentUserOutput,
    PhoneCodeInput,
    UserProfileInput,
)
from .services import answer_question, exchange_wechat_code, exchange_wechat_phone_code
from .time_service import beijing_today
from .ziwei_routes import router as ziwei_router
from .ziwei_interpret_routes import router as ziwei_interpret_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    """建表迁移、启动时预热公共缓存，并管理北京时间每日调度任务。"""
    runtime_settings = get_settings()
    # 生产表结构由部署命令 ``alembic upgrade head`` 管理；只有开发/测试环境
    # 才允许启动时自动建表和执行 SQLite 兼容迁移，避免线上隐式改表。
    if runtime_settings.environment.lower() != "production" and runtime_settings.auto_create_schema:
        Base.metadata.create_all(engine)
        migrate_development_schema(engine)
    scheduler_task: asyncio.Task | None = None
    # 正式运行时由带数据库租约的任务统一完成启动补跑，避免多worker在lifespan中
    # 同时写公共缓存。测试或显式关闭调度时仍同步预热，保持接口开箱即用。
    if runtime_settings.testing or not runtime_settings.daily_scheduler_enabled:
        with SessionLocal() as db:
            warm_public_color_cache(db, beijing_today())
    # 测试进程直接调用任务服务验证，不启动常驻循环，避免每个TestClient重复创建线程。
    if runtime_settings.daily_scheduler_enabled and not runtime_settings.testing:
        scheduler_task = asyncio.create_task(
            daily_cache_scheduler_loop(), name="daily-color-cache-scheduler"
        )
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            with suppress(CancelledError):
                await scheduler_task


settings = get_settings()
validate_runtime_settings(settings)

# Swagger /docs 按真实业务域分组。
OPENAPI_TAGS = [
    {
        "name": "系统状态",
        "description": "部署与运维检查接口，不读写用户业务数据。",
    },
    {
        "name": "账号与微信登录",
        "description": "微信 code2Session、JWT账号状态、手机号绑定及账号注销。除登录外均需 Bearer JWT。",
    },
    {
        "name": "生辰档案与历法",
        "description": "本人单档案的读取、保存、删除，以及公农历和四柱结构计算。全部接口按JWT隔离用户。",
    },
    {
        "name": "今日五色·用户端",
        "description": "小程序首页使用的公开内容，按北京时间和确定性历法规则每日自动生成并缓存，不要求登录。",
    },
    {
        "name": "AI国学·用户问答",
        "description": "AI国学权益次数、受约束问答、可用引用、历史和反馈。需要 Bearer JWT；前端通过quota接口的answer_ready判断服务是否就绪。",
    },
    {
        "name": "AI国学·知识库后台",
        "description": "知识资料上传、解析、切片、人工审核、向量同步和检索预览。需要 X-Admin-Key。",
    },
    {
        "name": "个人五色·用户端",
        "description": "按本人档案与当天时序生成个人五色，需有效AI国学体验或服务权益；提前缓存未来3天。",
    },
    {
        "name": "每日缓存·运维",
        "description": "北京时间每日00:00批量预热公共7天和有效用户个人3天缓存；状态与补跑接口需要 X-Admin-Key。",
    },
    {
        "name": "旧版兼容接口",
        "description": "仅为旧前端保留，已被新版接口替代，新功能不要接入。",
    },
]

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "五色知时小程序 Python API。用户端受保护接口使用 `Authorization: Bearer <JWT>`；"
        "知识库与运维接口使用 `X-Admin-Key`。接口文档中的“原型”或“旧版”分组不能作为正式业务能力。"
    ),
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)
app.mount(
    "/product-assets",
    StaticFiles(directory=Path(__file__).with_name("static") / "products"),
    name="product-assets",
)
app.add_middleware(
    CORSMiddleware,
    # 小程序客户端不受浏览器CORS约束；这里主要服务本地浏览器预览和运营页。
    # TODO（上线前）：配置明确的后台管理域名，禁止生产环境使用通配来源。
    allow_origins=(
        ["*"]
        if settings.environment == "development"
        else [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    ),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(public_guide_router)
app.include_router(daily_color_rule_router)
app.include_router(knowledge_router)
app.include_router(ai_router)
app.include_router(daily_update_router)
app.include_router(order_router)
app.include_router(ziwei_router)
app.include_router(ziwei_interpret_router)


@app.get("/health", tags=["系统状态"], summary="检查后端服务是否正常")
def health() -> dict[str, str]:
    """供部署平台检查进程是否正常响应，不读取业务数据。"""
    return {"status": "ok"}


@app.post(
    "/api/auth/wechat",
    response_model=TokenResponse,
    tags=["账号与微信登录"],
    summary="用微信临时code登录并签发JWT",
    response_description="Bearer JWT及令牌类型",
)
async def wechat_login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """用微信临时 code 换 openid，再签发只包含内部用户编号的 JWT。"""
    openid = await exchange_wechat_code(data.code)
    # openid在同一小程序内稳定且唯一；不同小程序之间不能直接用openid合并账号。
    user = db.scalar(select(User).where(User.openid == openid))
    if user is None:
        user = User(openid=openid)
        db.add(user)
        db.commit()
        db.refresh(user)
    return TokenResponse(access_token=create_token(user.id))


@app.get(
    "/api/users/me",
    response_model=CurrentUserOutput,
    tags=["账号与微信登录"],
    summary="读取当前登录账号状态",
)
def current_account(user: User = Depends(current_user)):
    """校验 JWT 并返回当前账号状态；不暴露 openid。"""
    return {
        "id": user.id, "phone_number": user.phone_number,
        "phone_bound": bool(user.phone_number),
        "wechat_phone_available": bool(settings.wechat_app_id and settings.wechat_app_secret),
        "created_at": user.created_at, "nickname": user.nickname, "avatar_url": user.avatar_url,
    }

@app.put("/api/users/me/profile", response_model=CurrentUserOutput, tags=["账号与微信登录"])
def update_account_profile(data: UserProfileInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.nickname = data.nickname.strip()
    user.avatar_url = data.avatar_url
    db.commit(); db.refresh(user)
    return {"id": user.id, "phone_number": user.phone_number, "phone_bound": bool(user.phone_number),
            "wechat_phone_available": bool(settings.wechat_app_id and settings.wechat_app_secret),
            "created_at": user.created_at, "nickname": user.nickname, "avatar_url": user.avatar_url}


@app.post(
    "/api/users/me/phone",
    response_model=CurrentUserOutput,
    tags=["账号与微信登录"],
    summary="使用微信手机号code绑定账号",
)
async def bind_phone(data: PhoneCodeInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """服务端换取并保存微信绑定手机号，临时 code 只能使用一次。"""
    phone_number = await exchange_wechat_phone_code(data.code)
    user.phone_number = phone_number
    user.phone_bound_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return {
        "id": user.id, "phone_number": user.phone_number, "phone_bound": True,
        "wechat_phone_available": True, "created_at": user.created_at,
    }


@app.get(
    "/api/profiles/current",
    response_model=BirthProfileOutput,
    tags=["生辰档案与历法"],
    summary="读取当前用户的生辰档案",
)
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """读取当前登录用户自己的档案；旧档案缺少历法缓存时自动补算。"""
    profile = db.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(status_code=404, detail="尚未创建生辰档案")
    if not profile.calendar_data_json:
        data = BirthProfileInput.model_validate(profile, from_attributes=True)
        try:
            apply_calendar_calculation(profile, data)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        db.commit()
        db.refresh(profile)
    return profile_output(profile)


@app.post(
    "/api/calendar/convert",
    response_model=CalendarConversionOutput,
    tags=["生辰档案与历法"],
    summary="预览公农历及四柱结构转换",
)
def convert_calendar(data: BirthProfileInput, _: User = Depends(current_user)):
    """只预览历法转换，不保存档案；仍要求登录以控制接口滥用。"""
    try:
        payload = calculate_birth_calendar(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized_date = date.fromisoformat(payload["solar_date"])
    if normalized_date > beijing_today():
        raise HTTPException(status_code=422, detail="出生日期不能晚于今天")
    if normalized_date < date(1900, 1, 1):
        raise HTTPException(status_code=422, detail="当前版本仅支持1900年1月1日及之后的日期")
    return payload


@app.put(
    "/api/profiles/current",
    response_model=BirthProfileOutput,
    tags=["生辰档案与历法"],
    summary="创建或修改当前用户的生辰档案",
)
def save_profile(data: BirthProfileInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """新增或更新当前用户档案，并用版本号驱动个人缓存失效。

    首次创建使用模型默认的 ``profile_version=1``；已有档案每次成功修改加一。
    个人五色缓存会记录这个版本，因此旧档案产生的结果不会误用于新档案。
    """
    profile = db.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id))
    if profile is None:
        # 新账号只有一份档案，user_id唯一约束也会在数据库层阻止重复创建。
        profile = BirthProfile(user_id=user.id, profile_version=1, **data.model_dump())
        db.add(profile)
    else:
        # 只复制Pydantic允许的档案字段，不接受前端提交id、user_id或版本号。
        for key, value in data.model_dump().items():
            setattr(profile, key, value)
        profile.profile_version += 1
    try:
        payload = apply_calendar_calculation(profile, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized_date = date.fromisoformat(payload["solar_date"])
    if normalized_date > beijing_today():
        raise HTTPException(status_code=422, detail="出生日期不能晚于今天")
    if normalized_date < date(1900, 1, 1):
        raise HTTPException(status_code=422, detail="当前版本仅支持1900年1月1日及之后的日期")
    # 档案首次创建或版本更新后，删除该用户所有日期的旧个人建议。未来改成三天预缓存
    # 时仍使用同一失效入口，避免旧生辰对应的结果继续被读取。
    db.query(DailyGuidance).filter(DailyGuidance.user_id == user.id).delete()
    # 只有AI国学体验或正式服务有效时才使用档案生成个人五色。个人结果不扣问答次数。
    quota = quota_for_user(db, user)
    if quota.active and quota.plan:
        warm_personal_color_cache(
            db, profile, quota.plan, beijing_today(), commit=False
        )
    db.commit()
    db.refresh(profile)
    return profile_output(profile)


@app.delete(
    "/api/profiles/current",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["生辰档案与历法"],
    summary="删除当前用户的生辰档案",
)
def delete_profile(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """删除本人档案及其每日建议，不会删除微信账号或使JWT失效。"""
    profile = db.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id))
    if profile is not None:
        db.query(DailyGuidance).filter(DailyGuidance.user_id == user.id).delete()
        db.delete(profile)
        db.commit()
    return Response(status_code=204)


@app.get(
    "/api/daily",
    response_model=DailyGuidanceOutput,
    tags=["个人五色·用户端"],
    summary="读取本人今日五色并预热未来3天",
)
def get_daily(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """权益有效时读取个人五色；未授权时不会加载档案进入个人规则计算。"""
    # 权益校验必须排在档案查询之前。体验到期后即使数据库还有旧缓存也不能返回。
    quota = quota_for_user(db, user)
    if not quota.active or not quota.plan:
        raise HTTPException(status_code=403, detail="个人五色需要有效的AI国学体验或服务权益")
    profile = db.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(status_code=409, detail="请先创建生辰档案")
    today = beijing_today()
    payloads = warm_personal_color_cache(db, profile, quota.plan, today)
    return payloads[today]


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    tags=["旧版兼容接口"],
    summary="旧版规则问答（请改用 /api/ai/chat）",
    deprecated=True,
)
def chat(data: ChatRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """旧版规则问答接口；正式知识库 AI 接口完成后将由 /api/ai/chat 替代。"""
    answer, category, references = answer_question(data.question.strip())
    db.add(ChatMessage(user_id=user.id, question=data.question, answer=answer))
    db.commit()
    return ChatResponse(answer=answer, category=category, references=references)


@app.delete(
    "/api/account",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["账号与微信登录"],
    summary="注销当前账号并删除个人数据",
)
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """注销当前账号，并清理个人档案、权益及全部问答历史。

    当前原型立即物理删除。TODO（上线前）：增加二次确认、审计记录、订单法定留存策略，
    并让已签发JWT通过token_version或撤销列表立即失效。
    """
    # 必须先删没有配置数据库级联的子表，否则PostgreSQL启用外键后会拒绝删除用户。
    db.query(AIConversationMessage).filter(AIConversationMessage.user_id == user.id).delete()
    db.query(AIConversation).filter(AIConversation.user_id == user.id).delete()
    db.query(AIDeletedUsage).filter(AIDeletedUsage.user_id == user.id).delete()
    db.query(AIServiceGrant).filter(AIServiceGrant.user_id == user.id).delete()
    db.query(ChatMessage).filter(ChatMessage.user_id == user.id).delete()
    db.query(DailyGuidance).filter(DailyGuidance.user_id == user.id).delete()
    db.query(Order).filter(Order.user_id == user.id).delete()
    db.query(ZiweiCompatibilityRecord).filter(ZiweiCompatibilityRecord.user_id == user.id).delete()
    db.query(ZiweiChartRecord).filter(ZiweiChartRecord.user_id == user.id).delete()
    db.delete(user)
    db.commit()
    return Response(status_code=204)
"""FastAPI 应用入口：装配路由，并提供登录、档案、每日建议与旧版问答接口。"""
