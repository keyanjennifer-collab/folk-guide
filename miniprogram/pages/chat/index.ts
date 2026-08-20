import { getApiErrorMessage, isApiError } from "../../services/api";
import {
  AIHistoryRecord,
  AIQuota,
  askAI,
  citationLabel,
  getAIHistory,
  getAIQuota,
  submitAIFeedback,
} from "../../services/ai";
import { getPersonalDailyGuidance, PersonalDailyColor } from "../../services/daily";

type ChatItem = {
  role: "user" | "assistant";
  text: string;
  references?: string[];
  feedback?: "helpful" | "unhelpful";
  messageId?: number;
  blocked?: boolean;
};

type PersonalColorView = PersonalDailyColor & { tone: string };

const PERSONAL_TONE_MAP: Record<string, string> = {
  "绿金": "green", "黑金": "black", "黄金": "gold", "白金": "white", "红金": "red",
};

const WELCOME: ChatItem = {
  role: "assistant",
  text: "你好。你可以问我传统典籍、五行五色、历法时序以及相关文化问题。",
};

function daysLeft(expiresAt: string | null): number {
  if (!expiresAt) return 0;
  const milliseconds = new Date(expiresAt).getTime() - Date.now();
  return Math.max(Math.ceil(milliseconds / 86_400_000), 0);
}

function historyMessages(records: AIHistoryRecord[]): ChatItem[] {
  const messages: ChatItem[] = [];
  // 后端按最新优先返回；页面聊天顺序需要从旧到新。
  [...records].reverse().forEach((record) => {
    messages.push({ role: "user", text: record.question });
    messages.push({
      role: "assistant",
      text: record.answer,
      references: record.citations.map(citationLabel),
      feedback: record.feedback || undefined,
      messageId: record.id,
    });
  });
  return messages.length ? messages : [WELCOME];
}

Page({
  data: {
    loading: true,
    serviceActive: false,
    answerReady: false,
    serviceTitle: "正在读取服务状态",
    serviceCopy: "请稍候",
    answerStatus: "问答服务状态读取中",
    trialDaysLeft: 0,
    dailyLimit: 0,
    remainingQuestions: 0,
    comparisonLimit: 0,
    remainingComparisons: 0,
    personalState: "locked" as "locked" | "loading" | "missing" | "ready" | "error",
    personalStatusCopy: "有效AI国学体验或服务期内，可按生辰档案查看个人五色。",
    personalDate: "",
    personalPrecision: "",
    personalColors: [] as PersonalColorView[],
    expandedPersonalRank: 1,
    personalPrimaryColor: "",
    personalSupportingColors: "",
    personalCombinationAdvice: "",
    personalFocus: "",
    personalComparisonNote: "",
    personalReminders: [] as string[],
    personalSuitable: "",
    personalCultureNote: "",
    question: "",
    sending: false,
    questions: [
      { group: "易学入门", items: ["《周易》主要讲什么？", "阴阳与八卦是什么关系？", "如何理解《易经》中的变？"] },
      { group: "五行五色", items: ["五行相生相克是什么意思？", "传统文化中五行怎样对应五色？", "《五行大义》如何讨论五行？"] },
      { group: "历法时序", items: ["天干地支的基本结构是什么？", "二十四节气有什么文化意义？", "《协纪辨方书》属于哪类典籍？"] },
      { group: "典籍阅读", items: ["《滴天髓》和《子平真诠》有什么区别？", "如何阅读《黄帝内经》的五行内容？", "不同传统术数流派为什么会有差异？"] },
    ],
    messages: [WELCOME] as ChatItem[],
  },

  async onShow() {
    this.setData({ loading: true });
    try {
      const [quota, history] = await Promise.all([getAIQuota(), getAIHistory(20)]);
      this.applyQuota(quota);
      this.setData({ messages: historyMessages(history) });
      // 先确认权益，再决定是否请求个人接口；无权益时不加载生辰计算结果。
      if (quota.active) await this.loadPersonalDaily();
      else this.setData({
        personalState: "locked",
        personalStatusCopy: "当前没有有效AI国学体验或服务权益，个人五色未加载。",
        personalColors: [],
      });
      this.setData({ loading: false });
    } catch (error: unknown) {
      this.setData({
        loading: false,
        serviceActive: false,
        serviceTitle: "问答服务暂时无法读取",
        serviceCopy: getApiErrorMessage(error, "请检查登录和后端服务"),
        personalState: "error",
        personalStatusCopy: "个人五色服务状态暂时无法读取。",
      });
    }
  },

  applyQuota(quota: AIQuota) {
    const remainingDays = daysLeft(quota.expires_at);
    let serviceTitle = "AI国学服务尚未开通";
    if (quota.plan === "new_user_3_days") serviceTitle = "新客3天体验";
    else if (quota.active) serviceTitle = "AI国学个人服务使用中";
    const serviceCopy = quota.active
      ? `剩余${remainingDays}天；普通问答与七日比较分别计算次数`
      : "当前权益已结束，历史回答仍可查看";
    this.setData({
      serviceActive: quota.active,
      answerReady: quota.answer_ready,
      serviceTitle,
      serviceCopy,
      answerStatus: quota.answer_ready ? "问答服务已就绪" : "问答服务准备中",
      trialDaysLeft: remainingDays,
      dailyLimit: quota.normal_limit,
      remainingQuestions: quota.normal_remaining,
      comparisonLimit: quota.comparison_limit,
      remainingComparisons: quota.comparison_remaining,
    });
  },

  async loadPersonalDaily() {
    this.setData({ personalState: "loading", personalStatusCopy: "正在按本人档案计算今日五色…" });
    try {
      const result = await getPersonalDailyGuidance();
      this.setData({
        personalState: "ready",
        personalStatusCopy: "今日个人五色已按档案与北京时间时序生成。",
        personalDate: result.date,
        personalPrecision: result.precision_mode === "four_pillars" ? "完整四柱" : "三柱参考",
        personalColors: result.colors.map((item) => ({ ...item, tone: PERSONAL_TONE_MAP[item.name] || "" })),
        expandedPersonalRank: 1,
        personalPrimaryColor: result.primary_color,
        personalSupportingColors: result.supporting_colors.join("、"),
        personalCombinationAdvice: result.combination_advice,
        personalFocus: result.personal_focus,
        personalComparisonNote: result.comparison_note,
        personalReminders: result.reminders,
        personalSuitable: result.suitable.join("、"),
        personalCultureNote: result.culture_note,
      });
    } catch (error: unknown) {
      if (isApiError(error, 409)) {
        this.setData({
          personalState: "missing",
          personalStatusCopy: "AI国学体验可用，完善生辰档案后即可生成个人五色。",
          personalColors: [],
        });
      } else if (isApiError(error, 403)) {
        this.setData({
          personalState: "locked",
          personalStatusCopy: "当前没有有效AI国学体验或服务权益，个人五色未加载。",
          personalColors: [],
        });
      } else {
        this.setData({
          personalState: "error",
          personalStatusCopy: getApiErrorMessage(error, "个人五色暂时无法读取，请稍后重试"),
          personalColors: [],
        });
      }
    }
  },

  togglePersonalColor(event: WechatMiniprogram.TouchEvent) {
    const rank = Number(event.currentTarget.dataset.rank);
    this.setData({ expandedPersonalRank: this.data.expandedPersonalRank === rank ? 0 : rank });
  },

  toProfile() {
    wx.navigateTo({ url: "/pages/profile/index" });
  },

  toIncense() {
    wx.switchTab({ url: "/pages/caikuxiang/index" });
  },

  setQuestion(event: WechatMiniprogram.Input) {
    this.setData({ question: event.detail.value });
  },

  chooseQuestion(event: WechatMiniprogram.TouchEvent) {
    const question = String(event.currentTarget.dataset.question || "");
    this.setData({ question });
    this.sendQuestion(question);
  },

  send() {
    this.sendQuestion(this.data.question.trim());
  },

  async sendQuestion(question: string) {
    if (!question || this.data.sending) return;
    if (!this.data.serviceActive) {
      wx.showModal({ title: "问答服务未开通", content: "当前没有可用的AI国学体验或服务权益。", showCancel: false });
      return;
    }
    if (!this.data.answerReady) {
      wx.showModal({ title: "问答服务准备中", content: "服务暂时还没有准备好，请稍后再试。", showCancel: false });
      return;
    }
    const comparison = /七日|7日|七天|未来一周|一周比较/.test(question);
    if (comparison ? this.data.remainingComparisons <= 0 : this.data.remainingQuestions <= 0) {
      wx.showModal({ title: "今日次数已用完", content: "次数将在下一个自然日恢复。历史回答仍可查看。", showCancel: false });
      return;
    }

    const pendingMessages: ChatItem[] = [...this.data.messages, { role: "user", text: question }];
    this.setData({ sending: true, question: "", messages: pendingMessages });
    try {
      const result = await askAI(question, comparison ? "seven_day_comparison" : "normal");
      const assistant: ChatItem = {
        role: "assistant",
        text: result.answer,
        references: result.citations.map(citationLabel),
        messageId: result.message_id,
        blocked: result.blocked,
      };
      const quotaField = comparison ? "remainingComparisons" : "remainingQuestions";
      this.setData({
        sending: false,
        messages: [...pendingMessages, assistant],
        [quotaField]: result.remaining_today,
      });
    } catch (error: unknown) {
      this.setData({ sending: false });
      if (isApiError(error, 429)) {
        wx.showModal({ title: "今日次数已用完", content: error.message, showCancel: false });
      } else if (isApiError(error, 403)) {
        wx.showModal({ title: "问答服务不可用", content: error.message, showCancel: false });
      } else {
        wx.showToast({ title: getApiErrorMessage(error, "本次回答失败，请稍后重试"), icon: "none", duration: 2800 });
      }
    }
  },

  async feedback(event: WechatMiniprogram.TouchEvent) {
    const index = Number(event.currentTarget.dataset.index);
    const messageId = Number(event.currentTarget.dataset.messageId);
    const value = event.currentTarget.dataset.value as "helpful" | "unhelpful";
    if (!messageId) return;
    try {
      await submitAIFeedback(messageId, value);
      const key = `messages[${index}].feedback`;
      this.setData({ [key]: value });
      wx.showToast({ title: value === "helpful" ? "感谢反馈" : "已提交纠错", icon: "none" });
    } catch (error: unknown) {
      wx.showToast({ title: getApiErrorMessage(error, "反馈提交失败"), icon: "none" });
    }
  },

  showRules() {
    wx.showModal({
      title: "服务与回答范围",
      content: "新用户赠送3天体验，每日20次普通问答、2次七日比较。内容用于传统文化学习和生活参考，不提供医疗、投资、灾祸或确定命运的结论。",
      showCancel: false,
    });
  },
});
