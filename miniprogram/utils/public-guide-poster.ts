export const PUBLIC_GUIDE_POSTER_WIDTH = 1080;
export const PUBLIC_GUIDE_POSTER_HEIGHT = 1620;

export interface PublicGuidePosterItem {
  rank: number;
  name: string;
  element: string;
  tier: string;
  status: string;
  palette: string;
  advice: string;
  resistance: string;
  swatches: string[];
}

export interface PublicGuidePosterData {
  solarDate: string;
  lunarDate: string;
  summary: string;
  items: PublicGuidePosterItem[];
}

type CanvasNode = WechatMiniprogram.Canvas;
type CanvasImage = WechatMiniprogram.Image;
type CanvasContext = WechatMiniprogram.CanvasRenderingContext.CanvasRenderingContext2D;

const POSTER_COLORS = {
  background: "#252422",
  panel: "#34312d",
  panelBorder: "#5a5147",
  gold: "#d5a56b",
  cream: "#f1e6d6",
  body: "#d0c4b5",
  muted: "#9f9589",
};

function roundedRect(
  context: CanvasContext,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): void {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + safeRadius, y);
  context.lineTo(x + width - safeRadius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + safeRadius);
  context.lineTo(x + width, y + height - safeRadius);
  context.quadraticCurveTo(x + width, y + height, x + width - safeRadius, y + height);
  context.lineTo(x + safeRadius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - safeRadius);
  context.lineTo(x, y + safeRadius);
  context.quadraticCurveTo(x, y, x + safeRadius, y);
  context.closePath();
}

function clipText(context: CanvasContext, text: string, maxWidth: number): string {
  if (context.measureText(text).width <= maxWidth) return text;
  let result = text;
  while (result.length > 1 && context.measureText(`${result}…`).width > maxWidth) {
    result = result.slice(0, -1);
  }
  return `${result}…`;
}

function splitTextLines(context: CanvasContext, text: string, maxWidth: number, maxLines: number): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return [];
  const lines: string[] = [];
  let current = "";
  for (const character of normalized) {
    const candidate = current + character;
    if (current && context.measureText(candidate).width > maxWidth) {
      lines.push(current);
      current = character;
      if (lines.length === maxLines) break;
    } else {
      current = candidate;
    }
  }
  if (lines.length < maxLines && current) lines.push(current);
  if (lines.length === maxLines && normalized !== lines.join("")) {
    lines[maxLines - 1] = clipText(context, `${lines[maxLines - 1]}…`, maxWidth);
  }
  return lines;
}

function loadCanvasImage(canvas: CanvasNode, source: string): Promise<CanvasImage> {
  return new Promise((resolve, reject) => {
    const image = canvas.createImage();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`poster-image-load-failed:${source}`));
    image.src = source;
  });
}

function drawBackground(context: CanvasContext): void {
  const gradient = context.createLinearGradient(0, 0, PUBLIC_GUIDE_POSTER_WIDTH, PUBLIC_GUIDE_POSTER_HEIGHT);
  gradient.addColorStop(0, "#403b35");
  gradient.addColorStop(0.42, POSTER_COLORS.background);
  gradient.addColorStop(1, "#1f1f1e");
  context.fillStyle = gradient;
  context.fillRect(0, 0, PUBLIC_GUIDE_POSTER_WIDTH, PUBLIC_GUIDE_POSTER_HEIGHT);

  context.save();
  context.globalAlpha = 0.08;
  context.strokeStyle = POSTER_COLORS.gold;
  context.lineWidth = 2;
  [240, 420, 610].forEach((radius) => {
    context.beginPath();
    context.arc(1040, 70, radius, 0, Math.PI * 2);
    context.stroke();
  });
  context.restore();
}

function drawHeader(context: CanvasContext, data: PublicGuidePosterData): void {
  context.fillStyle = POSTER_COLORS.gold;
  context.font = "34px serif";
  context.fillText("五色知时", 72, 84);
  context.fillStyle = POSTER_COLORS.muted;
  context.font = "20px sans-serif";
  context.fillText("WUSE ZHISHI · DAILY GUIDANCE", 72, 116);

  context.fillStyle = POSTER_COLORS.cream;
  context.font = "bold 72px serif";
  context.fillText("今日公共五色", 72, 220);
  context.fillStyle = POSTER_COLORS.gold;
  context.font = "28px sans-serif";
  context.fillText(data.solarDate, 72, 272);
  context.fillStyle = POSTER_COLORS.body;
  context.font = "25px sans-serif";
  context.fillText(clipText(context, data.lunarDate, 820), 72, 313);

  context.font = "27px sans-serif";
  context.fillStyle = POSTER_COLORS.body;
  splitTextLines(context, data.summary, 900, 2).forEach((line, index) => {
    context.fillText(line, 72, 362 + index * 42);
  });
}

function drawRankingItem(context: CanvasContext, item: PublicGuidePosterItem, y: number): void {
  const x = 72;
  const width = 936;
  const height = 164;
  roundedRect(context, x, y, width, height, 22);
  context.fillStyle = POSTER_COLORS.panel;
  context.fill();
  context.strokeStyle = POSTER_COLORS.panelBorder;
  context.lineWidth = 1.5;
  context.stroke();

  const accent = item.swatches[0] || POSTER_COLORS.gold;
  context.save();
  roundedRect(context, x, y, 15, height, 8);
  context.fillStyle = accent;
  context.fill();
  context.restore();

  context.fillStyle = POSTER_COLORS.gold;
  context.font = "32px sans-serif";
  context.fillText(`0${item.rank}`, 104, y + 55);
  context.fillStyle = POSTER_COLORS.cream;
  context.font = "bold 40px serif";
  context.fillText(item.name, 184, y + 55);

  context.font = "23px sans-serif";
  context.fillStyle = POSTER_COLORS.gold;
  context.fillText(`${item.element} · ${item.tier} · ${item.status}`, 390, y + 52);

  item.swatches.slice(0, 3).forEach((color, index) => {
    roundedRect(context, 836 + index * 43, y + 25, 34, 34, 8);
    context.fillStyle = color;
    context.fill();
    context.strokeStyle = "rgba(255,255,255,0.32)";
    context.lineWidth = 1;
    context.stroke();
  });

  context.fillStyle = POSTER_COLORS.body;
  context.font = "24px sans-serif";
  context.fillText(clipText(context, `穿衣色：${item.palette}`, 770), 104, y + 99);
  context.fillStyle = POSTER_COLORS.muted;
  context.font = "23px sans-serif";
  context.fillText(clipText(context, `搭配：${item.advice} · 少用：${item.resistance}`, 820), 104, y + 137);
}

function drawFooter(context: CanvasContext, qrCode: CanvasImage): void {
  const qrSize = 244;
  const qrX = PUBLIC_GUIDE_POSTER_WIDTH - 72 - qrSize;
  const qrY = PUBLIC_GUIDE_POSTER_HEIGHT - 72 - qrSize;

  context.fillStyle = POSTER_COLORS.gold;
  context.font = "32px serif";
  context.fillText("五色应时，知时而行", 72, 1400);
  context.fillStyle = POSTER_COLORS.body;
  context.font = "24px sans-serif";
  context.fillText("长按识别右侧小程序码", 72, 1446);
  context.fillStyle = POSTER_COLORS.muted;
  context.font = "21px sans-serif";
  context.fillText("传统文化与日常生活参考", 72, 1500);
  context.fillText("请结合实际情境判断", 72, 1534);

  roundedRect(context, qrX - 10, qrY - 10, qrSize + 20, qrSize + 20, 22);
  context.fillStyle = "#ffffff";
  context.fill();
  context.drawImage(qrCode, qrX, qrY, qrSize, qrSize);
}

/**
 * 只绘制公共结果，不读取用户档案，避免把个人五色带入可公开分享的海报。
 */
export async function drawPublicGuidePoster(
  canvas: CanvasNode,
  data: PublicGuidePosterData,
  qrCodePath: string,
): Promise<void> {
  if (data.items.length !== 5) throw new Error("poster-requires-five-public-colors");
  canvas.width = PUBLIC_GUIDE_POSTER_WIDTH;
  canvas.height = PUBLIC_GUIDE_POSTER_HEIGHT;
  const context = canvas.getContext("2d");
  drawBackground(context);
  drawHeader(context, data);
  data.items.forEach((item, index) => drawRankingItem(context, item, 430 + index * 178));
  const qrCode = await loadCanvasImage(canvas, qrCodePath);
  drawFooter(context, qrCode);
}
