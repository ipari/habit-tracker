const composer = document.querySelector("#share-composer");
const canvas = document.querySelector("#share-canvas");
const statusMessage = document.querySelector("#share-status");
const shareButton = document.querySelector("#share-image");
const downloadButton = document.querySelector("#download-image");

const PRESETS = {
  dawn: ["#f39d72", "#815ac0"],
  forest: ["#174f36", "#70a37f"],
  ocean: ["#075985", "#38bdf8"],
  sunset: ["#9f1239", "#fb923c"],
  lavender: ["#6d28d9", "#c4b5fd"],
  citrus: ["#a16207", "#facc15"],
  midnight: ["#020617", "#334155"],
  rose: ["#9f1239", "#fda4af"],
  sky: ["#0369a1", "#bae6fd"],
  stone: ["#44403c", "#a8a29e"],
};

function setStatus(message) {
  if (statusMessage) {
    statusMessage.textContent = message;
  }
}

function splitLines(context, text, maxWidth, maxLines) {
  const characters = Array.from(text.trim());
  const lines = [];
  let current = "";
  for (const character of characters) {
    const candidate = current + character;
    if (current && context.measureText(candidate).width > maxWidth) {
      lines.push(current);
      current = character;
      if (lines.length === maxLines - 1) {
        break;
      }
    } else {
      current = candidate;
    }
  }
  const consumed = lines.join("").length + current.length;
  if (consumed < characters.length) {
    while (current && context.measureText(`${current}…`).width > maxWidth) {
      current = Array.from(current).slice(0, -1).join("");
    }
    current = `${current}…`;
  }
  if (current) {
    lines.push(current);
  }
  return lines;
}

function drawShareImage() {
  if (!(composer instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement)) {
    return false;
  }
  const context = canvas.getContext("2d");
  if (!context) {
    return false;
  }
  const name = composer.dataset.habitName || "나의 습관";
  const emoji = composer.dataset.habitEmoji || "✨";
  const totalCount = Number.parseInt(composer.dataset.totalCount || "0", 10);
  const longestStreak = Number.parseInt(composer.dataset.longestStreak || "0", 10);
  const currentStreak = Number.parseInt(composer.dataset.currentStreak || "0", 10);
  const startLabel = composer.dataset.startLabel || "";
  const colors = PRESETS[composer.dataset.preset] || PRESETS.dawn;

  const gradient = context.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, colors[0]);
  gradient.addColorStop(1, colors[1]);
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.fillStyle = "rgb(0 0 0 / 24%)";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "rgb(255 255 255 / 10%)";
  context.beginPath();
  context.arc(900, 260, 330, 0, Math.PI * 2);
  context.fill();
  context.beginPath();
  context.arc(120, 1710, 430, 0, Math.PI * 2);
  context.fill();

  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "#ffffff";
  context.shadowColor = "rgb(0 0 0 / 30%)";
  context.shadowBlur = 24;
  let emojiSize = 190;
  context.font = `${emojiSize}px "Apple Color Emoji", "Noto Color Emoji", sans-serif`;
  while (emojiSize > 80 && context.measureText(emoji).width > 720) {
    emojiSize -= 10;
    context.font = `${emojiSize}px "Apple Color Emoji", "Noto Color Emoji", sans-serif`;
  }
  context.fillText(emoji, 540, 570);

  context.font = '700 108px -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif';
  const lines = splitLines(context, name, 860, 3);
  const lineHeight = 132;
  const firstLineY = 900 - ((lines.length - 1) * lineHeight) / 2;
  lines.forEach((line, index) => context.fillText(line, 540, firstLineY + index * lineHeight));

  const achievementStats = [
    ["현재 연속 달성", Number.isNaN(currentStreak) ? 0 : currentStreak],
    ["최장 연속 달성", Number.isNaN(longestStreak) ? 0 : longestStreak],
    ["총 달성", Number.isNaN(totalCount) ? 0 : totalCount],
  ];
  context.shadowColor = "rgb(0 0 0 / 22%)";
  context.shadowBlur = 10;
  achievementStats.forEach(([label, value], index) => {
    const centerX = 210 + index * 330;
    context.font = '600 30px -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif';
    context.fillStyle = "rgb(255 255 255 / 82%)";
    context.fillText(label, centerX, 1190);
    context.font = '700 76px -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif';
    context.fillStyle = "#ffffff";
    context.fillText(String(value), centerX, 1280);
  });

  context.shadowBlur = 0;
  context.strokeStyle = "rgb(255 255 255 / 20%)";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(375, 1155);
  context.lineTo(375, 1325);
  context.moveTo(705, 1155);
  context.lineTo(705, 1325);
  context.stroke();

  context.font = '500 38px -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif';
  context.fillStyle = "rgb(255 255 255 / 82%)";
  context.fillText(startLabel, 540, 1440);

  context.font = '600 30px -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif';
  context.letterSpacing = "8px";
  context.fillStyle = "rgb(255 255 255 / 78%)";
  context.fillText("HABIT TRACKER", 540, 1750);
  return true;
}

function canvasBlob() {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error("PNG 이미지를 생성하지 못했습니다."));
      }
    }, "image/png");
  });
}

function fileName() {
  const rawName = composer?.dataset.habitName || "habit-streak";
  const safeName = rawName.replaceAll(/[^\p{L}\p{N}_-]+/gu, "-").replaceAll(/^-|-$/g, "");
  return `${safeName || "habit-streak"}.png`;
}

async function downloadImage() {
  shareButton.disabled = true;
  downloadButton.disabled = true;
  setStatus("PNG를 준비하고 있습니다.");
  try {
    const blob = await canvasBlob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName();
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setStatus("PNG 다운로드를 시작했습니다.");
  } catch {
    setStatus("PNG를 다운로드하지 못했습니다. 잠시 후 다시 시도해 주세요.");
  } finally {
    shareButton.disabled = false;
    downloadButton.disabled = false;
  }
}

async function shareImage() {
  shareButton.disabled = true;
  downloadButton.disabled = true;
  setStatus("공유 이미지를 준비하고 있습니다.");
  try {
    const blob = await canvasBlob();
    const file = new File([blob], fileName(), { type: "image/png" });
    if (!navigator.share || !navigator.canShare?.({ files: [file] })) {
      setStatus("이 브라우저는 이미지 파일 공유를 지원하지 않습니다. PNG 다운로드를 이용해 주세요.");
      return;
    }
    await navigator.share({ files: [file], title: `${composer.dataset.habitName} 습관 기록` });
    setStatus("공유 요청을 완료했습니다.");
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      setStatus("공유를 취소했습니다. 필요하면 PNG로 다운로드할 수 있습니다.");
    } else {
      setStatus("공유하지 못했습니다. PNG 다운로드를 이용해 주세요.");
    }
  } finally {
    shareButton.disabled = false;
    downloadButton.disabled = false;
  }
}

async function prepareShareImage() {
  if (!composer || !canvas || !shareButton || !downloadButton) {
    return;
  }
  try {
    await document.fonts?.ready;
    if (!drawShareImage()) {
      throw new Error("미리보기를 그리지 못했습니다.");
    }
    composer.querySelector(".share-preview-frame")?.setAttribute("aria-busy", "false");
    shareButton.disabled = false;
    downloadButton.disabled = false;
    setStatus("");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "공유 이미지를 준비하지 못했습니다.");
  }
}

shareButton?.addEventListener("click", shareImage);
downloadButton?.addEventListener("click", downloadImage);
prepareShareImage();
