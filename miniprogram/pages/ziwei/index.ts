import { ensureLogin, getApiErrorMessage } from "../../services/api";
import { getTheme, AppTheme } from "../../services/theme";
import { deleteZiweiChart, deleteZiweiCompatibility, getZiweiCharts, getZiweiCompatibilities, saveZiweiChart, saveZiweiCompatibility, ZiweiBirthInput, ZiweiCompatibilityRecord, ZiweiChartRecord, ZiweiGender, ZiweiRelationType } from "../../services/ziwei";

type BirthForm = { label: string; name: string; birthDate: string; calendarType: "solar" | "lunar"; isLeapMonth: boolean; birthTime: string; gender: ZiweiGender; birthRegion: string[]; birthAddress: string; birthDetailAddress: string };
const emptyForm = (label: string): BirthForm => ({ label, name: "", birthDate: "", calendarType: "solar", isLeapMonth: false, birthTime: "12:00", gender: "male", birthRegion: [], birthAddress: "", birthDetailAddress: "" });

function toInput(form: BirthForm): ZiweiBirthInput {
  return { label: form.label.trim() || "未命名命盘", name: form.name.trim() || null, birth_date: form.birthDate,
    calendar_type: form.calendarType, is_leap_month: form.calendarType === "lunar" && form.isLeapMonth,
    birth_time: form.birthTime, gender: form.gender, birth_location: `${form.birthRegion.join("")}${form.birthDetailAddress.trim()}` || null };
}

Page({
  data: {
    themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    loading: true, saving: false, mode: "chart" as "chart" | "compatibility",
    chartForm: emptyForm("我的命盘"), personA: emptyForm("第一位"), personB: emptyForm("第二位"),
    relationType: "business" as ZiweiRelationType,
    relations: [{ id: "business", label: "生意合伙" }, { id: "love", label: "姻缘感情" }, { id: "family", label: "家庭亲子" }, { id: "friend", label: "朋友协作" }],
    savedCharts: [] as ZiweiChartRecord[], savedCompatibilities: [] as ZiweiCompatibilityRecord[],
  },
  async onLoad(options: Record<string, string>) {
    if (options.mode === "compatibility") this.setData({ mode: "compatibility" });
    try { await ensureLogin(); await this.loadRecords(); }
    catch (error: unknown) { wx.showToast({ title: getApiErrorMessage(error, "请先登录后使用紫微功能"), icon: "none" }); }
    finally { this.setData({ loading: false }); }
  },
  onShow() {
    if (!this.data.loading) void this.loadRecords();
  },
  async loadRecords() {
    const [savedCharts, savedCompatibilities] = await Promise.all([getZiweiCharts(), getZiweiCompatibilities()]);
    this.setData({ savedCharts, savedCompatibilities });
  },
  setMode(event: WechatMiniprogram.TouchEvent) { this.setData({ mode: event.currentTarget.dataset.mode }); },
  setFormInput(event: WechatMiniprogram.Input) {
    const person = event.currentTarget.dataset.person as "chartForm" | "personA" | "personB";
    const field = event.currentTarget.dataset.field as keyof BirthForm;
    this.setData({ [`${person}.${field}`]: event.detail.value });
  },
  setFormPicker(event: WechatMiniprogram.PickerChange) {
    const person = event.currentTarget.dataset.person as "chartForm" | "personA" | "personB";
    const field = event.currentTarget.dataset.field as keyof BirthForm;
    this.setData({ [`${person}.${field}`]: String(event.detail.value) });
  },
  setGender(event: WechatMiniprogram.TouchEvent) {
    const person = event.currentTarget.dataset.person as "chartForm" | "personA" | "personB";
    this.setData({ [`${person}.gender`]: event.currentTarget.dataset.gender as ZiweiGender });
  },
  setCalendar(event: WechatMiniprogram.TouchEvent) {
    const person = event.currentTarget.dataset.person as "chartForm" | "personA" | "personB";
    const calendarType = event.currentTarget.dataset.calendar as "solar" | "lunar";
    this.setData({ [`${person}.calendarType`]: calendarType, [`${person}.isLeapMonth`]: calendarType === "lunar" ? this.data[person].isLeapMonth : false });
  },
  setLeapMonth(event: WechatMiniprogram.SwitchChange) {
    const person = event.currentTarget.dataset.person as "chartForm" | "personA" | "personB";
    this.setData({ [`${person}.isLeapMonth`]: event.detail.value });
  },
  setBirthRegion(event: WechatMiniprogram.PickerChange) {
    const person = event.currentTarget.dataset.person as "chartForm" | "personA" | "personB";
    const birthRegion = (event.detail.value as string[]).map(value => String(value));
    this.setData({ [`${person}.birthRegion`]: birthRegion, [`${person}.birthAddress`]: birthRegion.join("") });
  },
  setRelation(event: WechatMiniprogram.TouchEvent) { this.setData({ relationType: event.currentTarget.dataset.relation as ZiweiRelationType }); },
  valid(form: BirthForm): boolean {
    if (!form.birthDate) { wx.showToast({ title: "请选择出生年月日", icon: "none" }); return false; }
    if (!form.birthTime) { wx.showToast({ title: "请选择具体出生时间", icon: "none" }); return false; }
    return true;
  },
  async createChart() {
    if (this.data.saving || !this.valid(this.data.chartForm)) return;
    this.setData({ saving: true });
    try {
      const chartResult = await saveZiweiChart(toInput(this.data.chartForm));
      // 结果已经交给独立结果页，当前起盘页只保留历史列表，避免返回后重复显示旧结果。
      this.setData({ savedCharts: [chartResult, ...this.data.savedCharts] });
      wx.navigateTo({ url: `/pages/ziwei/result?id=${chartResult.id}` });
      wx.showToast({ title: "命盘已保存" });
    } catch (error: unknown) { wx.showToast({ title: getApiErrorMessage(error, "起盘失败，请检查出生信息"), icon: "none" }); }
    finally { this.setData({ saving: false }); }
  },
  async createCompatibility() {
    if (this.data.saving || !this.valid(this.data.personA) || !this.valid(this.data.personB)) return;
    this.setData({ saving: true });
    try {
      const compatibilityResult = await saveZiweiCompatibility({ relation_type: this.data.relationType, person_a: toInput(this.data.personA), person_b: toInput(this.data.personB) });
      this.setData({ savedCompatibilities: [compatibilityResult, ...this.data.savedCompatibilities] });
      wx.navigateTo({ url: `/pages/ziwei/compatibility-result?id=${compatibilityResult.id}` });
      wx.showToast({ title: "合盘已保存" });
    } catch (error: unknown) { wx.showToast({ title: getApiErrorMessage(error, "合盘失败，请检查双方出生信息"), icon: "none" }); }
    finally { this.setData({ saving: false }); }
  },
  showChart(event: WechatMiniprogram.TouchEvent) {
    const chartResult = this.data.savedCharts.find(item => item.id === Number(event.currentTarget.dataset.id));
    if (chartResult) wx.navigateTo({ url: `/pages/ziwei/result?id=${chartResult.id}` });
  },
  async deleteChart(event: WechatMiniprogram.TouchEvent) {
    const id = Number(event.currentTarget.dataset.id);
    const record = this.data.savedCharts.find(item => item.id === id);
    if (!record) return;
    const modal = await wx.showModal({ title: "删除这份命盘？", content: `删除“${record.label}”后，命盘和已生成的解读缓存都会移除，且无法恢复。`, confirmText: "删除", confirmColor: "#a94b42" });
    if (!modal.confirm) return;
    try {
      await deleteZiweiChart(id);
      this.setData({ savedCharts: this.data.savedCharts.filter(item => item.id !== id) });
      wx.showToast({ title: "命盘已删除", icon: "success" });
    } catch (error: unknown) {
      wx.showToast({ title: getApiErrorMessage(error, "命盘删除失败"), icon: "none" });
    }
  },
  showCompatibility(event: WechatMiniprogram.TouchEvent) {
    const compatibilityResult = this.data.savedCompatibilities.find(item => item.id === Number(event.currentTarget.dataset.id));
    if (compatibilityResult) wx.navigateTo({ url: `/pages/ziwei/compatibility-result?id=${compatibilityResult.id}` });
  },
  async deleteCompatibility(event: WechatMiniprogram.TouchEvent) {
    const id = Number(event.currentTarget.dataset.id);
    const record = this.data.savedCompatibilities.find(item => item.id === id);
    if (!record) return;
    const modal = await wx.showModal({ title: "删除这份合盘？", content: "删除后双方命盘快照、合盘观察和已生成的解读缓存都会移除，且无法恢复。", confirmText: "删除", confirmColor: "#a94b42" });
    if (!modal.confirm) return;
    try {
      await deleteZiweiCompatibility(id);
      this.setData({ savedCompatibilities: this.data.savedCompatibilities.filter(item => item.id !== id) });
      wx.showToast({ title: "合盘已删除", icon: "success" });
    } catch (error: unknown) {
      wx.showToast({ title: getApiErrorMessage(error, "合盘删除失败"), icon: "none" });
    }
  },
});
