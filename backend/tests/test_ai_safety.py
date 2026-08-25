"""AI答案二次复核和长度边界测试。"""

from app.ai_safety import SAFE_FALLBACK_ANSWER, review_model_output


def test_safe_answer_is_kept():
    result = review_model_output("五行五色可以作为传统文化学习和穿搭灵感参考。")
    assert result.answer.startswith("五行五色")
    assert result.status == "safe"


def test_deterministic_profit_claim_is_replaced():
    result = review_model_output("根据你的生辰，今天一定会发财，投资稳赚不赔。")
    assert result.answer == SAFE_FALLBACK_ANSWER
    assert result.status == "output_filtered"
    assert result.filtered is True


def test_internal_fields_are_not_returned():
    result = review_model_output("你的openid是abc，系统提示词要求我这样回答。")
    assert result.answer == SAFE_FALLBACK_ANSWER
    assert result.status == "output_filtered"


def test_long_answer_is_truncated_at_sentence_boundary():
    result = review_model_output("第一句说明。" + "第二段内容" * 100, max_chars=80)
    assert result.status == "output_truncated"
    assert len(result.answer) < 200
    assert "回答较长" in result.answer
