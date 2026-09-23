import { getTheme, AppTheme } from "../../services/theme";
import { getApiErrorMessage, getToken, isApiError } from "../../services/api";
import { getCurrentUser, loginWithWechat, logoutLocalAccount, bindWechatPhone, requestWechatProfile, saveLocalUserProfile, getLocalUserProfile, updateUserProfile } from "../../services/account";
import { getAIQuota } from "../../services/ai";
import { getCurrentProfile, isProfileMissing } from "../../services/profile";
import { getOrders } from "../../services/orders";
let loadVersion = 0;
const EMPTY_COUNTS = { pending: "—", paid: "—", shipped: "—", after_sale: "—" };
type InfoDialog = { eyebrow: string; title: string; intro: string; sections: { title: string; body: string }[] };
const INFO_DIALOGS: Record<"help" | "privacy" | "about", InfoDialog> = {
  help: {
    eyebrow: "GUIDE", title: "使用帮助", intro: "从今日五色到选香、测算与个人记录，可按以下方式使用。",
    sections: [
      { title: "查看今日五色", body: "首页内容以北京时间公历自然日为边界自动更新。系统取得当日日柱后，仅取日支所属五行作为“当日五行”，再按固定生克关系排列贵人色、合作色、奋斗色、消耗色与不利色。" },
      { title: "阅读色序建议", body: "点击首页五种色系可切换对应香品；进入“五色详解”后，点击“展开”可查看色序依据、今日适宜、行动建议与需要留意的事项。" },
      { title: "选香、结算与支付", body: "商城包含五色知时线香套装及青木、朱蜜、黄檀、白桂、墨沉五款单香。加入购物袋后，可填写收货地址并使用微信支付；正式价格、运费和库存均在提交订单时由服务端核验。" },
      { title: "使用测一测", body: "“测一测”用于紫微斗数起盘与合盘。可先完善本人出生资料，为后续建立个人命盘或对照两份命盘做准备；相关内容仅供传统文化研究与生活参考。" },
      { title: "管理个人内容", body: "微信登录后可完善本人档案、查看个人五色及订单状态。手机号仅在你主动授权后绑定。若页面内容未及时更新，可下拉刷新或重新进入小程序。" },
    ],
  },
  privacy: {
    eyebrow: "PRIVACY", title: "账号与隐私", intro: "个人信息只用于提供你主动使用的账号与个性化功能。",
    sections: [
      { title: "账号信息", body: "微信登录用于识别你的账号并同步订单、档案与问答记录。手机号不会自动读取，只有在你点击授权后才会绑定。" },
      { title: "本人档案", body: "你填写的档案用于生成个人五色等功能，可随时进入“本人档案”修改或删除。传统文化内容仅供学习与生活参考。" },
      { title: "订单与收货信息", body: "购物袋保存在当前设备；收货人、电话和地址在你提交后保存于账号，仅用于计价、配送、售后和依法留存。退出登录不会删除已经提交的订单；注销账号时，交易、退款和开票所需记录将按法律要求保留或脱敏处理。" },
      { title: "你的选择", body: "你可以不绑定微信手机号，也可以在本人档案中管理已填写内容。交易与售后相关问题可通过结算页“购买、配送与售后须知”中公示的客服方式提出。商城预购商品的发货时间、取消和退款规则以提交订单时展示的版本为准。" },
      { title: "内容说明", body: "五色寓意、香气札记和AI生成内容用于传统文化学习、审美体验与日常参考，不承诺医疗、运势、收益或其他确定性效果。" },
    ],
  },
  about: {
    eyebrow: "ABOUT US", title: "关于我们", intro: "五色应时，知时而行。",
    sections: [
      { title: "五色知时", body: "我们以传统五行时序为线索，把每日色序、香气选择与紫微测算整理成更容易进入日常的体验。" },
      { title: "我们在做什么", body: "每日五色遵循公开、固定的历法与五行关系生成；五款香以青木、朱蜜、黄檀、白桂、墨沉对应五方意象，让时序可以被看见，也可以被闻见。" },
      { title: "使用边界", body: "内容用于传统文化学习、审美体验与日常观察，不替代医疗、法律、投资等专业意见，也不作为现实决策的唯一依据。" },
    ],
  },
};
Page({
  data: { themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    isLoggedIn: false, nickname: "五色知时用户", avatarUrl: "/assets/brand/logo-ai.png", editingProfile: false, showProfileHint: false, dashboardLoading: false, loginBusy: false, accountError: "",
    phoneDisplay: "未绑定手机号", phoneBound: false, wechatPhoneAvailable: false,
    profileSummary: "完善档案，查看自己的五色", hasProfile: false, profileCompleteness: 0,
    serviceTitle: "紫微起盘与合盘", serviceCopy: "购买产品后开通测算服务", remainingQuestions: "—",
    orderCounts: EMPTY_COUNTS, orderError: "",
    infoDialog: null as InfoDialog | null,
    orderEntries: [{ id: "pending", label: "待付款", icon: "pay" }, { id: "paid", label: "待发货", icon: "box" }, { id: "shipped", label: "待收货", icon: "delivery" }, { id: "after_sale", label: "退款 / 售后", icon: "service" }],
  },
  onShow() { const theme = getTheme(); this.setData({ theme, themeClass: `theme-${theme}` }); (this as any).getTabBar?.()?.setData({ selected: 3 }); const p = getLocalUserProfile(); this.setData({ nickname: p.nickname, avatarUrl: p.avatarUrl, showProfileHint: !!p.nickname && !wx.getStorageSync("profile_edit_hint_shown") }); void this.loadAccount(); },
  onHide() { loadVersion++; this.setData({ dashboardLoading: false }); },
  onPullDownRefresh() { void this.loadAccount().finally(() => wx.stopPullDownRefresh()); },
  resetAccount() {
    this.setData({ isLoggedIn: false, phoneDisplay: "未绑定手机号", phoneBound: false, wechatPhoneAvailable: false,
      profileSummary: "完善档案，查看自己的五色", hasProfile: false, profileCompleteness: 0,
      serviceTitle: "紫微起盘与合盘", serviceCopy: "购买产品后开通测算服务", remainingQuestions: "—",
      orderCounts: EMPTY_COUNTS, orderError: "", accountError: "" });
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
      const [profile, quota, orders] = await Promise.allSettled([getCurrentProfile(), getAIQuota(), getOrders("all", 0, 1)]);
      if (version !== loadVersion) return;
      if (profile.status === "fulfilled") this.setData({ hasProfile: true, profileCompleteness: profile.value.completeness,
        profileSummary: "本人档案 · 完整度 " + profile.value.completeness + "%" });
      else this.setData({ profileSummary: isProfileMissing(profile.reason) ? "还未创建档案，去填写" : "档案暂时无法读取，请刷新" });
      if (quota.status === "fulfilled") this.setData({
        serviceTitle: quota.value.active ? "测一测 · 个人服务" : "紫微起盘与合盘",
        serviceCopy: quota.value.active ? "个人五色与测算服务已开通" : "购买产品后开通测算服务",
        remainingQuestions: String(quota.value.normal_remaining),
      });
      else this.setData({ serviceCopy: "权益暂时无法读取，请刷新" });
      if (orders.status === "fulfilled") {
        const c = orders.value.counts;
        this.setData({ orderCounts: { pending: String(c.pending), paid: String(c.paid), shipped: String(c.shipped), after_sale: String((c.after_sale || 0) + (c.refunded || 0)) }, orderError: "" });
      } else this.setData({ orderError: "订单暂时无法读取，点此重试" });
    } catch (error) {
      if (version !== loadVersion) return;
      if (isApiError(error, 401)) logoutLocalAccount();
      this.setData({ accountError: getApiErrorMessage(error, "账号暂时无法读取，请重试") });
    } finally { if (version === loadVersion) this.setData({ dashboardLoading: false }); }
  },
  async realLogin() {
    if (this.data.loginBusy) return;
    const consent = await new Promise<boolean>((resolve) => wx.showModal({ title: "使用微信登录", content: "是否使用微信账号登录五色知时？", confirmText: "同意登录", cancelText: "暂不登录", success: (result) => resolve(result.confirm), fail: () => resolve(false) }));
    if (!consent) return;
    this.setData({ loginBusy: true });
    try {
      await loginWithWechat();
      const savedProfile = getLocalUserProfile();
      if (savedProfile.source === "default") {
        const profileConsent = await new Promise<boolean>((resolve) => wx.showModal({ title: "授权头像和昵称", content: "是否允许使用你的微信头像和昵称显示在主页？", confirmText: "授权", cancelText: "暂不授权", success: (result) => resolve(result.confirm), fail: () => resolve(false) }));
        if (profileConsent) {
        try { const profile = await requestWechatProfile(); saveLocalUserProfile({ nickname: profile.userInfo.nickName, avatarUrl: profile.userInfo.avatarUrl, source: "wechat" }); }
        catch (_) { this.setData({ editingProfile: true }); }
        }
      }
      await this.loadAccount();
    } catch (error) { this.setData({ accountError: getApiErrorMessage(error, "登录失败，请重试") }); }
    finally { this.setData({ loginBusy: false }); }
  },
  chooseAvatar(event: any) { this.setData({ avatarUrl: event.detail.avatarUrl }); },
  toggleProfileEdit() { wx.setStorageSync("profile_edit_hint_shown", true); this.setData({ editingProfile: !this.data.editingProfile, showProfileHint: false }); },
  editNickname(event: any) { this.setData({ nickname: event.detail.value }); },
  async saveProfile() { const nickname = String(this.data.nickname || "").trim(); if (!nickname) { wx.showToast({ title: "请输入昵称", icon: "none" }); return; } saveLocalUserProfile({ nickname, avatarUrl: this.data.avatarUrl, source: "custom" }); try { await updateUserProfile(nickname, this.data.avatarUrl); wx.showToast({ title: "资料已保存", icon: "success" }); this.setData({ editingProfile: false }); } catch (_) { wx.showToast({ title: "已保存到本机", icon: "none" }); } },
  toOrders(event: WechatMiniprogram.TouchEvent) { wx.navigateTo({ url: "/pages/orders/index?status=" + (event.currentTarget.dataset.status || "all") }); },
  toProfile() {
    if (!this.data.isLoggedIn) { wx.showToast({ title: "请先点击微信登录", icon: "none" }); return; }
    wx.navigateTo({ url: "/pages/profile/index" });
  },
  toTest() { wx.switchTab({ url: "/pages/chat/index" }); },
  toShop() { wx.switchTab({ url: "/pages/caikuxiang/index" }); },
  async bindPhone(event: WechatMiniprogram.ButtonGetPhoneNumber) {
    const code = (event.detail as { code?: string }).code;
    if (!code) return;
    try { await bindWechatPhone(code); await this.loadAccount(); }
    catch (error) { wx.showToast({ title: getApiErrorMessage(error, "绑定失败，请重试"), icon: "none" }); }
  },
  logout() { wx.showModal({ title: "退出登录", content: "确定退出当前微信账号吗？", confirmText: "退出", cancelText: "取消", success: (result) => { if (!result.confirm) return; loadVersion++; logoutLocalAccount(); this.resetAccount(); this.setData({ dashboardLoading: false, editingProfile: false }); wx.showToast({ title: "已退出登录", icon: "success" }); } }); },
  showHelp() { this.setData({ infoDialog: INFO_DIALOGS.help }); },
  showPrivacy() { this.setData({ infoDialog: INFO_DIALOGS.privacy }); },
  showAbout() { this.setData({ infoDialog: INFO_DIALOGS.about }); },
  closeInfo() { this.setData({ infoDialog: null }); },
  noop() {},
});



