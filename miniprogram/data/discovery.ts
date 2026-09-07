/** 兴趣探索，不收集年龄/性格数据，也不作健康、运势或效果判断。 */
export const SCENT_QUIZ = [
  { title:"这段时间，想留给什么？", options:[{id:"read",label:"读书 · 独处"},{id:"gather",label:"相聚 · 闲聊"},{id:"home",label:"居家 · 慢下来"}] },
  { title:"哪一种气息更吸引你？", options:[{id:"fresh",label:"清润草木"},{id:"sweet",label:"柔和花甜"},{id:"wood",label:"温厚木韵"}] },
];
export function matchScent(moment: string, note: string): string | null {
  if (!SCENT_QUIZ[0].options.some(o=>o.id===moment) || !SCENT_QUIZ[1].options.some(o=>o.id===note)) return null;
  if (note==="fresh") return "green";
  if (note==="sweet") return moment==="gather" ? "red" : "white";
  return moment==="read" ? "black" : "gold";
}
export const DAILY_IDEAS = [
  {title:"给今天留一个颜色",tag:"散步 · 摄影",copy:"留意窗边或路上的一种颜色。拍一张不加滤镜的照片，给它起个只有你知道的名字。"},
  {title:"把一段旧时光聊回来",tag:"家人 · 相聚",copy:"和家人聊聊小时候最熟悉的一种气味。不急着找答案，听听同一个季节在不同人记忆里的样子。"},
  {title:"用三句话记下此刻",tag:"书写 · 独处",copy:"写下眼前看到的、耳边听到的，以及此刻最想做的一件小事。写给自己就好，不必发布。"},
  {title:"一起猜一题",tag:"朋友 · 共读",copy:"打开「国学一题」，轮流说出自己的答案，再看看解析。答错也能成为一段有趣的闲聊。"},
];
export const QUIZ = [
  {question:"传统纹样里的「岁寒三友」指什么？",options:["松、竹、梅","兰、菊、荷","桃、李、杏"],answer:0,explanation:"松、竹、梅合称岁寒三友，也是器物与绘画中常见的组合。",sourceTitle:"故宫博物院 · 岁寒三友纹杯",source:"https://www.dpm.org.cn/collection/bamboo/230731.html"},
  {question:"二十四节气主要依据什么形成？",options:["月亮的圆缺","太阳的周年运动","每个月的第一天"],answer:1,explanation:"二十四节气源于对太阳周年运动与时令变化的观察，并不是按月亮圆缺划分。",sourceTitle:"中国非遗网 · 二十四节气",source:"https://www.ihchina.cn/solar_terms.html"},
  {question:"「岁寒三友图」中，哪一项不在其中？",options:["竹","梅","荷"],answer:2,explanation:"岁寒三友的组合是松、竹、梅。观察传统器物时，可以试着找一找这些纹样。",sourceTitle:"中国国家博物馆 · 青花松竹梅纹盘",source:"https://www.chnmuseum.cn/zp/zpml/201812/t20181218_23818.shtml"},
];
