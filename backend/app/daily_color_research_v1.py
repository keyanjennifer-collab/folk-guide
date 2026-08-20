"""五色知时“资料综合版 V1.0”的可执行配置。

这不是把某一本古籍包装成现代穿衣打分公式。代码中的映射分三层：

* 古籍可考层：五行五色、生克次序、四时旺相休囚死、月令和日主原则；
* 产品解释层：把候选颜色视作用户当天采用的五行，把日期视作公共环境；
* 工程参数层：权重、倍率、阈值、藏干比例和同分顺序。

所有工程参数都集中在本文件，方便产品试运行后以新版本替换，禁止在引擎里散落
“魔法数字”。状态使用 ``source_reviewed``，意思是资料已经整理，但没有冒充线下
专家背书。
"""

from .daily_color_personal_config import (
    DayMasterStrengthThresholds,
    DayMasterStrategyScores,
    ElementRoleScores,
    HiddenStemShare,
    PersonalPillarWeights,
    PersonalRuleConfiguration,
    SeasonalStateMultipliers,
)
from .daily_color_rule_config import (
    ElementRelationScores,
    PublicFactorWeights,
    PublicRuleConfiguration,
    TendencyThresholds,
)


PUBLIC_RESEARCH_VERSION = "wuse-public-research-v1.0"
PERSONAL_RESEARCH_VERSION = "wuse-personal-research-v1.0"


# 二十四节气按其所在月建的主五行归类：寅卯木、辰土、巳午火、未土、申酉金、
# 戌土、亥子水、丑土。四个季末土月单列，避免把二十四节气机械四等分。
SOLAR_TERM_ELEMENT_V1 = {
    "立春": "木", "雨水": "木", "惊蛰": "木", "春分": "木",
    "清明": "土", "谷雨": "土",
    "立夏": "火", "小满": "火", "芒种": "火", "夏至": "火",
    "小暑": "土", "大暑": "土",
    "立秋": "金", "处暑": "金", "白露": "金", "秋分": "金",
    "寒露": "土", "霜降": "土",
    "立冬": "水", "小雪": "水", "大雪": "水", "冬至": "水",
    "小寒": "土", "大寒": "土",
}


PUBLIC_RESEARCH_CONFIG = PublicRuleConfiguration(
    version=PUBLIC_RESEARCH_VERSION,
    status="source_reviewed",
    algorithm_summary=(
        "资料综合版公共五色：按北京时间取得年、月、日三柱与当前节气；日期层45%、"
        "月令季节层45%、年层10%。候选色相对公共环境按生克关系换算后加权。关系层级"
        "采用环境生候选、同类、候选克环境、候选生环境、环境克候选的工程顺序；它是"
        "基于传统生克原则的现代生活建议模型，不是古籍原生穿衣公式。"
    ),
    factor_weights=PublicFactorWeights(
        year_stem=5,
        year_branch=5,
        month_stem=15,
        month_branch=25,
        day_stem=25,
        day_branch=20,
        solar_term=5,
    ),
    relation_scores=ElementRelationScores(
        same_element=20,
        candidate_generates_reference=-10,
        reference_generates_candidate=30,
        candidate_controls_reference=5,
        reference_controls_candidate=-25,
    ),
    solar_term_elements=SOLAR_TERM_ELEMENT_V1,
    # 精确同分仅用于保证缓存和测试的确定性。顺序采用木→火→土→金→水的相生循环，
    # 不表示在任何日期木色天然优先。
    tie_break_color_order=["绿金", "红金", "黄金", "白金", "黑金"],
    tendency_thresholds=TendencyThresholds(
        strong_support_min=18,
        support_min=8,
        balanced_min=0,
        caution_min=-10,
    ),
    professional_references=[
        "《黄帝内经·素问·阴阳应象大论》：东方木青、南方火赤、中央土黄、西方金白、北方水黑。https://ctext.org/huangdi-neijing/yin-yang-ying-xiang-da-lun/zh",
        "《五行大义》卷二：五行相生次序、干支五行与春夏季夏秋冬旺相休囚死。https://ctext.org/wiki.pl?if=gb&chapter=599847",
        "《子平真诠评注》：八字用神专求月令，同时须结合年日时根气判断强弱。https://ctext.org/wiki.pl?if=gb&chapter=974137",
        "公共颜色的百分制权重和五档关系分是本项目工程参数，不是上述原典中的数值。",
    ],
)


# 地支藏干采用现代排盘中常见的主气/中气/余气启发式比例。古籍记载藏干内容，
# 但没有统一的百分比；所以这里明确把百分比当作项目参数。
HIDDEN_STEMS_V1 = {
    "子": [HiddenStemShare(stem="癸", share=100)],
    "丑": [HiddenStemShare(stem="己", share=60), HiddenStemShare(stem="癸", share=30), HiddenStemShare(stem="辛", share=10)],
    "寅": [HiddenStemShare(stem="甲", share=60), HiddenStemShare(stem="丙", share=30), HiddenStemShare(stem="戊", share=10)],
    "卯": [HiddenStemShare(stem="乙", share=100)],
    "辰": [HiddenStemShare(stem="戊", share=60), HiddenStemShare(stem="乙", share=30), HiddenStemShare(stem="癸", share=10)],
    "巳": [HiddenStemShare(stem="丙", share=60), HiddenStemShare(stem="戊", share=30), HiddenStemShare(stem="庚", share=10)],
    "午": [HiddenStemShare(stem="丁", share=70), HiddenStemShare(stem="己", share=30)],
    "未": [HiddenStemShare(stem="己", share=60), HiddenStemShare(stem="丁", share=30), HiddenStemShare(stem="乙", share=10)],
    "申": [HiddenStemShare(stem="庚", share=60), HiddenStemShare(stem="壬", share=30), HiddenStemShare(stem="戊", share=10)],
    "酉": [HiddenStemShare(stem="辛", share=100)],
    "戌": [HiddenStemShare(stem="戊", share=60), HiddenStemShare(stem="辛", share=30), HiddenStemShare(stem="丁", share=10)],
    "亥": [HiddenStemShare(stem="壬", share=70), HiddenStemShare(stem="甲", share=30)],
}


MONTH_DOMINANT_ELEMENT_V1 = {
    "寅": "木", "卯": "木", "辰": "土",
    "巳": "火", "午": "火", "未": "土",
    "申": "金", "酉": "金", "戌": "土",
    "亥": "水", "子": "水", "丑": "土",
}


PERSONAL_RESEARCH_CONFIG = PersonalRuleConfiguration(
    version=PERSONAL_RESEARCH_VERSION,
    status="source_reviewed",
    public_rule_version=PUBLIC_RESEARCH_VERSION,
    algorithm_summary=(
        "个人层以出生日干为日主，月支为最高单项权重；天干按本气计，地支按版本化"
        "藏干比例展开，再用月令旺相休囚死倍率形成五行结构。以生我加同我的占比划分"
        "偏弱、平衡、偏强，分别使用生扶、补缺、泄耗克策略。个人出生结构占70%，"
        "当天公共环境占30%；未知时辰删除时柱后归一化，不补造数据。"
    ),
    pillar_weights=PersonalPillarWeights(
        year_stem=8,
        year_branch=12,
        month_stem=12,
        month_branch=28,
        day_stem=15,
        day_branch=15,
        time_stem=5,
        time_branch=5,
    ),
    hidden_stems=HIDDEN_STEMS_V1,
    month_dominant_elements=MONTH_DOMINANT_ELEMENT_V1,
    seasonal_multipliers=SeasonalStateMultipliers(
        wang=1.40,
        xiang=1.20,
        xiu=1.00,
        qiu=0.80,
        si=0.60,
    ),
    strength_thresholds=DayMasterStrengthThresholds(
        weak_max=42.0,
        strong_min=58.0,
    ),
    strategy_scores=DayMasterStrategyScores(
        weak=ElementRoleScores(resource=35, peer=25, output=-8, wealth=-15, officer=-25),
        balanced=ElementRoleScores(resource=2, peer=0, output=4, wealth=2, officer=-2),
        strong=ElementRoleScores(resource=-25, peer=-20, output=30, wealth=20, officer=12),
    ),
    balance_target_percent=20.0,
    deficiency_weight=0.8,
    deficiency_adjustment_limit=15.0,
    birth_structure_weight=70,
    public_environment_weight=30,
    tie_break_color_order=["绿金", "红金", "黄金", "白金", "黑金"],
    tendency_thresholds=TendencyThresholds(
        strong_support_min=22,
        support_min=10,
        balanced_min=0,
        caution_min=-12,
    ),
    research_references=[
        "《五行大义》卷二：四时旺相休囚死及五行生克次序。",
        "《子平真诠评注》：专求月令；得时为旺、失时为衰，并结合年日时根气。",
        "《滴天髓》相关篇章：扶抑须得其宜、损益以求其中；用于原则约束，不直接提供数值。",
        "藏干百分比、柱权重、旺衰倍率、42/58阈值和70/30融合均为资料综合后的工程参数。",
        "《协纪辨方书》主要用于历法与择日义例，本版本不把其宜忌条目直接换算成个人颜色分。",
    ],
)

