/** 个人每日五色接口。只有AI国学权益有效时，页面才应调用这里。 */

import { isApiError, request } from "./api";

export interface PublicDailyColor {
  rank: number;
  color: string;
  element: string;
  smoothness: string;
  suitable: string[];
  resistance: string;
  advice: string;
  product_code: string;
  incense_name: string;
  scent: string;
}

export interface PublicDailyGuide {
  guide_date: string;
  weekday: string;
  lunar_date: string;
  solar_term: string;
  day_ganzhi: string;
  items: PublicDailyColor[];
  share_title: string;
  share_summary: string;
  push_summary: string;
  rule_version: string;
  /** 公开接口成功响应通常省略状态；保留可选字段兼容运营接口回包。 */
  status?: string;
}

export interface PersonalDailyColor {
  rank: number;
  name: string;
  element: string;
  tendency: string;
  suitable: string[];
  resistance: string;
  advice: string;
  incense: string;
  scent: string;
  reason: string;
}

export interface PersonalDailyGuidance {
  date: string;
  timezone: "Asia/Shanghai";
  content_version: string;
  rule_version: string;
  rule_status: string;
  precision_mode: "three_pillars" | "four_pillars";
  profile_version: number;
  entitlement_plan: string;
  primary_color: string;
  supporting_colors: string[];
  combination_advice: string;
  personal_focus: string;
  comparison_note: string;
  colors: PersonalDailyColor[];
  suitable: string[];
  reminders: string[];
  culture_note: string;
  disclaimer: string;
}

/** 后端会再次校验权益；前端判断只用于避免无权益时加载个人档案结果。 */
export function getPersonalDailyGuidance(): Promise<PersonalDailyGuidance> {
  return request<PersonalDailyGuidance>({ path: "/api/daily", showError: false });
}

/** 读取已人工确认的公共每日五色；未确认日期会以 machine code 明确返回待更新。 */
export function getPublicDailyGuide(targetDate?: string): Promise<PublicDailyGuide> {
  const path = targetDate ? `/api/public-guides/${targetDate}` : "/api/public-guides/today";
  return request<PublicDailyGuide>({ path, auth: false, showError: false });
}

/** 供页面区分“尚未人工确认”与网络/服务故障。 */
export function isPublicDailyGuidePending(error: unknown): boolean {
  return isApiError(error) && (
    error.code === "daily_guide_pending" || error.status === "pending_confirmation"
  );
}

/** 供页面在服务暂不可用时展示重试入口。 */
export function isPublicDailyGuideUnavailable(error: unknown): boolean {
  return isApiError(error) && (
    error.code === "daily_guide_unavailable" || error.status === "unavailable"
  );
}
