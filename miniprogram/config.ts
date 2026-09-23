/**
 * 小程序前端的非敏感运行配置。
 *
 * 注意：这里只能放能够公开给所有用户的信息，例如后端地址和请求超时。
 * 微信 AppSecret、JWT 密钥、数据库密码和模型密钥只能放在 Python 后端环境变量中。
 */

/**
 * 微信开发者工具访问电脑本机后端时使用 127.0.0.1。
 * 真机中的 127.0.0.1 指向手机自身，因此真机调试和正式发布前必须换成 HTTPS 域名，
 * 同时在微信公众平台的“开发管理 -> 开发设置”中配置 request 合法域名。
 */
//export const API_BASE_URL = "https://api.wusezhishi.com";
export const API_BASE_URL = "http://127.0.0.1:8000";
/** 品牌字体由同一 API 域名提供，开发者工具失败时会回退到包内字体。 */
export const FONT_ASSET_BASE_URL = `${API_BASE_URL}/font-assets`;
/** 单次接口最长等待15秒，避免网络断开后页面长期停留在加载状态。 */
export const API_TIMEOUT_MS = 15_000;

/** JWT 在微信本地缓存中的键名。修改它会使已有用户需要重新登录。 */
export const AUTH_TOKEN_STORAGE_KEY = "token";


