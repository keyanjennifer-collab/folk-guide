import { Product, PRODUCTS, SINGLE_PRODUCTS, SCENT_DETAILS } from "../../data/products";
import { getPersonalDailyGuidance, getPublicDailyGuide, PersonalDailyColor, PublicDailyGuide } from "../../services/daily";
import { getTheme, AppTheme } from "../../services/theme";
import { getToken, isApiError } from "../../services/api";
import {
  drawPublicGuidePoster,
  PUBLIC_GUIDE_POSTER_HEIGHT,
  PUBLIC_GUIDE_POSTER_WIDTH,
} from "../../utils/public-guide-poster";

type Guide = {
  rank: number; name: string; element: string; status: string; tier: string;
  suitable: string[]; resistance: string; advice: string; palette: string;
  product: Product; scent: string; expanded: boolean; relationReason: string; [key: string]: any;
};

type ElementName = "木" | "火" | "土" | "金" | "水";
type BranchMeta = { zodiac: string; element: ElementName };
type DayOption = { date: string; label: string; weekday: string; active: boolean };
type PersonalHomeColor = Pick<PersonalDailyColor, "rank" | "name" | "element" | "product" | "score" | "public_rank" | "rank_change" | "tendency" | "advice" | "suitable" | "resistance"> & {
  rankChangeLabel: string;
  palette: string;
  swatches: string[];
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
const BRANCH_META: Record<string, BranchMeta> = {
  子: { zodiac: "鼠", element: "水" }, 丑: { zodiac: "牛", element: "土" },
  寅: { zodiac: "虎", element: "木" }, 卯: { zodiac: "兔", element: "木" },
  辰: { zodiac: "龙", element: "土" }, 巳: { zodiac: "蛇", element: "火" },
  午: { zodiac: "马", element: "火" }, 未: { zodiac: "羊", element: "土" },
  申: { zodiac: "猴", element: "金" }, 酉: { zodiac: "鸡", element: "金" },
  戌: { zodiac: "狗", element: "土" }, 亥: { zodiac: "猪", element: "水" },
};

function formatSolarDate(value: string, weekday: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return `公历 ${year}年${month}月${day}日 · ${weekday}`;
}

function addDays(value: string, offset: number): string {
  // 使用纯 UTC 日期运算；若带 +08:00 后再 setUTCDate，会在当天 16:00 UTC 上加一天，导致日期标签不变。
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}

function dayOption(payload: PublicDailyGuide, active: boolean, requestedDate = payload.guide_date): DayOption {
  const [, month, day] = requestedDate.split("-");
  return { date: requestedDate, label: `${Number(month)}月${Number(day)}日`, weekday: payload.weekday.replace("星期", "周"), active };
}

function relationReason(rank: number, dayElement: ElementName, colorElement: string): string {
  return [
    `${dayElement}生${colorElement}，依“我生”取为贵人色`,
    `${dayElement}与${colorElement}同气，依“同我”取为合作色`,
    `${colorElement}克${dayElement}，依“克我”取为奋斗色`,
    `${colorElement}生${dayElement}，依“生我”取为消耗色`,
    `${dayElement}克${colorElement}，依“我克”取为不利色`,
  ][rank - 1];
}
let midnightTimer: ReturnType<typeof setTimeout> | undefined;

Page({
  data: {
    theme: "night" as AppTheme, themeClass: "theme-night",
    guides: [] as Guide[], selected: null as Guide | null, dayOptions: [] as DayOption[],
    details: SCENT_DETAILS, statusBarHeight: 44, primaryElement: "",
    scent: SINGLE_PRODUCTS[0], gift: PRODUCTS[0], source: "确定性历法规则",
    contentSource: "loading", dateLabel: "今日", calendarLabel: "",
    solarDateLabel: "公历今日", lunarDateLabel: "农历时序", dayPillar: "", dayBranch: "", dayElement: "", dayBasis: "",
    term: "时序流转", summary: "观色知序，为今天安排一份从容。",
    shareTitle: "五色知时 · 今日五色",
    personalState: "locked" as "locked" | "missing" | "ready" | "error",
    personalOpen: false,
    personalDate: "",
    personalPrimaryColor: "",
    personalFocus: "",
    personalColors: [] as PersonalHomeColor[],
    posterGenerating: false,
    posterVisible: false,
    posterPath: "",
  },
  onLoad() { const theme = getTheme(); this.setData({ statusBarHeight: wx.getWindowInfo().statusBarHeight, theme, themeClass: `theme-${theme}` }); },
  onShow() { (this as any).getTabBar?.()?.setData({ selected: 0 }); void this.loadToday(); void this.loadPersonalColors(); this.scheduleRefresh(); },
  onHide() { if (midnightTimer) clearTimeout(midnightTimer); },
  onUnload() { if (midnightTimer) clearTimeout(midnightTimer); },
  onPullDownRefresh() { void this.loadToday().finally(() => wx.stopPullDownRefresh()); },
  scheduleRefresh() {
    if (midnightTimer) clearTimeout(midnightTimer);
    const now = Date.now(), beijing = new Date(now + 8 * 3600000);
    const next = Date.UTC(beijing.getUTCFullYear(), beijing.getUTCMonth(), beijing.getUTCDate() + 1) - 8 * 3600000;
    midnightTimer = setTimeout(() => { void this.loadToday(); this.scheduleRefresh(); }, Math.max(1000, next - now + 1000));
  },
  async loadToday(targetDate?: string) {
    this.setData({ contentSource: "loading", selected: null, guides: [] });
    try {
      const payload: PublicDailyGuide = await getPublicDailyGuide(targetDate);
      const futureDates = targetDate ? [] : Array.from({ length: 6 }, (_, index) => addDays(payload.guide_date, index + 1));
      const futurePayloads = await Promise.all(futureDates.map(date => getPublicDailyGuide(date)));
      if (!payload.guide_date || !Array.isArray(payload.items) || payload.items.length !== 5) throw new Error("invalid-guide");
      const dayBranch = payload.day_ganzhi.slice(1, 2);
      const branchMeta = BRANCH_META[dayBranch];
      if (!branchMeta) throw new Error("invalid-day-branch");
      const guides = payload.items.map<Guide>(item => {
        const codeKey = (item.product_code || "").match(/(?:JIN|MU|SHUI|HUO|TU)/)?.[0];
        const codeMap: Record<string, string> = { JIN: "white", MU: "green", SHUI: "black", HUO: "red", TU: "gold" };
        const productId = COLOR_TO_PRODUCT[item.color] || ELEMENT_TO_PRODUCT[item.element] || (codeKey ? codeMap[codeKey] : undefined);
        const product = PRODUCTS.find(candidate => candidate.id === productId);
        if (!product) throw new Error("unknown-product");
        return {
          ...item, name: item.color, product, status: item.smoothness,
          tier: RANK_ROLES[item.rank - 1], palette: COLOR_PALETTES[product.id], expanded: item.rank === 1,
          relationReason: relationReason(item.rank, branchMeta.element, item.element),
        };
      }).sort((a, b) => a.rank - b.rank);
      if (new Set(guides.map(item => item.element)).size !== 5) throw new Error("invalid-ranking");
      const shortDate = payload.guide_date.slice(5).replace("-", " · ");
      this.setData({
        guides, selected: guides[0], scent: guides[0].product, contentSource: "ready",
        primaryElement: branchMeta.element, dateLabel: shortDate, term: payload.solar_term,
        solarDateLabel: formatSolarDate(payload.guide_date, payload.weekday),
        lunarDateLabel: `农历${payload.lunar_date} · ${payload.day_ganzhi}日 · ${payload.solar_term}`,
        dayPillar: payload.day_ganzhi, dayBranch, dayElement: branchMeta.element,
        dayBasis: `今日为${payload.day_ganzhi}日，仅取日支“${dayBranch}”。${dayBranch}对应生肖${branchMeta.zodiac}，五行属${branchMeta.element}，因此今日以${branchMeta.element}为“我”。`,
        summary: payload.share_summary, source: payload.rule_version || "确定性历法规则",
        calendarLabel: `${payload.lunar_date} · ${payload.day_ganzhi}日 · ${payload.weekday}`,
        shareTitle: payload.share_title || `五色知时 · ${payload.guide_date} 今日五色`,
        dayOptions: targetDate
          ? this.data.dayOptions.map(item => ({ ...item, active: item.date === payload.guide_date }))
          : [payload, ...futurePayloads].map((item, index) => dayOption(item, index === 0, [payload.guide_date, ...futureDates][index])),
      });
    } catch (_) {
      this.setData({
        contentSource: "error", guides: [], selected: null, primaryElement: "",
        dateLabel: "今日", term: "时序流转", calendarLabel: "",
        solarDateLabel: "公历今日", lunarDateLabel: "农历时序", dayPillar: "", dayBranch: "", dayElement: "", dayBasis: "",
        summary: "今日内容暂时没有取到，轻触下方即可重新读取。",
      });
    }
  },
  async selectDate(event: WechatMiniprogram.TouchEvent) {
    const targetDate = String(event.currentTarget.dataset.date || "");
    if (!targetDate || targetDate === this.data.dayOptions.find(item => item.active)?.date) return;
    await Promise.all([this.loadToday(targetDate), this.loadPersonalColors(targetDate)]);
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
  async loadPersonalColors(targetDate?: string) {
    if (!getToken()) { this.setData({ personalState: "locked", personalOpen: false, personalColors: [] }); return; }
    try {
      const result = await getPersonalDailyGuidance(targetDate);
      this.setData({
        personalState: "ready", personalDate: result.date, personalPrimaryColor: result.primary_color,
        personalFocus: result.personal_focus, personalColors: result.colors.map(item => ({
          ...(() => {
            const productId = COLOR_TO_PRODUCT[item.name] || ELEMENT_TO_PRODUCT[item.element];
            const product = PRODUCTS.find(candidate => candidate.id === productId);
            return { palette: product ? COLOR_PALETTES[product.id] : "", swatches: product?.swatches || [] };
          })(),
          rank: item.rank, name: item.name, element: item.element, product: item.product, score: item.score,
          public_rank: item.public_rank, rank_change: item.rank_change,
          rankChangeLabel: item.rank_change > 0 ? `↑${item.rank_change}` : item.rank_change < 0 ? `↓${-item.rank_change}` : "→0",
          tendency: item.tendency, suitable: item.suitable, resistance: item.resistance, advice: item.advice,
        })),
      });
    } catch (error: unknown) {
      this.setData({ personalState: isApiError(error, 409) ? "missing" : "error", personalColors: [], personalOpen: false });
    }
  },
  togglePersonalColors() { this.setData({ personalOpen: !this.data.personalOpen }); },
  getPublicGuidePosterCanvas(): Promise<WechatMiniprogram.Canvas> {
    return new Promise((resolve, reject) => {
      // 2D Canvas 必须先通过节点查询取得实例，不能使用旧版 canvas-id 上下文混画。
      wx.createSelectorQuery().in(this).select("#publicGuidePoster").fields({ node: true, size: true }, (result: WechatMiniprogram.IAnyObject) => {
        const canvas = result?.node as WechatMiniprogram.Canvas | undefined;
        if (canvas) resolve(canvas);
        else reject(new Error("poster-canvas-not-found"));
      }).exec();
    });
  },
  async generatePublicPoster() {
    if (this.data.posterGenerating) return;
    if (this.data.contentSource !== "ready" || this.data.guides.length !== 5) {
      wx.showToast({ title: "今日五色尚未准备好", icon: "none" });
      return;
    }
    this.setData({ posterGenerating: true });
    wx.showLoading({ title: "正在生成海报", mask: true });
    try {
      const canvas = await this.getPublicGuidePosterCanvas();
      await drawPublicGuidePoster(canvas, {
        solarDate: this.data.solarDateLabel,
        lunarDate: this.data.lunarDateLabel,
        summary: this.data.summary,
        // 海报只取公共五色字段，个人档案和个人排名不会进入可分享图片。
        items: this.data.guides.map(item => ({
          rank: item.rank,
          name: item.name,
          element: item.element,
          tier: item.tier,
          status: item.status,
          palette: item.palette,
          advice: item.advice,
          resistance: item.resistance,
          swatches: item.product.swatches,
        })),
      }, "/assets/share/public-five-colors-code.jpg");
      await new Promise<void>(resolve => canvas.requestAnimationFrame(() => resolve()));
      const result = await wx.canvasToTempFilePath({
        canvas,
        width: PUBLIC_GUIDE_POSTER_WIDTH,
        height: PUBLIC_GUIDE_POSTER_HEIGHT,
        destWidth: PUBLIC_GUIDE_POSTER_WIDTH,
        destHeight: PUBLIC_GUIDE_POSTER_HEIGHT,
        fileType: "jpg",
        quality: 0.94,
      }, this);
      this.setData({ posterPath: result.tempFilePath, posterVisible: true });
    } catch (error) {
      console.error("生成公共五色海报失败", error);
      wx.showToast({ title: "海报生成失败，请重试", icon: "none" });
    } finally {
      wx.hideLoading();
      this.setData({ posterGenerating: false });
    }
  },
  closePublicPoster() { this.setData({ posterVisible: false }); },
  preventPosterTouchMove() {},
  async sharePublicPoster() {
    if (!this.data.posterPath) return;
    try {
      await wx.showShareImageMenu({
        path: this.data.posterPath,
        entrancePath: "/pages/home/index",
        needShowEntrance: true,
      });
    } catch (error) {
      const message = String((error as WechatMiniprogram.GeneralCallbackResult)?.errMsg || "");
      if (!message.includes("cancel")) wx.showToast({ title: "暂时无法分享，请先保存图片", icon: "none" });
    }
  },
  async savePublicPoster() {
    if (!this.data.posterPath) return;
    try {
      await wx.saveImageToPhotosAlbum({ filePath: this.data.posterPath });
      wx.showToast({ title: "已保存到相册", icon: "success" });
    } catch (error) {
      const message = String((error as WechatMiniprogram.GeneralCallbackResult)?.errMsg || "");
      if (message.includes("auth deny") || message.includes("authorize:fail")) {
        wx.showModal({
          title: "需要相册权限",
          content: "请在设置中允许保存到相册，再回来保存海报。",
          confirmText: "去设置",
          success: result => { if (result.confirm) void wx.openSetting(); },
        });
      } else if (!message.includes("cancel")) {
        wx.showToast({ title: "保存失败，请重试", icon: "none" });
      }
    }
  },
  toProfile() { wx.navigateTo({ url: "/pages/profile/index" }); },
  toSettings() { wx.switchTab({ url: "/pages/settings/index" }); },
  toPersonalColors() { wx.switchTab({ url: "/pages/caikuxiang/index" }); },
  onShareAppMessage() { return { title: this.data.shareTitle, path: "/pages/home/index" }; },
});
