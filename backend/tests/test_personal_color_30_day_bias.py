"""PERSONAL_FIVE_COLOR_V1 的三用户三十日稳定性与偏置检测。"""

from collections import Counter
from datetime import date, timedelta

from app.calendar_service import apply_calendar_calculation
from app.daily_color_context import build_personal_rule_input, build_public_rule_input
from app.daily_color_personal_engine_v1 import calculate_personal_rule_v1
from app.daily_color_research_v1 import PERSONAL_RESEARCH_CONFIG, PUBLIC_RESEARCH_CONFIG
from app.daily_color_rule_engine import calculate_public_rule
from app.models import BirthProfile
from app.schemas import BirthProfileInput


def profile(birth_date: date, birth_time: str, city: str, version: int) -> BirthProfile:
    data = BirthProfileInput(
        birth_date=birth_date,
        time_known=True,
        birth_time=birth_time,
        birth_city=city,
        gender="unspecified",
    )
    result = BirthProfile(user_id=10_000 + version, profile_version=1, **data.model_dump())
    apply_calendar_calculation(result, data)
    return result


def public_snapshot(target_date: date) -> list[dict[str, str | int]]:
    calculation = calculate_public_rule(
        build_public_rule_input(target_date, PUBLIC_RESEARCH_CONFIG.version),
        PUBLIC_RESEARCH_CONFIG,
    )
    old_to_element = {"白金": "金", "绿金": "木", "黑金": "水", "红金": "火", "黄金": "土"}
    return [
        {"rank": item.rank, "color": item.color, "element": old_to_element[item.color]}
        for item in calculation.result.ranking.items
    ]


def test_three_users_thirty_days_have_no_single_color_bias(capsys):
    users = [
        profile(date(1988, 2, 14), "07:30", "北京", 1),
        profile(date(1995, 6, 18), "14:30", "杭州", 2),
        profile(date(2001, 11, 3), "21:10", "成都", 3),
    ]
    start = date(2042, 3, 1)
    distributions: list[Counter[str]] = []
    all_results: dict[tuple[int, date], tuple[str, ...]] = {}

    for user_index, user in enumerate(users):
        first_counts: Counter[str] = Counter()
        for offset in range(30):
            target = start + timedelta(days=offset)
            rule_input = build_personal_rule_input(user, target, PERSONAL_RESEARCH_CONFIG.version)
            snapshot = public_snapshot(target)
            result = calculate_personal_rule_v1(
                rule_input,
                PERSONAL_RESEARCH_CONFIG,
                PUBLIC_RESEARCH_CONFIG,
                public_ranking=snapshot,
            )
            repeat = calculate_personal_rule_v1(
                rule_input,
                PERSONAL_RESEARCH_CONFIG,
                PUBLIC_RESEARCH_CONFIG,
                public_ranking=snapshot,
            )
            assert result.result.final_scores == repeat.result.final_scores
            assert result.result.ranking == repeat.result.ranking
            assert len(result.result.ranking.items) == 5
            assert all(0 <= item.score <= 100 for item in result.result.ranking.items)
            first_counts[result.result.ranking.items[0].element] += 1
            all_results[(user_index, target)] = tuple(item.element for item in result.result.ranking.items)
        distributions.append(first_counts)

    assert all(max(counts.values(), default=0) <= 15 for counts in distributions)
    assert all(sum(sorted(counts.values(), reverse=True)[:2]) <= 24 for counts in distributions)
    assert len({all_results[(index, start)][0] for index in range(3)}) >= 2
    assert len({all_results[(1, start + timedelta(days=offset))][0] for offset in range(30)}) >= 2

    print("PERSONAL_FIVE_COLOR_V1 30-day first-color distribution:")
    for index, counts in enumerate(distributions, start=1):
        print(f"user{index}: {dict(sorted(counts.items()))}")
    captured = capsys.readouterr().out
    assert "WARNING" not in captured
