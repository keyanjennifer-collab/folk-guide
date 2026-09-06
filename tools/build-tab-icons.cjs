// 用矢量线条生成微信原生 tabBar 所需 PNG；不依赖远程图片。
const sharp = require('sharp');
const path = require('node:path');
const fs = require('node:fs/promises');
const icons = {
  today: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2M1 12h2m18 0h2"/>',
  shop: '<path d="M5 7h14l1 14H4L5 7Z"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/>',
  ai: '<path d="M12 5C8 2 3 3 3 3v16s5-1 9 2c4-3 9-2 9-2V3s-5-1-9 2v16M6 8l3 1m-3 3 3 1m6-4 3-1m-3 5 3-1"/>',
  mine: '<circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
};
async function main() {
  const dir = path.join(__dirname, '../miniprogram/assets/nav');
  await fs.mkdir(dir, {recursive:true});
  for (const [name, shape] of Object.entries(icons)) {
    for (const [suffix, color] of [['', '#97866c'], ['-active', '#e1b97f']]) {
      const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 24 24" fill="none" stroke="'+color+'" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">'+shape+'</svg>';
      await sharp(Buffer.from(svg)).png().toFile(path.join(dir, name+suffix+'.png'));
    }
  }
}
main().catch(error => { console.error(error); process.exitCode=1; });
