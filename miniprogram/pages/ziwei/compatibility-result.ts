import { ensureLogin, getApiErrorMessage } from "../../services/api";
import { getTheme, AppTheme } from "../../services/theme";
import { deleteZiweiCompatibility, getZiweiCompatibilities, interpretZiweiCompatibility, ZiweiCompatibilityRecord } from "../../services/ziwei";

const RELATION_LABELS: Record<string, string> = {
  business: "生意与合伙",
  love: "姻缘与相处",
  family: "亲子与家庭",
  friend: "朋友与协作",
};

Page({
  data: {
    themeClass: "theme-" + getTheme(), theme: getTheme() as AppTheme,
    loading: true, compatibilityResult: null as ZiweiCompatibilityRecord | null, relationLabel: "",
    compatibilityAnalysis: "", compatibilityAnalysisLoading: false,
  },
  async onLoad(options: Record<string, string>) {
    try {
      await ensureLogin();
      const id = Number(options.id);
      const records = await getZiweiCompatibilities();
      const compatibilityResult = records.find(item => item.id === id) || records[0];
      if (!compatibilityResult) throw new Error("没有找到合盘记录");
      this.setData({ compatibilityResult, relationLabel: RELATION_LABELS[compatibilityResult.relation_type] || compatibilityResult.relation_type, loading: false });
      void this.loadRemoteAnalysis(compatibilityResult.id);
    } catch (error: unknown) {
      this.setData({ loading: false });
      wx.showToast({ title: getApiErrorMessage(error, "合盘读取失败"), icon: "none" });
    }
  },
  async loadRemoteAnalysis(compatibilityId: number) {
    this.setData({ compatibilityAnalysisLoading: true });
    try {
      const result = await interpretZiweiCompatibility({ compatibility_id: compatibilityId });
      this.setData({ compatibilityAnalysis: result.answer });
    } catch (_) {
      // 模型暂时不可用时仍显示已保存的结构化合盘观察。
    } finally {
      this.setData({ compatibilityAnalysisLoading: false });
    }
  },
  async deleteCompatibility() {
    const compatibilityResult = this.data.compatibilityResult;
    if (!compatibilityResult) return;
    const modal = await wx.showModal({ title: "删除这份合盘？", content: "删除后双方命盘快照、合盘观察和已生成的解读缓存都会移除，且无法恢复。", confirmText: "删除", confirmColor: "#a94b42" });
    if (!modal.confirm) return;
    try {
      await deleteZiweiCompatibility(compatibilityResult.id);
      wx.showToast({ title: "合盘已删除", icon: "success" });
      wx.navigateBack();
    } catch (error: unknown) {
      wx.showToast({ title: getApiErrorMessage(error, "合盘删除失败"), icon: "none" });
    }
  },
});
