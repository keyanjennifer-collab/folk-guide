import { getApiErrorMessage, getToken, isApiError } from "../../services/api";
import { getCurrentUser, loginWithWechat, logoutLocalAccount, bindWechatPhone } from "../../services/account";
import { getAIHistory, getAIQuota } from "../../services/ai";
import { getCurrentProfile, isProfileMissing } from "../../services/profile";
import { getOrders } from "../../services/orders";
let loadVersion = 0;
const EMPTY_COUNTS = { pending: "—", paid: "—", shipped: "—", after_sale: "—" };
Page({
  data: {
    isLoggedIn: false, dashboardLoading: false, loginBusy: false, accountError: "",
    phoneDisplay: "未绑定手机号", phoneBound: false, wechatPhoneAvailable: false,
    profileSummary: "完善档案，查看自己的五色", hasProfile: false, profileCompleteness: 0,
    serviceTitle: "AI国学", serviceCopy: "登录后查看问答权益", remainingQuestions: "—",
    historySummary: "登录后查看自己的问答", orderCounts: EMPTY_COUNTS, orderError: "",
    orderEntries: [{ id: "pending", label: "待付款", icon: "pay" }, { id: "paid", label: "待发货", icon: "box" }, { id: "shipped", label: "待收货", icon: "delivery" }, { id: "after_sale", label: "退款 / 售后", icon: "service" }],
  },
  onShow() { (this as any).getTabBar?.()?.setData({ selected: 3 }); void this.loadAccount(); },
  onHide() { loadVersion++; this.setData({ dashboardLoading: false }); },
  onPullDownRefresh() { void this.loadAccount().finally(() => wx.stopPullDownRefresh()); },
  resetAccount() {
    this.setData({ isLoggedIn: false, phoneDisplay: "未绑定手机号", phoneBound: false, wechatPhoneAvailable: false,
      profileSummary: "完善档案，查看自己的五色", hasProfile: false, profileCompleteness: 0,
      serviceTitle: "AI国学", serviceCopy: "登录后查看问答权益", remainingQuestions: "—",
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
        serviceTitle: quota.value.active ? "AI国学 · 个人服务" : "AI国学 · 暂无有效权益",
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
  showHelp() { wx.showModal({ title: "使用帮助", content: "今日五色每天按北京时间更新；点击颜色可切换对应香品。\n商品详情可加入购物袋，目前尚未开放下单。\n登录后可管理本人档案、查看个人五色和问答历史。AI回答下方可提交纠错。", showCancel: false }); },
  showPrivacy() { wx.showModal({ title: "账号与隐私", content: "登录用于建立你的个人账号。手机号需另行授权；档案与问答记录按账号保存。\n本人档案可在档案页修改或删除；退出登录将清除本机登录状态。购物袋仅为本机选香清单。", showCancel: false }); },
  showAbout() { wx.showModal({ title: "五色知时", content: "五色应时，知时而行。\n观色知序，循心择香。以传统五行时序，为日常穿搭、香气与生活提供参考。", showCancel: false }); },
});
