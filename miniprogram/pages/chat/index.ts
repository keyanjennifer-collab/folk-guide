import { getApiErrorMessage, getToken, isApiError } from "../../services/api";
import { productForElement } from "../../data/products";
import { isPublicRankingQuestion } from "../../data/confirmed-colors";
import {
  AIHistoryRecord,
  AIQuota,
  askAI,
  citationLabel,
  getAIHistory,
  AIConversation,
  getAIConversations,
  getAIConversation,
  deleteAIConversation,
  getAIQuota,
  submitAIFeedback,
} from "../../services/ai";
import { getPersonalDailyGuidance, PersonalDailyColor } from "../../services/daily";

type ChatItem = {
  role: "user" | "assistant";
  text: string;
  references: string[];
  feedback?: "helpful" | "unhelpful";
  messageId?: number;
  blocked?: boolean;
  safetyStatus?: "safe" | "blocked" | "output_filtered" | "output_truncated";
};

type PersonalColorView = PersonalDailyColor & { tone: string };

const PERSONAL_TONE_MAP: Record<string, string> = {
  "绿金": "green", "黑金": "black", "黄金": "gold", "白金": "white", "红金": "red",
};
const PERSONAL_COLOR_LABEL: Record<string, string> = {
  "绿金": "绿色系", "黑金": "黑色系", "黄金": "黄色系", "白金": "白色系", "红金": "红色系",
};

const WELCOME: ChatItem = {
  role: "assistant",
  text: "你好。你可以问我传统典籍、五行五色、历法时序以及相关文化问题。",
  references: [],
};
let chatLoadVersion = 0;
function historyDate(value: string): string { const date = new Date(/Z$|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`); return `${date.getMonth() + 1}月${date.getDate()}日`; }

function daysLeft(expiresAt: string | null): number {
  if (!expiresAt) return 0;
  // 数据库事件时间按UTC保存；兼容早期接口未在字符串末尾携带Z的情况，避免
  // 手机按本地时间误解后与“我的”页面显示出不同的剩余天数。
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(expiresAt);
  const milliseconds = new Date(hasTimezone ? expiresAt : `${expiresAt}Z`).getTime() - Date.now();
  return Math.max(Math.ceil(milliseconds / 86_400_000), 0);
}

function historyMessages(records: AIHistoryRecord[]): ChatItem[] {
  const messages: ChatItem[] = [];
  // 后端按最新优先返回；页面聊天顺序需要从旧到新。
  [...records].reverse().forEach((record) => {
    messages.push({ role: "user", text: record.question, references: [] });
    messages.push({
      role: "assistant",
      text: record.answer,
      references: record.citations.map(citationLabel),
      feedback: record.feedback || undefined,
      messageId: record.id,
      safetyStatus: record.safety_status,
    });
  });
  return messages.length ? messages : [WELCOME];
}

Page({
  data: {
    isLoggedIn: false,
    activeGroup: 0,
    personalOpen: false,
    inputFocus: false,
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
    personalStatusCopy: "有效时序文化体验或服务期内，可按生辰档案查看个人五色。",
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
    historyOpen: false,
    history: [] as Array<AIHistoryRecord & { dateLabel: string }>,
    conversations: [] as AIConversation[],
    historyDetailId: 0,
    historyDetailMessages: [] as ChatItem[],
    currentConversationId: 0,
    draftMessages: [WELCOME] as ChatItem[],
    draftConversationId: 0,
  },

  async onShow() {
    (this as any).getTabBar?.()?.setData({ selected: 2 });
    const loadVersion = ++chatLoadVersion;
    if (!getToken()) {
      this.setData({ isLoggedIn: false, loading: false, serviceActive: false, answerReady: false,
        serviceTitle: "登录后开启国学对话", serviceCopy: "保存问答记录，查看个人五色",
        messages: [WELCOME], personalState: "locked", personalColors: [],
        remainingQuestions: 0, dailyLimit: 0, personalOpen: false, sending: false });
      return;
    }
    this.setData({ isLoggedIn: true });
    this.setData({ loading: true });
    try {
      const [quota, history, conversationPage] = await Promise.all([getAIQuota(), getAIHistory(20), getAIConversations()]);
      const conversations = conversationPage.items;
      if (loadVersion !== chatLoadVersion || !getToken()) return;
      this.applyQuota(quota);
      // 每次进入页面都从新对话开始；历史会话只在用户点击“历史记录”后打开。
      this.setData({ messages: [WELCOME], history: history.map(item => ({ ...item, dateLabel: historyDate(item.created_at) })), conversations, currentConversationId: 0, historyOpen: false });
      // 先确认权益，再决定是否请求个人接口；无权益时不加载生辰计算结果。
      if (quota.active) await this.loadPersonalDaily();
      else this.setData({
        personalState: "locked",
        personalStatusCopy: "当前没有有效时序文化体验或服务权益，个人五色未加载。",
        personalColors: [],
      });
      this.setData({ loading: false });
    } catch (error: unknown) {
      if (loadVersion !== chatLoadVersion) return;
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

  onHide() { chatLoadVersion++; },
  onUnload() { chatLoadVersion++; },

  applyQuota(quota: AIQuota) {
    const remainingDays = daysLeft(quota.expires_at);
    let serviceTitle = "时序文化服务尚未开通";
    if (quota.plan === "new_user_3_days") serviceTitle = "新客3天体验";
    else if (quota.active) serviceTitle = "时序文化个人服务使用中";
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
    const token = getToken();
    this.setData({ personalState: "loading", personalStatusCopy: "正在按本人档案计算今日五色…" });
    try {
      const result = await getPersonalDailyGuidance();
      if (getToken() !== token) return;
      this.setData({
        personalState: "ready",
        personalStatusCopy: "今日个人五色已按档案与北京时间时序生成。",
        personalDate: result.date,
        personalPrecision: result.precision_mode === "four_pillars" ? "完整四柱" : "三柱参考",
        personalColors: result.colors.map((item) => {
          const product = productForElement(item.element);
          return { ...item, name: PERSONAL_COLOR_LABEL[item.name] || item.name, incense: product?.name || item.incense, scent: product?.scent || item.scent, tone: PERSONAL_TONE_MAP[item.name] || "" };
        }),
        expandedPersonalRank: 1,
        personalPrimaryColor: PERSONAL_COLOR_LABEL[result.primary_color] || result.primary_color,
        personalSupportingColors: result.supporting_colors.map(color => PERSONAL_COLOR_LABEL[color] || color).join("、"),
        personalCombinationAdvice: result.combination_advice,
        personalFocus: result.personal_focus,
        personalComparisonNote: result.comparison_note,
        personalReminders: result.reminders,
        personalSuitable: result.suitable.join("、"),
        personalCultureNote: result.culture_note,
      });
    } catch (error: unknown) {
      if (getToken() !== token) return;
      if (isApiError(error, 409)) {
        this.setData({
          personalState: "missing",
          personalStatusCopy: "时序文化体验可用，完善生辰档案后即可生成个人五色。",
          personalColors: [],
        });
      } else if (isApiError(error, 403)) {
        this.setData({
          personalState: "locked",
          personalStatusCopy: "当前没有有效时序文化体验或服务权益，个人五色未加载。",
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

  toLogin() { wx.switchTab({ url: "/pages/settings/index" }); },
  chooseGroup(event: WechatMiniprogram.TouchEvent) { this.setData({ activeGroup: Number(event.currentTarget.dataset.index) }); },
  togglePersonal() { this.setData({ personalOpen: !this.data.personalOpen }); },
  toggleHistory() { this.setData({ historyOpen: !this.data.historyOpen }); },
  newConversation() {
    // 空白新对话不写入数据库；保留当前会话，用户可通过“当前对话”返回。
    const hasCurrent = this.data.currentConversationId || this.data.messages.length > 1;
    this.setData({
      messages: [WELCOME], question: "", historyOpen: false, historyDetailId: 0, historyDetailMessages: [],
      currentConversationId: 0,
      ...(hasCurrent ? { draftMessages: this.data.messages, draftConversationId: this.data.currentConversationId } : {}),
    });
    wx.pageScrollTo({ scrollTop: 0, duration: 200 });
  },
  openHistory(event: WechatMiniprogram.TouchEvent) {
    const id = Number(event.currentTarget.dataset.id);
    const record = this.data.history.find(item => item.id === id);
    if (!record) return;
    this.setData({ messages: historyMessages([record]), historyOpen: false });
    wx.nextTick(() => wx.pageScrollTo({ selector: "#conversationEnd", duration: 200 }));
  },
  async openConversation(event: WechatMiniprogram.TouchEvent) {
    const id = Number(event.currentTarget.dataset.id);
    if (!id) return;
    if (this.data.historyDetailId === id) {
      this.setData({ historyDetailId: 0, historyDetailMessages: [] });
      return;
    }
    try {
      const detail = await getAIConversation(id);
      this.setData({ historyDetailId: id, historyDetailMessages: historyMessages(detail.messages) });
    } catch (_) { wx.showToast({ title: "历史对话读取失败", icon: "none" }); }
  },
  continueConversation() {
    const id = Number(this.data.historyDetailId);
    if (!id) return;
    this.setData({ draftMessages: this.data.messages, draftConversationId: this.data.currentConversationId, currentConversationId: id, messages: this.data.historyDetailMessages, historyOpen: false, historyDetailId: 0, historyDetailMessages: [] });
    wx.nextTick(() => wx.pageScrollTo({ selector: "#conversationEnd", duration: 200 }));
  },
  returnCurrentConversation() {
    this.setData({ messages: this.data.draftMessages, currentConversationId: this.data.draftConversationId, historyOpen: false, historyDetailId: 0, historyDetailMessages: [] });
    wx.nextTick(() => wx.pageScrollTo({ selector: "#conversationEnd", duration: 200 }));
  },
  async deleteConversation(event: WechatMiniprogram.TouchEvent) {
    const id = Number(event.currentTarget.dataset.id);
    if (!id) return;
    wx.showModal({ title: "删除这段对话？", content: "删除后问题、回答和引用都会移除，已用次数不会恢复。", confirmText: "删除", success: async result => {
      if (!result.confirm) return;
      try {
        await deleteAIConversation(id);
        const conversations = this.data.conversations.filter(item => item.id !== id);
        this.setData({ conversations, historyOpen: true, ...(this.data.currentConversationId === id ? { currentConversationId: 0, messages: [WELCOME] } : {}) });
      } catch (_) { wx.showToast({ title: "删除失败，请稍后重试", icon: "none" }); }
    } });
  },

  chooseQuestion(event: WechatMiniprogram.TouchEvent) {
    const question = String(event.currentTarget.dataset.question || "");
    this.setData({ question, inputFocus: true });
  },

  send() {
    this.sendQuestion(this.data.question.trim());
  },

  async sendQuestion(question: string) {
    if (!question || this.data.sending) return;
    if (isPublicRankingQuestion(question)) {
      wx.showModal({ title: "今日色序说明", content: "首页五色由确定性历法规则每日自动更新，不由 AI 临时编排。内容用于传统文化学习与日常观察，完整排行和行动建议请回到首页查看。", confirmText: "查看五色", success: result => { if (result.confirm) wx.switchTab({ url: "/pages/home/index" }); } });
      return;
    }
    if (!getToken()) { this.toLogin(); return; }
    if (!this.data.serviceActive) {
      wx.showModal({ title: "问答服务未开通", content: "当前没有可用的时序文化体验或服务权益。", showCancel: false });
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

    const pendingMessages: ChatItem[] = [...this.data.messages, { role: "user", text: question, references: [] }];
    this.setData({ sending: true, question: "", messages: pendingMessages });
    wx.nextTick(() => wx.pageScrollTo({ selector: "#conversationEnd", duration: 250 }));
    const tokenAtSend = getToken();
    try {
      const result = await askAI(question, comparison ? "seven_day_comparison" : "normal", this.data.currentConversationId || undefined);
      if (getToken() !== tokenAtSend) { this.setData({ sending: false, messages: [WELCOME] }); return; }
      const assistant: ChatItem = {
        role: "assistant",
        text: result.answer,
        references: result.citations.map(citationLabel),
        messageId: result.message_id,
        blocked: result.blocked,
        safetyStatus: result.safety_status,
      };
      const quotaField = comparison ? "remainingComparisons" : "remainingQuestions";
      const conversationId = result.conversation_id || this.data.currentConversationId;
      const existing = this.data.conversations.find(item => item.id === conversationId);
      const conversations = existing
        ? this.data.conversations.map(item => item.id === conversationId ? { ...item, message_count: item.message_count + 1, updated_at: new Date().toISOString(), title: item.title === "新对话" ? question.slice(0, 200) : item.title } : item)
        : conversationId ? [{ id: conversationId, title: question.slice(0, 200), message_count: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), archived: false }, ...this.data.conversations] : this.data.conversations;
      this.setData({
        sending: false,
        messages: [...pendingMessages, assistant],
        [quotaField]: result.remaining_today,
        currentConversationId: conversationId,
        conversations,
      });
      wx.nextTick(() => wx.pageScrollTo({ selector: "#conversationEnd", duration: 250 }));
    } catch (error: unknown) {
      this.setData({ sending: false, question });
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
      content: "可询问传统典籍、五行五色与历法时序，问答权益以当前账号显示为准。个人五色需先完善本人档案。回答仅作文化学习和生活参考，保留自己的判断。",
      showCancel: false,
    });
  },
});
