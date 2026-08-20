import { getApiErrorMessage, getToken } from "../../services/api";
import {
  bindWechatPhone,
  CurrentUser,
  getCurrentUser,
  loginWithWechat,
  logoutLocalAccount,
} from "../../services/account";
import { getCurrentProfile, isProfileMissing, ProfileResponse } from "../../services/profile";

Page({
  data: {
    isLoggedIn: false,
    phoneBound: false,
    phoneDisplay: "未绑定手机号",
    wechatPhoneAvailable: false,
    nickname: "微信用户",
    hasProfile: false,
    profileCompleteness: 50,
    profileSummary: "尚未创建档案 · 点击填写出生日期",
    trialDaysLeft: 3,
    questionRemaining: 20,
    pushEnabled: false,
    pushTime: "08:00",
    pendingCards: 1,
    activeCards: 0,
    orderCounts: { unpaid: 0, unshipped: 1, shipped: 0, afterSale: 0 },
  },
  /** 每次打开“我的”都让后端验证缓存 JWT。 */
  async onShow() {
    if (!getToken()) return this.resetLoggedOutState();
    try {
      this.applyAccount(await getCurrentUser());
      await this.loadProfileSummary();
    } catch (_) {
      this.resetLoggedOutState();
    }
  },
  /** 将账号接口返回值映射成页面展示状态，并对手机号中间四位脱敏。 */
  applyAccount(user: CurrentUser) {
    const phone = user.phone_number || "";
    this.setData({ isLoggedIn: true, phoneBound: user.phone_bound,
      phoneDisplay: phone ? `${phone.slice(0, 3)}****${phone.slice(-4)}` : "未绑定手机号",
      wechatPhoneAvailable: user.wechat_phone_available });
  },
  /** wx.login 获取临时 code；后端换 openid、创建用户并返回 JWT。 */
  async realLogin() {
    wx.showLoading({ title: "登录中" });
    try {
      await loginWithWechat();
      this.applyAccount(await getCurrentUser());
      await this.loadProfileSummary();
      wx.showToast({ title: "登录成功" });
    } catch (error: unknown) {
      this.resetLoggedOutState();
      wx.showToast({ title: getApiErrorMessage(error, "登录失败，请稍后重试"), icon: "none", duration: 2600 });
    }
    finally { wx.hideLoading(); }
  },

  /** 读取数据库中的真实档案摘要；尚未创建档案是正常状态，不弹错误。 */
  async loadProfileSummary() {
    try {
      this.applyProfileSummary(await getCurrentProfile());
    } catch (error: unknown) {
      if (isProfileMissing(error)) {
        this.setData({ hasProfile: false, profileCompleteness: 50, profileSummary: "尚未创建档案 · 点击填写出生日期" });
      } else {
        this.setData({ hasProfile: false, profileCompleteness: 50, profileSummary: "档案状态暂时无法读取" });
      }
    }
  },

  /** 根据后端missing_fields生成可读摘要，不在前端重新猜测完整度。 */
  applyProfileSummary(profile: ProfileResponse) {
    const missingNames: Record<string, string> = { birth_time: "时辰", birth_city: "城市", gender: "性别" };
    const missing = profile.missing_fields.map((field) => missingNames[field]).filter(Boolean);
    const summary = missing.length ? `出生日期已填写 · ${missing.join("、")}待完善` : "出生信息已完整填写";
    this.setData({ hasProfile: true, profileCompleteness: profile.completeness, profileSummary: summary });
  },

  /** 清除页面里的个人状态，防止退出后仍看到上一账号的档案摘要。 */
  resetLoggedOutState() {
    this.setData({
      isLoggedIn: false,
      phoneBound: false,
      phoneDisplay: "未绑定手机号",
      wechatPhoneAvailable: false,
      hasProfile: false,
      profileCompleteness: 50,
      profileSummary: "尚未创建档案 · 点击填写出生日期",
    });
  },
  /** 手机号按钮返回一次性 code，由后端调用微信接口换取号码。 */
  async bindPhone(event: WechatMiniprogram.ButtonGetPhoneNumber) {
    const code = event.detail.code;
    if (!code) return wx.showToast({ title: "你取消了手机号授权", icon: "none" });
    try { this.applyAccount(await bindWechatPhone(code)); wx.showToast({ title: "绑定成功" }); }
    catch (error: unknown) { wx.showToast({ title: getApiErrorMessage(error, "手机号能力尚未配置"), icon: "none", duration: 2600 }); }
  },
  logout() { logoutLocalAccount(); this.resetLoggedOutState(); },
  toProfile() { wx.navigateTo({ url: "/pages/profile/index" }); },
  toAi() { wx.switchTab({ url: "/pages/chat/index" }); },
  showOrders(event: WechatMiniprogram.TouchEvent) {
    const label = String(event.currentTarget.dataset.label || "全部订单");
    wx.showModal({ title: label, content: "订单列表、物流与售后将在接入商城后台后显示。当前为前端流程演示。", showCancel: false });
  },
  showCards() {
    wx.showModal({
      title: "我的服务卡",
      content: "你有1张新客3天体验卡正在使用，另有1张30天服务卡待开启。待开启服务卡可立即开启、暂存或赠送好友。",
      confirmText: "查看AI国学", cancelText: "关闭",
      success: (result) => { if (result.confirm) this.toAi(); },
    });
  },
  activateCard() {
    wx.showModal({ title: "开启30天服务卡", content: "开启后将连续使用30天。当前新客体验仍在使用中，正式系统会在体验结束后再开始消耗服务卡。", showCancel: false });
  },
  giftCard() {
    wx.showModal({
      title: "赠送好友",
      content: "正式版本将生成微信赠礼卡。好友领取前可以撤回；先领取者获得，领取后不能再次转赠。",
      confirmText: "生成赠礼卡", cancelText: "暂不赠送",
    });
  },
  togglePush(event: WechatMiniprogram.SwitchChange) {
    const enabled = event.detail.value;
    this.setData({ pushEnabled: enabled });
    wx.showToast({ title: enabled ? "已记录提醒意愿" : "已关闭提醒", icon: "none" });
  },
  selectPushTime(event: WechatMiniprogram.PickerChange) {
    const times = ["07:00", "08:00", "09:00"];
    this.setData({ pushTime: times[Number(event.detail.value)] });
  },
  showRecords(event: WechatMiniprogram.TouchEvent) {
    const title = String(event.currentTarget.dataset.title);
    wx.showModal({ title, content: "历史记录页面将在连接个人结果和问答数据库后展示。用户可以查看并主动清空记录。", showCancel: false });
  },
  showHelp() { wx.showModal({ title: "帮助与反馈", content: "后续将提供常见问题、在线反馈、回答纠错和售后联系入口。", showCancel: false }); },
  showPrivacy() { wx.showModal({ title: "隐私与数据", content: "用户可以查看、修改和删除生辰档案，清空问答记录，并申请注销账号。", showCancel: false }); },
  showAbout() { wx.showModal({ title: "关于五行五色", content: "现代、好看、每天愿意打开的传统五行生活工具。内容仅供文化了解和生活参考。", showCancel: false }); },
});
