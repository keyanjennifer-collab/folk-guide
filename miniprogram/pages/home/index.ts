import { getApiErrorMessage, isApiError, request } from "../../services/api";
import { Product, PRODUCTS, SINGLE_PRODUCTS, SCENT_DETAILS, productForElement } from "../../data/products";

type Guide = {
  rank: number; name: string; element: string; status: string; suitable: string[];
  resistance: string; advice: string; product: Product;
};
type PublicGuide = {
  guide_date: string; weekday: string; lunar_date: string; solar_term: string; day_ganzhi: string;
  items: { rank: number; color: string; element: string; smoothness: string; suitable: string[]; resistance: string; advice: string }[];
  share_title: string;
};
let midnightTimer: ReturnType<typeof setTimeout> | undefined;
const ordinal = ["壹", "贰", "叁", "肆", "伍"];

Page({
  data: {
    guides: [] as Guide[], selected: null as Guide | null,
    details: SCENT_DETAILS, statusBarHeight: 44, primaryElement: "",
    rankLabels: ["得时之色", "相助之色", "守衡之色", "费力之色", "慎行之色"],
    scent: SINGLE_PRODUCTS[0], scents: SINGLE_PRODUCTS, gift: PRODUCTS[0], ordinal,
    contentSource: "loading", contentMessage: "", dateLabel: "", calendarLabel: "每日按北京时间更新",
    term: "静候时序", showGuide: false, shareTitle: "五色知时 · 今日五色",
  },
  onLoad() { this.setData({ statusBarHeight: wx.getWindowInfo().statusBarHeight }); },
  onShow() { void this.loadToday(); this.scheduleRefresh(); },
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
    this.setData({ contentSource: "loading", selected: null, guides: [], showGuide: false });
    try {
      const data = await request<PublicGuide>({ path: "/api/public-guides/today", auth: false, showError: false, retryOnUnauthorized: false });
      const guides = data.items.map(item => {
        const product = productForElement(item.element);
        if (!product) throw new Error("Unknown element");
        return { rank: item.rank, name: product.color, element: item.element, status: item.smoothness,
          suitable: item.suitable, resistance: item.resistance, advice: item.advice, product };
      }).sort((a, b) => a.rank - b.rank);
      if (guides.length !== 5 || new Set(guides.map(item => item.element)).size !== 5) throw new Error("Invalid guides");
      this.setData({ guides, selected: guides[0], scent: guides[0].product, contentSource: "ready",
        primaryElement: guides[0].element,
        dateLabel: data.guide_date.slice(5).replace("-", " · "), term: data.solar_term,
        calendarLabel: data.lunar_date + " · " + data.day_ganzhi + "日 · " + data.weekday,
        shareTitle: "五色知时 · 今日主色 " + guides[0].name,
      });
    } catch (error) {
      this.setData({ contentSource: "error", guides: [], selected: null, dateLabel: "", term: "静候时序",
        primaryElement: "",
        calendarLabel: "每日按北京时间更新",
        contentMessage: isApiError(error, 404) ? "今日内容正在准备，请稍后再来。" : getApiErrorMessage(error, "暂时无法读取今日五色，请重新读取。") });
    }
  },
  selectGuide(event: WechatMiniprogram.TouchEvent) {
    const guide = this.data.guides.find(item => item.rank === Number(event.currentTarget.dataset.rank));
    if (guide) this.setData({ selected: guide, scent: guide.product });
  },
  selectScent(event: WechatMiniprogram.TouchEvent) {
    const scent = SINGLE_PRODUCTS.find(item => item.id === event.currentTarget.dataset.id);
    if (scent) this.setData({ scent });
  },
  openGuide() { if (this.data.selected) this.setData({ showGuide: true }); },
  closeGuide() { this.setData({ showGuide: false }); },
  noop() {},
  toProduct() { wx.navigateTo({ url: "/pages/product/index?id=" + this.data.scent.id }); },
  toGift() { wx.navigateTo({ url: "/pages/product/index?id=gift" }); },
  toAi() { wx.switchTab({ url: "/pages/chat/index" }); },
  toMine() { wx.switchTab({ url: "/pages/settings/index" }); },
  onShareAppMessage() { return { title: this.data.shareTitle, path: "/pages/home/index" }; },
});
