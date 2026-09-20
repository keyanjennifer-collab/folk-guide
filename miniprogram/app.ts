import { AUTH_TOKEN_STORAGE_KEY, FONT_ASSET_BASE_URL } from "./config";
import { applyTheme } from "./services/theme";

type FontLoader = (options: {
  family: string;
  source: string;
  global?: boolean;
  success?: () => void;
  fail?: (error: unknown) => void;
}) => void;

/**
 * 显式注册品牌字体，绕过微信 iOS 对 app.wxss 相对路径 @font-face 的兼容差异。
 * global=true 让字体对已打开和后续打开的页面都生效；失败时静默使用 app.wxss 回退栈。
 */
function loadBrandFonts(): void {
  const loadFontFace = (wx as unknown as { loadFontFace?: FontLoader }).loadFontFace;
  if (!loadFontFace) return;
  for (const [family, file] of [
    ["Wuse Sans", "wuse-sans.woff2"],
    ["Wuse Serif", "wuse-serif.woff2"],
  ] as const) {
    loadFontFace({
      family,
      source: `url("${FONT_ASSET_BASE_URL}/${file}")`,
      global: true,
      fail: () => {
        // 开发者工具或离线调试时，尝试包内资源；正式真机优先使用 HTTPS 资源。
        loadFontFace({
          family,
          source: `url("/assets/fonts/${file}")`,
          global: true,
          fail: () => {
            // 系统字体回退由 app.wxss 的跨平台栈负责，不打断首页渲染。
          },
        });
      },
    });
  }
}

/**
 * 小程序全局只保存登录令牌。
 * openid、AppSecret、生辰档案和手机号都不能放进 globalData，业务数据应从后端读取。
 */
App({
  globalData: {
    token: String(wx.getStorageSync(AUTH_TOKEN_STORAGE_KEY) || ""),
    theme: "night" as const,
  },
  onLaunch() {
    applyTheme();
    loadBrandFonts();
  },
});
