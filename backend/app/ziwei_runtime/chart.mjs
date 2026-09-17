/**
 * 与 ziwei-doushu-main/lib/ziwei/algorithm.ts 使用同一套 iztro 排盘核心。
 * 本脚本只负责 stdin JSON -> stdout JSON；鉴权、校验、数据库持久化均在 Python API 层。
 */
import { astro } from "iztro";
import { Solar } from "lunar-javascript";

const BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"];
const STEMS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"];

function parseWuxingJu(name) {
  return ({ 二: 2, 三: 3, 四: 4, 五: 5, 六: 6 })[[...name].find((char) => "二三四五六".includes(char))] || 3;
}

function starList(palace) {
  const major = (palace.majorStars || []).map((star) => ({ name: star.name, type: "major", brightness: star.brightness || null, siHua: star.mutagen || null }));
  const minor = [...(palace.minorStars || []), ...(palace.adjectiveStars || [])]
    .map((star) => ({ name: star.name, type: "minor", brightness: star.brightness || null, siHua: star.mutagen || null }));
  return [...major, ...minor];
}

function buildChart(input) {
  const { year, month, day, hour, gender, name = null, location = null } = input;
  const astrolabe = astro.bySolar(`${year}-${month}-${day}`, hour, gender === "male" ? "男" : "女", true, "zh-CN");
  const solar = Solar.fromYmd(year, month, day);
  const lunar = solar.getLunar();
  const currentAge = new Date().getFullYear() - year;
  const palaces = astrolabe.palaces.map((palace) => {
    const daXianAge = palace.decadal?.range ? [palace.decadal.range[0], palace.decadal.range[1]] : null;
    return {
      branch: BRANCHES.indexOf(palace.earthlyBranch),
      stem: STEMS.indexOf(palace.heavenlyStem),
      name: palace.name,
      stars: starList(palace),
      daXianAge,
      isMingGong: palace.name === "命宫",
      isShenGong: Boolean(palace.isBodyPalace),
      isCurrentDaXian: Boolean(daXianAge && currentAge >= daXianAge[0] && currentAge <= daXianAge[1]),
    };
  });
  const daXians = palaces.filter((palace) => palace.daXianAge).sort((a, b) => a.daXianAge[0] - b.daXianAge[0])
    .map((palace) => ({ startAge: palace.daXianAge[0], endAge: palace.daXianAge[1], palaceBranch: palace.branch, palaceName: palace.name }));
  const ziweiPalace = palaces.find((palace) => palace.stars.some((star) => star.name === "紫微"));

  return {
    calculationVersion: "iztro-2.5.8",
    birthInfo: { year, month, day, hour, gender, name, location },
    lunarInfo: {
      lunarYear: lunar.getYear(), lunarMonth: Math.abs(lunar.getMonth()), lunarDay: lunar.getDay(),
      isLeapMonth: lunar.getMonth() < 0, lunarText: lunar.toString(),
      yearGanZhi: lunar.getYearInGanZhi(), monthGanZhi: lunar.getMonthInGanZhi(), dayGanZhi: lunar.getDayInGanZhi(), timeGanZhi: lunar.getTimeInGanZhi(),
    },
    mingGongBranch: BRANCHES.indexOf(astrolabe.earthlyBranchOfSoulPalace),
    shenGongBranch: BRANCHES.indexOf(astrolabe.earthlyBranchOfBodyPalace),
    wuxingJu: parseWuxingJu(astrolabe.fiveElementsClass), wuxingJuName: astrolabe.fiveElementsClass,
    ziweiPos: ziweiPalace?.branch ?? 0, palaces, daXians, currentAge,
    currentDaXianIndex: daXians.findIndex((item) => currentAge >= item.startAge && currentAge <= item.endAge),
  };
}

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  try { process.stdout.write(JSON.stringify(buildChart(JSON.parse(input)))); }
  catch (error) { process.stderr.write(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
});
