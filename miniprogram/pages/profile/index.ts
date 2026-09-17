import { getTheme, AppTheme } from "../../services/theme";
import { ensureLogin, getApiErrorMessage, showApiError } from "../../services/api";
import {
  CalendarResult,
  CalendarType,
  deleteCurrentProfile,
  Gender,
  getCurrentProfile,
  isProfileMissing,
  ProfileInput,
  ProfileResponse,
  ProfileResultMode,
  saveCurrentProfile,
} from "../../services/profile";

Page({
  data: { themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    loading: true,
    loadFailed: false,
    loadError: "",
    saving: false,
    deleting: false,
    hasProfile: false,
    calendarType: "solar" as CalendarType,
    isLeapMonth: false,
    birthDate: "",
    timeKnown: false,
    birthTime: "",
    // 原生 region picker 提供省 / 市 / 区县三级联动，birthAddress 是最终保存、展示的完整地址。
    birthRegion: [] as string[],
    birthAddress: "",
    birthDetailAddress: "",
    // 旧档案只有一段 birth_city 文本；未重新选择地区前保存时必须原样保留，不能丢失旧资料。
    birthAddressEdited: false,
    gender: "unspecified" as Gender,
    timezone: "Asia/Shanghai",
    completeness: 50,
    completenessIsPreview: true,
    resultMode: "simplified" as ProfileResultMode,
    privacyAgreed: false,
    calendar: null as CalendarResult | null,
  },

  /**
   * 第21项链路：进入页面后先完成微信登录，再读取当前账号档案。
   * 明确拆成两个await，可以保证GET /api/profiles/current发出前已经取得JWT；后续401
   * 仍由统一请求层自动重新登录并重试一次。
   */
  async onLoad() {
    try {
      await ensureLogin();
    } catch (error: unknown) {
      this.setData({ loading: false, loadFailed: true, loadError: getApiErrorMessage(error, "微信登录失败，请稍后重试") });
      showApiError(error, "微信登录失败，请稍后重试");
      return;
    }
    await this.loadProfile();
  },

  /**
   * 首次进入和用户点击“重新加载”共用同一条读取链路。
   * 非404错误会锁住编辑表单，避免网络故障时把已有档案误当空档案覆盖。
   */
  async loadProfile() {
    this.setData({ loading: true, loadFailed: false, loadError: "" });
    try {
      this.applyProfile(await getCurrentProfile());
    } catch (error: unknown) {
      // 404是正常的“第一次创建”状态，不应该提示成系统故障。
      if (isProfileMissing(error)) this.resetEmptyProfile();
      else {
        this.setData({ loadFailed: true, loadError: getApiErrorMessage(error, "档案加载失败，请稍后重试") });
        showApiError(error, "档案加载失败，请稍后重试");
      }
    } finally {
      this.setData({ loading: false });
    }
  },

  retryLoad() {
    void this.loadProfile();
  },

  /** 将后端返回值一次性同步到表单和历法结果区，避免保存与读取使用两套赋值逻辑。 */
  applyProfile(profile: ProfileResponse) {
    this.setData({
      hasProfile: true,
      calendarType: profile.calendar_type,
      isLeapMonth: profile.is_leap_month,
      birthDate: profile.birth_date,
      timeKnown: profile.time_known,
      birthTime: profile.birth_time || "",
      birthRegion: [],
      birthAddress: profile.birth_city || "",
      birthDetailAddress: "",
      birthAddressEdited: false,
      gender: profile.gender,
      timezone: profile.timezone,
      completeness: profile.completeness,
      // 保存或读取成功后，这两个值以Python后端计算结果为准，不再显示为本地预览。
      completenessIsPreview: false,
      resultMode: profile.result_mode,
      calendar: profile.calendar,
      privacyAgreed: true,
    });
  },

  /** 删除档案或首次使用时恢复安全的空表单，不保留上一位用户的数据。 */
  resetEmptyProfile() {
    this.setData({
      hasProfile: false,
      calendarType: "solar",
      isLeapMonth: false,
      birthDate: "",
      timeKnown: false,
      birthTime: "",
      birthRegion: [],
      birthAddress: "",
      birthDetailAddress: "",
      birthAddressEdited: false,
      gender: "unspecified",
      timezone: "Asia/Shanghai",
      completeness: 50,
      completenessIsPreview: true,
      resultMode: "simplified",
      privacyAgreed: false,
      calendar: null,
    });
  },

  setCalendar(event: WechatMiniprogram.TouchEvent) {
    const calendarType = event.currentTarget.dataset.type as CalendarType;
    this.setData({ calendarType, isLeapMonth: calendarType === "lunar" ? this.data.isLeapMonth : false });
  },
  setLeapMonth(event: WechatMiniprogram.SwitchChange) { this.setData({ isLeapMonth: event.detail.value }); },
  setDate(event: WechatMiniprogram.PickerChange) { this.setData({ birthDate: String(event.detail.value) }); },
  setTimeKnown(event: WechatMiniprogram.SwitchChange) {
    const timeKnown = event.detail.value;
    this.setData({ timeKnown, birthTime: timeKnown ? (this.data.birthTime || "12:00") : "" });
    this.updateLocalCompleteness();
  },
  setTime(event: WechatMiniprogram.PickerChange) {
    this.setData({ birthTime: String(event.detail.value), timeKnown: true });
    this.updateLocalCompleteness();
  },
  setBirthRegion(event: WechatMiniprogram.PickerChange) {
    const birthRegion = (event.detail.value as string[]).map((item) => String(item));
    this.setData({ birthRegion, birthAddress: birthRegion.join(""), birthAddressEdited: true });
    this.updateLocalCompleteness();
  },
  setBirthDetailAddress(event: WechatMiniprogram.Input) {
    this.setData({ birthDetailAddress: event.detail.value, birthAddressEdited: true });
    this.updateLocalCompleteness();
  },
  setGender(event: WechatMiniprogram.TouchEvent) {
    this.setData({ gender: event.currentTarget.dataset.gender as Gender });
    this.updateLocalCompleteness();
  },
  togglePrivacy(event: WechatMiniprogram.CheckboxGroupChange) {
    this.setData({ privacyAgreed: event.detail.value.includes("agreed") });
  },
  showPrivacy() {
    wx.showModal({
      title: "生辰档案使用说明",
      content: "出生信息仅用于传统历法计算及个人文化参考。出生地点可选择省、市、区县并补充详细地址；资料可随时修改或删除，默认不用于模型训练和广告画像。",
      showCancel: false,
    });
  },
  /**
   * 只根据当前页面data预览完整度和结果模式。
   * 本函数不调用API、不写本地缓存，也不把预览值放进保存请求；保存成功后必须由
   * applyProfile使用后端返回的completeness和result_mode覆盖。
   */
  getBirthAddress(): string | null {
    // 为避免编辑其他字段时覆盖旧版本只保存城市的档案，只有用户触碰地址控件后才重新拼接。
    if (!this.data.birthAddressEdited) return this.data.birthAddress.trim() || null;
    return `${this.data.birthRegion.join("")}${this.data.birthDetailAddress.trim()}` || null;
  },
  updateLocalCompleteness() {
    let completeness = 50;
    if (this.data.timeKnown && this.data.birthTime) completeness += 25;
    if (this.getBirthAddress()) completeness += 15;
    if (this.data.gender !== "unspecified") completeness += 10;
    this.setData({
      completeness,
      completenessIsPreview: true,
      resultMode: this.data.timeKnown && !!this.data.birthTime ? "full" : "simplified",
    });
  },
  async save() {
    // 第23项：按钮已经禁用时再做一次函数级防重，避免快速点击产生两个PUT请求。
    if (this.data.saving) return;
    // 日期和隐私同意是提交前置条件；出生时辰开启后也必须填写完整。
    if (!this.data.birthDate) return wx.showToast({ title: "请选择出生日期", icon: "none" });
    if (!this.data.privacyAgreed) return wx.showToast({ title: "请先阅读并同意资料使用说明", icon: "none" });
    if (this.data.timeKnown && !this.data.birthTime) return wx.showToast({ title: "请选择出生时间，或关闭时辰开关", icon: "none" });
    this.setData({ saving: true });
    try {
      const input: ProfileInput = {
        calendar_type: this.data.calendarType,
        is_leap_month: this.data.calendarType === "lunar" && this.data.isLeapMonth,
        birth_date: this.data.birthDate,
        time_known: this.data.timeKnown,
        birth_time: this.data.timeKnown ? this.data.birthTime : null,
        // 后端沿用 birth_city 字段名以兼容已有档案；内容为省、市、区/县和详细地址的拼接结果。
        birth_city: this.getBirthAddress(),
        gender: this.data.gender,
        timezone: "Asia/Shanghai",
      };
      // saveCurrentProfile固定使用PUT /api/profiles/current；完整度和历法结果由后端返回。
      const profile = await saveCurrentProfile(input);
      this.applyProfile(profile);
      wx.showToast({ title: "档案已保存" });
    } catch (_) {
      // saveCurrentProfile已通过统一请求层显示后端的中文错误，这里只负责恢复按钮状态。
    } finally {
      this.setData({ saving: false });
    }
  },
  async deleteProfile() {
    if (this.data.deleting) return;
    const result = await wx.showModal({ title: "删除生辰档案", content: "档案及基于旧资料生成的个人缓存将被删除，此操作无法恢复。", confirmText: "确认删除", confirmColor: "#a94b42" });
    if (!result.confirm) return;
    this.setData({ deleting: true });
    try {
      await deleteCurrentProfile();
      this.resetEmptyProfile();
      wx.showToast({ title: "档案已删除" });
    } catch (_) {
      // deleteCurrentProfile已经统一显示错误。
    } finally {
      this.setData({ deleting: false });
    }
  },
});

