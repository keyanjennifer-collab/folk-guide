# 五色知时字体资源

小程序使用两个经过字符精简的 Noto CJK 字体文件：

- `wuse-sans.woff2`：Noto Sans SC，正文、按钮、数字
- `wuse-serif.woff2`：Noto Serif SC，标题、章节名、东方气质较强的短文本

字体由 Google Fonts 分发，原字体按 SIL Open Font License 1.1 授权，允许商业使用、修改和再分发。`OFL-1.1.txt` 为随包附带的完整许可证文本；字体源文件与授权说明见：

- https://fonts.google.com/specimen/Noto+Sans+SC
- https://fonts.google.com/specimen/Noto+Serif+SC

当前 WOFF2 是仅包含本小程序界面字符的子集，缺少的动态字符会按 `app.wxss` 中的跨平台回退字体显示。

小程序启动时还会通过 `wx.loadFontFace` 从 `https://api.wusezhishi.com/font-assets/` 显式加载同一份字体，解决微信 iOS 对包内相对路径字体支持不稳定的问题。发布前需要把 `backend/app/static/fonts/` 一并部署，并在微信公众平台的业务域名中配置 `api.wusezhishi.com`（请求/下载合法域名）。
