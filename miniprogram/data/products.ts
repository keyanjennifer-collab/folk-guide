/** 包装稿中的正式品名；参考价沿用已有原型，开售前由商品后台确认。 */
export interface Product {
  id: string; name: string; color: string; element: string; beast: string;
  mood: string; scent: string; story: string; price: number; image: string;
  emblem: string; gallery: string[]; swatches: string[]; category: "set" | "single";
}

const asset = "/assets/brand/";
export const PRODUCTS: Product[] = [
  { id: "gift", name: "五色知时线香套装", color: "五色", element: "五行", beast: "五方图腾", mood: "五色齐备 · 随时择香", scent: "五款线香与矿石香插，收于一盒。", story: "将青木、朱蜜、黄檀、白桂、墨沉五款香气收于一盒。随时序择色，也随心择香。", price: 239, image: asset + "gift.jpg", emblem: asset + "logo.png", gallery: [asset + "gift.jpg", asset + "gift-gallery.jpg", asset + "gift-open.jpg", asset + "five-set.jpg"], swatches: ["#60734e", "#9c3b36", "#b8893c", "#e1d8c9", "#303735"], category: "set" },
  { id: "green", name: "青木", color: "青色", element: "木", beast: "青龙", mood: "草木清润", scent: "沉香 · 檀香 · 灵香 · 排草", story: "清凉木气转入柔润檀香，余韵微甜而清醒。留一缕草木气，陪伴阅读与日常。", price: 59, image: asset + "green.jpg", emblem: asset + "green-emblem-v2.png", gallery: [asset + "green.jpg", asset + "green-detail.jpg"], swatches: ["#8c9e78", "#627354", "#344a37"], category: "single" },
  { id: "red", name: "朱蜜", color: "赤色", element: "火", beast: "朱雀", mood: "暖甜明烈", scent: "檀香 · 沉香 · 降真香 · 琥珀", story: "木香中透出柔软蜜意，尾韵温厚。让一缕暖香，为相聚的时刻添一点温度。", price: 59, image: asset + "red.jpg", emblem: asset + "red-emblem-v2.png", gallery: [asset + "red.jpg", asset + "red-detail.jpg"], swatches: ["#bb5c52", "#953b36", "#672927"], category: "single" },
  { id: "gold", name: "黄檀", color: "黄色", element: "土", beast: "麒麟", mood: "温润从容", scent: "老檀香 · 温润木韵", story: "柔和的檀木香慢慢铺开，清甜而温润。在熟悉的日常里，留一点从容。", price: 59, image: asset + "gold.jpg", emblem: asset + "gold-emblem-v2.png", gallery: [asset + "gold.jpg"], swatches: ["#ddb266", "#b6812e", "#776141"], category: "single" },
  { id: "white", name: "白桂", color: "白色", element: "金", beast: "白虎", mood: "清简收敛", scent: "沉香 · 檀香 · 乳香 · 桂花", story: "干净木香与桂花的清甜相遇，乳香让尾韵更柔和。适合留给自己的一段安静时光。", price: 59, image: asset + "white.jpg", emblem: asset + "white-emblem-v2.png", gallery: [asset + "white.jpg", asset + "white-detail.jpg"], swatches: ["#f2eee5", "#dcd0bf", "#aaa69e"], category: "single" },
  { id: "black", name: "墨沉", color: "黑色", element: "水", beast: "玄武", mood: "幽沉安定", scent: "沉香 · 檀香 · 降香", story: "凉香绵长，木韵内敛，尾端留有温厚的木质甜意。适合独处、复盘与缓慢思考。", price: 59, image: asset + "black.jpg", emblem: asset + "black-emblem-v2.png", gallery: [asset + "black.jpg", asset + "black-detail-1.jpg", asset + "black-detail-2.jpg"], swatches: ["#161b1a", "#343a38", "#616b67"], category: "single" },
];

export const SCENT_DETAILS: Record<string, { label: string; notes: string; intro: string; aroma: string[] }> = {
  green: { label: "绿色系", notes: "沉香凉甜 · 檀木 · 灵香排草", intro: "清凉木气转入柔润檀香，余韵微甜而清醒。", aroma: ["凉甜沉香", "檀木与青草", "微甜灵香"] },
  black: { label: "黑色系", notes: "沉香木韵 · 岩兰草 · 广藿香", intro: "初闻像雨后沉木，最后落在温厚的广藿香上。", aroma: ["湿润沉木", "岩兰与土壤", "温厚广藿"] },
  gold: { label: "黄色系", notes: "老山檀 · 安息香 · 雪松", intro: "温暖檀木与柔甜安息香相遇，雪松收尾，稳而不闷。", aroma: ["温暖檀木", "柔甜安息香", "干净雪松"] },
  white: { label: "白色系", notes: "白檀 · 桂花 · 零陵香", intro: "白檀的干净木香里留一层淡甜，尾韵轻柔清简。", aroma: ["清净白檀", "淡甜桂花", "轻柔零陵香"] },
  red: { label: "红色系", notes: "降真香 · 蜂蜜 · 肉桂", intro: "降真香的明亮辛感转入柔软蜜意，肉桂在尾端添暖。", aroma: ["明亮降真香", "柔软蜂蜜", "温暖肉桂"] },
};
// 香调文案以用户指定的深色交互概念稿为准；不是商品成分检验声明。
PRODUCTS.forEach(product => {
  const details = SCENT_DETAILS[product.id];
  if (details) { product.scent = details.notes; product.story = details.intro; }
});
export const SINGLE_PRODUCTS = PRODUCTS.filter(item => item.category === "single");
export const ELEMENT_PRODUCT: Record<string, string> = { 木: "green", 火: "red", 土: "gold", 金: "white", 水: "black" };
export function productForElement(element: string): Product | undefined {
  return PRODUCTS.find(item => item.id === ELEMENT_PRODUCT[element]);
}
