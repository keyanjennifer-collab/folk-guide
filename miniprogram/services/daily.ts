/** 个人每日五色接口。只有时序文化权益有效时，页面才应调用这里。 */

import { request } from "./api";

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

/** 按北京时间读取由确定性规则自动生成并缓存的公共每日五色。 */
export function getPublicDailyGuide(targetDate?: string): Promise<PublicDailyGuide> {
  const path = targetDate ? `/api/public-guides/${targetDate}` : "/api/public-guides/today";
  return request<PublicDailyGuide>({ path, auth: false, showError: false });
}
