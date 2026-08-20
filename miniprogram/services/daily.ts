/** 个人每日五色接口。只有AI国学权益有效时，页面才应调用这里。 */

import { request } from "./api";

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
