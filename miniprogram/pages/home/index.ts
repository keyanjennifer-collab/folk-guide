import { Product, PRODUCTS, SINGLE_PRODUCTS, SCENT_DETAILS } from "../../data/products";
import { getPublicDailyGuide, PublicDailyGuide } from "../../services/daily";

type Guide = {
  rank: number; name: string; element: string; status: string; tier: string;
  suitable: string[]; resistance: string; advice: string; palette: string;
  product: Product; scent: string; expanded: boolean; [key: string]: any;
};

const COLOR_TO_PRODUCT: Record<string, string> = { 白色系: "white", 绿色系: "green", 黑色系: "black", 红色系: "red", 黄色系: "gold" };
const ELEMENT_TO_PRODUCT: Record<string, string> = { 金: "white", 木: "green", 水: "black", 火: "red", 土: "gold" };
const COLOR_PALETTES: Record<string, string> = {
  white: "白色、银色、灰色、米白色",
  gold: "黄色、米色、咖啡色、棕色",
  green: "绿色、青色、翠绿色",
  red: "红色、粉色、紫色、橙色",
  black: "黑色、蓝色、藏蓝色",
};
const RANK_ROLES = ["贵人色", "合作色", "奋斗色", "消耗色", "不利色"];
let midnightTimer: ReturnType<typeof setTimeout> | undefined;

Page({
  data: {
    guides: [] as Guide[], selected: null as Guide | null,
    details: SCENT_DETAILS, statusBarHeight: 44, primaryElement: "",
    scent: SINGLE_PRODUCTS[0], gift: PRODUCTS[0], source: "确定性历法规则",
    contentSource: "loading", dateLabel: "今日", calendarLabel: "",
    term: "时序流转", summary: "观色知序，为今天安排一份从容。",
    shareTitle: "五色知时 · 今日五色",
  },
  onLoad() { this.setData({ statusBarHeight: wx.getWindowInfo().statusBarHeight }); },
  onShow() { (this as any).getTabBar?.()?.setData({ selected: 0 }); void this.loadToday(); this.scheduleRefresh(); },
  onHide() { if (midnightTimer) clearTimeout(midnightTimer); },
  onUnload() { if (midnightTimer) clearTimeout(midnightTimer); },
  onPullDownRefresh() { void this.loadToday().finally(() => wx.stopPullDownRefresh()); },
  scheduleRefresh() {
    if (midnightTimer) clearTimeout(midnightTimer);
    const now = Date.now(), beijing = new Date(now + 8 * 3600000);
    const next = Date.UTC(beijing.getUTCFullYear(), beijing.getUTCMonth(), beijing.getUTCDate() + 1) - 8 * 3600000;
    midnightTimer = setTimeout(() => { void this.loadToday(); this.scheduleRefresh(); }, Math.max(1000, next - now + 1000));
  },
  async loadToday() {
    this.setData({ contentSource: "loading", selected: null, guides: [] });
    try {
      const payload: PublicDailyGuide = await getPublicDailyGuide();
      if (!payload.guide_date || !Array.isArray(payload.items) || payload.items.length !== 5) throw new Error("invalid-guide");
      const guides = payload.items.map<Guide>(item => {
        const codeKey = (item.product_code || "").match(/(?:JIN|MU|SHUI|HUO|TU)/)?.[0];
        const codeMap: Record<string, string> = { JIN: "white", MU: "green", SHUI: "black", HUO: "red", TU: "gold" };
        const productId = COLOR_TO_PRODUCT[item.color] || ELEMENT_TO_PRODUCT[item.element] || (codeKey ? codeMap[codeKey] : undefined);
        const product = PRODUCTS.find(candidate => candidate.id === productId);
        if (!product) throw new Error("unknown-product");
        return {
          ...item, name: item.color, product, status: item.smoothness,
          tier: RANK_ROLES[item.rank - 1], palette: COLOR_PALETTES[product.id], expanded: item.rank === 1,
        };
      }).sort((a, b) => a.rank - b.rank);
      if (new Set(guides.map(item => item.element)).size !== 5) throw new Error("invalid-ranking");
      const shortDate = payload.guide_date.slice(5).replace("-", " · ");
      this.setData({
        guides, selected: guides[0], scent: guides[0].product, contentSource: "ready",
        primaryElement: guides[0].element, dateLabel: shortDate, term: payload.solar_term,
        summary: payload.share_summary, source: payload.rule_version || "确定性历法规则",
        calendarLabel: `${payload.lunar_date} · ${payload.day_ganzhi}日 · ${payload.weekday}`,
        shareTitle: payload.share_title || `五色知时 · ${payload.guide_date} 今日五色`,
      });
    } catch (_) {
      this.setData({
        contentSource: "error", guides: [], selected: null, primaryElement: "",
        dateLabel: "今日", term: "时序流转", calendarLabel: "",
        summary: "今日内容暂时没有取到，轻触下方即可重新读取。",
      });
    }
  },
  selectGuide(event: WechatMiniprogram.TouchEvent) {
    const guide = this.data.guides.find(item => item.rank === Number(event.currentTarget.dataset.rank));
    if (guide) this.setData({ selected: guide, scent: guide.product });
  },
  toggleGuide(event: WechatMiniprogram.TouchEvent) {
    const rank = Number(event.currentTarget.dataset.rank);
    this.setData({ guides: this.data.guides.map(item => (
      item.rank === rank ? { ...item, expanded: !item.expanded } : item
    )) });
  },
  toGuideProduct(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({ url: "/pages/product/index?id=" + event.currentTarget.dataset.id });
  },
  toGift() { wx.navigateTo({ url: "/pages/product/index?id=gift" }); },
  toExplore(event: WechatMiniprogram.TouchEvent) { wx.navigateTo({ url: "/pages/explore/index?tab=" + (event.currentTarget.dataset.tab || "daily") }); },
  toAi() { wx.switchTab({ url: "/pages/chat/index" }); },
  toMine() { wx.switchTab({ url: "/pages/settings/index" }); },
  onShareAppMessage() { return { title: this.data.shareTitle, path: "/pages/home/index" }; },
});
