/** AI 问答中的公共排行识别；具体排行必须读取每日自动接口，不能由模型临时编造。 */
export function isPublicRankingQuestion(question: string) {
  if (/本人|个人|生辰|八字|专属/.test(question)) return false;
  return /五色|颜色|色系|穿衣|穿什么/.test(question)
    && /今天|今日|明天|明日|后天|排行|排名|推荐|未来|一周|七天/.test(question);
}
