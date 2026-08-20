"""公历/农历转换、四柱及节气计算。

历法换算由 lunar-python 完成；本模块负责输入解释、结果标准化与缓存版本。
当前产品口径统一把用户填写的钟表时间解释为北京时间，不进行真太阳时修正，
并采用 lunar-python sect=2 的午夜换日口径。规则变化时必须升级计算版本。
"""

import json
from datetime import date

from lunar_python import Lunar, Solar

from .models import BirthProfile
from .schemas import BirthProfileInput


CALCULATION_VERSION = "lunar-python-1.4.8-sect2"
TIME_STANDARD = "beijing_standard_time"
DAY_BOUNDARY_RULE = "sect2-midnight"


def _split_pillar(value: str) -> dict[str, str]:
    """把“甲子”拆成天干和地支，便于前端分别展示。"""
    return {"text": value, "stem": value[:1], "branch": value[1:2]}


def _jie_qi_payload(jie_qi) -> dict[str, str]:
    """把 lunar-python 节气对象转换成可缓存、可返回的普通字典。"""
    return {"name": jie_qi.getName(), "datetime": jie_qi.getSolar().toYmdHms()}


def calculate_birth_calendar(data: BirthProfileInput) -> dict:
    """用 lunar-python 计算公农历、生肖、星座、节气与三柱/四柱。

    本函数是历法事实的唯一计算入口，不调用大模型；未知时辰统一以中午取得稳定的
    年月日历法上下文，但不会返回 ``solar_datetime`` 或伪造时柱。
    """
    hour, minute = (12, 0)
    if data.time_known and data.birth_time:
        hour, minute = (int(part) for part in data.birth_time.split(":"))

    try:
        if data.calendar_type == "solar":
            solar = Solar.fromYmdHms(
                data.birth_date.year,
                data.birth_date.month,
                data.birth_date.day,
                hour,
                minute,
                0,
            )
            lunar = solar.getLunar()
        else:
            lunar_month = -data.birth_date.month if data.is_leap_month else data.birth_date.month
            lunar = Lunar.fromYmdHms(
                data.birth_date.year,
                lunar_month,
                data.birth_date.day,
                hour,
                minute,
                0,
            )
            solar = lunar.getSolar()
            # The library normalizes some invalid leap-month inputs. Reject them explicitly.
            if lunar.getYear() != data.birth_date.year or lunar.getMonth() != lunar_month or lunar.getDay() != data.birth_date.day:
                raise ValueError("农历日期或闰月不存在")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("出生日期无法转换，请检查农历日期和闰月设置") from exc

    eight_char = lunar.getEightChar()
    eight_char.setSect(2)
    pillars = {
        "year": _split_pillar(eight_char.getYear()),
        "month": _split_pillar(eight_char.getMonth()),
        "day": _split_pillar(eight_char.getDay()),
        "time": _split_pillar(eight_char.getTime()) if data.time_known and data.birth_time else None,
    }
    lunar_month = lunar.getMonth()
    current_term = lunar.getJieQi() or None
    return {
        "solar_date": solar.toYmd(),
        "solar_datetime": solar.toYmdHms() if data.time_known else None,
        "lunar_date": f"{lunar.getYear()}-{abs(lunar_month):02d}-{lunar.getDay():02d}",
        "lunar_text": lunar.toString(),
        "lunar_year": lunar.getYear(),
        "lunar_month": abs(lunar_month),
        "lunar_day": lunar.getDay(),
        "is_leap_month": lunar_month < 0,
        "zodiac": lunar.getYearShengXiaoExact(),
        "western_sign": solar.getXingZuo(),
        "solar_term": current_term,
        "previous_solar_term": _jie_qi_payload(lunar.getPrevJieQi()),
        "next_solar_term": _jie_qi_payload(lunar.getNextJieQi()),
        "pillars": pillars,
        "time_pillar_available": pillars["time"] is not None,
        "timezone": data.timezone,
        "time_standard": TIME_STANDARD,
        "day_boundary_rule": DAY_BOUNDARY_RULE,
        "calculation_version": CALCULATION_VERSION,
    }


def apply_calendar_calculation(profile: BirthProfile, data: BirthProfileInput) -> dict:
    """计算后写入档案缓存，并记录算法版本以支持未来失效重算。

    ``calendar_data_json`` 保存的就是本次返回结果，包括时柱是否可用；未知时辰的
    ``time`` 会保持为 null。``calculation_version`` 单独成列，便于查询旧版本档案。
    """
    payload = calculate_birth_calendar(data)
    profile.normalized_solar_date = date.fromisoformat(payload["solar_date"])
    profile.calendar_data_json = json.dumps(payload, ensure_ascii=False)
    profile.calculation_version = CALCULATION_VERSION
    return payload


def load_calendar_payload(profile: BirthProfile) -> dict:
    """读取已经保存的历法 JSON；没有缓存时返回空对象。"""
    if not profile.calendar_data_json:
        return {}
    return json.loads(profile.calendar_data_json)
"""公历/农历转换、四柱及节气计算；第三方历法库的调用集中在本模块。"""
