import { request } from "./api";
export type OrderStatus = "pending" | "paid" | "shipped" | "completed" | "after_sale" | "refunded" | "cancelled";
export const ORDER_LABELS: Record<OrderStatus, string> = {
  pending: "待付款", paid: "待发货", shipped: "待收货", completed: "已完成", after_sale: "退款处理中", refunded: "已退款", cancelled: "已取消",
};
export interface Order {
  id: number; number: string; status: OrderStatus; subtotal_fen: number; shipping_fee_fen: number; total_fen: number; created_at: string;
  carrier: string | null; tracking_number: string | null;
  receiver_name: string; receiver_phone: string; receiver_address: string; remark: string | null;
  expires_at: string | null; paid_at: string | null; shipped_at: string | null; refunded_at: string | null;
  items: { product_id: string; name: string; quantity: number; unit_price_fen: number; subtotal_fen: number }[];
}
export interface OrderList { items: Order[]; counts: Record<OrderStatus, number>; has_more: boolean; }
export function getOrders(status = "all", offset = 0, limit = 20): Promise<OrderList> {
  const query = status === "all" ? "" : "&status=" + encodeURIComponent(status);
  return request<OrderList>({ path: "/api/orders?offset=" + offset + "&limit=" + limit + query, showError: false, retryOnUnauthorized: false });
}
