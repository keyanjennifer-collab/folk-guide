/** “我的”页面使用的账号接口；页面不需要知道具体 API 路径。 */

import { clearLogin, ensureLogin, request } from "./api";

/** 后端返回的当前账号信息，不包含微信 openid。 */
export interface CurrentUser {
  id: number;
  phone_number: string | null;
  phone_bound: boolean;
  wechat_phone_available: boolean;
  created_at: string;
  nickname: string | null;
  avatar_url: string | null;
}
export function updateUserProfile(nickname: string, avatarUrl: string | null): Promise<CurrentUser> { return request<CurrentUser>({ path: "/api/users/me/profile", method: "PUT", data: { nickname, avatar_url: avatarUrl }, showError: false }); }

/** 用户点击微信登录按钮时调用；force会确保重新取得有效微信临时 code。 */
export function loginWithWechat(force = false): Promise<string> {
  return ensureLogin(force);
}

/** 用JWT确认当前账号仍然有效。调用方自行决定加载失败时的页面状态。 */
export function getCurrentUser(): Promise<CurrentUser> {
  return request<CurrentUser>({ path: "/api/users/me", showError: false });
}

/** 手机号临时 code 只能交给后端换取，前端不能解析或直接提交手机号。 */
export function bindWechatPhone(code: string): Promise<CurrentUser> {
  return request<CurrentUser>({ path: "/api/users/me/phone", method: "POST", data: { code }, showError: false });
}

/** 本地退出只删除JWT；不会注销数据库中的微信账号。 */
export function logoutLocalAccount(): void {
  clearLogin();
}


export interface LocalUserProfile { nickname: string; avatarUrl: string; source: "wechat" | "custom" | "default"; }
const PROFILE_KEY = "local_user_profile";
export function getLocalUserProfile(): LocalUserProfile { return wx.getStorageSync(PROFILE_KEY) || { nickname: "五色知时用户", avatarUrl: "/assets/brand/logo-ai.png", source: "default" }; }
export function saveLocalUserProfile(profile: LocalUserProfile): void { wx.setStorageSync(PROFILE_KEY, profile); }
/** 必须由用户点击触发；微信会在此处显示头像昵称授权弹窗。 */
export function requestWechatProfile(): Promise<WechatMiniprogram.GetUserProfileSuccessCallbackResult> { return new Promise((resolve, reject) => wx.getUserProfile({ desc: "用于在主页显示你的微信头像和昵称", success: resolve, fail: reject })); }
