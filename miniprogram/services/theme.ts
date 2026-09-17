/** 日间主题暂不开放；保留服务入口，之后恢复时不必修改各页面。 */
export type AppTheme = "night";
const KEY = "folk-guide-theme";
export function getTheme(): AppTheme { return "night"; }
export function applyTheme(): void {
  // 清除旧版用户已保存的日间偏好，避免升级后仍看到浅色页面背景。
  wx.removeStorageSync(KEY);
  wx.setBackgroundColor({ backgroundColor: "#262626", backgroundColorTop: "#262626", backgroundColorBottom: "#262626" });
}
export function toggleTheme(): AppTheme { applyTheme(); return "night"; }
