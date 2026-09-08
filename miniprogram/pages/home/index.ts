import { Product, PRODUCTS, SINGLE_PRODUCTS, SCENT_DETAILS } from "../../data/products";
import { confirmedForDate, CONFIRMED_COLOR_SOURCE } from "../../data/confirmed-colors";
import { getPublicDailyGuide, isPublicDailyGuidePending, isPublicDailyGuideUnavailable, PublicDailyGuide } from "../../services/daily";

type Guide = { rank: number; name: string; element: string; status: string; suitable: string[]; resistance: string; advice: string; product: Product; [key: string]: any };

const COLOR_TO_PRODUCT: Record<string, string> = { 白色系: "white", 绿色系: "green", 黑色系: "black", 红色系: "red", 黄色系: "gold" };
const ELEMENT_TO_PRODUCT: Record<string, string> = { 金: "white", 木: "green", 水: "black", 火: "red", 土: "gold" };
const beijingDate = () => new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
let midnightTimer: ReturnType<typeof setTimeout> | undefined;
Page({
  data: {
    guides: [] as Guide[], selected: null as Guide | null,
    details: SCENT_DETAILS, statusBarHeight: 44, primaryElement: "",
    scent: SINGLE_PRODUCTS[0], scents: SINGLE_PRODUCTS, gift: PRODUCTS[0], source: "每日公开资料",
    contentSource: "loading", contentMessage: "", dateLabel: "", calendarLabel: "",
    term: "", showGuide: false, isToday: false, summary: "",
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
    this.setData({ contentSource: "loading", contentMessage: "正在读取今日公开资料…", selected: null, guides: [], showGuide: false });
    try {
      const payload: PublicDailyGuide = await getPublicDailyGuide();
      const date = payload.guide_date;
      const isToday = date === beijingDate();
      const hasPublishedStatus = payload.status === undefined || payload.status === "published";
      if (!hasPublishedStatus || !date || !Array.isArray(payload.items) || payload.items.length !== 5) throw new Error("not-published");
      const guides = payload.items.map<Guide>(item => {
        const code = item.product_code || "";
        const codeKey = code.match(/(?:JIN|MU|SHUI|HUO|TU)/)?.[0];
        const productId = COLOR_TO_PRODUCT[item.color] || ELEMENT_TO_PRODUCT[item.element] || (codeKey ? { JIN: "white", MU: "green", SHUI: "black", HUO: "red", TU: "gold" }[codeKey] : undefined);
        const product = PRODUCTS.find(p => p.id === productId);
        if (!product) throw new Error("unknown-product");
        return { ...item, name: product.color, element: item.element, tier: item.smoothness, status: item.smoothness,
          palette: item.suitable.join("、"), product };
      }).sort((a, b) => a.rank - b.rank);
      if (new Set(guides.map(item => item.element)).size !== 5) throw new Error("invalid-ranking");
      this.setData({ guides, selected: guides[0], scent: guides[0].product, contentSource: "ready", showGuide: false,
        primaryElement: guides[0].element, dateLabel: date.slice(5).replace("-", " · "), term: payload.solar_term,
        isToday, summary: payload.share_summary,
        source: payload.rule_version || "每日公开资料",
        calendarLabel: payload.lunar_date + " · " + payload.day_ganzhi + "日 · " + payload.weekday,
        shareTitle: payload.share_title || `五色知时 · ${date} 今日五色` });
    } catch (error) {
      const pending = isPublicDailyGuidePending(error);
      const unavailable = isPublicDailyGuideUnavailable(error) || !pending;
      const confirmed = confirmedForDate(beijingDate()).record;
      if (confirmed) {
        const guides = confirmed.items.map<Guide>(item => {
          const product = PRODUCTS.find(productItem => productItem.id === item.productId);
          if (!product) throw new Error("unknown-confirmed-product");
          return { ...item, name: item.color, element: product.element, suitable: [], resistance: "", product };
        });
        const shortDate = confirmed.date.slice(5).replace("-", " · ");
        this.setData({ contentSource: "archive", guides, selected: guides[0], scent: guides[0].product, isToday: false,
          dateLabel: shortDate, term: "已确认资料", primaryElement: guides[0].element, summary: confirmed.summary,
          source: CONFIRMED_COLOR_SOURCE.title,
          calendarLabel: `${confirmed.date.replace(/-/g, "年").replace(/年(\d{2})年/, "年$1月")}日 · 来自已确认聊天记录`,
          contentMessage: pending ? "今日资料待确认，现展示最近一次已确认内容。" : "服务暂不可用，现展示最近一次已确认内容。",
          shareTitle: `五色知时 · ${confirmed.date} 已确认五色` });
        return;
      }
      this.setData({ contentSource: unavailable ? "error" : "waiting", guides: [], selected: null, isToday: false, dateLabel: "", term: pending ? "待确认" : "暂时不可用", primaryElement: "", summary: "",
        calendarLabel: pending ? "公开资料发布后会显示今日色序" : "服务器恢复后可重新读取", contentMessage: pending ? "今日暂无已发布的五色资料，请稍后再来看看。" : "今日五色暂时无法读取，请点击重试。" });
    }
  },
  selectGuide(event: WechatMiniprogram.TouchEvent) {
    const guide=this.data.guides.find(item=>item.rank===Number(event.currentTarget.dataset.rank));
    if(guide)this.setData({selected:guide,scent:guide.product});
  },
  selectScent(event: WechatMiniprogram.TouchEvent) {
    const scent=SINGLE_PRODUCTS.find(item=>item.id===event.currentTarget.dataset.id);
    if(scent)this.setData({scent});
  },
  openGuide(){if(this.data.selected)this.setData({showGuide:true});},
  closeGuide(){this.setData({showGuide:false});}, noop(){},
  toProduct(){wx.navigateTo({url:"/pages/product/index?id="+this.data.scent.id});},
  toGift(){wx.navigateTo({url:"/pages/product/index?id=gift"});},
  toExplore(event: WechatMiniprogram.TouchEvent){wx.navigateTo({url:"/pages/explore/index?tab="+(event.currentTarget.dataset.tab||"daily")});},
  toAi(){wx.switchTab({url:"/pages/chat/index"});},
  toMine(){wx.switchTab({url:"/pages/settings/index"});},
  onShareAppMessage(){return{title:this.data.shareTitle,path:"/pages/home/index"};},
});
