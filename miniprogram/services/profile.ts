/**
 * 生辰档案业务接口和前后端共用的数据结构。
 * 页面只处理表单展示，API路径、方法和返回类型全部集中在本文件。
 */

import { isApiError, request } from "./api";

export type CalendarType = "solar" | "lunar";
export type Gender = "male" | "female" | "unspecified";
export type ProfileResultMode = "full" | "simplified";

export interface CalendarPillar {
  text: string;
}

export interface CalendarTerm {
  name: string;
  datetime: string;
}

/** 后端历法服务返回的结果；该结果由Python计算，不由前端或AI临时推算。 */
export interface CalendarResult {
  solar_date: string;
  lunar_text: string;
  zodiac: string;
  western_sign: string;
  calculation_version: string;
  previous_solar_term: CalendarTerm;
  next_solar_term: CalendarTerm;
  pillars: {
    year: CalendarPillar;
    month: CalendarPillar;
    day: CalendarPillar;
    time: CalendarPillar | null;
  };
}

/** 创建和修改档案时提交给后端的数据。 */
export interface ProfileInput {
  calendar_type: CalendarType;
  is_leap_month: boolean;
  birth_date: string;
  time_known: boolean;
  birth_time: string | null;
  birth_city: string | null;
  gender: Gender;
  timezone: "Asia/Shanghai";
}

/** 保存或读取档案后由后端返回的数据。 */
export interface ProfileResponse extends ProfileInput {
  id: number;
  profile_version: number;
  completeness: number;
  missing_fields: string[];
  result_mode: ProfileResultMode;
  calendar: CalendarResult;
  created_at: string;
  updated_at: string;
}

/** 读取当前JWT对应用户的档案；404代表账号存在但尚未创建档案。 */
export function getCurrentProfile(): Promise<ProfileResponse> {
  return request<ProfileResponse>({ path: "/api/profiles/current", showError: false });
}

/** PUT具有“没有则创建、已有则修改”的语义，后端同时写入历法计算缓存。 */
export function saveCurrentProfile(data: ProfileInput): Promise<ProfileResponse> {
  return request<ProfileResponse>({ path: "/api/profiles/current", method: "PUT", data });
}

/** 删除档案及个人每日建议缓存，但保留微信账号。 */
export function deleteCurrentProfile(): Promise<void> {
  return request<void>({ path: "/api/profiles/current", method: "DELETE" });
}

/** 集中判断“尚未创建档案”，避免页面依赖后端中文文案。 */
export function isProfileMissing(error: unknown): boolean {
  return isApiError(error, 404);
}

