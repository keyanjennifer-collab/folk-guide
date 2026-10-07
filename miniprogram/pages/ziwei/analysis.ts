export type AnalysisKey = "overview" | "wealth" | "career" | "love" | "personality" | "health" | "family" | "children" | "move" | "friends" | "home" | "spirit" | "parents";
export type PeriodMode = "mingpan" | "liunian" | "xiaoxian" | "liuyue" | "liuri" | "liushi" | number;
export const ANALYSIS_TABS: { key: AnalysisKey; label: string; palace: string }[] = [
  { key: "overview", label: "命盘分析", palace: "命" }, { key: "wealth", label: "财运", palace: "财帛" },
  { key: "career", label: "事业", palace: "官禄" }, { key: "love", label: "感情", palace: "夫妻" },
  { key: "personality", label: "性格", palace: "命" }, { key: "health", label: "健康", palace: "疾厄" },
  { key: "family", label: "兄弟合伙", palace: "兄弟" }, { key: "children", label: "子女", palace: "子女" },
  { key: "move", label: "迁移外出", palace: "迁移" }, { key: "friends", label: "人际贵人", palace: "仆役" },
  { key: "home", label: "田宅", palace: "田宅" }, { key: "spirit", label: "福德", palace: "福德" },
  { key: "parents", label: "父母长辈", palace: "父母" },
];
const STAR_MEANINGS: Record<string, string> = {
  "紫微": "主尊贵、统筹与领导，重视掌控全局", "天机": "主思考、变化与策划，善于找方法", "太阳": "主光明、名望与付出，重视责任感",
  "武曲": "主财务、执行与决断，做事直接务实", "天同": "主福气、随和与享受，重视生活舒适", "廉贞": "主原则、情感与取舍，界线感强",
  "天府": "主守成、资源与管理，擅长积累与统筹", "太阴": "主细腻、储蓄与内在安全感，感受力强", "贪狼": "主才艺、社交与欲望，机会来自人际往来",
  "巨门": "主表达、辨析与口舌，适合研究和沟通", "天相": "主协调、公信力与助力，擅长平衡关系", "天梁": "主庇护、原则与解决问题，责任心重",
  "七杀": "主开创、压力与决断，适合在变化中突破", "破军": "主改革、重启与突破，人生阶段变化明显",
};
const CATEGORY_ADVICE: Record<AnalysisKey, string> = {
  overview: "先看命宫、身宫与三方四正，再结合当前时期判断落地方式。", wealth: "财运适合结合财帛宫与官禄宫一起看，重要支出和投资要留出缓冲。",
  career: "事业要看能力发挥、资源配置和长期节奏，选择能持续积累的方向更稳。", love: "感情要同时看夫妻宫与福德宫，沟通边界和现实分工比单一吉凶更重要。",
  personality: "性格是倾向而不是定论；把优势用在稳定的行动上，才能转化为现实成果。", health: "健康分析只作生活提醒，作息、饮食和不适症状应以专业意见为准。",
  family: "合作关系需要提前约定职责、收益与决策方式，避免只凭熟悉感推进。", children: "子女与陪伴主题适合看长期投入和沟通方式，减少单一标准的比较。",
  move: "外出、迁移和环境变化会改变机会密度，提前准备资源和退路更有利。", friends: "人际贵人来自长期兑现承诺，边界清楚比一味迎合更能保持关系。",
  home: "田宅主题可从居住稳定、家庭分工和资产规划三个方面逐步落实。", spirit: "福德宫反映内在恢复力，给自己留出休息和独处时间有助于维持长期状态。",
  parents: "与长辈相处适合把关心落实为具体安排，同时保留彼此的生活边界。",
};
const SIHUA_TABLE: Record<number, [string, string, string, string]> = {
  0: ["廉贞", "破军", "武曲", "太阳"], 1: ["天机", "天梁", "紫微", "太阴"], 2: ["天同", "天机", "文昌", "廉贞"],
  3: ["太阴", "天同", "天机", "巨门"], 4: ["贪狼", "太阴", "右弼", "天机"], 5: ["武曲", "贪狼", "天梁", "文曲"],
  6: ["太阳", "武曲", "太阴", "天同"], 7: ["巨门", "太阳", "文曲", "文昌"], 8: ["天梁", "紫微", "左辅", "武曲"], 9: ["破军", "巨门", "太阴", "贪狼"],
};

export function normalizePalaceName(name: string): string { return (name || "").replace(/宫$/, ""); }
function findPalace(chart: any, target: string): any {
  const list = chart?.palaces || [];
  return list.find((p: any) => normalizePalaceName(p.name) === target || p.name === target || (target === "命" && p.name === "命宫")) || list[0] || { name: target, stars: [] };
}
function periodText(chart: any, mode: PeriodMode): string {
  if (mode === "liunian") return `流年 ${new Date().getFullYear()}`;
  if (mode === "xiaoxian") return "小限 · 当前岁运";
  if (mode === "liuyue") return "流月 · 当前月份";
  if (mode === "liuri") return "流日 · 今日";
  if (mode === "liushi") return "流时 · 当前时辰";
  if (typeof mode === "number") { const dx = chart?.daXians?.[mode]; return dx ? `大限 ${dx.startAge}–${dx.endAge}岁 · ${normalizePalaceName(dx.palaceName)}` : "大限"; }
  return "本命盘";
}
function periodOverlay(chart: any, mode: PeriodMode): string {
  let stemIndex: number | null = null;
  if (mode === "liunian") stemIndex = ((new Date().getFullYear() - 4) % 10 + 10) % 10;
  if (typeof mode === "number") {
    const dx = chart?.daXians?.[mode];
    const palace = (chart?.palaces || []).find((p: any) => p.name === dx?.palaceName || p.branch === dx?.palaceBranch);
    if (palace && typeof palace.stem === "number") stemIndex = palace.stem;
  }
  if (stemIndex === null || !SIHUA_TABLE[stemIndex]) return "";
  const names = SIHUA_TABLE[stemIndex];
  return `本时期四化：${names[0]}化禄、${names[1]}化权、${names[2]}化科、${names[3]}化忌`;
}
export function makeAnalysis(chart: any, key: AnalysisKey, mode: PeriodMode): any {
  const tab = ANALYSIS_TABS.find(item => item.key === key) || ANALYSIS_TABS[0];
  const palace = findPalace(chart, tab.palace);
  const stars = (palace.stars || []).filter((s: any) => s.type === "major");
  const starNames = stars.map((s: any) => s.name);
  const starText = starNames.length ? starNames.join("、") : "空宫（需参考对宫）";
  const traits = starNames.map((name: string) => STAR_MEANINGS[name]).filter(Boolean);
  const siHua = (palace.stars || []).filter((s: any) => s.siHua).map((s: any) => `${s.name}化${s.siHua}`).join("、");
  const secondary = (palace.stars || []).filter((s: any) => s.type !== "major").map((s: any) => s.name).slice(0, 8).join("、");
  const opposite = (chart?.palaces || []).find((p: any) => p.branch === ((palace.branch + 6) % 12));
  const oppositeStars = (opposite?.stars || []).filter((s: any) => s.type === "major").map((s: any) => s.name).join("、") || "暂无主星资料";
  const period = periodText(chart, mode);
  const overlay = periodOverlay(chart, mode);
  const age = palace.daXianAge ? `该宫对应大限为 ${palace.daXianAge[0]}–${palace.daXianAge[1]} 岁。` : "该宫当前没有单独标注大限年龄。";
  const details = [
    `${normalizePalaceName(palace.name)}宫主星为${starText}，对应的重点是${traits.length ? traits.join("；") : "先观察环境变化，再结合对宫取象"}。`,
    secondary ? `同宫辅星、杂曜包括${secondary}，这些信息会影响主星表现的强弱与具体落点。` : "本宫未显示可供展开的辅星，建议同时参考三方四正和现实经历。",
    `对宫为${normalizePalaceName(opposite?.name || "对宫")}，主星为${oppositeStars}；本宫信息不足时，需要借对宫补足判断。`,
    `${period}阶段可把这个主题落实到具体计划中，先观察机会、压力与资源是否同时出现，再决定推进速度。`,
  ];
  return {
    title: tab.label, palaceName: normalizePalaceName(palace.name), period, stars: starText,
    summary: `${period}重点落在${normalizePalaceName(palace.name)}。${traits.length ? traits.join("；") + "。" : "主星信息较少，需结合对宫、三方四正和现实经历综合判断。"}`,
    evidence: `命宫在${chart?.mingGongBranch ?? "—"}，身宫在${chart?.shenGongBranch ?? "—"}；${age}${siHua ? `本宫四化：${siHua}。` : "本宫未显示四化标记。"}${overlay ? ` ${overlay}。` : ""}`,
    advice: CATEGORY_ADVICE[key], details, overlay,
  };
}


export function makeAnalysisForPalace(chart: any, palace: any, key: AnalysisKey, mode: PeriodMode): any {
  if (!palace) return makeAnalysis(chart, key, mode);
  const target = ANALYSIS_TABS.find(item => item.key === key)?.palace || normalizePalaceName(palace.name);
  const palaces = (chart.palaces || []).map((item: any) => item.branch === palace.branch ? { ...item, name: target } : item);
  const copy = { ...chart, palaces };
  return makeAnalysis(copy, key, mode);
}
