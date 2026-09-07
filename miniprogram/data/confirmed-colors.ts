/** 用户指定来源的逐日资料。只录入原文，不推导、补齐或滚动生成排名。 */
export const CONFIRMED_COLOR_SOURCE = {
  title: "今日五色排行",
  conversationId: "6a9d75f3-3350-83e8-ba45-508763ad5ce5",
};
export const CONFIRMED_COLORS = [{
  date: "2026-09-06",
  summary: "顺势取白，稳中用黄；青可进，红宜节，黑宜收。",
  items: [
    { rank: 1, color: "白色系", productId: "white", tier: "贵人色", status: "大吉", palette: "白色、银色、灰色、米白色", advice: "今日土生金，整体助力较强，适合重要沟通、见客、推进关键事项。" },
    { rank: 2, color: "黄色系", productId: "gold", tier: "合作色", status: "吉", palette: "黄色、米色、咖啡色、棕色", advice: "与今日土气同频，状态较稳，适合协作、洽谈、维持关系。" },
    { rank: 3, color: "绿色系", productId: "green", tier: "奋斗色", status: "平", palette: "绿色、青色、翠绿色", advice: "木克土，需要主动投入，适合有明确目标、需要推进突破的事情。" },
    { rank: 4, color: "红色系", productId: "red", tier: "消耗色", status: "慎用", palette: "红色、粉色、紫色、橙色", advice: "火生土，自身能量向外输出，容易忙碌、消耗较多。" },
    { rank: 5, color: "黑色系", productId: "black", tier: "不利色", status: "少用", palette: "黑色、蓝色、藏蓝色", advice: "土克水，今日受到环境制约，重要场合不建议作为大面积主色。" },
  ],
}];
export function confirmedForDate(today: string) {
  const record = [...CONFIRMED_COLORS].filter(item => item.date <= today).sort((a,b) => b.date.localeCompare(a.date))[0];
  return { record: record || null, isToday: record?.date === today };
}
export function beijingDate() { return new Date(Date.now() + 8 * 3600000).toISOString().slice(0,10); }
export function isPublicRankingQuestion(question: string) {
  if (/本人|个人|生辰|八字|专属/.test(question)) return false;
  return /五色|颜色|色系|穿衣|穿什么/.test(question) && /今天|今日|明天|明日|后天|排行|排名|推荐|未来|一周|七天/.test(question);
}
