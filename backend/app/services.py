"""原型阶段微信交换、每日建议和旧版规则问答服务。"""

import hashlib
import json
from datetime import date

import httpx
from fastapi import HTTPException

from .config import get_settings
from .models import BirthProfile


async def exchange_wechat_code(code: str) -> str:
    """开发环境生成模拟 openid；配置微信密钥后才调用真实 code2session。"""
    settings = get_settings()
    # 自动化测试必须始终使用确定性的本地openid，不能受开发者本机.env影响。
    if settings.testing:
        return "test_" + hashlib.sha256(code.encode()).hexdigest()[:24]
    # 只有开发环境且没有配置AppID时才允许模拟openid，生产环境绝不能走此分支。
    if settings.environment == "development" and not settings.wechat_app_id:
        return "dev_" + hashlib.sha256(code.encode()).hexdigest()[:24]
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise HTTPException(status_code=503, detail="微信登录尚未配置")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": settings.wechat_app_id,
                "secret": settings.wechat_app_secret,
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )
    data = response.json()
    if "openid" not in data:
        raise HTTPException(status_code=401, detail="微信登录失败")
    return data["openid"]


async def exchange_wechat_phone_code(code: str) -> str:
    """用手机号一次性 code 换取号码。

    该流程必须由后端完成：先用 AppID/AppSecret 取得小程序 access_token，再调用
    getuserphonenumber。AppSecret 绝不能发送给小程序或写入前端代码。
    """
    settings = get_settings()
    if settings.testing:
        raise HTTPException(status_code=503, detail="微信手机号能力在自动化测试中未启用")
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise HTTPException(status_code=503, detail="微信手机号能力尚未配置，请先完成小程序注册并配置AppID/AppSecret")
    # TODO（上线前）：access_token有效期内应缓存并在微信返回失效码时刷新，避免每次绑定都取新token。
    # 多实例部署时应使用Redis等共享缓存，而不是单进程内存。
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": settings.wechat_app_id, "secret": settings.wechat_app_secret},
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=502, detail="获取微信接口凭证失败")
        phone_response = await client.post(
            f"https://api.weixin.qq.com/wxa/business/getuserphonenumber?access_token={access_token}",
            json={"code": code},
        )
    data = phone_response.json()
    phone_number = (data.get("phone_info") or {}).get("phoneNumber")
    if data.get("errcode") != 0 or not phone_number:
        raise HTTPException(status_code=422, detail="微信手机号授权失败或临时code已失效")
    return phone_number


def build_daily_guidance(profile: BirthProfile, today: date) -> dict:
    """生成可重复的每日建议原型；同一档案同一天结果保持稳定。"""
    # 骨架阶段使用稳定、低风险的本地结果；后续替换为“排盘结果 + 知识检索 + LLM”。
    seed = int(hashlib.sha256(f"{profile.birth_date}:{today}".encode()).hexdigest(), 16)
    palettes = [
        ("蓝色", "米白色", "清爽、易搭配，可作为今日穿搭灵感"),
        ("绿色", "浅灰色", "自然柔和，适合日常通勤搭配"),
        ("暖黄色", "深蓝色", "明快但不过分强烈，可用于局部点缀"),
    ]
    first, second, reason = palettes[seed % len(palettes)]
    return {
        "date": today.isoformat(),
        "colors": [{"name": first, "reason": reason}, {"name": second, "reason": "可作为辅助配色"}],
        "suitable": ["整理近期计划", "进行适度运动", "耐心完成重要沟通"],
        "reminders": ["避免冲动消费", "重要决定请结合现实信息独立判断"],
        "culture_note": "传统历法反映了古人观察时间与自然的方式，适合从文化角度了解。",
        "disclaimer": "内容由程序生成，仅供传统文化了解和生活灵感参考。",
    }


BLOCKED_TERMS = {"血光之灾", "什么时候死", "彩票号码", "保证发财", "代替就医"}


def answer_question(question: str) -> tuple[str, str, list[str]]:
    """旧版关键词回答占位，不读取向量知识库，也不代表正式 AI 结论。"""
    if any(term in question for term in BLOCKED_TERMS):
        return (
            "生辰和民俗资料不能用于预测灾祸、疾病、死亡或投资结果。请依据现实信息和专业意见作出重要决定。",
            "high_risk_prediction",
            [],
        )
    return (
        "这是一个文化问答接口骨架。下一步接入审核过的知识库后，我会先检索资料，再以“传统文化中通常解释为”的方式回答，并列出来源。",
        "normal_culture",
        ["待接入：审核知识库"],
    )


def dumps_payload(payload: dict) -> str:
    """把中文业务数据序列化为数据库 JSON 文本。"""
    return json.dumps(payload, ensure_ascii=False)


def loads_payload(payload: str) -> dict:
    """从数据库 JSON 文本恢复字典。"""
    return json.loads(payload)
"""原型阶段的微信交换、每日建议和旧规则问答服务。"""
