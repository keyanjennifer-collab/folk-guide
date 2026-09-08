const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');
const root = path.join(__dirname, '../miniprogram');
const cache = new Map(), storage = new Map();
let page, token = '', publicResult, requests = 0;
const wx = {
  getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, value),
  showToast() {}, showModal() {}, nextTick: fn => fn(), pageScrollTo() {},
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
async function main() {
  const app = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'));
  assert.equal(app.tabBar.list.length, 4);
  assert.equal(app.tabBar.custom, true);
  assert.equal(app.window.navigationBarTextStyle, 'white');
  assert.equal(app.window.navigationBarBackgroundColor.toLowerCase(), '#262626');
  assert.equal(app.tabBar.backgroundColor.toLowerCase(), '#262626');
  assert.equal(app.lazyCodeLoading, undefined, 'native tab pages must render without component lazy-loading');
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
  for (const p of PRODUCTS) for (const image of [p.image,p.emblem]) assert(fs.existsSync(path.join(root,image)));
  const productPage = instance('pages/product/index.ts');
  assert.equal(productPage.data.setContents,'青木、朱蜜、黄檀、白桂、墨沉。五款线香与对应矿石香插，承载一份应时心意。');
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
  publicResult={guide_date:'2026-09-07',weekday:'星期一',lunar_date:'七月廿五',solar_term:'白露前',day_ganzhi:'甲子',
    items:[['白色系','金','白桂'],['黄色系','土','黄檀'],['绿色系','木','青木'],['红色系','火','朱蜜'],['黑色系','水','墨沉']].map((row,i)=>({rank:i+1,color:row[0],element:row[1],smoothness:'比较合适',suitable:['整理'],resistance:'留意节奏',advice:'适量配色',product_code:row[2],incense_name:row[2],scent:'香气描述'})),
    share_title:'今日五色',share_summary:'今日公开资料',push_summary:'今日五色已更新',rule_version:'daily-rule-v1'};
  const homeRequests=requests;
  const home=instance('pages/home/index.ts');
  await home.loadToday();
  assert.equal(home.data.guides.length,5);
  assert.equal(home.data.scent.name,'白桂');
  assert.equal(home.data.guides.map(g=>g.product.id).join(','),'white,gold,green,red,black');
  assert(home.data.guides.every(g=>g.suitable.length && g.resistance && g.advice && g.palette));
  assert.equal(home.data.guides.filter(g=>g.expanded).length,1,'only the first detail card starts expanded');
  assert.equal(requests,homeRequests+1,'home reads the server-published daily guide');
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
  console.log('PASS: 4 tabs; 6 SKUs/assets; cart bounds; automatic rich daily guide; no stale fallback; public AI guard; scent matching; quiz sources; guest orders');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
