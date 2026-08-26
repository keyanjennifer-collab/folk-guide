import { getApiErrorMessage, isApiError, request } from "../../services/api";

type ColorGuide = {
  rank: number; name: string; element: string; tone: string; status: string;
  suitable: string[]; resistance: string; advice: string; incense: string; scent: string;
};

type PublicGuideResponse = {
  guide_date: string; weekday: string; lunar_date: string; solar_term: string; day_ganzhi: string;
  items: Array<{
    rank: number; color: string; element: string; smoothness: string; suitable: string[];
    resistance: string; advice: string; incense_name: string; scent: string;
  }>;
  share_title: string; share_summary: string; push_summary: string; rule_version: string;
};

const TONE_MAP: Record<string, string> = { "绿金": "green", "黑金": "black", "黄金": "gold", "白金": "white", "红金": "red" };

// 首页停留在前台跨过零点时，也必须主动切换到新一天的公共五色。
// 用户离开首页后会清理计时器；再次进入首页时，onShow 会立即读取当天接口。
let midnightRefreshTimer: ReturnType<typeof setTimeout> | undefined;

function millisecondsUntilNextBeijingMidnight(now = new Date()): number {
  const beijingOffsetMilliseconds = 8 * 60 * 60 * 1000;
  const beijingNow = new Date(now.getTime() + beijingOffsetMilliseconds);
  const nextMidnightTimestamp = Date.UTC(
    beijingNow.getUTCFullYear(),
    beijingNow.getUTCMonth(),
    beijingNow.getUTCDate() + 1,
  ) - beijingOffsetMilliseconds;
  // 多等一秒，避免请求刚好在服务器日期切换前到达。
  return Math.max(1000, nextMidnightTimestamp - now.getTime() + 1000);
}

Page({
  data: {
    // 首页图片统一从这里配置，方便以后替换成品牌自己的摄影素材。
    // 暂时没有合适图片的区域保持空字符串，WXML 会自动隐藏对应图片位。
    heroImage: "/assets/home/hero-forest.jpg",
    philosophyImage: "",
    // 线香图片尚未拍摄时保持空字符串，页面使用品牌化无图视觉；后续只需填写资源路径。
    incenseImage: "",
    expandedRank: 1,
    contentSource: "loading",
    statusLabel: "读取中",
    contentMessage: "正在读取今日五色内容…",
    dateLabel: "今日 · 北京时间",
    calendarLabel: "每日内容以北京时间更新",
    shareTitle: "今日五色排名与生活建议",
    primaryColor: "静候今日",
    primaryElement: "",
    primaryTone: "",
    primaryStatus: "正在读取今日时序",
    supportingColors: "",
    primarySuitable: "",
    incenseName: "",
    incenseScent: "",
    // 真实接口返回前保持空数组，绝不把固定示例冒充当天推荐。
    guides: [] as ColorGuide[],
  },
  onShow() {
    void this.loadToday();
    this.scheduleMidnightRefresh();
  },
  onHide() {
    this.clearMidnightRefresh();
  },
  onUnload() {
    this.clearMidnightRefresh();
  },
  scheduleMidnightRefresh() {
    this.clearMidnightRefresh();
    midnightRefreshTimer = setTimeout(() => {
      void this.loadToday();
      this.scheduleMidnightRefresh();
    }, millisecondsUntilNextBeijingMidnight());
  },
  clearMidnightRefresh() {
    if (midnightRefreshTimer !== undefined) {
      clearTimeout(midnightRefreshTimer);
      midnightRefreshTimer = undefined;
    }
  },
  async loadToday() {
    this.setData({ contentSource: "loading", statusLabel: "读取中", contentMessage: "正在读取今日五色内容…" });
    try {
      // 公共五色不要求登录；页面只展示后端已经审核并发布的真实内容。
      const data = await request<PublicGuideResponse>({
        path: "/api/public-guides/today",
        auth: false,
        showError: false,
        retryOnUnauthorized: false,
      });
      const [year, month, day] = data.guide_date.split("-");
      const dateText = `${year}年${Number(month)}月${Number(day)}日`;
      const automaticallyGenerated = data.rule_version === "wuse-public-research-v1.0";
      const guides = data.items.map((item) => ({
        rank: item.rank, name: item.color, element: item.element, tone: TONE_MAP[item.color],
        status: item.smoothness, suitable: item.suitable, resistance: item.resistance,
        advice: item.advice, incense: item.incense_name, scent: item.scent,
      }));
      const primary = guides[0];
      this.setData({
        contentSource: "published",
        statusLabel: automaticallyGenerated ? "今日已生成" : "今日已发布",
        contentMessage: "",
        dateLabel: `${dateText} · ${data.weekday}`,
        calendarLabel: `${data.lunar_date} · ${data.solar_term} · ${data.day_ganzhi}`,
        shareTitle: data.share_title,
        guides,
        primaryColor: primary?.name || "今日五色",
        primaryElement: primary?.element || "",
        primaryTone: primary?.tone || "",
        primaryStatus: primary?.status || "今日内容已生成",
        supportingColors: guides.slice(1, 3).map((item) => item.name).join("、"),
        primarySuitable: primary?.suitable.slice(0, 2).join("、") || "",
        incenseName: primary?.incense || "",
        incenseScent: primary?.scent || "",
      });
    } catch (error) {
      // 404 表示内容尚未发布；网络或服务异常另行提示，二者都不能降级为演示排名。
      const notPublished = isApiError(error, 404);
      this.setData({
        contentSource: notPublished ? "empty" : "error",
        statusLabel: notPublished ? "准备中" : "暂不可用",
        contentMessage: notPublished ? "今日详细指南正在更新，稍后再来看看。" : getApiErrorMessage(error, "今日内容暂时无法读取，请稍后重试。"),
        guides: [],
        primaryColor: "静候今日",
        primaryElement: "",
        primaryTone: "",
        primaryStatus: "今日内容准备中",
        supportingColors: "",
        primarySuitable: "",
        incenseName: "",
        incenseScent: "",
      });
    }
  },
  toggleGuide(event: WechatMiniprogram.TouchEvent) {
    const rank = Number(event.currentTarget.dataset.rank);
    this.setData({ expandedRank: this.data.expandedRank === rank ? 0 : rank });
  },
  showPersonalLogin() {
    wx.showModal({
      title: "查看我的个人结果",
      content: "公共五色无需登录。个人五色仅在AI国学体验或服务期内开放，并会结合本人档案与当天时序生成。",
      confirmText: "进入AI国学", cancelText: "暂时不用",
      success: (result) => { if (result.confirm) wx.switchTab({ url: "/pages/chat/index" }); },
    });
  },
  toAi() {
    wx.switchTab({ url: "/pages/chat/index" });
  },
  scrollToRanking() {
    wx.pageScrollTo({ selector: "#rankingSection", duration: 420 });
  },
  /** 向第一次接触品牌的用户解释口号，不使用“幸运色”等确定性表述。 */
  showBrandMeaning() {
    wx.showModal({
      title: "五色应时，知时而行",
      content: "五色不是固定不变的结论，而是金、木、水、火、土在当下时序中的现代化表达。每一天的日期、节气、干支和五行关系不同，五色之间的关系也会变化。五色知时把这些传统规律转化成今天能用的颜色、穿搭、香品和生活建议——知道当下，再决定怎么行动。",
      showCancel: false,
      confirmText: "我知道了",
    });
  },
  toIncense() { wx.switchTab({ url: "/pages/caikuxiang/index" }); },
  onShareAppMessage() { return { title: this.data.shareTitle, path: "/pages/home/index?from=share" }; },
});
