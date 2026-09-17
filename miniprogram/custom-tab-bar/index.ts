Component({
  data: {
    selected: 0,
    tabs: [
      { path: "/pages/home/index", label: "今日五色", icon: "today" },
      { path: "/pages/caikuxiang/index", label: "产品商城", icon: "shop" },
      { path: "/pages/chat/index", label: "测一测", icon: "ai" },
      { path: "/pages/settings/index", label: "我的", icon: "mine" },
    ],
  },
  lifetimes: { attached() { this.syncRoute(); } },
  pageLifetimes: { show() { this.syncRoute(); } },
  methods: {
    syncRoute() {
      const pages = getCurrentPages();
      const route = "/" + pages[pages.length - 1]?.route;
      const selected = this.data.tabs.findIndex(tab => tab.path === route);
      if (selected >= 0) this.setData({ selected });
    },
    switchTab(event: WechatMiniprogram.TouchEvent) {
      const index = Number(event.currentTarget.dataset.index);
      const tab = this.data.tabs[index];
      if (!tab || index === this.data.selected) return;
      wx.switchTab({ url: tab.path });
    },
  },
});
