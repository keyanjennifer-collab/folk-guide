import { ensureLogin, getApiErrorMessage } from "../../services/api";
import { getTheme, AppTheme } from "../../services/theme";
import { deleteZiweiChart, getZiweiCharts, interpretZiwei, ZiweiChartRecord, ZiweiPeriodType } from "../../services/ziwei";
import { ANALYSIS_TABS, AnalysisKey, PeriodMode, makeAnalysis, makeAnalysisForPalace, normalizePalaceName } from "./analysis";

Page({
  data: {
    themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    loading: true, chartResult: null as ZiweiChartRecord | null,
    analysisTabs: ANALYSIS_TABS, activeAnalysis: "overview" as AnalysisKey,
    periodMode: "mingpan" as PeriodMode, analysis: null as any, analysisText: "", analysisLoading: false, selectedPalaceBranch: -1,
  },
  async onLoad(options: Record<string, string>) {
    try {
      await ensureLogin();
      const id = Number(options.id);
      const records = await getZiweiCharts();
      const chartResult = records.find(item => item.id === id) || records[0];
      if (!chartResult) throw new Error("没有找到命盘记录");
      this.setData({ chartResult, analysis: makeAnalysis(chartResult.chart, "overview", "mingpan"), loading: false });
      void this.loadRemoteAnalysis("overview", "mingpan", null);
    } catch (error: unknown) {
      this.setData({ loading: false });
      wx.showToast({ title: getApiErrorMessage(error, "命盘读取失败"), icon: "none" });
    }
  },
  selectAnalysis(event: WechatMiniprogram.TouchEvent) {
    const chart = this.data.chartResult?.chart;
    if (!chart) return;
    const key = event.currentTarget.dataset.key as AnalysisKey;
    this.setData({ activeAnalysis: key, selectedPalaceBranch: -1, analysis: makeAnalysis(chart, key, this.data.periodMode), analysisText: "" });
    void this.loadRemoteAnalysis(key, this.data.periodMode, null);
  },
  selectPeriod(event: WechatMiniprogram.TouchEvent) {
    const chart = this.data.chartResult?.chart;
    if (!chart) return;
    const raw = String(event.currentTarget.dataset.period);
    const periodMode: PeriodMode = ["mingpan", "liunian", "xiaoxian", "liuyue", "liuri", "liushi"].includes(raw) ? raw as PeriodMode : Number(raw);
    this.setData({ periodMode, analysis: makeAnalysis(chart, this.data.activeAnalysis, periodMode), analysisText: "" });
    void this.loadRemoteAnalysis(this.data.activeAnalysis, periodMode, this.data.selectedPalaceBranch >= 0 ? this.data.selectedPalaceBranch : null);
  },
  selectPalace(event: WechatMiniprogram.TouchEvent) {
    const chart = this.data.chartResult?.chart;
    if (!chart) return;
    const branch = Number(event.currentTarget.dataset.branch);
    const palace = (chart.palaces || []).find((item: any) => item.branch === branch);
    const tab = ANALYSIS_TABS.find(item => normalizePalaceName(item.palace) === normalizePalaceName(palace?.name || "")) || ANALYSIS_TABS[0];
    this.setData({ activeAnalysis: tab.key, selectedPalaceBranch: branch, analysis: makeAnalysisForPalace(chart, palace, tab.key, this.data.periodMode), analysisText: "" });
    void this.loadRemoteAnalysis(tab.key, this.data.periodMode, branch);
  },
  async loadRemoteAnalysis(topic: AnalysisKey, mode: PeriodMode, palaceBranch: number | null) {
    const chartResult = this.data.chartResult;
    if (!chartResult) return;
    const period_type: ZiweiPeriodType = typeof mode === "number" ? "daxian" : mode;
    const period_key = typeof mode === "number" ? String(mode) : null;
    this.setData({ analysisLoading: true });
    try {
      const result = await interpretZiwei({ chart_id: chartResult.id, topic, period_type, period_key, palace_branch: palaceBranch });
      this.setData({ analysisText: result.answer });
    } catch (_) {
      // 保留本地结构化分析，模型暂不可用时仍能浏览命盘。
    } finally {
      this.setData({ analysisLoading: false });
    }
  },
  async deleteChart() {
    const chartResult = this.data.chartResult;
    if (!chartResult) return;
    const modal = await wx.showModal({ title: "删除这份命盘？", content: `删除“${chartResult.label}”后，命盘和已生成的解读缓存都会移除，且无法恢复。`, confirmText: "删除", confirmColor: "#a94b42" });
    if (!modal.confirm) return;
    try {
      await deleteZiweiChart(chartResult.id);
      wx.showToast({ title: "命盘已删除", icon: "success" });
      wx.navigateBack();
    } catch (error: unknown) {
      wx.showToast({ title: getApiErrorMessage(error, "命盘删除失败"), icon: "none" });
    }
  },
});
