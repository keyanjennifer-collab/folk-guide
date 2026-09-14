const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');
const root = path.join(__dirname, '../miniprogram');
const cache = new Map(), storage = new Map();
let page, token = '', publicResult, requests = 0, lastSwitchTab = '';
const wx = {
  getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, value),
  showToast() {}, showModal() {}, switchTab: ({url}) => { lastSwitchTab=url; }, nextTick: fn => fn(), pageScrollTo() {},
};
function load(relative) {
  const file = path.resolve(root, relative);
  if (cache.has(file)) return cache.get(file);
  const source = fs.readFileSync(file, 'utf8');
  const output = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText;
  const module = {exports:{}};
  const localRequire = name => {
    if (name.endsWith('/services/api') || ((relative.endsWith('/orders.ts') || relative.endsWith('/daily.ts')) && name === './api')) return {
      getToken: () => token, getApiErrorMessage: (_, fallback) => fallback, isApiError: value => Boolean(value && value.__api),
      request: async () => { requests++; if (publicResult instanceof Error) throw publicResult; return publicResult; },
    };
    return load(path.relative(root, path.resolve(path.dirname(file), name + '.ts')));
  };
  vm.runInNewContext(output, {exports:module.exports, module, require:localRequire, wx, setTimeout, clearTimeout, Page: config => {page=config;}}, {filename:file});
  cache.set(file, module.exports);
  return module.exports;
}
function instance(file) {
  cache.delete(path.join(root, file));
  load(file);
  const target = {...page, data:structuredClone(page.data), setData(values) {Object.assign(this.data, values);}};
  return target;
}
function directoryBytes(directory) {
  return fs.readdirSync(directory, {withFileTypes:true}).reduce((total, entry) => {
    const file = path.join(directory, entry.name);
    return total + (entry.isDirectory() ? directoryBytes(file) : fs.statSync(file).size);
  }, 0);
}
async function main() {
  const app = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'));
  assert.equal(app.tabBar.list.length, 4);
  assert.equal(app.tabBar.custom, true);
  assert.equal(app.window.navigationBarTextStyle, 'white');
  assert.equal(app.window.navigationBarBackgroundColor.toLowerCase(), '#262626');
  assert.equal(app.tabBar.backgroundColor.toLowerCase(), '#262626');
  assert.equal(app.lazyCodeLoading, undefined, 'native tab pages must render without component lazy-loading');
  const homeWxml=fs.readFileSync(path.join(root,'pages/home/index.wxml'),'utf8');
  const homeWxss=fs.readFileSync(path.join(root,'pages/home/index.wxss'),'utf8');
  assert(!homeWxml.includes('today-subtitle') && !homeWxml.includes('calendar-pill'),'home hero stays compact');
  assert(!homeWxml.includes('今日色序') && !homeWxml.includes('today-hero'),'home combines the date and ranking into one 今日五色 card');
  assert.equal((homeWxml.match(/今日五色/g) || []).length,1,'home displays 今日五色 only once');
  assert(homeWxml.includes('{{solarDateLabel}}') && homeWxml.includes('{{lunarDateLabel}}'),'home displays both Gregorian and lunar dates');
  assert(homeWxml.includes('{{item.relationReason}}') && homeWxml.includes('日支取象'),'home explains the day-branch derivation and each color relation');
  assert(!homeWxml.includes('product.emblem'),'divine-beast emblems stay out of the home page');
  assert(homeWxss.includes('justify-content: center') && homeWxss.includes('linear-gradient(155deg'),'centered brand and full color gradients are retained');
  assert(directoryBytes(root) < 1.9 * 1024 * 1024, 'miniprogram source must retain margin below WeChat\'s 2 MB upload limit');
  const settingsWxss=fs.readFileSync(path.join(root,'pages/settings/index.wxss'),'utf8');
  assert(!/(^|[,>+~\s])(view|text|button|image|input|textarea|picker)(?=[.#:[>+~\s,{]|$)/m.test(settingsWxss),'settings component styles must use class selectors');
  const tabWxss=fs.readFileSync(path.join(root,'custom-tab-bar/index.wxss'),'utf8');
  assert(!/(^|[,>+~\s])(view|text|button|image|input|textarea|picker)(?=[.#:[>+~\s,{]|$)/m.test(tabWxss),'custom tab bar styles must use class selectors');
  for (const ext of ['ts','json','wxml','wxss']) assert(fs.existsSync(path.join(root,'custom-tab-bar/index.'+ext)));
  for (const item of app.tabBar.list) {
    assert(app.pages.includes(item.pagePath));
    for (const icon of [item.iconPath,item.selectedIconPath]) assert(fs.existsSync(path.join(root, icon)));
  }
  for (const route of app.pages) for (const ext of ['ts','wxml','wxss','json']) assert(fs.existsSync(path.join(root, route+'.'+ext)), route+'.'+ext);
  const {PRODUCTS} = load('data/products.ts');
  assert.equal(PRODUCTS.length,6);
  assert.equal(new Set(PRODUCTS.map(p=>p.id)).size,6);
  assert.equal(PRODUCTS.filter(p=>p.category==='single').map(p=>p.name).join('|'),'青木|朱蜜|黄檀|白桂|墨沉');
  assert(PRODUCTS.filter(p=>p.category==='single').every(p=>p.emblem.endsWith('-emblem-v2.png')),'all five beasts use the unified relief set');
  for (const p of PRODUCTS) for (const image of [p.image,p.emblem,...p.gallery]) assert(fs.existsSync(path.join(root,image)));
  assert.equal(PRODUCTS.find(p=>p.id==='gift').gallery.includes('/assets/brand/gift-gallery.jpg'),true,'gift detail includes the supplied five-color render');
  assert.equal(PRODUCTS.find(p=>p.id==='black').gallery.filter(image=>image.includes('black-detail')).length,2,'both supplied 墨沉 renders are retained');
  const productPage = instance('pages/product/index.ts');
  assert.equal(productPage.data.setContents,'青木、朱蜜、黄檀、白桂、墨沉。五款线香与对应矿石香插，承载一份应时心意。');
  productPage.toBag();
  assert.equal(storage.get('wuse-open-cart-on-show'),true,'product detail requests the shopping bag directly');
  assert.equal(lastSwitchTab,'/pages/caikuxiang/index');
  const shopPage=instance('pages/caikuxiang/index.ts');
  shopPage.onShow();
  assert.equal(shopPage.data.showCart,true,'shop opens its bag sheet when requested by product detail');
  assert.equal(storage.get('wuse-open-cart-on-show'),false);
  const shopWxml=fs.readFileSync(path.join(root,'pages/caikuxiang/index.wxml'),'utf8');
  assert(!shopWxml.includes('↗'),'shop removes emoji-style diagonal arrows from product cards');
  assert(shopWxml.includes('bag-total price-figure') && shopWxml.includes('product-price price-figure'),'shop applies the dedicated price numeral style');
  assert(shopWxml.includes('sale-dialog'),'shop uses the branded opening notice instead of a native modal');
  shopPage.checkout();
  assert.equal(shopPage.data.showSaleNotice,true);
  shopPage.closeSaleNotice();
  assert.equal(shopPage.data.showSaleNotice,false);
  const cart = load('services/cart.ts');
  assert.equal(cart.readCart().length,0);
  cart.changeCart('green',2);
  assert.equal(cart.readCart()[0].subtotal,118);
  cart.changeCart('green',200);
  assert.equal(cart.readCart()[0].quantity,99);
  cart.changeCart('green',-200);
  assert.equal(cart.readCart().length,0);
  cart.changeCart('unknown',1);
  assert.equal(cart.readCart().length,0);
  storage.set('wuse-shopping-bag-v1',[{id:'green',quantity:'bad'},{id:'red',quantity:-3}]);
  assert.equal(cart.readCart().length,0);
  const {isPublicRankingQuestion}=load('data/confirmed-colors.ts');
  assert.equal(isPublicRankingQuestion('今日五色排行'),true);
  assert.equal(isPublicRankingQuestion('明天穿什么颜色'),true);
  assert.equal(isPublicRankingQuestion('五色在传统文化中有什么含义'),false);
  const chat=instance('pages/chat/index.ts');
  assert(chat.data.messages.every(message=>Array.isArray(message.references)),'AI page initial messages must be render-safe');
  publicResult={guide_date:'2026-09-09',weekday:'星期三',lunar_date:'七月廿八',solar_term:'白露',day_ganzhi:'丙戌',
    items:[['白色系','金','白桂'],['黄色系','土','黄檀'],['绿色系','木','青木'],['红色系','火','朱蜜'],['黑色系','水','墨沉']].map((row,i)=>({rank:i+1,color:row[0],element:row[1],smoothness:['得生助旺','同气相和','克制求进','生泄耗气','受制势弱'][i],suitable:['整理'],resistance:'留意节奏',advice:'适量配色',product_code:row[2],incense_name:row[2],scent:'香气描述'})),
    share_title:'今日五色',share_summary:'今日公开资料',push_summary:'今日五色已更新',rule_version:'daily-rule-v1'};
  const homeRequests=requests;
  const home=instance('pages/home/index.ts');
  await home.loadToday();
  assert.equal(home.data.guides.length,5);
  assert.equal(home.data.scent.name,'白桂');
  assert.equal(home.data.solarDateLabel,'公历 2026年9月9日 · 星期三');
  assert.equal(home.data.lunarDateLabel,'农历七月廿八 · 丙戌日 · 白露');
  assert.equal(home.data.dayElement,'土');
  assert.equal(home.data.dayPillar,'丙戌');
  assert.equal(home.data.dayBranch,'戌');
  assert.equal(home.data.dayBasis,'今日为丙戌日，仅取日支“戌”。戌对应生肖狗，五行属土，因此今日以土为“我”。');
  assert.deepEqual(Array.from(home.data.guides, item=>item.relationReason),[
    '土生金，依“我生”取为贵人色', '土与土同气，依“同我”取为合作色', '木克土，依“克我”取为奋斗色',
    '火生土，依“生我”取为消耗色', '土克水，依“我克”取为不利色',
  ]);
  assert.equal(home.data.guides.map(g=>g.product.id).join(','),'white,gold,green,red,black');
  assert(home.data.guides.every(g=>g.suitable.length && g.resistance && g.advice && g.palette));
  assert.equal(home.data.guides.filter(g=>g.expanded).length,1,'only the first detail card starts expanded');
  assert.equal(requests,homeRequests+7,'home reads today and the next six server-published daily guides');
  assert.equal(home.data.dayOptions.length,7,'home exposes seven selectable daily guides');
  assert.equal(home.data.dayOptions.filter(item=>item.active).length,1,'only one daily guide is active');
  home.selectGuide({currentTarget:{dataset:{rank:4}}});
  assert.equal(home.data.scent.name,'朱蜜');
  home.toggleGuide({currentTarget:{dataset:{rank:2}}});
  assert.equal(home.data.guides.find(g=>g.rank===2).expanded,true);
  publicResult=new Error('network');
  await home.loadToday();
  assert.equal(home.data.contentSource,'error','network failures never relabel stale data as today');
  assert.equal(home.data.guides.length,0);
  const {SCENT_QUIZ,matchScent,QUIZ}=load('data/discovery.ts');
  for (const moment of SCENT_QUIZ[0].options) for (const note of SCENT_QUIZ[1].options) {
    assert(PRODUCTS.some(p=>p.id===matchScent(moment.id,note.id)), 'every taste combination yields an existing SKU');
  }
  assert.equal(matchScent('invalid','invalid'),null);
  for(const q of QUIZ) assert(q.options[q.answer] && q.source.startsWith('https://'));
  const orders=instance('pages/orders/index.ts'), before=requests;
  await orders.loadOrders();
  assert.equal(requests,before,'guest must not fetch personal orders');
  assert.equal(orders.data.loggedIn,false);
  const settings=instance('pages/settings/index.ts');
  settings.showHelp();
  assert.equal(settings.data.infoDialog.title,'使用帮助');
  assert(settings.data.infoDialog.sections.length>=5,'help explains all major areas in detail');
  settings.showAbout();
  assert.equal(settings.data.infoDialog.title,'关于我们');
  settings.closeInfo();
  assert.equal(settings.data.infoDialog,null);
  console.log('PASS: 4 tabs; 6 SKUs/assets; cart bounds; automatic rich daily guide; no stale fallback; public AI guard; scent matching; quiz sources; guest orders');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
