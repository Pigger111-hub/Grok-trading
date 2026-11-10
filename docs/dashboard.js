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
    caption: "ถือเหรียญเมื่อราคาปิดอยู่เหนือเส้นค่าเฉลี่ย แล้วถือเงินสดเมื่อหลุดเส้น",
    caption4h: "กติกาเดียวกัน แต่คิดจากแท่ง 4 ชั่วโมง 200 แท่ง ประมาณ 33 วัน ไม่ใช่ 200 วัน",
    href: "#term-sma",
    color1d: "#4b5563",
    color4h: "#9ca3af",
  },
  macd: {
    title: "แมคดี (MACD)",
    caption: "ถือเหรียญเมื่อเส้นเร็วอยู่เหนือเส้นช้า แล้วถือเงินสดเมื่อหลุด",
    href: "#term-macd",
    color1d: "#64748b",
    color4h: "#94a3b8",
  },
  donchian: {
    title: "กรอบดอนเชียน (Donchian)",
    caption: "ซื้อเมื่อราคาทะลุกรอบสูง ขายเมื่อหลุดกรอบต่ำ",
    href: "#term-donchian",
    color1d: "#78716c",
    color4h: "#a8a29e",
  },
  buy_and_hold: {
    title: "ซื้อแล้วถือเฉยๆ",
    caption: "ซื้อครั้งเดียวตอนเริ่ม แล้วไม่ขาย เป็นตัวเทียบ ไม่ใช่วิธีที่เลือก",
    href: "#term-bh",
    color1d: "#a3a3a3",
    color4h: "#a3a3a3",
  },
};

const FALLBACK_INFO = {
  title: "วิธีนี้",
  caption: "กติกาซื้อขายเงินสมมติ",
  href: "#glossary",
  color1d: "#24312b",
  color4h: "#24312b",
};

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
  return {
    title: intraday && info.title4h ? info.title4h : info.title,
    caption: intraday && info.caption4h ? info.caption4h : info.caption,
    href: info.href,
    color: intraday ? info.color4h : info.color1d,
  };
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

function bestBadge(row, benchmark) {
  const pnl = describePnl(row.value);
  if (pnl.tone === "good") return "อันดับ 1 · ดีที่สุดตอนนี้ และกำไรจากเงินเริ่ม";
  if (pnl.tone === "bad") return "อันดับ 1 · ดีที่สุดตอนนี้ แต่ยังขาดทุนจากเงินเริ่ม";
  return "อันดับ 1 · ดีที่สุดตอนนี้";
}

function coinLead(ranked) {
  const winners = ranked.rows.filter((row) => row.value != null && row.value >= START_DOLLARS);
  let text;
  if (!ranked.rows.length) text = "ยังไม่มีตัวเลขของวิธีนี้";
  else if (winners.length === 0) text = "ยังไม่มีวิธีไหนกำไรจากเงินเริ่ม 10,000 ดอลลาร์";
  else if (winners.length === 1) text = "มี 1 วิธีที่กำไรจากเงินเริ่ม 10,000 ดอลลาร์";
  else text = "มี " + winners.length + " วิธีที่กำไรจากเงินเริ่ม 10,000 ดอลลาร์";
  if (ranked.best && ranked.benchmark && ranked.best.value != null && ranked.benchmark.value != null) {
    if (ranked.best.value > ranked.benchmark.value) {
      text += " วิธีที่เหลือเงินมากสุด ยังมากกว่าการซื้อแล้วถือเฉย ๆ";
    } else if (ranked.best.value < ranked.benchmark.value) {
      text += " ตอนนี้การซื้อแล้วถือเฉย ๆ เหลือเงินมากกว่าทุกวิธีที่กำลังจำลอง";
    }
  }
  return text;
}

function renderHero(row, benchmark) {
  const info = strategyInfo(row.strategy, row.timeframe);
  const hold = holdingOf(row);
  const pnl = describePnl(row.value);
  const hero = el("article", "hero");
  const kicker = el("p", "kicker");
  kicker.append(document.createTextNode("ดีที่สุด · " + info.title + " · " + clockLabel(row.timeframe)));
  kicker.append(tip(info.caption));
  hero.append(kicker);
  hero.append(el("p", "hero-money num", dollars(row.value)));
  hero.append(el("p", "hero-pnl num " + pnl.tone, pnl.label));
  const meta = el("p", "hero-meta");
  meta.append(document.createTextNode(hold.title));
  if (benchmark && benchmark.value != null) {
    meta.append(document.createTextNode(" · " + describeGap(row.value, benchmark.value).label));
  }
  hero.append(meta);
  return hero;
}

function renderStrategyCard(row, rank, benchmark) {
  const info = strategyInfo(row.strategy, row.timeframe);
  const hold = holdingOf(row);
  const pnl = describePnl(row.value);
  const card = el("article", "card");
  const top = el("div", "card-top");
  const title = el("h3");
  const link = el("a", "", info.title);
  link.href = info.href;
  title.append(link);
  title.append(tip(info.caption));
  top.append(title);
  top.append(el("span", "rank", "อันดับ " + rank));
  card.append(top);
  card.append(el("p", "quiet", clockLabel(row.timeframe)));
  const rowLine = el("div", "card-row");
  rowLine.append(el("p", "card-money num", dollars(row.value)));
  rowLine.append(el("p", "pnl num " + pnl.tone, pnl.label));
  card.append(rowLine);
  const meta = el("p", "quiet");
  meta.append(document.createTextNode(hold.title));
  if (benchmark && benchmark.value != null) {
    meta.append(document.createTextNode(" · " + describeGap(row.value, benchmark.value).label));
  }
  card.append(meta);
  return card;
}

function renderBenchmarkCard(row) {
  const info = strategyInfo(row.strategy, row.timeframe);
  const hold = holdingOf(row);
  const pnl = describePnl(row.value);
  const card = el("article", "bench");
  const top = el("div", "bench-top");
  const title = el("h3");
  const link = el("a", "", "ตัวเทียบ · " + info.title);
  link.href = info.href;
  title.append(link);
  title.append(tip(info.caption));
  top.append(title);
  card.append(top);
  const rowLine = el("div", "card-row");
  rowLine.append(el("p", "card-money num", dollars(row.value)));
  rowLine.append(el("p", "pnl num " + pnl.tone, pnl.label));
  card.append(rowLine);
  card.append(el("p", "quiet", hold.title));
  return card;
}

function renderSummary(data, staleAssets) {
  const root = document.getElementById("summary-root");
  const grid = el("div", "coin-grid");
  COINS.forEach((asset) => {
    const ranked = rankRows(rowsFor(data, asset));
    const block = el("div", "coin");
    const head = el("div", "coin-head");
    head.append(el("h3", "", coinName(asset)));
    if (staleAssets.indexOf(asset) !== -1) {
      head.append(el("p", "chip amber", ticker(asset) + " ราคาค้าง · อัปเดตล่าสุด " + formatChip(latestPriceUnix(data, asset))));
    }
    block.append(head);
    if (ranked.best) block.append(renderHero(ranked.best, ranked.benchmark));
    const cards = el("div", "cards");
    ranked.rows.slice(1).forEach((row, index) => {
      cards.append(renderStrategyCard(row, index + 2, ranked.benchmark));
    });
    if (ranked.benchmark) cards.append(renderBenchmarkCard(ranked.benchmark));
    block.append(cards);
    grid.append(block);
  });
  root.replaceChildren(grid);
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
    else root.append(table);
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
    extra.append(extraTable);
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
  const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  if (dark) {
    return {
      bg: "#1a1a1a",
      text: "#f4f4f4",
      grid: "rgba(255,255,255,0.06)",
      scale: "#3a3a3a",
      up: "#3dd68c",
      down: "#ff8d8d",
      accent: "#8eb0ff",
      bench: "#8a8a8a",
    };
  }
  return {
    bg: "#ffffff",
    text: "#171717",
    grid: "rgba(23,23,23,0.06)",
    scale: "#e6e6e4",
    up: "#157a3b",
    down: "#c43131",
    accent: "#2457d6",
    bench: "#a3a3a3",
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
      lineWidth: key === bestKey ? 2 : 1,
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
  renderSummary(data, stale);
  renderTrades(data);
  renderHistory(data);
  renderReasons(data);
  setupCharts(data);
}

async function loadData() {
  const response = await fetch("data/dashboard.json");
  if (!response.ok) throw new Error("status " + response.status);
  return response.json();
}

function showLoadError() {
  const status = document.getElementById("page-status");
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
  };
}
