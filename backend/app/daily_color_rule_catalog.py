"""每日五色规则因子目录。

``FRAMEWORK_RULE_DEFINITION`` 是早期空框架；``RESEARCH_RULE_DEFINITION`` 是已把
公开古籍原则和项目工程参数分开记录的资料综合版。资料综合版不冒充线下专家审核，
所以状态是 ``source_reviewed``，以后若有新的审核或样本结论，应升级版本而不是
直接篡改既有版本。
"""

from .daily_color_context import RULE_FRAMEWORK_VERSION
from .daily_color_research_v1 import PERSONAL_RESEARCH_VERSION
from .daily_color_schemas import ProfessionalRuleDefinition, RuleBasisDefinition


FRAMEWORK_RULE_DEFINITION = ProfessionalRuleDefinition(
    version=RULE_FRAMEWORK_VERSION,
    status="test_only",
    algorithm_summary=(
        "先由程序取得北京时间下的日期、节气和干支事实，再由待审核规则计算五行相对关系；"
        "个人层只增加出生三柱或四柱及日主信息。当前版本尚未定义权重、排名和同分处理。"
    ),
    factors=[
        RuleBasisDefinition(
            code="PUBLIC_DAY_STEM",
            title="当日日干",
            description="记录当日日干及其五行，作为公共日序关系的候选基础因子。",
            applies_to=["public", "personal"],
            professional_reference="具体作用和权重待专业顾问按项目采用的统一流派确认。",
        ),
        RuleBasisDefinition(
            code="PUBLIC_DAY_BRANCH",
            title="当日日支",
            description="记录当日日支主五行；藏干展开方式及权重暂不写入代码。",
            applies_to=["public", "personal"],
            professional_reference="地支藏干和旺衰口径必须单独审核后版本化。",
        ),
        RuleBasisDefinition(
            code="PUBLIC_MONTH_SEASON",
            title="月令与季节",
            description="使用日期月柱和节令位置表达季节背景，不由模型猜测旺衰。",
            applies_to=["public", "personal"],
            professional_reference="月令取法、节气交界和权重待专业顾问确认。",
        ),
        RuleBasisDefinition(
            code="PUBLIC_SOLAR_TERM",
            title="节气位置",
            description="使用前后节气准确时刻和当天是否交节作为候选修正因子。",
            applies_to=["public", "personal"],
            professional_reference="节气修正规则待专业顾问确认。",
        ),
        RuleBasisDefinition(
            code="PERSON_DAY_MASTER",
            title="个人日主",
            description="个人层以出生日期柱天干及五行为核心候选因子。",
            applies_to=["personal"],
            professional_reference="日主强弱不能只由模型或单一日干判断，具体规则待审核。",
        ),
        RuleBasisDefinition(
            code="PERSON_PILLAR_BALANCE",
            title="出生三柱或四柱结构",
            description="依据用户已知信息使用出生三柱或四柱；未知时辰时明确降级，不补造时柱。",
            applies_to=["personal"],
            professional_reference="五行计分、藏干、月令权重及调候范围待专业顾问确认。",
        ),
        RuleBasisDefinition(
            code="PERSON_TODAY_RELATION",
            title="个人与当日关系",
            description="将已经审核的个人结构与当天公共时序做关系计算，形成个人五色排名。",
            applies_to=["personal"],
            professional_reference="生克泄耗、扶抑或调候采用哪一口径必须先统一。",
        ),
        RuleBasisDefinition(
            code="PERSON_MISSING_TIME",
            title="未知时辰降级",
            description="出生时辰未知时只生成三柱模式，并降低结论粒度，不输出精确时段判断。",
            applies_to=["personal"],
            professional_reference="属于数据完整度约束，不是命理结论。",
        ),
    ],
)


RESEARCH_RULE_DEFINITION = ProfessionalRuleDefinition(
    version=PERSONAL_RESEARCH_VERSION,
    status="source_reviewed",
    algorithm_summary=(
        "公共层综合年月日干支和节气，个人层以日主、月令、藏干结构为主，并按"
        "个人70%与公共环境30%融合。古籍只提供原则，全部权重、倍率和阈值均明确"
        "登记为项目资料综合后的工程参数。"
    ),
    factors=[
        RuleBasisDefinition(
            code="PUBLIC_DAY_STEM",
            title="当日日干",
            description="公共日序的主要日层因子之一；资料综合版权重25%。",
            applies_to=["public", "personal"],
            professional_reference="权重是项目工程值，不是古籍原值。",
        ),
        RuleBasisDefinition(
            code="PUBLIC_DAY_BRANCH",
            title="当日日支",
            description="公共日序的主要日层因子之一；资料综合版按主五行计，权重20%。",
            applies_to=["public", "personal"],
            professional_reference="公共层不展开当日地支藏干，避免与个人出生结构算法混淆。",
        ),
        RuleBasisDefinition(
            code="PUBLIC_MONTH_SEASON",
            title="月令与季节",
            description="月干、月支合计40%，另有节气5%，共同表达月令季节背景。",
            applies_to=["public", "personal"],
            professional_reference="《五行大义》四时休王；《子平真诠》重月令。",
        ),
        RuleBasisDefinition(
            code="PUBLIC_SOLAR_TERM",
            title="节气位置",
            description="二十四节气按月建主五行映射，作为5%的边界修正。",
            applies_to=["public", "personal"],
            professional_reference="节气映射可考，5%是项目工程权重。",
        ),
        RuleBasisDefinition(
            code="PERSON_DAY_MASTER",
            title="个人日主",
            description="以出生日干五行为个人结构判断中心。",
            applies_to=["personal"],
            professional_reference="《子平真诠》及子平体系通行原则。",
        ),
        RuleBasisDefinition(
            code="PERSON_PILLAR_BALANCE",
            title="出生结构与月令",
            description="四柱天干和地支藏干按柱权重、月令倍率形成五行百分比分布。",
            applies_to=["personal"],
            professional_reference="藏干比例、柱权重和旺衰倍率均为版本化工程参数。",
        ),
        RuleBasisDefinition(
            code="PERSON_TODAY_RELATION",
            title="个人与当日融合",
            description="出生结构需求70%，当天公共五色环境30%。",
            applies_to=["personal"],
            professional_reference="70/30为产品工程参数。",
        ),
        RuleBasisDefinition(
            code="PERSON_MISSING_TIME",
            title="未知时辰降级",
            description="未知时辰时删除时干时支，并将其余贡献重新归一化。",
            applies_to=["personal"],
            professional_reference="不补造时柱，结果标记three_pillars。",
        ),
    ],
)
