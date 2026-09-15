import { getApiErrorMessage, getToken, isApiError } from "../../services/api";
import { getCurrentUser, loginWithWechat, logoutLocalAccount, bindWechatPhone } from "../../services/account";
import { getAIHistory, getAIQuota } from "../../services/ai";
import { getCurrentProfile, isProfileMissing } from "../../services/profile";
import { getOrders } from "../../services/orders";
let loadVersion = 0;
const EMPTY_COUNTS = { pending: "—", paid: "—", shipped: "—", after_sale: "—" };
type InfoDialog = { eyebrow: string; title: string; intro: string; sections: { title: string; body: string }[] };
const INFO_DIALOGS: Record<"help" | "privacy" | "about", InfoDialog> = {
  help: {
    eyebrow: "GUIDE", title: "使用帮助", intro: "从今日五色到选香、问答与个人记录，可按以下方式使用。",
    sections: [
      { title: "查看今日五色", body: "首页内容以北京时间公历自然日为边界自动更新。系统取得当日日柱后，仅取日支所属五行作为“当日五行”，再按固定生克关系排列贵人色、合作色、奋斗色、消耗色与不利色。" },
      { title: "阅读色序建议", body: "点击首页五种色系可切换对应香品；进入“五色详解”后，点击“展开”可查看色序依据、今日适宜、行动建议与需要留意的事项。" },
      { title: "选香与购物袋", body: "商城包含五色知时线香套装及青木、朱蜜、黄檀、白桂、墨沉五款单香。商品详情可调整数量并加入购物袋；购物袋保存在本机。目前为展示阶段，不会生成订单或发起扣款。" },
      { title: "使用时序文化", body: "可从典籍、节气与日常处境出发提问。今日五色排行以首页发布结果为准，不由 AI 临时生成；回答中的参考资料可继续查阅，发现问题也可提交纠错。" },
      { title: "管理个人内容", body: "微信登录后可完善本人档案、查看个人五色、问答记录及订单状态。手机号仅在你主动授权后绑定。若页面内容未及时更新，可下拉刷新或重新进入小程序。" },
    ],
  },
  privacy: {
    eyebrow: "PRIVACY", title: "账号与隐私", intro: "个人信息只用于提供你主动使用的账号与个性化功能。",
    sections: [
      { title: "账号信息", body: "微信登录用于识别你的账号并同步订单、档案与问答记录。手机号不会自动读取，只有在你点击授权后才会绑定。" },
      { title: "本人档案", body: "你填写的档案用于生成个人五色等功能，可随时进入“本人档案”修改或删除。传统文化内容仅供学习与生活参考。" },
      { title: "本机数据", body: "购物袋是保存在当前设备上的选香清单。退出登录会清除本机登录状态，但不会自动删除账号内已经保存的记录。" },
      { title: "你的选择", body: "你可以不绑定手机号，也可以在本人档案中管理已填写内容。如需进一步处理账号数据，可通过后续开放的客服入口提出申请。" },
    ],
  },
  about: {
    eyebrow: "ABOUT US", title: "关于我们", intro: "五色应时，知时而行。",
    sections: [
      { title: "五色知时", body: "我们以传统五行时序为线索，把每日色序、香气选择与国学阅读整理成更容易进入日常的体验。" },
      { title: "我们在做什么", body: "每日五色遵循公开、固定的历法与五行关系生成；五款香以青木、朱蜜、黄檀、白桂、墨沉对应五方意象，让时序可以被看见，也可以被闻见。" },
      { title: "使用边界", body: "内容用于传统文化学习、审美体验与日常观察，不替代医疗、法律、投资等专业意见，也不作为现实决策的唯一依据。" },
    ],
  },
};
Page({
  data: {
    isLoggedIn: false, dashboardLoading: false, loginBusy: false, accountError: "",
    phoneDisplay: "未绑定手机号", phoneBound: false, wechatPhoneAvailable: false,
    profileSummary: "完善档案，查看自己的五色", hasProfile: false, profileCompleteness: 0,
    serviceTitle: "时序文化", serviceCopy: "登录后查看问答权益", remainingQuestions: "—",
    historySummary: "登录后查看自己的问答", orderCounts: EMPTY_COUNTS, orderError: "",
    infoDialog: null as InfoDialog | null,
    orderEntries: [{ id: "pending", label: "待付款", icon: "pay" }, { id: "paid", label: "待发货", icon: "box" }, { id: "shipped", label: "待收货", icon: "delivery" }, { id: "after_sale", label: "退款 / 售后", icon: "service" }],
  },
  onShow() { (this as any).getTabBar?.()?.setData({ selected: 3 }); void this.loadAccount(); },
  onHide() { loadVersion++; this.setData({ dashboardLoading: false }); },
  onPullDownRefresh() { void this.loadAccount().finally(() => wx.stopPullDownRefresh()); },
  resetAccount() {
    this.setData({ isLoggedIn: false, phoneDisplay: "未绑定手机号", phoneBound: false, wechatPhoneAvailable: false,
      profileSummary: "完善档案，查看自己的五色", hasProfile: false, profileCompleteness: 0,
      serviceTitle: "时序文化", serviceCopy: "登录后查看问答权益", remainingQuestions: "—",
      historySummary: "登录后查看自己的问答", orderCounts: EMPTY_COUNTS, orderError: "", accountError: "" });
  },
  async loadAccount() {
    const version = ++loadVersion;
    if (!getToken()) { this.resetAccount(); return; }
    this.resetAccount();
    this.setData({ dashboardLoading: true });
    try {
      const user = await getCurrentUser();
      if (version !== loadVersion) return;
      this.setData({ isLoggedIn: true, phoneBound: user.phone_bound, wechatPhoneAvailable: user.wechat_phone_available,
        phoneDisplay: user.phone_number ? user.phone_number.slice(0,3) + "****" + user.phone_number.slice(-4) : "未绑定手机号" });
      const [profile, quota, history, orders] = await Promise.allSettled([getCurrentProfile(), getAIQuota(), getAIHistory(5), getOrders("all", 0, 1)]);
      if (version !== loadVersion) return;
      if (profile.status === "fulfilled") this.setData({ hasProfile: true, profileCompleteness: profile.value.completeness,
        profileSummary: "本人档案 · 完整度 " + profile.value.completeness + "%" });
      else this.setData({ profileSummary: isProfileMissing(profile.reason) ? "还未创建档案，去填写" : "档案暂时无法读取，请刷新" });
      if (quota.status === "fulfilled") this.setData({
        serviceTitle: quota.value.active ? "时序文化 · 个人服务" : "时序文化 · 暂无有效权益",
        serviceCopy: quota.value.active ? "今日普通问答 " + quota.value.normal_remaining + " / " + quota.value.normal_limit + " 次" : "历史问答仍可查看",
        remainingQuestions: String(quota.value.normal_remaining),
      });
      else this.setData({ serviceCopy: "权益暂时无法读取，请刷新" });
      if (history.status === "fulfilled") this.setData({ historySummary: history.value[0] ? history.value[0].question : "还没有问答记录，去问一句" });
      else this.setData({ historySummary: "问答记录暂时无法读取" });
      if (orders.status === "fulfilled") {
        const c = orders.value.counts;
        this.setData({ orderCounts: { pending: String(c.pending), paid: String(c.paid), shipped: String(c.shipped), after_sale: String(c.after_sale) }, orderError: "" });
      } else this.setData({ orderError: "订单暂时无法读取，点此重试" });
    } catch (error) {
      if (version !== loadVersion) return;
      if (isApiError(error, 401)) logoutLocalAccount();
      this.setData({ accountError: getApiErrorMessage(error, "账号暂时无法读取，请重试") });
    } finally { if (version === loadVersion) this.setData({ dashboardLoading: false }); }
  },
  async realLogin() {
    if (this.data.loginBusy) return;
    this.setData({ loginBusy: true });
    try { await loginWithWechat(); await this.loadAccount(); }
    catch (error) { this.setData({ accountError: getApiErrorMessage(error, "登录失败，请重试") }); }
    finally { this.setData({ loginBusy: false }); }
  },
  toOrders(event: WechatMiniprogram.TouchEvent) { wx.navigateTo({ url: "/pages/orders/index?status=" + (event.currentTarget.dataset.status || "all") }); },
  toProfile() {
    if (!this.data.isLoggedIn) { wx.showToast({ title: "请先点击微信登录", icon: "none" }); return; }
    wx.navigateTo({ url: "/pages/profile/index" });
  },
  toAi() { wx.switchTab({ url: "/pages/chat/index" }); },
  toShop() { wx.switchTab({ url: "/pages/caikuxiang/index" }); },
  async bindPhone(event: WechatMiniprogram.ButtonGetPhoneNumber) {
    const code = (event.detail as { code?: string }).code;
    if (!code) return;
    try { await bindWechatPhone(code); await this.loadAccount(); }
    catch (error) { wx.showToast({ title: getApiErrorMessage(error, "绑定失败，请重试"), icon: "none" }); }
  },
  logout() { loadVersion++; logoutLocalAccount(); this.resetAccount(); this.setData({ dashboardLoading: false }); },
  showHelp() { this.setData({ infoDialog: INFO_DIALOGS.help }); },
  showPrivacy() { this.setData({ infoDialog: INFO_DIALOGS.privacy }); },
  showAbout() { this.setData({ infoDialog: INFO_DIALOGS.about }); },
  closeInfo() { this.setData({ infoDialog: null }); },
  noop() {},
});
