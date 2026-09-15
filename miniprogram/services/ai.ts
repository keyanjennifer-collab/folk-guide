/** 时序文化真实接口封装。页面只处理展示状态，不直接拼 API 路径。 */

import { request } from "./api";

export interface AICitation {
  kind: "knowledge" | "personal_daily" | "web";
  document_id: number | null;
  chunk_id: number | null;
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
  conversation_id?: number;
  answer: string;
  category: string;
  blocked: boolean;
  citations: AICitation[];
  remaining_today: number;
  model_name: string;
  safety_status: "safe" | "blocked" | "output_filtered" | "output_truncated";
  disclaimer: string;
}

export interface AIHistoryRecord {
  id: number;
  conversation_id?: number | null;
  question: string;
  answer: string;
  category: string;
  citations: AICitation[];
  feedback: "helpful" | "unhelpful" | null;
  safety_status: "safe" | "blocked" | "output_filtered" | "output_truncated";
  created_at: string;
}
export interface AIConversation { id: number; title: string; message_count: number; created_at: string; updated_at: string; }
export interface AIConversationPage { items: AIConversation[]; next_cursor: string | null; }
export interface AIConversationDetail extends AIConversation { messages: AIHistoryRecord[]; }

export function getAIQuota(): Promise<AIQuota> {
  return request<AIQuota>({ path: "/api/ai/quota", showError: false });
}

export function askAI(question: string, questionType: "normal" | "seven_day_comparison" = "normal", conversationId?: number): Promise<AIChatResponse> {
  return request<AIChatResponse>({
    path: "/api/ai/chat",
    method: "POST",
    data: { question, question_type: questionType, ...(conversationId ? { conversation_id: conversationId } : {}) },
    showError: false,
  });
}

export function getAIHistory(limit = 20): Promise<AIHistoryRecord[]> {
  return request<AIHistoryRecord[]>({ path: `/api/ai/history?limit=${limit}`, showError: false });
}
export function createAIConversation(): Promise<AIConversation> { return request<AIConversation>({ path: "/api/ai/conversations", method: "POST", data: {}, showError: false }); }
export function getAIConversations(): Promise<AIConversationPage> { return request<AIConversationPage>({ path: "/api/ai/conversations", showError: false }); }
export function getAIConversation(id: number): Promise<AIConversationDetail> { return request<AIConversationDetail>({ path: `/api/ai/conversations/${id}`, showError: false }); }
export function deleteAIConversation(id: number): Promise<void> { return request<void>({ path: `/api/ai/conversations/${id}`, method: "DELETE", showError: false }); }

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
  if (citation.kind === "personal_daily") {
    const date = citation.heading ? ` · ${citation.heading}` : "";
    return `${citation.title}${date}｜${citation.source_name}`;
  }
  if (citation.kind === "web") {
    const date = citation.heading ? ` · ${citation.heading}` : "";
    return `网页：${citation.title}${date}｜${citation.source_name}`;
  }
  const heading = citation.heading ? ` · ${citation.heading}` : "";
  const page = citation.page_start
    ? citation.page_end && citation.page_end !== citation.page_start
      ? ` · PDF第${citation.page_start}—${citation.page_end}页`
      : ` · PDF第${citation.page_start}页`
    : "";
  return `《${citation.title}》${heading}${page}｜${citation.source_name}`;
}
