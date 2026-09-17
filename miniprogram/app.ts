import { AUTH_TOKEN_STORAGE_KEY } from "./config";
import { applyTheme } from "./services/theme";

/**
 * 小程序全局只保存登录令牌。
 * openid、AppSecret、生辰档案和手机号都不能放进 globalData，业务数据应从后端读取。
 */
App({
  globalData: {
    token: String(wx.getStorageSync(AUTH_TOKEN_STORAGE_KEY) || ""),
    theme: "night" as const,
  },
  onLaunch() { applyTheme(); },
});
