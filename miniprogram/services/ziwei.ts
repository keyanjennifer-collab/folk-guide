import { request } from "./api";

export type ZiweiGender = "male" | "female";
export type ZiweiRelationType = "business" | "love" | "family" | "friend";

export interface ZiweiBirthInput {
  label: string;
  name: string | null;
  birth_date: string;
  calendar_type: "solar" | "lunar";
  is_leap_month: boolean;
  birth_time: string;
  gender: ZiweiGender;
  birth_location: string | null;
}

export interface ZiweiChartRecord extends ZiweiBirthInput {
  id: number;
  chart: any;
  created_at: string;
  updated_at: string;
}

export interface ZiweiCompatibilityRecord {
  id: number;
  relation_type: ZiweiRelationType;
  person_a: { name: string | null; chart: any };
  person_b: { name: string | null; chart: any };
  result: { title: string; basis: string; observations: string[]; discussion_topics: string[]; disclaimer: string };
  created_at: string;
}
export type ZiweiAnalysisTopic = "overview" | "wealth" | "career" | "love" | "personality" | "health" | "family" | "children" | "move" | "friends" | "home" | "spirit" | "parents";
export type ZiweiPeriodType = "mingpan" | "daxian" | "liunian" | "xiaoxian" | "liuyue" | "liuri" | "liushi";
export interface ZiweiInterpretation {
  chart_id: number; topic: ZiweiAnalysisTopic; period_type: ZiweiPeriodType; period_key: string | null;
  palace_branch: number | null; answer: string; model_name: string; cached: boolean; knowledge_version: string;
}
export interface ZiweiCompatibilityInterpretation {
  compatibility_id: number; answer: string; model_name: string; cached: boolean; knowledge_version: string;
}

export function saveZiweiChart(data: ZiweiBirthInput): Promise<ZiweiChartRecord> {
  return request<ZiweiChartRecord>({ path: "/api/ziwei/charts", method: "POST", data });
}
export function getZiweiCharts(): Promise<ZiweiChartRecord[]> { return request<ZiweiChartRecord[]>({ path: "/api/ziwei/charts" }); }
export function deleteZiweiChart(chartId: number): Promise<void> { return request<void>({ path: `/api/ziwei/charts/${chartId}`, method: "DELETE" }); }
export function saveZiweiCompatibility(data: { relation_type: ZiweiRelationType; person_a: ZiweiBirthInput; person_b: ZiweiBirthInput }): Promise<ZiweiCompatibilityRecord> {
  return request<ZiweiCompatibilityRecord>({ path: "/api/ziwei/compatibilities", method: "POST", data });
}
export function getZiweiCompatibilities(): Promise<ZiweiCompatibilityRecord[]> { return request<ZiweiCompatibilityRecord[]>({ path: "/api/ziwei/compatibilities" }); }
export function deleteZiweiCompatibility(compatibilityId: number): Promise<void> { return request<void>({ path: `/api/ziwei/compatibilities/${compatibilityId}`, method: "DELETE" }); }
export function interpretZiwei(data: { chart_id: number; topic: ZiweiAnalysisTopic; period_type: ZiweiPeriodType; period_key?: string | null; palace_branch?: number | null }): Promise<ZiweiInterpretation> {
  return request<ZiweiInterpretation>({ path: "/api/ziwei/interpret", method: "POST", data, timeoutMs: 120_000 });
}
export function interpretZiweiCompatibility(data: { compatibility_id: number; question?: string }): Promise<ZiweiCompatibilityInterpretation> {
  return request<ZiweiCompatibilityInterpretation>({ path: "/api/ziwei/compatibility/analyze", method: "POST", data, timeoutMs: 120_000 });
}
