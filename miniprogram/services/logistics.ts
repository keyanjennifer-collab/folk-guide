import { request } from "./api";
import { OrderStatus } from "./orders";

export interface LogisticsEvent {
  time: string;
  title: string;
  description: string;
}

export interface OrderLogistics {
  order_id: number;
  order_number: string;
  order_status: OrderStatus;
  carrier: string | null;
  tracking_number: string | null;
  shipment_recorded: boolean;
  tracking_status: "not_shipped" | "not_connected" | "available" | "temporarily_unavailable";
  tracking_message: string;
  tracking_updated_at: string | null;
  tracking_events: LogisticsEvent[];
  order_events: LogisticsEvent[];
}

export function getOrderLogistics(orderId: number): Promise<OrderLogistics> {
  return request<OrderLogistics>({
    path: `/api/orders/${orderId}/logistics`, showError: false, retryOnUnauthorized: false,
  });
}

export function logisticsTimeLabel(value: string | null): string {
  if (!value) return "";
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : value + "Z";
  const time = Date.parse(normalized);
  if (!Number.isFinite(time)) return "";
  // 不依赖设备时区或小程序 Intl 支持，固定使用北京时间。
  const date = new Date(time + 8 * 3600000);
  const pad = (part: number): string => String(part).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}
