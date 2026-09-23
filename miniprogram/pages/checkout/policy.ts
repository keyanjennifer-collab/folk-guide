import { getCatalog } from "../../services/commerce";
import { getTheme } from "../../services/theme";

Page({
  data: { themeClass: "theme-" + getTheme(), merchantName: "五色知时", customerService: "", shippingEta: "付款后两个月内发货" },
  async onLoad() {
    try {
      const catalog = await getCatalog();
      this.setData({ merchantName: catalog.merchant_name, customerService: catalog.customer_service, shippingEta: catalog.shipping_eta });
    } catch (_) { /* 保留基础须知，结算接口恢复后会重新读取正式信息。 */ }
  },
});
