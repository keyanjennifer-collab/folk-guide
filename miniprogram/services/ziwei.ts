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

export function saveZiweiChart(data: ZiweiBirthInput): Promise<ZiweiChartRecord> {
  return request<ZiweiChartRecord>({ path: "/api/ziwei/charts", method: "POST", data });
}
export function getZiweiCharts(): Promise<ZiweiChartRecord[]> { return request<ZiweiChartRecord[]>({ path: "/api/ziwei/charts" }); }
export function saveZiweiCompatibility(data: { relation_type: ZiweiRelationType; person_a: ZiweiBirthInput; person_b: ZiweiBirthInput }): Promise<ZiweiCompatibilityRecord> {
  return request<ZiweiCompatibilityRecord>({ path: "/api/ziwei/compatibilities", method: "POST", data });
}
export function getZiweiCompatibilities(): Promise<ZiweiCompatibilityRecord[]> { return request<ZiweiCompatibilityRecord[]>({ path: "/api/ziwei/compatibilities" }); }
