/**
 * 小程序统一 HTTP 请求层。
 *
 * 这个文件只解决所有接口共有的问题：
 * 1. 拼接 Python API 地址并设置超时；
 * 2. 自动把 JWT 写入 Authorization 请求头；
 * 3. JWT 过期后只执行一次 wx.login，并自动重试原请求；
 * 4. 把 FastAPI、HTTP 和网络错误转换成统一的 ApiError；
 * 5. 用同一套中文提示向用户展示接口错误。
 *
 * 页面不应该直接调用 wx.request，也不应该自己保存 user_id 或 openid。
 */

import { API_BASE_URL, API_TIMEOUT_MS, AUTH_TOKEN_STORAGE_KEY } from "../config";

/** 当前后端实际使用到的 HTTP 方法。 */
export type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

/** 调用 request 时可配置的参数。 */
export interface ApiRequestOptions {
  /** API 路径，例如 /api/profiles/current。 */
  path: string;
  /** 默认使用 GET。 */
  method?: HttpMethod;
  /** 发送给后端的 JSON 对象。 */
  data?: object;
  /** 默认需要登录；公共接口和微信登录接口要显式传 false。 */
  auth?: boolean;
  /** 默认统一弹出错误提示；允许演示数据降级的页面可关闭。 */
  showError?: boolean;
  /** JWT 失效时是否自动重新登录并重试一次，默认开启。 */
  retryOnUnauthorized?: boolean;
  /** 覆盖单次 wx.request 超时时间；模型生成等慢请求可单独放宽。 */
  timeoutMs?: number;
}

/** 错误来自哪个阶段，便于页面针对网络、登录或普通接口错误作不同处理。 */
export type ApiErrorKind = "network" | "http" | "auth";

/**
 * 所有接口失败都转换成这个类型。
 * 页面可以读取 statusCode 判断404，也可以直接使用 message 展示后端中文 detail。
 */
export class ApiError extends Error {
  readonly statusCode: number;
  readonly kind: ApiErrorKind;
  readonly responseData?: unknown;
  /** 后端返回的稳定机器码，例如 daily_guide_unavailable。 */
  readonly code?: string;
  /** 后端业务状态，例如 pending_confirmation 或 unavailable。 */
  readonly status?: string;

  constructor(
    message: string,
    statusCode = 0,
    kind: ApiErrorKind = "http",
    responseData?: unknown,
    code?: string,
    status?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.kind = kind;
    this.responseData = responseData;
    this.code = code;
    this.status = status;
  }
}

/** 同一时刻只允许一个登录任务，避免多个401同时触发多次 wx.login。 */
let loginTask: Promise<string> | null = null;

/** 从内存读取令牌；内存与本地缓存由 setToken/clearLogin 同步维护。 */
export function getToken(): string {
  return getApp<IAppOption>().globalData.token || "";
}

/** 登录成功后，同时写入内存和微信本地缓存。 */
function setToken(token: string): void {
  const app = getApp<IAppOption>();
  app.globalData.token = token;
  wx.setStorageSync(AUTH_TOKEN_STORAGE_KEY, token);
}

/** 退出登录或令牌失效时，同时清除内存与本地缓存。 */
export function clearLogin(): void {
  const app = getApp<IAppOption>();
  app.globalData.token = "";
  wx.removeStorageSync(AUTH_TOKEN_STORAGE_KEY);
}

/** 把 FastAPI 的 detail 字符串或字段校验数组整理成适合用户阅读的一句话。 */
function extractFastApiDetail(data: unknown): string {
  if (!data || typeof data !== "object") return "";
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" ? String((item as { msg?: unknown }).msg || "") : ""))
      .filter(Boolean);
    return messages.join("；");
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown; detail?: unknown }).message
      ?? (detail as { detail?: unknown }).detail;
    return typeof message === "string" ? message : "";
  }
  return "";
}

/** 读取后端错误对象中的稳定机器码和业务状态。 */
function extractFastApiMetadata(data: unknown): { code?: string; status?: string } {
  if (!data || typeof data !== "object") return {};
  const detail = (data as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return {};
  const code = (detail as { code?: unknown }).code;
  const status = (detail as { status?: unknown }).status;
  return {
    code: typeof code === "string" ? code : undefined,
    status: typeof status === "string" ? status : undefined,
  };
}

/** 后端没有提供 detail 时，根据状态码给出稳定的中文提示。 */
function statusFallback(statusCode: number): string {
  if (statusCode === 400) return "提交的数据不正确，请检查后重试";
  if (statusCode === 401 || statusCode === 403) return "登录状态已失效，请重新登录";
  if (statusCode === 404) return "请求的内容不存在";
  if (statusCode === 409) return "当前操作条件不满足";
  if (statusCode === 422) return "填写内容未通过校验，请检查后重试";
  if (statusCode >= 500) return "服务器暂时繁忙，请稍后重试";
  return "请求失败，请稍后重试";
}

/** 把 wx.request 的网络失败对象转换成统一错误。 */
function networkError(error: unknown): ApiError {
  const raw = error && typeof error === "object" ? String((error as { errMsg?: unknown }).errMsg || "") : "";
  const timeout = raw.toLowerCase().includes("timeout");
  return new ApiError(timeout ? "请求超时，请检查网络后重试" : "无法连接服务器，请检查网络和后端是否启动", 0, "network", error);
}

/** 判断一个未知异常是否为指定状态码的接口错误。 */
export function isApiError(error: unknown, statusCode?: number): error is ApiError {
  return error instanceof ApiError && (statusCode === undefined || error.statusCode === statusCode);
}

/** 页面需要自定义兜底文案时，仍然通过这里取得统一错误信息。 */
export function getApiErrorMessage(error: unknown, fallback = "操作失败，请稍后重试"): string {
  if (error instanceof ApiError && error.message) return error.message;
  return fallback;
}

/** 统一使用无图标 Toast 展示错误，避免每个页面的措辞和持续时间不同。 */
export function showApiError(error: unknown, fallback?: string): void {
  wx.showToast({ title: getApiErrorMessage(error, fallback), icon: "none", duration: 2600 });
}

/**
 * 最底层请求函数：只发出一次网络请求，不在这里显示 Toast。
 * 401恢复和最终错误提示分别由 sendWithAuthRecovery 与 request 负责。
 */
function sendOnce<T>(options: ApiRequestOptions): Promise<T> {
  const method = options.method || "GET";
  const token = getToken();
  const header: Record<string, string> = { "content-type": "application/json" };
  if (options.auth !== false && token) header.Authorization = `Bearer ${token}`;

  return new Promise<T>((resolve, reject) => {
    wx.request({
      url: `${API_BASE_URL}${options.path}`,
      method,
      data: options.data,
      header,
      timeout: options.timeoutMs ?? API_TIMEOUT_MS,
      success: (response) => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.data as T);
          return;
        }
        const metadata = extractFastApiMetadata(response.data);
        const detail = extractFastApiDetail(response.data) || statusFallback(response.statusCode);
        const kind: ApiErrorKind = response.statusCode === 401 || response.statusCode === 403 ? "auth" : "http";
        reject(new ApiError(detail, response.statusCode, kind, response.data, metadata.code, metadata.status));
      },
      fail: (error) => reject(networkError(error)),
    });
  });
}

/** 发送请求；JWT过期时清除旧令牌、重新登录，并且只重试原请求一次。 */
async function sendWithAuthRecovery<T>(options: ApiRequestOptions, alreadyRetried = false): Promise<T> {
  try {
    return await sendOnce<T>(options);
  } catch (error) {
    const canRetry = options.auth !== false && options.retryOnUnauthorized !== false && !alreadyRetried;
    if (canRetry && isApiError(error) && (error.statusCode === 401 || error.statusCode === 403)) {
      clearLogin();
      await ensureLogin(true);
      return sendWithAuthRecovery<T>(options, true);
    }
    throw error;
  }
}

/**
 * 所有页面和业务服务使用的统一入口。
 * 需要登录的请求如果还没有JWT，会先静默执行微信登录；最终失败时默认统一提示。
 */
export async function request<T>(options: ApiRequestOptions): Promise<T> {
  const normalized: ApiRequestOptions = {
    method: "GET",
    auth: true,
    showError: true,
    retryOnUnauthorized: true,
    ...options,
  };
  try {
    if (normalized.auth !== false && !getToken()) await ensureLogin();
    return await sendWithAuthRecovery<T>(normalized);
  } catch (error) {
    if (normalized.showError !== false) showApiError(error);
    throw error;
  }
}

/**
 * 显式使用回调形式取得微信临时 code。
 *
 * 部分开发者工具或较低基础库会把不传参数的 wx.login() 处理成空结果；
 * 使用官方回调形式能确保在 success 回调中读取 code，也能保留原始失败信息。
 */
/** 本机联调时，后端会把任意非空 code 映射为开发账号；正式域名绝不能使用它。 */
function getLocalDevelopmentCode(): string | null {
  const isLocalApi = /^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?(?:\/|$)/i.test(API_BASE_URL);
  if (!isLocalApi) return null;
  return `local-dev-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function getWechatLoginCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    wx.login({
      timeout: 10_000,
      success: (result) => {
        if (result.code) {
          resolve(result.code);
          return;
        }
        const localCode = getLocalDevelopmentCode();
        if (localCode) {
          resolve(localCode);
          return;
        }
        reject(new ApiError("微信未返回登录凭证，请重新进入小程序后重试", 0, "auth", result));
      },
      fail: (error) => {
        const localCode = getLocalDevelopmentCode();
        if (localCode) {
          resolve(localCode);
          return;
        }
        reject(new ApiError("微信登录失败，请检查微信网络后重试", 0, "auth", error));
      },
    });
  });
}

/**
 * 使用 wx.login 的临时 code 向 Python 后端换取 JWT。
 * force=true 用于旧JWT已经被后端拒绝的情况；并发调用会共享同一个 loginTask。
 */
export async function ensureLogin(force = false): Promise<string> {
  const currentToken = getToken();
  if (currentToken && !force) return currentToken;
  if (loginTask) return loginTask;

  loginTask = (async () => {
    try {
      const code = await getWechatLoginCode();
      const result = await sendOnce<{ access_token: string }>({
        path: "/api/auth/wechat",
        method: "POST",
        data: { code },
        auth: false,
        showError: false,
        retryOnUnauthorized: false,
      });
      if (!result.access_token) throw new ApiError("服务器未返回登录凭证", 0, "auth");
      setToken(result.access_token);
      return result.access_token;
    } catch (error) {
      clearLogin();
      if (error instanceof ApiError) throw error;
      throw networkError(error);
    }
  })();

  try {
    return await loginTask;
  } finally {
    loginTask = null;
  }
}
