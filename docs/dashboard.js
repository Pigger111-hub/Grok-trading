"use strict";

// Reads docs/data/dashboard.json and only changes how the numbers are shown.
// START_DOLLARS matches crypto_lab.assumptions.INITIAL_CASH.
const START_DOLLARS = 10000;
const STALE_HOURS = 8;
const COINS = ["BTC", "ETH"];

const STRATEGY_INFO = {
  sma_filter: {
    title: "เส้นค่าเฉลี่ย 200 วัน (SMA 200)",
    title4h: "เส้นค่าเฉลี่ย 200 แท่ง (SMA 200)",
    short: "เส้น 200 วัน",
    short4h: "เส้น 200 แท่ง",
    caption: "ถือเหรียญเมื่อราคาปิดอยู่เหนือเส้นค่าเฉลี่ย แล้วถือเงินสดเมื่อหลุดเส้น",
    caption4h: "กติกาเดียวกัน แต่คิดจากแท่ง 4 ชั่วโมง 200 แท่ง ประมาณ 33 วัน ไม่ใช่ 200 วัน",
    href: "#term-sma",
    token1d: "--s-sma-1d",
    token4h: "--s-sma-4h",
  },
  macd: {
    title: "แมคดี (MACD)",
    short: "แมคดี",
    caption: "ถือเหรียญเมื่อเส้นเร็วอยู่เหนือเส้นช้า แล้วถือเงินสดเมื่อหลุด",
    href: "#term-macd",
    token1d: "--s-macd-1d",
    token4h: "--s-macd-4h",
  },
  donchian: {
    title: "กรอบดอนเชียน (Donchian)",
    short: "ดอนเชียน",
    caption: "ซื้อเมื่อราคาทะลุกรอบสูง ขายเมื่อหลุดกรอบต่ำ",
    href: "#term-donchian",
    token1d: "--s-don-1d",
    token4h: "--s-don-4h",
  },
  trend_vol: {
    title: "คะแนนเทรนด์ + เป้าความแกว่ง 40%",
    short: "คะแนนเทรนด์",
    caption: "เงินสมมติเท่านั้น ถือบางส่วนตาม 5 กติกา แล้วลดขนาดเมื่อราคาแกว่งแรงกว่า 40% ต่อปี ไม่ได้ส่งคำสั่งจริง",
    href: "#term-trend",
    token1d: "--s-trend-1d",
    token4h: "--s-trend-1d",
  },
  buy_and_hold: {
    title: "ซื้อแล้วถือเฉยๆ",
    short: "ซื้อแล้วถือ",
    caption: "ซื้อครั้งเดียวตอนเริ่ม แล้วไม่ขาย เป็นตัวเทียบ ไม่ใช่วิธีที่เลือก",
    href: "#term-bh",
    token1d: "--s-bench",
    token4h: "--s-bench",
  },
};

const FALLBACK_INFO = {
  title: "วิธีนี้",
  caption: "กติกาซื้อขายเงินสมมติ",
  href: "#glossary",
  token1d: "--s-bench",
  token4h: "--s-bench",
};

const DAY_SECONDS = 24 * 60 * 60;

let pageData = null;
let currentAsset = "BTC";
let visible = new Set();
let priceChart = null;
let equityChart = null;
let priceObserver = null;
let equityObserver = null;

function portfolioValue(row) {
  const cash = Number(row.cash);
  const market = Number(row.market_value);
  if (!Number.isFinite(cash) || !Number.isFinite(market)) return null;
  return cash + market;
}

function priceIsStale(unixSeconds, nowMs, hours) {
  const limit = hours == null ? STALE_HOURS : hours;
  if (unixSeconds == null || nowMs == null) return true;
  return nowMs - Number(unixSeconds) * 1000 > limit * 60 * 60 * 1000;
}

function rankRows(rows) {
  const list = (rows || []).map((row) => ({ ...row, value: portfolioValue(row) }));
  const benchmark = list.find((row) => row.strategy === "buy_and_hold") || null;
  const ranked = list
    .filter((row) => row.strategy !== "buy_and_hold")
    .sort((a, b) => {
      const av = a.value == null ? -Infinity : a.value;
      const bv = b.value == null ? -Infinity : b.value;
      if (bv !== av) return bv - av;
      const byName = String(a.strategy).localeCompare(String(b.strategy));
      if (byName !== 0) return byName;
      return String(a.timeframe).localeCompare(String(b.timeframe));
    });
  return { rows: ranked, best: ranked[0] || null, benchmark };
}

function seriesKey(row) {
  return row.strategy + "|" + row.timeframe;
}

function defaultSeriesKeys(rows) {
  const ranked = rankRows(rows);
  const top = ranked.rows.slice(0, 3).map(seriesKey);
  const bench = ranked.benchmark ? [seriesKey(ranked.benchmark)] : [];
  return top.concat(bench);
}

function coinName(asset) {
  if (asset === "BTC") return "บิตคอยน์ (BTC)";
  if (asset === "ETH") return "อีเธอเรียม (ETH)";
  return String(asset);
}

function strategyInfo(strategy, timeframe) {
  const info = STRATEGY_INFO[strategy] || { ...FALLBACK_INFO, title: strategy };
  const intraday = timeframe === "4h";
  const title = intraday && info.title4h ? info.title4h : info.title;
  const short = intraday && info.short4h ? info.short4h : info.short || title;
  return {
    title,
    short,
    caption: intraday && info.caption4h ? info.caption4h : info.caption,
    href: info.href,
    color: cssColor(intraday ? info.token4h : info.token1d, "#7a8394"),
  };
}

// ---------- colours: the stylesheet is the single source ----------

const colorCache = new Map();

function cssColor(token, fallback) {
  if (typeof document === "undefined" || typeof getComputedStyle === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  if (!raw) return fallback;
  if (colorCache.has(raw)) return colorCache.get(raw);
  // Canvas-based charts do not read oklch(), so resolve through a 1px canvas.
  let out = fallback;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.fillStyle = "#010203";
    ctx.fillStyle = raw;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    if (!(r === 1 && g === 2 && b === 3)) out = "rgb(" + r + "," + g + "," + b + ")";
  } catch (error) {
    out = fallback;
  }
  colorCache.set(raw, out);
  return out;
}

function withAlpha(rgb, alpha) {
  const match = /^rgb\((\d+),(\d+),(\d+)\)$/.exec(rgb || "");
  if (!match) return rgb;
  return "rgba(" + match[1] + "," + match[2] + "," + match[3] + "," + alpha + ")";
}

function clockLabel(timeframe) {
  return timeframe === "4h" ? "ดูทุก 4 ชั่วโมง" : "ดูวันละครั้ง";
}

function numberText(value, digits) {
  return Number(value).toLocaleString("th-TH-u-nu-latn", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function dollars(value) {
  if (value == null || !Number.isFinite(Number(value))) return "ไม่มีตัวเลข";
  return numberText(Math.round(Number(value)), 0) + " ดอลลาร์";
}

function describePnl(value, start) {
  const base = start == null ? START_DOLLARS : start;
  if (value == null || !Number.isFinite(Number(value))) return { tone: "flat", label: "ไม่มีตัวเลข" };
  const diff = Number(value) - base;
  if (Math.abs(diff) < 0.5) return { tone: "flat", label: "เท่าทุน" };
  const pct = numberText(Math.abs((diff / base) * 100), 1);
  if (diff > 0) return { tone: "good", label: "กำไร " + pct + "%" };
  return { tone: "bad", label: "ขาดทุน " + pct + "%" };
}

function describeGap(value, benchmark) {
  if (value == null || benchmark == null) return { tone: "flat", label: "ยังเทียบกับซื้อแล้วถือไม่ได้" };
  const diff = Number(value) - Number(benchmark);
  if (Math.abs(diff) < 0.5) return { tone: "flat", label: "พอ ๆ กับซื้อแล้วถือ" };
  const amount = numberText(Math.abs(Math.round(diff)), 0);
  if (diff > 0) return { tone: "good", label: "มากกว่าซื้อแล้วถือ " + amount + " ดอลลาร์" };
  return { tone: "bad", label: "น้อยกว่าซื้อแล้วถือ " + amount + " ดอลลาร์" };
}

function holdingOf(row) {
  const weight = Number(row.weight);
  const partial = row.side === "partial" || row.side_th === "ถือบางส่วน";
  if (partial) {
    const pct = Number.isFinite(weight) ? " " + Math.round(weight * 100) + "%" : "";
    return {
      title: "ถือบางส่วน" + pct,
      caption: "เงินสมมติบางส่วนอยู่ในเหรียญ ที่เหลือเป็นเงินสด ราคาขึ้นลงมีผลแค่ส่วนที่ถือ",
      klass: "partial",
    };
  }
  if (row.side === "long" || row.side_th === "ถือเหรียญ") {
    return {
      title: "ถือเหรียญ",
      caption: "เงินอยู่ในเหรียญ ราคาขึ้นลงมีผลกับก้อนนี้",
      klass: "coin",
    };
  }
  return {
    title: "ถือเงินสด",
    caption: "ขายเหรียญแล้ว เก็บเป็นดอลลาร์ ราคาขึ้นลงไม่มีผลกับก้อนนี้",
    klass: "cash",
  };
}

function parseStamp(value) {
  if (!value) return null;
  const raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return new Date(raw + "T00:00:00Z");
  let text = raw;
  if (text.endsWith(" UTC")) text = text.slice(0, -4).trim() + "Z";
  if (/^\d{4}-\d{2}-\d{2} /.test(text)) text = text.replace(" ", "T");
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) text += ":00Z";
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(text)) text += "Z";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

function parseBangkokWall(value) {
  if (!value) return null;
  let text = String(value).trim().replace(" ", "T");
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) text += ":00";
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(text)) text += "+07:00";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(date, withTime) {
  if (!date) return "ไม่ทราบเวลา";
  const options = {
    timeZone: "Asia/Bangkok",
    year: "numeric",
    month: "short",
    day: "numeric",
    numberingSystem: "latn",
  };
  if (withTime) {
    options.hour = "2-digit";
    options.minute = "2-digit";
    options.hourCycle = "h23";
  }
  const text = new Intl.DateTimeFormat("th-TH", options).format(date);
  return withTime ? text + " น." : text;
}

function formatStamp(value) {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
  return formatDate(parseStamp(value), !dateOnly);
}

function formatUnix(unix) {
  if (unix == null) return "ไม่ทราบเวลา";
  return formatDate(new Date(Number(unix) * 1000), true);
}

function latestPriceUnix(data, asset) {
  const candles = data.candles && data.candles[asset];
  if (candles && candles.length) return candles[candles.length - 1].time;
  const position = (data.positions || []).find((row) => row.asset === asset && row.as_of);
  if (!position) return null;
  const date = parseStamp(position.as_of);
  return date ? Math.floor(date.getTime() / 1000) : null;
}

function rowsFor(data, asset) {
  return (data.positions || []).filter((row) => row.asset === asset);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function ticker(asset) {
  return asset === "BTC" || asset === "ETH" ? asset : String(asset);
}

function formatChip(unix) {
  if (unix == null) return "ไม่ทราบเวลา";
  const date = new Date(Number(unix) * 1000);
  const day = new Intl.DateTimeFormat("th-TH-u-nu-latn", {
    timeZone: "Asia/Bangkok",
    day: "numeric",
    month: "short",
  }).format(date);
  const time = new Intl.DateTimeFormat("th-TH-u-nu-latn", {
    timeZone: "Asia/Bangkok",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
  return day + " " + time;
}

function tip(text) {
  const wrap = el("span", "tip");
  const button = el("button", "tip-btn", "?");
  button.type = "button";
  button.setAttribute("aria-label", "คำอธิบาย");
  button.setAttribute("aria-expanded", "false");
  const bubble = el("span", "tip-bubble", text);
  bubble.setAttribute("role", "tooltip");
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const open = !wrap.classList.contains("open");
    document.querySelectorAll(".tip.open").forEach((node) => node.classList.remove("open"));
    wrap.classList.toggle("open", open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
  });
  wrap.append(button, bubble);
  return wrap;
}

function renderUpdated(data) {
  const list = document.getElementById("updated-list");
  list.replaceChildren();
  COINS.forEach((asset) => {
    const unix = latestPriceUnix(data, asset);
    const item = el("li", "update-chip", ticker(asset) + " · " + formatUnix(unix));
    list.append(item);
  });
  const generated = document.getElementById("generated");
  const built = parseBangkokWall(data.updated_bangkok);
  const parts = [];
  if (built) parts.push("สร้างหน้านี้เมื่อ " + formatDate(built, true));
  const asOf = parseStamp(data.price_as_of);
  if (asOf) parts.push("เวลาอ้างอิงของชุดข้อมูล (เหรียญที่เก่าสุด) คือ " + formatDate(asOf, true));
  generated.textContent = parts.join(" ");
}

function renderStale(data, nowMs) {
  const now = nowMs == null ? Date.now() : nowMs;
  return COINS.filter((asset) => priceIsStale(latestPriceUnix(data, asset), now));
}

// ---------- what changed in the last 24 hours ----------
// Pure helpers first, so they can be tested without a browser.

function equityAt(points, unix) {
  if (!points || !points.length || unix == null) return null;
  let found = null;
  for (let i = 0; i < points.length; i += 1) {
    if (points[i].time <= unix) found = points[i];
    else break;
  }
  return found ? found.value * 100 : null;
}

function latestEquityTime(book) {
  let latest = null;
  Object.keys(book || {}).forEach((key) => {
    const points = book[key];
    if (points && points.length) {
      const t = points[points.length - 1].time;
      if (latest == null || t > latest) latest = t;
    }
  });
  return latest;
}

function dayChanges(book) {
  const now = latestEquityTime(book);
  const out = {};
  if (now == null) return out;
  Object.keys(book || {}).forEach((key) => {
    const today = equityAt(book[key], now);
    const before = equityAt(book[key], now - DAY_SECONDS);
    const diff = today != null && before != null ? today - before : null;
    out[key] = {
      now: today,
      before,
      diff,
      pct: diff != null && before ? (diff / before) * 100 : null,
    };
  });
  return out;
}

function rankMoves(rows, book) {
  // Positive move = climbed the table since the same time yesterday.
  const ranked = rankRows(rows).rows;
  const changes = dayChanges(book);
  const yesterday = ranked
    .map((row) => ({ key: seriesKey(row), before: changes[seriesKey(row)] ? changes[seriesKey(row)].before : null }))
    .sort((a, b) => {
      const av = a.before == null ? -Infinity : a.before;
      const bv = b.before == null ? -Infinity : b.before;
      return bv - av;
    });
  const out = {};
  ranked.forEach((row, index) => {
    const key = seriesKey(row);
    const was = yesterday.findIndex((item) => item.key === key);
    out[key] = was === -1 || changes[key] == null || changes[key].before == null ? 0 : was - index;
  });
  return out;
}

function tradeTime(value) {
  const date = parseStamp(value);
  return date ? Math.floor(date.getTime() / 1000) : null;
}

function recentTradeEvents(trades, sinceUnix, untilUnix) {
  const events = [];
  (trades || []).forEach((row) => {
    const entry = tradeTime(row.entry_date);
    if (entry != null && entry > sinceUnix && entry <= untilUnix) {
      events.push({ kind: "buy", time: entry, row });
    }
    const closed = Number(row.closed) === 1 || row.closed === true;
    const exit = closed ? tradeTime(row.exit_date) : null;
    if (exit != null && exit > sinceUnix && exit <= untilUnix) {
      events.push({ kind: "sell", time: exit, row });
    }
  });
  return events.sort((a, b) => b.time - a.time);
}

function headlineCounts(data) {
  let total = 0;
  let above = 0;
  let beatHold = 0;
  COINS.forEach((asset) => {
    const ranked = rankRows(rowsFor(data, asset));
    ranked.rows.forEach((row) => {
      if (row.value == null) return;
      total += 1;
      if (row.value >= START_DOLLARS) above += 1;
      if (ranked.benchmark && ranked.benchmark.value != null && row.value > ranked.benchmark.value) beatHold += 1;
    });
  });
  return { total, above, beatHold };
}

// ---------- rendering ----------

function motionAllowed() {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

function deltaPill(diff, pct, extraClass) {
  if (diff == null || !Number.isFinite(diff)) return el("span", "delta flat " + (extraClass || ""), "ไม่มีตัวเลข");
  const tone = Math.abs(diff) < 0.5 ? "flat" : diff > 0 ? "good" : "bad";
  const arrow = tone === "flat" ? "■" : tone === "good" ? "▲" : "▼";
  const sign = tone === "flat" ? "" : tone === "good" ? "+" : "−";
  const text = pct == null ? dollars(Math.abs(diff)) : numberText(Math.abs(pct), 1) + "%";
  const pill = el("span", "delta " + tone + " " + (extraClass || ""));
  const icon = el("span", "", arrow);
  icon.setAttribute("aria-hidden", "true");
  pill.append(icon, document.createTextNode(sign + text));
  return pill;
}

function pnlPill(value) {
  const diff = value == null ? null : Number(value) - START_DOLLARS;
  const pill = deltaPill(diff, diff == null ? null : (diff / START_DOLLARS) * 100);
  const pnl = describePnl(value);
  pill.setAttribute("aria-label", pnl.label + " จากเงินเริ่ม");
  pill.title = pnl.label + " จากเงินเริ่ม";
  return pill;
}

function renderHeadline(data) {
  const node = document.getElementById("headline");
  const counts = headlineCounts(data);
  node.replaceChildren();
  if (!counts.total) {
    node.textContent = "ยังไม่มีตัวเลขของสมุดเล่มไหน";
    return;
  }
  const strong = (text) => el("span", "hl-num", text);
  if (counts.above === 0) {
    node.append("วันนี้ยังไม่มีวิธีไหนอยู่เหนือเงินเริ่ม");
  } else {
    node.append("วันนี้ ", strong(String(counts.above)), " จาก ", strong(String(counts.total)), " วิธียังกำไร");
  }
  if (counts.beatHold > 0) {
    node.append(" และ ", strong(String(counts.beatHold)), " วิธีนำซื้อแล้วถือ");
  }
}

function placeOnTrack(value, lo, hi) {
  if (hi <= lo) return 50;
  return Math.min(100, Math.max(0, ((value - lo) / (hi - lo)) * 100));
}

function edgeClass(pct) {
  if (pct > 82) return " edge-right";
  if (pct < 18) return " edge-left";
  return "";
}

function renderTrack(ranked) {
  const all = ranked.rows.concat(ranked.benchmark ? [ranked.benchmark] : []).filter((row) => row.value != null);
  const track = el("div", "track");
  track.setAttribute("aria-hidden", "true");
  if (!all.length) return track;
  const values = all.map((row) => row.value).concat([START_DOLLARS]);
  const span = Math.max(...values) - Math.min(...values) || START_DOLLARS * 0.1;
  const lo = Math.min(...values) - span * 0.06;
  const hi = Math.max(...values) + span * 0.06;
  const start = placeOnTrack(START_DOLLARS, lo, hi);

  track.append(el("div", "track-line"));
  const loss = el("div", "track-loss");
  loss.style.width = start + "%";
  track.append(loss);
  const line = el("div", "track-start");
  line.style.left = start + "%";
  track.append(line);
  const startLabel = el("div", "track-start-label" + edgeClass(start), "เงินเริ่ม 10,000");
  startLabel.style.left = start + "%";
  track.append(startLabel);

  const lanes = [];
  const order = all.slice().sort((a, b) => a.value - b.value);
  order.forEach((row) => {
    const pct = placeOnTrack(row.value, lo, hi);
    let lane = 0;
    while (lanes[lane] != null && pct - lanes[lane] < 4 && lane < 2) lane += 1;
    lanes[lane] = pct;
    const isLeader = ranked.best && row === ranked.best;
    const isBench = row.strategy === "buy_and_hold";
    let klass = "track-dot";
    if (isLeader) klass += " leader";
    else {
      if (isBench) klass += " bench";
      if (lane) klass += " lane-" + lane;
    }
    const dot = el("div", klass);
    dot.style.left = pct + "%";
    dot.dataset.from = String(start - pct);
    track.append(dot);
    if (isLeader) {
      const label = el("div", "track-leader-label" + edgeClass(pct), "อันดับ 1");
      label.style.left = pct + "%";
      track.append(label);
    }
  });
  return track;
}

function renderLap(data, asset, stale) {
  const ranked = rankRows(rowsFor(data, asset));
  const book = (data.equity && data.equity[asset]) || {};
  const changes = dayChanges(book);
  const lap = el("article", "lap");
  const head = el("div", "lap-head");
  const coin = el("h2", "lap-coin", asset === "BTC" ? "บิตคอยน์" : asset === "ETH" ? "อีเธอเรียม" : asset);
  coin.append(el("span", "ticker", ticker(asset)));
  head.append(coin);
  if (stale) {
    head.append(el("span", "chip amber", "ราคาค้าง · " + formatChip(latestPriceUnix(data, asset))));
  }
  lap.append(head);

  const best = ranked.best;
  if (!best) {
    lap.append(el("p", "band-quiet", "ยังไม่มีตัวเลขของเหรียญนี้"));
    return lap;
  }
  const info = strategyInfo(best.strategy, best.timeframe);
  const leader = el("p", "lap-leader");
  leader.append("นำอยู่: ", el("strong", "", info.title), " · " + clockLabel(best.timeframe));
  leader.append(tip(info.caption));
  lap.append(leader);

  const money = el("div", "lap-money");
  const value = el("span", "lap-value");
  value.dataset.target = String(Math.round(best.value));
  value.textContent = numberText(Math.round(best.value), 0);
  money.append(value, el("span", "lap-unit", "ดอลลาร์"));
  lap.append(money);

  const stats = el("div", "lap-stats");
  stats.append(pnlPill(best.value));
  const change = changes[seriesKey(best)];
  if (change && change.diff != null) {
    if (Math.abs(change.diff) < 0.5) {
      stats.append(el("span", "delta flat soft", "24 ชม. เท่าเดิม"));
    } else {
      const day = deltaPill(change.diff, change.pct, "soft");
      day.prepend(document.createTextNode("24 ชม. "));
      stats.append(day);
    }
  }
  lap.append(stats);

  lap.append(renderTrack(ranked));
  const key = el("p", "track-key");
  const k1 = el("span");
  k1.append(el("span", "key-dot"), document.createTextNode("วิธีที่จำลอง " + ranked.rows.length + " วิธี"));
  key.append(k1);
  if (ranked.benchmark) {
    const k2 = el("span");
    k2.append(el("span", "key-dot bench"), document.createTextNode("ซื้อแล้วถือ " + dollars(ranked.benchmark.value)));
    key.append(k2);
  }
  lap.append(key);
  return lap;
}

function renderRace(data, staleAssets) {
  const root = document.getElementById("race");
  root.replaceChildren(...COINS.map((asset) => renderLap(data, asset, staleAssets.indexOf(asset) !== -1)));
}

function eventItem(iconText, tone, title, detail, trailing) {
  const item = el("li", "event");
  const icon = el("span", "event-icon " + tone, iconText);
  icon.setAttribute("aria-hidden", "true");
  const body = el("div", "event-body");
  body.append(el("b", "", title));
  if (detail) body.append(el("span", "", detail));
  item.append(icon, body);
  item.append(trailing || el("span"));
  return item;
}

function renderChanges(data) {
  const root = document.getElementById("changes-root");
  const wrap = el("div", "changes");

  // Column 1: trades in the last 24 hours.
  const tradesCol = el("div", "change-col");
  tradesCol.append(el("h3", "", "ซื้อขาย"));
  const allBooks = {};
  COINS.forEach((asset) => Object.assign(allBooks, (data.equity && data.equity[asset]) || {}));
  const until = latestEquityTime(allBooks);
  const events = until == null ? [] : recentTradeEvents(data.trades, until - DAY_SECONDS, until);
  if (!events.length) {
    tradesCol.append(el("p", "event-empty", "ไม่มีการซื้อหรือขายใน 24 ชั่วโมงนี้ ทุกวิธียังถือสถานะเดิม"));
  } else {
    const list = el("ul", "events");
    events.forEach((event) => {
      const info = strategyInfo(event.row.strategy, event.row.timeframe);
      const title = (event.kind === "buy" ? "ซื้อ " : "ขาย ") + ticker(event.row.asset) + " · " + info.short;
      const detail = clockLabel(event.row.timeframe) + " · " + formatUnix(event.time);
      let trailing = el("span");
      if (event.kind === "sell" && event.row.return_pct != null) {
        const pct = Number(event.row.return_pct) * 100;
        trailing = deltaPill(pct, pct);
        trailing.setAttribute("aria-label", tradeResult(event.row).label);
      }
      list.append(eventItem(event.kind === "buy" ? "ซ" : "ข", event.kind === "buy" ? "brand" : "", title, detail, trailing));
    });
    tradesCol.append(list);
  }
  wrap.append(tradesCol);

  // Column 2: rank moves and the biggest swings in money.
  const moveCol = el("div", "change-col");
  moveCol.append(el("h3", "", "อันดับและเงิน"));
  const list = el("ul", "events");
  const swings = [];
  COINS.forEach((asset) => {
    const rows = rowsFor(data, asset);
    const book = (data.equity && data.equity[asset]) || {};
    const moves = rankMoves(rows, book);
    const ranked = rankRows(rows);
    ranked.rows.forEach((row, index) => {
      const key = seriesKey(row);
      const move = moves[key];
      if (move) {
        const info = strategyInfo(row.strategy, row.timeframe);
        const up = move > 0;
        list.append(
          eventItem(
            up ? "▲" : "▼",
            up ? "good" : "bad",
            ticker(asset) + " · " + info.short + " " + (up ? "ขึ้น" : "ลง") + " " + Math.abs(move) + " อันดับ",
            clockLabel(row.timeframe) + " · ตอนนี้อันดับ " + (index + 1),
          ),
        );
      }
    });
    const changes = dayChanges(book);
    Object.keys(changes).forEach((key) => {
      if (changes[key].diff != null) swings.push({ asset, key, ...changes[key] });
    });
  });
  if (!list.children.length) {
    list.append(eventItem("=", "", "อันดับเหมือนเมื่อวานทั้งสองเหรียญ", "ไม่มีวิธีไหนแซงกัน"));
  }
  const moving = swings.filter((item) => Math.abs(item.diff) >= 0.5).sort((a, b) => b.pct - a.pct);
  if (moving.length) {
    const top = moving[0];
    const bottom = moving[moving.length - 1];
    const describe = (item, label) => {
      const parts = item.key.split("|");
      const info = strategyInfo(parts[0], parts[1]);
      const pill = deltaPill(item.diff, item.pct);
      return eventItem(
        item.diff > 0 ? "▲" : "▼",
        item.diff > 0 ? "good" : "bad",
        label + " · " + ticker(item.asset) + " " + info.short,
        clockLabel(parts[1]) + " · " + (item.diff > 0 ? "+" : "−") + dollars(Math.abs(item.diff)),
        pill,
      );
    };
    if (top.diff > 0) list.append(describe(top, "เงินเพิ่มมากสุด"));
    if (bottom.diff < 0 && bottom !== top) list.append(describe(bottom, "เงินลดมากสุด"));
  } else {
    list.append(eventItem("■", "", "เงินของทุกวิธีเท่าเดิม", "ทุกเล่มถือเงินสด หรือราคาแทบไม่ขยับ"));
  }
  moveCol.append(list);
  wrap.append(moveCol);
  root.replaceChildren(wrap);
}

function renderStanding(row, rank, scaleMax, move, isFirst) {
  const info = strategyInfo(row.strategy, row.timeframe);
  const hold = holdingOf(row);
  const bench = row.strategy === "buy_and_hold";
  const item = el("li", "stand" + (bench ? " bench" : "") + (isFirst ? " first" : ""));

  const rankCell = el("div", "stand-rank");
  if (bench) rankCell.append(el("span", "", "เทียบ"));
  else {
    rankCell.append(el("span", "", String(rank)));
    if (move) {
      const up = move > 0;
      const m = el("span", "move " + (up ? "good" : "bad"), (up ? "▲" : "▼") + Math.abs(move));
      m.setAttribute("aria-label", (up ? "ขึ้น " : "ลง ") + Math.abs(move) + " อันดับจากเมื่อวาน");
      rankCell.append(m);
    } else {
      const m = el("span", "move flat", "–");
      m.setAttribute("aria-label", "อันดับเท่าเมื่อวาน");
      rankCell.append(m);
    }
  }
  item.append(rankCell);

  const name = el("div", "stand-name");
  const title = el("div", "stand-title");
  const link = el("a", "", bench ? "ซื้อแล้วถือเฉยๆ" : info.short);
  link.href = info.href;
  link.title = info.title;
  title.append(link, tip(info.title + " · " + info.caption));
  name.append(title);
  const sub = el("div", "stand-sub");
  sub.append(el("span", "", clockLabel(row.timeframe)));
  sub.append(el("span", "hold-chip " + hold.klass, hold.title));
  name.append(sub);
  item.append(name);

  const money = el("div", "stand-money");
  money.append(el("span", "stand-value", dollars(row.value)));
  money.append(pnlPill(row.value));
  item.append(money);

  const bar = el("div", "stand-bar");
  const fill = el("div", "stand-fill" + (row.value != null && row.value < START_DOLLARS ? " under" : ""));
  fill.style.width = (row.value == null ? 0 : Math.max(1.5, (row.value / scaleMax) * 100)) + "%";
  bar.append(fill);
  const mark = el("div", "stand-mark");
  mark.style.left = (START_DOLLARS / scaleMax) * 100 + "%";
  mark.title = "เงินเริ่ม 10,000 ดอลลาร์";
  bar.append(mark);
  item.append(bar);
  return item;
}

function renderSummary(data, staleAssets) {
  const root = document.getElementById("summary-root");
  const grid = el("div", "coin-grid");
  COINS.forEach((asset) => {
    const rows = rowsFor(data, asset);
    const ranked = rankRows(rows);
    const moves = rankMoves(rows, (data.equity && data.equity[asset]) || {});
    const block = el("div", "coin");
    const head = el("div", "coin-head");
    head.append(el("h3", "", coinName(asset)));
    if (staleAssets.indexOf(asset) !== -1) {
      head.append(el("p", "chip amber", ticker(asset) + " ราคาค้าง · อัปเดตล่าสุด " + formatChip(latestPriceUnix(data, asset))));
    }
    block.append(head);
    const values = ranked.rows.concat(ranked.benchmark ? [ranked.benchmark] : []).map((row) => row.value || 0);
    const scaleMax = Math.max(START_DOLLARS, ...values) * 1.04;
    const list = el("ol", "standings");
    let placedBench = false;
    ranked.rows.forEach((row, index) => {
      if (!placedBench && ranked.benchmark && ranked.benchmark.value != null && row.value != null && ranked.benchmark.value > row.value) {
        list.append(renderStanding(ranked.benchmark, null, scaleMax, 0, false));
        placedBench = true;
      }
      list.append(renderStanding(row, index + 1, scaleMax, moves[seriesKey(row)], index === 0));
    });
    if (!placedBench && ranked.benchmark) list.append(renderStanding(ranked.benchmark, null, scaleMax, 0, false));
    if (!ranked.rows.length) block.append(el("p", "event-empty", "ยังไม่มีตัวเลขของเหรียญนี้"));
    else block.append(list);
    grid.append(block);
  });
  root.replaceChildren(grid);
}

// ---------- motion: everything is already in its final state; this only replays the arrival ----------

function easeOutQuart(t) {
  return 1 - Math.pow(1 - t, 4);
}

function animateArrival() {
  if (!motionAllowed()) return;
  document.querySelectorAll(".lap-value[data-target]").forEach((node) => {
    const target = Number(node.dataset.target);
    if (!Number.isFinite(target)) return;
    const from = START_DOLLARS;
    const started = performance.now();
    const duration = 1100;
    const finalText = numberText(target, 0);
    node.setAttribute("aria-label", finalText + " ดอลลาร์");
    const step = (now) => {
      const t = Math.min(1, (now - started) / duration);
      node.textContent = numberText(Math.round(from + (target - from) * easeOutQuart(t)), 0);
      if (t < 1) requestAnimationFrame(step);
      else node.textContent = finalText;
    };
    requestAnimationFrame(step);
    setTimeout(() => {
      node.textContent = finalText;
    }, duration + 400);
  });
  if (!Element.prototype.animate) return;
  document.querySelectorAll(".track").forEach((track) => {
    const width = track.clientWidth;
    track.querySelectorAll(".track-dot").forEach((dot, index) => {
      const from = (Number(dot.dataset.from) / 100) * width;
      dot.animate(
        [{ transform: "translateX(" + from + "px)", opacity: 0.4 }, { transform: "translateX(0)", opacity: 1 }],
        { duration: 900, delay: 120 + index * 50, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "backwards" },
      );
    });
  });
  document.querySelectorAll(".standings").forEach((list) => {
    list.querySelectorAll(".stand-fill").forEach((fill, index) => {
      fill.animate([{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], {
        duration: 700,
        delay: 200 + index * 45,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        fill: "backwards",
      });
    });
  });
}

function tradeResult(row) {
  if (row.return_pct == null || row.return_pct === "") {
    return { tone: "flat", label: row.closed ? "ไม่มีตัวเลขผล" : "ยังไม่มีผล เพราะยังไม่ขาย" };
  }
  const pct = Number(row.return_pct) * 100;
  if (!Number.isFinite(pct)) return { tone: "flat", label: "ไม่มีตัวเลขผล" };
  const open = row.closed ? "" : " และยังไม่ขาย";
  if (Math.abs(pct) < 0.05) return { tone: "flat", label: "เกือบเท่าทุน" + open };
  const shown = numberText(Math.abs(pct), 1);
  if (pct > 0) return { tone: "good", label: "กำไร " + shown + "%" + open };
  return { tone: "bad", label: "ขาดทุน " + shown + "%" + open };
}

function renderTrades(data) {
  const root = document.getElementById("trades");
  const trades = data.trades || [];
  if (!trades.length) {
    root.replaceChildren(el("p", "quiet", "ยังไม่มีรายการซื้อขาย"));
    return;
  }
  const list = el("div", "trades");
  trades.forEach((row) => {
    const info = strategyInfo(row.strategy, row.timeframe);
    const result = tradeResult(row);
    const item = el("article", "trade");
    const when = el("div", "trade-when");
    when.append(el("span", "tag buy", "ซื้อ"));
    when.append(el("span", "num", formatStamp(row.entry_date)));
    if (row.closed) {
      when.append(el("span", "tag sell", "ขาย"));
      when.append(el("span", "num", formatStamp(row.exit_date)));
    } else {
      when.append(el("span", "tag hold", "ถืออยู่"));
    }
    item.append(when);
    item.append(el("div", "trade-what", ticker(row.asset) + " · " + info.title + " · " + clockLabel(row.timeframe)));
    item.append(el("div", "pnl num " + result.tone, result.label));
    list.append(item);
  });
  root.replaceChildren(list);
}

function plainHistoryName(row) {
  const known = {
    sma_filter: row.timeframe === "4h" ? "เส้นค่าเฉลี่ย 200 แท่ง (SMA 200)" : "เส้นค่าเฉลี่ย 200 วัน (SMA 200)",
    macd: "แมคดี (MACD)",
    donchian: "กรอบดอนเชียน (Donchian)",
    trend_vol: "คะแนนเทรนด์ + เป้าความแกว่ง 40% (เงินสมมติ)",
    sma_cross: "เส้นค่าเฉลี่ยสั้นตัดเส้นยาว",
    rsi: "ดัชนีแรงสัมพัทธ์ (ซื้อเมื่อถูก ขายเมื่อแพง)",
    bollinger: "แถบโบลลินเจอร์ (ซื้อขอบล่าง ขายตรงกลาง)",
    dca_weekly: "ทยอยซื้อทุกสัปดาห์ แล้วถือยาว",
    buy_and_hold: "ซื้อแล้วถือเฉยๆ",
  };
  return known[row.strategy] || row.name_th || row.strategy;
}

function signedPercent(value) {
  if (value == null || !Number.isFinite(Number(value))) return null;
  const pct = Number(value) * 100;
  return { tone: pct > 0.05 ? "good" : pct < -0.05 ? "bad" : "flat", shown: numberText(Math.abs(pct), 1), raw: pct };
}

function renderHistory(data) {
  const root = document.getElementById("history-root");
  const extra = document.getElementById("history-extra");
  const rows = data.leaderboard || [];
  root.replaceChildren();
  extra.replaceChildren();
  COINS.forEach((asset) => {
    const group = rows
      .filter((row) => row.asset === asset)
      .slice()
      .sort((a, b) => Number(b.cagr) - Number(a.cagr));
    root.append(el("h3", "", coinName(asset)));
    const table = el("table", "mini");
    const head = document.createElement("tr");
    ["อันดับ", "วิธี", "โตเฉลี่ยต่อปี", "ร่วงจากจุดสูงสุด", "ครั้ง"].forEach((label) => head.append(el("th", "", label)));
    table.append(head);
    group.forEach((row, index) => {
      const growth = signedPercent(row.cagr);
      const drop = signedPercent(row.max_drawdown);
      const line = document.createElement("tr");
      line.append(el("td", "num", String(index + 1)));
      line.append(el("td", "", plainHistoryName(row) + " · " + clockLabel(row.timeframe)));
      const growthCell = el("td", "num" + (growth ? " " + growth.tone : ""));
      growthCell.textContent = growth ? (growth.raw >= 0 ? "+" : "−") + growth.shown + "%" : "—";
      line.append(growthCell);
      line.append(el("td", "num", drop ? drop.shown + "%" : "—"));
      line.append(el("td", "num", String(row.n_trades)));
      table.append(line);
    });
    if (!group.length) root.append(el("p", "quiet", "ไม่มีผลทดสอบของเหรียญนี้"));
    else {
      const scroll = el("div", "table-scroll");
      scroll.append(table);
      root.append(scroll);
    }
    extra.append(el("h3", "", coinName(asset)));
    const extraTable = el("table", "mini");
    group.forEach((row) => {
      const win = signedPercent(row.win_rate);
      const line = document.createElement("tr");
      line.append(el("td", "", plainHistoryName(row) + " · " + clockLabel(row.timeframe)));
      line.append(el("td", "num", win ? "ชนะ " + win.shown + "%" : "—"));
      line.append(el("td", "num", row.sharpe == null ? "—" : numberText(Number(row.sharpe), 2)));
      extraTable.append(line);
    });
    const extraScroll = el("div", "table-scroll");
    extraScroll.append(extraTable);
    extra.append(extraScroll);
  });
}

function renderReasons(data) {
  const root = document.getElementById("reasons");
  const seen = new Set();
  const stack = el("div", "stack");
  (data.reasons || []).forEach((row) => {
    if (seen.has(row.strategy)) return;
    seen.add(row.strategy);
    const info = strategyInfo(row.strategy, "1d");
    const card = el("article", "");
    card.append(el("h3", "", info.title));
    card.append(el("p", "quiet", row.why_th || ""));
    stack.append(card);
  });
  if (!seen.size) stack.append(el("p", "", "ไม่มีคำอธิบาย"));
  root.replaceChildren(stack);
}

function equityDollars(points) {
  return (points || []).map((point) => ({ time: point.time, value: point.value * 100 }));
}

function lastEquityDollars(points) {
  if (!points || !points.length) return null;
  return points[points.length - 1].value * 100;
}

function positionByKey(data, asset) {
  const map = {};
  rowsFor(data, asset).forEach((row) => {
    map[seriesKey(row)] = row;
  });
  return map;
}

function orderedKeys(data, asset) {
  const book = (data.equity && data.equity[asset]) || {};
  const ranked = rankRows(rowsFor(data, asset));
  const order = ranked.rows.map(seriesKey);
  if (ranked.benchmark) order.push(seriesKey(ranked.benchmark));
  const rest = Object.keys(book).filter((key) => order.indexOf(key) === -1);
  return order.filter((key) => book[key]).concat(rest);
}

function legendValue(data, asset, key) {
  const row = positionByKey(data, asset)[key];
  if (row && row.value != null) return dollars(row.value);
  if (row) return dollars(portfolioValue(row));
  const book = data.equity[asset] || {};
  return dollars(lastEquityDollars(book[key]));
}

function renderLegend(data) {
  const root = document.getElementById("legend");
  const keys = orderedKeys(data, currentAsset);
  const ranked = rankRows(rowsFor(data, currentAsset));
  const bestKey = ranked.best ? seriesKey(ranked.best) : "";
  root.replaceChildren();
  keys.forEach((key) => {
    const parts = key.split("|");
    const info = strategyInfo(parts[0], parts[1]);
    const benchmark = parts[0] === "buy_and_hold";
    const label = el("label", "legend-item");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = key;
    input.checked = visible.has(key);
    input.addEventListener("change", () => {
      if (input.checked) visible.add(key);
      else visible.delete(key);
      drawEquity(data);
    });
    const palette = theme();
    const color = key === bestKey ? palette.accent : benchmark ? palette.bench : info.color;
    const swatch = el("span", benchmark ? "swatch dashed" : "swatch");
    swatch.style.background = color;
    swatch.style.color = color;
    const copy = el("span", "legend-copy");
    const name = benchmark ? "ตัวเทียบ: " + info.title : info.title;
    const suffix = key === bestKey ? " · ดีที่สุดตอนนี้" : "";
    copy.append(el("span", "", name + " · " + clockLabel(parts[1]) + suffix));
    copy.append(document.createElement("br"));
    copy.append(el("span", "", legendValue(data, currentAsset, key)));
    label.append(input, swatch, copy);
    root.append(label);
  });
}

function theme() {
  colorCache.clear();
  const text = cssColor("--ink", "#1c2333");
  return {
    bg: cssColor("--surface", "#ffffff"),
    text,
    grid: withAlpha(text, 0.07),
    scale: cssColor("--line", "#dde1ea"),
    up: cssColor("--up", "#13805c"),
    down: cssColor("--down", "#c2412f"),
    accent: cssColor("--brand-ink", "#55612c"),
    bench: cssColor("--s-bench", "#8b93a3"),
  };
}

function chartOptions(elNode) {
  const colors = theme();
  return {
    width: elNode.clientWidth || 320,
    height: elNode.clientHeight || 380,
    layout: {
      background: { color: colors.bg },
      textColor: colors.text,
      fontFamily: '"IBM Plex Sans Thai", "Noto Sans Thai", sans-serif',
      fontSize: 16,
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { color: colors.grid },
    },
    rightPriceScale: { borderColor: colors.scale },
    timeScale: {
      borderColor: colors.scale,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time, tickMarkType) => tickLabel(time, tickMarkType),
    },
    localization: {
      locale: "th-TH",
      priceFormatter: (price) => numberText(Math.round(price), 0),
      timeFormatter: (time) => formatUnix(timeValue(time)),
    },
    crosshair: { mode: 0 },
  };
}

function timeValue(time) {
  if (typeof time === "number") return time;
  if (time && time.year) return Date.UTC(time.year, time.month - 1, time.day) / 1000;
  return null;
}

function tickLabel(time, tickMarkType) {
  const unix = timeValue(time);
  if (unix == null) return "";
  const date = new Date(unix * 1000);
  const options = { timeZone: "Asia/Bangkok", numberingSystem: "latn" };
  if (tickMarkType <= 0) options.year = "numeric";
  else if (tickMarkType === 1) {
    options.month = "short";
    options.year = "numeric";
  } else if (tickMarkType === 2) {
    options.day = "numeric";
    options.month = "short";
  } else {
    options.hour = "2-digit";
    options.minute = "2-digit";
    options.hourCycle = "h23";
  }
  return new Intl.DateTimeFormat("th-TH", options).format(date);
}

function watchChart(node, chart) {
  if (typeof ResizeObserver === "undefined") return null;
  const observer = new ResizeObserver(() => {
    const width = node.clientWidth;
    const height = node.clientHeight;
    if (width > 0 && height > 0) chart.applyOptions({ width, height });
  });
  observer.observe(node);
  return observer;
}

function markerColor(text) {
  const colors = theme();
  return String(text || "").indexOf("ขาย") !== -1 ? colors.down : colors.accent;
}

function drawPrice(data) {
  const node = document.getElementById("price");
  const error = document.getElementById("chart-error");
  if (!window.LightweightCharts) {
    error.hidden = false;
    return;
  }
  error.hidden = true;
  if (priceObserver) priceObserver.disconnect();
  if (priceChart) priceChart.remove();
  node.replaceChildren();
  priceChart = LightweightCharts.createChart(node, chartOptions(node));
  priceObserver = watchChart(node, priceChart);
  const colors = theme();
  const series = priceChart.addCandlestickSeries({
    upColor: colors.up,
    downColor: colors.down,
    borderUpColor: colors.up,
    borderDownColor: colors.down,
    wickUpColor: colors.up,
    wickDownColor: colors.down,
  });
  const candles = (data.candles && data.candles[currentAsset]) || [];
  series.setData(candles);
  const times = new Set(candles.map((candle) => candle.time));
  const grouped = new Map();
  (data.markers || [])
    .filter((marker) => marker.asset === currentAsset && times.has(marker.time))
    .slice()
    .sort((a, b) => a.time - b.time || String(a.text).localeCompare(String(b.text), "th"))
    .forEach((marker) => {
      const existing = grouped.get(marker.time);
      if (!existing) {
        grouped.set(marker.time, {
          time: marker.time,
          position: marker.position,
          color: markerColor(marker.text),
          shape: marker.shape,
          text: "",
        });
        return;
      }
      existing.text = "";
    });
  series.setMarkers(Array.from(grouped.values()));
  priceChart.timeScale().fitContent();
}

function drawEquity(data) {
  const node = document.getElementById("equity");
  const empty = document.getElementById("chart-empty");
  if (!window.LightweightCharts) return;
  if (equityObserver) equityObserver.disconnect();
  if (equityChart) equityChart.remove();
  node.replaceChildren();
  const book = (data.equity && data.equity[currentAsset]) || {};
  const keys = orderedKeys(data, currentAsset).filter((key) => visible.has(key) && book[key]);
  if (!keys.length) {
    empty.hidden = false;
    equityChart = null;
    return;
  }
  empty.hidden = true;
  const ranked = rankRows(rowsFor(data, currentAsset));
  const bestKey = ranked.best ? seriesKey(ranked.best) : "";
  equityChart = LightweightCharts.createChart(node, chartOptions(node));
  equityObserver = watchChart(node, equityChart);
  keys.forEach((key) => {
    const parts = key.split("|");
    const info = strategyInfo(parts[0], parts[1]);
    const benchmark = parts[0] === "buy_and_hold";
    const palette = theme();
    const series = equityChart.addLineSeries({
      color: key === bestKey ? palette.accent : benchmark ? palette.bench : info.color,
      lineWidth: key === bestKey ? 3 : 2,
      lineStyle: benchmark ? 2 : 0,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(equityDollars(book[key]));
  });
  equityChart.timeScale().fitContent();
}

function showAsset(data, asset) {
  currentAsset = asset;
  visible = new Set(defaultSeriesKeys(rowsFor(data, asset)));
  document.querySelectorAll(".switch button").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.asset === asset ? "true" : "false");
  });
  renderLegend(data);
  drawPrice(data);
  drawEquity(data);
}

function setupCharts(data) {
  document.querySelectorAll(".switch button").forEach((button) => {
    button.addEventListener("click", () => showAsset(data, button.dataset.asset));
  });
  document.getElementById("reset-lines").addEventListener("click", () => {
    visible = new Set(defaultSeriesKeys(rowsFor(data, currentAsset)));
    renderLegend(data);
    drawEquity(data);
  });
  const start = () => showAsset(data, currentAsset);
  const fonts = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  Promise.race([fonts, new Promise((resolve) => setTimeout(resolve, 1500))]).then(start);
  if (window.matchMedia) {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const redraw = () => {
      renderLegend(data);
      drawPrice(data);
      drawEquity(data);
    };
    if (media.addEventListener) media.addEventListener("change", redraw);
  }
  document.addEventListener("click", () => {
    document.querySelectorAll(".tip.open").forEach((node) => {
      node.classList.remove("open");
      const button = node.querySelector("button");
      if (button) button.setAttribute("aria-expanded", "false");
    });
  });
}

function renderPage(data, nowMs) {
  const stale = renderStale(data, nowMs);
  renderUpdated(data);
  renderHeadline(data);
  renderRace(data, stale);
  renderChanges(data);
  renderSummary(data, stale);
  renderTrades(data);
  renderHistory(data);
  renderReasons(data);
  setupCharts(data);
  requestAnimationFrame(animateArrival);
}

async function loadData() {
  const response = await fetch("data/dashboard.json");
  if (!response.ok) throw new Error("status " + response.status);
  return response.json();
}

function showLoadError() {
  const status = document.getElementById("page-status");
  const headline = document.getElementById("headline");
  if (headline) headline.textContent = "อ่านตัวเลขไม่สำเร็จ";
  ["changes", "standings", "charts", "trades-section"].forEach((id) => {
    const section = document.getElementById(id);
    if (section) section.hidden = true;
  });
  status.hidden = false;
  status.textContent = "อ่านข้อมูลไม่สำเร็จ หน้านี้ต้องเปิดผ่านเว็บเซิร์ฟเวอร์ และมีไฟล์ data/dashboard.json อยู่ข้าง ๆ เช่น คำสั่ง python -m http.server ในโฟลเดอร์ docs";
}

async function main() {
  const status = document.getElementById("page-status");
  try {
    pageData = await loadData();
    status.hidden = true;
    renderPage(pageData);
  } catch (error) {
    showLoadError();
  }
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    START_DOLLARS,
    STALE_HOURS,
    portfolioValue,
    priceIsStale,
    rankRows,
    defaultSeriesKeys,
    describePnl,
    describeGap,
    equityAt,
    dayChanges,
    rankMoves,
    recentTradeEvents,
    headlineCounts,
    holdingOf,
    strategyInfo,
  };
}
