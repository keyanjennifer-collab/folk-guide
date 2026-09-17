Page({
  onShow() { (this as any).getTabBar?.()?.setData({ selected: 2 }); },
  toProfile() { wx.navigateTo({ url: "/pages/profile/index?source=ziwei-chart" }); },
  toMatchProfile() { wx.navigateTo({ url: "/pages/profile/index?source=ziwei-match" }); },
});
