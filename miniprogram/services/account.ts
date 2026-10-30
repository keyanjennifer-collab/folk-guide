/** “我的”页面使用的账号接口；页面不需要知道具体 API 路径。 */

import { ApiError, clearLogin, ensureLogin, getToken, request } from "./api";
import { API_BASE_URL } from "../config";

export const DEFAULT_NICKNAME = "五色知时用户";
export const DEFAULT_AVATAR_URL = "/assets/brand/logo-ai.png";
const MAX_AVATAR_BASE64_LENGTH = Math.ceil(2 * 1024 * 1024 / 3) * 4;

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
/** undefined 表示本机临时文件，必须读取图片内容后上传，不能直接存地址。 */
function persistentAvatarUrl(value: string | null): string | null | undefined {
  if (!value || value === DEFAULT_AVATAR_URL) return null;
  const relative = value.startsWith(API_BASE_URL + "/avatar-assets/") ? value.slice(API_BASE_URL.length) : value;
  if (/^\/avatar-assets\/[1-9][0-9]*-[0-9a-f]{32}\.(png|jpg|webp)$/.test(relative)) return relative;
  if (/^https:\/\/(?!tmp(?:[/:]|$)|usr(?:[/:]|$)|localhost(?:[/:]|$))[^/]+/i.test(value)) return value;
  return undefined;
}

export function userProfilePresentation(user: CurrentUser): { nickname: string; avatarUrl: string } {
  const saved = persistentAvatarUrl(user.avatar_url);
  return {
    nickname: user.nickname?.trim() || DEFAULT_NICKNAME,
    avatarUrl: saved ? (saved.startsWith("/") ? API_BASE_URL + saved : saved) : DEFAULT_AVATAR_URL,
  };
}

export async function updateUserProfile(nickname: string, avatarUrl: string | null): Promise<CurrentUser> {
  const token = getToken();
  if (!token) throw new ApiError("请先登录再保存资料", 401, "auth");
  const data: { nickname: string; avatar_url?: string | null; avatar_base64?: string } = { nickname };
  const saved = persistentAvatarUrl(avatarUrl);
  if (saved === undefined && avatarUrl) {
    // 小头像沿用已配置的 request 域名上传，不增加 uploadFile 域名或依赖。
    data.avatar_base64 = await new Promise<string>((resolve, reject) => wx.getFileSystemManager().readFile({
      filePath: avatarUrl, encoding: "base64",
      success: result => typeof result.data === "string" ? resolve(result.data) : reject(new ApiError("头像读取失败，请重新选择")),
      fail: () => reject(new ApiError("头像临时文件已失效，请重新选择头像")),
    }));
    if (data.avatar_base64.length > MAX_AVATAR_BASE64_LENGTH) throw new ApiError("头像不能超过2MB，请换一张图片");
  } else data.avatar_url = saved ?? null;
  if (getToken() !== token) throw new ApiError("登录状态已变化，请重新登录后保存", 401, "auth");
  const user = await request<CurrentUser>({ path: "/api/users/me/profile", method: "PUT", data,
    showError: false, retryOnUnauthorized: false });
  if (data.avatar_base64 && !user.avatar_url?.startsWith("/avatar-assets/")) {
    throw new ApiError("头像未保存成功，请更新后台后重试");
  }
  return user;
}

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
