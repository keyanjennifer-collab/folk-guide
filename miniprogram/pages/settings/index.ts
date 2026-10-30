import { getTheme, AppTheme } from "../../services/theme";
import { getApiErrorMessage, getToken, isApiError } from "../../services/api";
import { DEFAULT_AVATAR_URL, DEFAULT_NICKNAME, getCurrentUser, loginWithWechat, logoutLocalAccount, bindWechatPhone, updateUserProfile, userProfilePresentation } from "../../services/account";
import { getAIQuota } from "../../services/ai";
import { entitlementPresentation } from "../../services/entitlements";
import { getCurrentProfile, isProfileMissing } from "../../services/profile";
import { getOrders } from "../../services/orders";
import { contactAfterSales, prepareAfterSalesContact } from "../../services/after-sales";
let loadVersion = 0;
let profileSaveVersion = 0;
const EMPTY_COUNTS = { pending: "—", paid: "—", shipped: "—", after_sale: "—" };
type InfoDialog = { eyebrow: string; title: string; intro: string; sections: { title: string; body: string }[] };
const INFO_DIALOGS: Record<"help" | "privacy" | "about", InfoDialog> = {
  help: {
    eyebrow: "GUIDE", title: "使用帮助", intro: "从今日五色到选香、测算与个人记录，可按以下方式使用。",
    sections: [
      { title: "体验与永久权益", body: "新用户注册后可体验7天个人今日五色与测一测全部功能。购买268元五色套装，付款成功后赠送购买账号全部功能的永久使用权，已有未退款套装订单也享有权益。订单成功退款后撤销对应赠送权益；AI问答保留每日使用次数。" },
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
      { title: "账号信息", body: "微信登录用于识别你的账号并同步订单、档案与问答记录。头像和昵称在你点击“保存资料”后上传并保存在账号中，下次登录时恢复。手机号不会自动读取，只有在你点击授权后才会绑定。" },
      { title: "本人档案", body: "你填写的档案用于生成个人五色等功能，可随时进入“本人档案”修改或删除。传统文化内容仅供学习与生活参考。" },
      { title: "订单与收货信息", body: "购物袋保存在当前设备；收货人、电话和地址在你提交后保存于账号，仅用于计价、配送、售后和依法留存。退出登录不会删除已经提交的订单；注销账号时，交易、退款和开票所需记录将按法律要求保留或脱敏处理。" },
      { title: "你的选择", body: "你可以不绑定微信手机号，也可以在本人档案中管理已填写内容。交易与售后相关问题可通过“我的”或订单详情中的“售后客服”提出。商品的发货时间、取消和退款规则以提交订单时展示的版本为准。" },
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
    isLoggedIn: false, accountId: 0, nickname: DEFAULT_NICKNAME, avatarUrl: DEFAULT_AVATAR_URL,
    savedNickname: DEFAULT_NICKNAME, savedAvatarUrl: DEFAULT_AVATAR_URL,
    editingProfile: false, profileDirty: false, profileSaving: false, profileError: "",
    showProfileHint: false, dashboardLoading: false, loginBusy: false, accountError: "",
    phoneDisplay: "未绑定手机号", phoneBound: false, wechatPhoneAvailable: false,
    profileSummary: "完善档案，查看自己的五色", hasProfile: false, profileCompleteness: 0,
    serviceTitle: "登录享7天体验", serviceCopy: "购买268元五色套装，赠送全部功能永久使用权", remainingQuestions: "—",
    orderCounts: EMPTY_COUNTS, orderError: "",
    infoDialog: null as InfoDialog | null,
    orderEntries: [{ id: "pending", label: "待付款", icon: "pay" }, { id: "paid", label: "待发货", icon: "box" }, { id: "shipped", label: "待收货", icon: "delivery" }, { id: "after_sale", label: "退款 / 售后", icon: "service" }],
  },
  onShow() { void prepareAfterSalesContact(); const theme = getTheme(); this.setData({ theme, themeClass: `theme-${theme}` }); (this as any).getTabBar?.()?.setData({ selected: 3 }); void this.loadAccount(); },
  onHide() { loadVersion++; this.setData({ dashboardLoading: false }); },
  onUnload() { loadVersion++; profileSaveVersion++; },
  onPullDownRefresh() { void this.loadAccount().finally(() => wx.stopPullDownRefresh()); },
  resetAccount() {
    profileSaveVersion++;
    this.setData({ isLoggedIn: false, accountId: 0, nickname: DEFAULT_NICKNAME, avatarUrl: DEFAULT_AVATAR_URL,
      savedNickname: DEFAULT_NICKNAME, savedAvatarUrl: DEFAULT_AVATAR_URL,
      editingProfile: false, profileDirty: false, profileSaving: false, profileError: "",
      phoneDisplay: "未绑定手机号", phoneBound: false, wechatPhoneAvailable: false,
      profileSummary: "完善档案，查看自己的五色", hasProfile: false, profileCompleteness: 0,
      serviceTitle: "登录享7天体验", serviceCopy: "购买268元五色套装，赠送全部功能永久使用权", remainingQuestions: "—",
      orderCounts: EMPTY_COUNTS, orderError: "", accountError: "" });
  },
  async loadAccount() {
    const version = ++loadVersion;
    if (!getToken()) { this.resetAccount(); return; }
    this.setData({ dashboardLoading: true, accountError: "" });
    try {
      const user = await getCurrentUser();
      if (version !== loadVersion) return;
      const identity = userProfilePresentation(user);
      const sameAccount = this.data.accountId === user.id;
      if (!sameAccount) profileSaveVersion++;
      const restoreIdentity = !sameAccount || (!this.data.profileDirty && !this.data.profileSaving);
      this.setData({ isLoggedIn: true, accountId: user.id,
        savedNickname: identity.nickname, savedAvatarUrl: identity.avatarUrl,
        ...(restoreIdentity ? { ...identity, profileDirty: false, profileError: "" } : {}),
        ...(!sameAccount ? { editingProfile: false, profileSaving: false } : {}),
        showProfileHint: !wx.getStorageSync("profile_edit_hint_shown"),
        phoneBound: user.phone_bound, wechatPhoneAvailable: user.wechat_phone_available,
        phoneDisplay: user.phone_number ? user.phone_number.slice(0,3) + "****" + user.phone_number.slice(-4) : "未绑定手机号" });
      const orderTask = getOrders("all", 0, 1);
      // 订单读取会补查微信付款结果，完成后再读权益，避免同屏仍显示旧会员状态。
      const quotaTask = orderTask.then(() => getAIQuota(), () => getAIQuota());
      const [profile, quota, orders] = await Promise.allSettled([getCurrentProfile(), quotaTask, orderTask]);
      if (version !== loadVersion) return;
      if (profile.status === "fulfilled") this.setData({ hasProfile: true, profileCompleteness: profile.value.completeness,
        profileSummary: "本人档案 · 完整度 " + profile.value.completeness + "%" });
      else this.setData({ profileSummary: isProfileMissing(profile.reason) ? "还未创建档案，去填写" : "档案暂时无法读取，请刷新" });
      if (quota.status === "fulfilled") {
        const presentation = entitlementPresentation(quota.value);
        this.setData({ serviceTitle: presentation.title, serviceCopy: presentation.description,
          remainingQuestions: String(quota.value.normal_remaining) });
      }
      else this.setData({ serviceCopy: "权益暂时无法读取，请刷新" });
      if (orders.status === "fulfilled") {
        const c = orders.value.counts;
        this.setData({ orderCounts: { pending: String(c.pending), paid: String(c.paid), shipped: String(c.shipped), after_sale: String((c.after_sale || 0) + (c.refunded || 0)) }, orderError: "" });
      } else this.setData({ orderError: "订单暂时无法读取，点此重试" });
    } catch (error) {
      if (version !== loadVersion) return;
      if (isApiError(error, 401)) { logoutLocalAccount(); this.resetAccount(); }
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
      await this.loadAccount();
    } catch (error) { this.setData({ accountError: getApiErrorMessage(error, "登录失败，请重试") }); }
    finally { this.setData({ loginBusy: false }); }
  },
  chooseAvatar(event: WechatMiniprogram.CustomEvent<{ avatarUrl: string }>) {
    if (!this.data.profileSaving && event.detail.avatarUrl) this.setData({ avatarUrl: event.detail.avatarUrl, profileDirty: true, profileError: "" });
  },
  toggleProfileEdit() {
    if (!this.data.isLoggedIn || this.data.profileSaving) return;
    wx.setStorageSync("profile_edit_hint_shown", true);
    this.setData({ editingProfile: !this.data.editingProfile, showProfileHint: false,
      ...(this.data.editingProfile ? { nickname: this.data.savedNickname, avatarUrl: this.data.savedAvatarUrl, profileDirty: false, profileError: "" } : {}) });
  },
  editNickname(event: WechatMiniprogram.Input) { if (!this.data.profileSaving) this.setData({ nickname: event.detail.value, profileDirty: true, profileError: "" }); },
  async saveProfile() {
    if (this.data.profileSaving || !this.data.isLoggedIn) return;
    const nickname = String(this.data.nickname || "").trim();
    if (!nickname) { wx.showToast({ title: "请输入昵称", icon: "none" }); return; }
    const accountId = this.data.accountId;
    const version = ++profileSaveVersion;
    loadVersion++; // 已开始的旧账号读取不能在保存完成后覆盖新头像。
    this.setData({ profileSaving: true, profileError: "", dashboardLoading: false });
    try {
      const user = await updateUserProfile(nickname, this.data.avatarUrl);
      if (version !== profileSaveVersion || accountId !== this.data.accountId) return;
      const identity = userProfilePresentation(user);
      loadVersion++; // 保存期间重新进入页面发起的读取，也不能晚到后覆盖已保存资料。
      this.setData({ ...identity, savedNickname: identity.nickname, savedAvatarUrl: identity.avatarUrl,
        profileDirty: false, editingProfile: false, dashboardLoading: false });
      wx.showToast({ title: "资料已保存", icon: "success" });
    } catch (error) {
      if (version !== profileSaveVersion || accountId !== this.data.accountId) return;
      const message = getApiErrorMessage(error, "资料保存失败，请稍后重试");
      this.setData({ profileError: message });
      wx.showToast({ title: message, icon: "none" });
    } finally { if (version === profileSaveVersion) this.setData({ profileSaving: false }); }
  },
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
  logout() { if (this.data.profileSaving) return; wx.showModal({ title: "退出登录", content: "确定退出当前微信账号吗？", confirmText: "退出", cancelText: "取消", success: (result) => { if (!result.confirm || this.data.profileSaving) return; loadVersion++; logoutLocalAccount(); this.resetAccount(); this.setData({ dashboardLoading: false, editingProfile: false }); wx.showToast({ title: "已退出登录", icon: "success" }); } }); },
  showHelp() { this.setData({ infoDialog: INFO_DIALOGS.help }); },
  contactSupport() { contactAfterSales(); },
  showPrivacy() { this.setData({ infoDialog: INFO_DIALOGS.privacy }); },
  showAbout() { this.setData({ infoDialog: INFO_DIALOGS.about }); },
  closeInfo() { this.setData({ infoDialog: null }); },
  noop() {},
});



