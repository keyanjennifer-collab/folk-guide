import { getApiErrorMessage, getToken, isApiError } from "../../services/api";
import {
  bindWechatPhone,
  CurrentUser,
  getCurrentUser,
  loginWithWechat,
  logoutLocalAccount,
} from "../../services/account";
import { AIHistoryRecord, AIQuota, getAIHistory, getAIQuota } from "../../services/ai";
import { getPersonalDailyGuidance } from "../../services/daily";
import { getCurrentProfile, isProfileMissing, ProfileResponse } from "../../services/profile";

/**
 * 数据库事件时间按 UTC 保存。早期接口可能返回没有 Z 的时间字符串，这里统一按
 * UTC 解释，避免手机误当成本地时间后让剩余天数相差一天。
 */
function parseApiTime(value: string): Date {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

/** 按当前时刻计算权益还剩几个计时日；不足一天仍显示 1 天。 */
function daysLeft(expiresAt: string | null): number {
  if (!expiresAt) return 0;
  const milliseconds = parseApiTime(expiresAt).getTime() - Date.now();
  return Math.max(Math.ceil(milliseconds / 86_400_000), 0);
}

/** 把服务到期时间转成适合“我的”页面阅读的本地日期。 */
function expiryText(expiresAt: string | null): string {
  if (!expiresAt) return "暂无有效期";
  const value = parseApiTime(expiresAt);
  if (Number.isNaN(value.getTime())) return "有效期读取失败";
  return `有效期至 ${value.getFullYear()}年${value.getMonth() + 1}月${value.getDate()}日`;
}

/** 弹窗中只展示简短问题，避免一条长问题占满整个微信弹窗。 */
function shortQuestion(question: string): string {
  return question.length > 28 ? `${question.slice(0, 28)}…` : question;
}

Page({
  data: {
    isLoggedIn: false,
    dashboardLoading: false,
    phoneBound: false,
    phoneDisplay: "未绑定手机号",
    wechatPhoneAvailable: false,
    nickname: "微信用户",

    // 档案完整度完全以后端计算结果为准，前端只负责展示。
    hasProfile: false,
    profileCompleteness: 0,
    profileSummary: "尚未创建档案 · 点击填写出生日期",

    // AI 权益和次数来自 /api/ai/quota，不再使用写死的“3天、20次”。
    serviceActive: false,
    answerReady: false,
    memberStatus: "正在读取服务状态",
    serviceLabel: "服务状态",
    serviceTitle: "AI国学服务状态读取中",
    serviceCopy: "请稍候",
    serviceExpiry: "暂无有效期",
    serviceDaysLeft: 0,
    serviceProgress: 0,
    questionRemaining: 0,
    questionLimit: 0,
    comparisonRemaining: 0,
    comparisonLimit: 0,
    answerStatus: "问答服务状态读取中",

    // 最近几条记录只用于本页摘要和弹窗，完整历史仍在 AI 国学页展示。
    aiHistory: [] as AIHistoryRecord[],
    historySummary: "还没有问答记录",
    personalResultSummary: "需要有效服务与生辰档案",
  },

  /**
   * 每次进入“我的”先让后端验证 JWT，再读取档案、权益和历史。
   * 某个业务接口失败不会被误判为退出登录；只有账号接口失败才清空登录态。
   */
  async onShow() {
    if (!getToken()) {
      this.resetLoggedOutState();
      return;
    }
    this.setData({ dashboardLoading: true });
    try {
      this.applyAccount(await getCurrentUser());
      await this.loadDashboard();
    } catch (_) {
      this.resetLoggedOutState();
    } finally {
      this.setData({ dashboardLoading: false });
    }
  },

  /** 将账号接口返回值映射为页面状态，并对手机号中间四位脱敏。 */
  applyAccount(user: CurrentUser) {
    const phone = user.phone_number || "";
    this.setData({
      isLoggedIn: true,
      phoneBound: user.phone_bound,
      phoneDisplay: phone ? `${phone.slice(0, 3)}****${phone.slice(-4)}` : "未绑定手机号",
      wechatPhoneAvailable: user.wechat_phone_available,
    });
  },

  /** wx.login 获取临时 code；后端换 openid、创建用户并返回 JWT。 */
  async realLogin() {
    wx.showLoading({ title: "登录中" });
    try {
      await loginWithWechat();
      this.applyAccount(await getCurrentUser());
      await this.loadDashboard();
      wx.showToast({ title: "登录成功" });
    } catch (error: unknown) {
      this.resetLoggedOutState();
      wx.showToast({
        title: getApiErrorMessage(error, "登录失败，请稍后重试"),
        icon: "none",
        duration: 2600,
      });
    } finally {
      wx.hideLoading();
    }
  },

  /**
   * 三个接口互不依赖，使用并行请求缩短页面等待时间。
   * Promise.allSettled 允许其中一块暂时失败时继续展示其他真实数据。
   */
  async loadDashboard() {
    const [profileResult, quotaResult, historyResult] = await Promise.allSettled([
      getCurrentProfile(),
      getAIQuota(),
      getAIHistory(5),
    ]);

    let profileState: "ready" | "missing" | "error" = "error";
    if (profileResult.status === "fulfilled") {
      profileState = "ready";
      this.applyProfileSummary(profileResult.value);
    } else if (isProfileMissing(profileResult.reason)) {
      profileState = "missing";
      this.setMissingProfileState();
    } else {
      this.setData({
        hasProfile: false,
        profileCompleteness: 0,
        profileSummary: "档案状态暂时无法读取",
      });
    }

    let quota: AIQuota | null = null;
    if (quotaResult.status === "fulfilled") {
      quota = quotaResult.value;
      this.applyQuota(quota);
    } else {
      this.setUnavailableServiceState();
    }

    if (historyResult.status === "fulfilled") {
      this.applyHistory(historyResult.value);
    } else {
      this.setData({ aiHistory: [], historySummary: "问答记录暂时无法读取" });
    }

    // 只有权益有效且确有档案时才读取个人五色，顺序与后端隐私边界保持一致。
    if (quota?.active && profileState === "ready") {
      await this.loadPersonalResultSummary();
    } else if (profileState === "missing") {
      this.setData({ personalResultSummary: "完善生辰档案后生成今日个人五色" });
    } else if (profileState === "error") {
      this.setData({ personalResultSummary: "档案状态暂时无法读取" });
    } else {
      this.setData({ personalResultSummary: "当前没有有效服务，个人五色未加载" });
    }
  },

  /** 根据后端 missing_fields 生成可读摘要，不在前端重新猜测完整度。 */
  applyProfileSummary(profile: ProfileResponse) {
    const missingNames: Record<string, string> = {
      birth_time: "时辰",
      birth_city: "城市",
      gender: "性别",
    };
    const missing = profile.missing_fields.map((field) => missingNames[field]).filter(Boolean);
    const summary = missing.length
      ? `出生日期已填写 · ${missing.join("、")}待完善`
      : "出生信息已完整填写";
    this.setData({
      hasProfile: true,
      profileCompleteness: profile.completeness,
      profileSummary: summary,
    });
  },

  setMissingProfileState() {
    this.setData({
      hasProfile: false,
      profileCompleteness: 0,
      profileSummary: "尚未创建档案 · 点击填写出生日期",
    });
  },

  /** 把真实权益计划、剩余次数和模型就绪状态转换成页面文案。 */
  applyQuota(quota: AIQuota) {
    const remainingDays = daysLeft(quota.expires_at);
    let memberStatus = "当前无有效权益";
    let serviceLabel = "暂未开通";
    let serviceTitle = "AI国学服务尚未开通";
    let totalDays = 0;

    if (quota.plan === "new_user_3_days") {
      memberStatus = "新客体验中";
      serviceLabel = "新客赠送";
      serviceTitle = "3天AI国学体验";
      totalDays = 3;
    } else if (quota.active) {
      memberStatus = "个人服务使用中";
      serviceLabel = "服务使用中";
      serviceTitle = quota.plan === "paid_30_days" ? "30天AI国学个人服务" : "AI国学个人服务";
      totalDays = quota.plan === "paid_30_days" ? 30 : Math.max(remainingDays, 1);
    }

    const progress = quota.active && totalDays
      ? Math.min(Math.round((remainingDays / totalDays) * 100), 100)
      : 0;
    const serviceCopy = quota.active
      ? `普通问答 ${quota.normal_remaining}/${quota.normal_limit} · 七日比较 ${quota.comparison_remaining}/${quota.comparison_limit}`
      : "历史回答仍可查看；开通服务后可继续提问";

    this.setData({
      serviceActive: quota.active,
      answerReady: quota.active && quota.answer_ready,
      memberStatus,
      serviceLabel,
      serviceTitle,
      serviceCopy,
      serviceExpiry: expiryText(quota.expires_at),
      serviceDaysLeft: remainingDays,
      serviceProgress: progress,
      questionRemaining: quota.normal_remaining,
      questionLimit: quota.normal_limit,
      comparisonRemaining: quota.comparison_remaining,
      comparisonLimit: quota.comparison_limit,
      answerStatus: !quota.active
        ? "当前无有效服务"
        : quota.answer_ready
          ? "问答服务已就绪"
          : "问答服务准备中",
    });
  },

  setUnavailableServiceState() {
    this.setData({
      serviceActive: false,
      answerReady: false,
      memberStatus: "服务状态暂时无法读取",
      serviceLabel: "读取失败",
      serviceTitle: "AI国学服务状态暂时无法读取",
      serviceCopy: "请确认后端服务正常后重试",
      serviceExpiry: "有效期暂时无法读取",
      serviceDaysLeft: 0,
      serviceProgress: 0,
      questionRemaining: 0,
      questionLimit: 0,
      comparisonRemaining: 0,
      comparisonLimit: 0,
      answerStatus: "问答服务状态未知",
    });
  },

  /** 保存最近5条本人问答；后端已经按JWT的用户编号完成隔离。 */
  applyHistory(history: AIHistoryRecord[]) {
    const latest = history[0];
    this.setData({
      aiHistory: history,
      historySummary: latest ? `最近：${shortQuestion(latest.question)}` : "还没有问答记录",
    });
  },

  /** 读取与 AI 国学页面完全相同的今日个人结果，不在本页重复计算。 */
  async loadPersonalResultSummary() {
    try {
      const result = await getPersonalDailyGuidance();
      this.setData({
        personalResultSummary: `今日已生成 · 主色${result.primary_color} · ${result.precision_mode === "four_pillars" ? "完整四柱" : "三柱参考"}`,
      });
    } catch (error: unknown) {
      if (isApiError(error, 409)) {
        this.setData({ personalResultSummary: "完善生辰档案后生成今日个人五色" });
      } else if (isApiError(error, 403)) {
        this.setData({ personalResultSummary: "当前没有有效服务，个人五色未加载" });
      } else {
        this.setData({ personalResultSummary: "今日个人五色暂时无法读取" });
      }
    }
  },

  /** 清除页面里的个人状态，防止退出后仍看到上一账号的数据。 */
  resetLoggedOutState() {
    this.setData({
      isLoggedIn: false,
      dashboardLoading: false,
      phoneBound: false,
      phoneDisplay: "未绑定手机号",
      wechatPhoneAvailable: false,
      hasProfile: false,
      profileCompleteness: 0,
      profileSummary: "尚未创建档案 · 点击填写出生日期",
      serviceActive: false,
      answerReady: false,
      memberStatus: "尚未登录",
      serviceLabel: "服务状态",
      serviceTitle: "登录后查看AI国学服务",
      serviceCopy: "登录后读取真实权益与次数",
      serviceExpiry: "暂无有效期",
      serviceDaysLeft: 0,
      serviceProgress: 0,
      questionRemaining: 0,
      questionLimit: 0,
      comparisonRemaining: 0,
      comparisonLimit: 0,
      answerStatus: "尚未登录",
      aiHistory: [],
      historySummary: "登录后查看问答记录",
      personalResultSummary: "登录并完善档案后查看",
    });
  },

  /** 手机号按钮返回一次性 code，由后端调用微信接口换取号码。 */
  async bindPhone(event: WechatMiniprogram.ButtonGetPhoneNumber) {
    const code = event.detail.code;
    if (!code) {
      wx.showToast({ title: "你取消了手机号授权", icon: "none" });
      return;
    }
    try {
      this.applyAccount(await bindWechatPhone(code));
      wx.showToast({ title: "绑定成功" });
    } catch (error: unknown) {
      wx.showToast({
        title: getApiErrorMessage(error, "手机号能力尚未配置"),
        icon: "none",
        duration: 2600,
      });
    }
  },

  logout() {
    logoutLocalAccount();
    this.resetLoggedOutState();
  },

  toProfile() {
    wx.navigateTo({ url: "/pages/profile/index" });
  },

  toAi() {
    wx.switchTab({ url: "/pages/chat/index" });
  },

  /** 展示当前真实权益，不再显示尚不存在的30天服务卡和虚构有效期。 */
  showServiceDetails() {
    const content = this.data.serviceActive
      ? `${this.data.serviceExpiry}\n${this.data.serviceCopy}\n${this.data.answerStatus}`
      : `${this.data.serviceCopy}\n历史问答仍可在“AI国学”页面查看。`;
    wx.showModal({ title: this.data.serviceTitle, content, showCancel: false });
  },

  /** 当前数据库已经保存本人问答历史；弹窗只做轻量预览。 */
  showAIRecords() {
    const history = this.data.aiHistory as AIHistoryRecord[];
    if (!history.length) {
      wx.showModal({ title: "AI问答记录", content: "当前账号还没有问答记录。", showCancel: false });
      return;
    }
    const content = history
      .slice(0, 3)
      .map((item, index) => `${index + 1}. ${shortQuestion(item.question)}`)
      .join("\n");
    wx.showModal({
      title: "最近问答",
      content,
      confirmText: "进入AI国学",
      cancelText: "关闭",
      showCancel: true,
      success: (result) => {
        if (result.confirm) this.toAi();
      },
    });
  },

  openPersonalResult() {
    if (!this.data.hasProfile) {
      wx.showModal({
        title: "先完善生辰档案",
        content: "保存档案后，AI国学会读取同一份个人五色结果。",
        confirmText: "去填写",
        success: (result) => {
          if (result.confirm) this.toProfile();
        },
      });
      return;
    }
    this.toAi();
  },

  showPushPending() {
    wx.showModal({
      title: "每日五色提醒",
      content: "该功能尚未接入微信订阅消息。正式上线前会增加用户主动订阅、模板消息和发送记录。",
      showCancel: false,
    });
  },

  showHelp() {
    wx.showModal({
      title: "帮助与反馈",
      content: "后续将提供常见问题、在线反馈、回答纠错和服务联系入口。",
      showCancel: false,
    });
  },

  showPrivacy() {
    wx.showModal({
      title: "隐私与数据",
      content: "用户可以查看、修改和删除生辰档案，并可申请注销账号。个人资料和问答记录只按当前登录账号读取。",
      showCancel: false,
    });
  },

  showAbout() {
    wx.showModal({
      title: "关于五色知时",
      content: "五色应时，知时而行。内容仅供传统文化了解和生活参考。",
      showCancel: false,
    });
  },
});
