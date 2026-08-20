/** AI国学真实接口封装。页面只处理展示状态，不直接拼API路径。 */

import { request } from "./api";

export interface AICitation {
  document_id: number;
  chunk_id: number;
  title: string;
  heading: string | null;
  source_name: string;
  page_start: number | null;
  page_end: number | null;
}

export interface AIQuota {
  active: boolean;
  plan: string | null;
  expires_at: string | null;
  normal_limit: number;
  normal_used: number;
  normal_remaining: number;
  comparison_limit: number;
  comparison_used: number;
  comparison_remaining: number;
  answer_ready: boolean;
}

export interface AIChatResponse {
  message_id: number;
  answer: string;
  category: string;
  blocked: boolean;
  citations: AICitation[];
  remaining_today: number;
  model_name: string;
  disclaimer: string;
}

export interface AIHistoryRecord {
  id: number;
  question: string;
  answer: string;
  category: string;
  citations: AICitation[];
  feedback: "helpful" | "unhelpful" | null;
  created_at: string;
}

export function getAIQuota(): Promise<AIQuota> {
  return request<AIQuota>({ path: "/api/ai/quota", showError: false });
}

export function askAI(question: string, questionType: "normal" | "seven_day_comparison" = "normal"): Promise<AIChatResponse> {
  return request<AIChatResponse>({
    path: "/api/ai/chat",
    method: "POST",
    data: { question, question_type: questionType },
    showError: false,
  });
}

export function getAIHistory(limit = 20): Promise<AIHistoryRecord[]> {
  return request<AIHistoryRecord[]>({ path: `/api/ai/history?limit=${limit}`, showError: false });
}

export function submitAIFeedback(messageId: number, rating: "helpful" | "unhelpful"): Promise<AIHistoryRecord> {
  return request<AIHistoryRecord>({
    path: `/api/ai/messages/${messageId}/feedback`,
    method: "PUT",
    data: { rating },
    showError: false,
  });
}

/** 把后端结构化引用转换成用户可读的一行，不暴露内部chunk_id。 */
export function citationLabel(citation: AICitation): string {
  const heading = citation.heading ? ` · ${citation.heading}` : "";
  const page = citation.page_start
    ? citation.page_end && citation.page_end !== citation.page_start
      ? ` · PDF第${citation.page_start}—${citation.page_end}页`
      : ` · PDF第${citation.page_start}页`
    : "";
  return `《${citation.title}》${heading}${page}｜${citation.source_name}`;
}
