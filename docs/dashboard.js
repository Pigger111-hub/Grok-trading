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
    color1d: "#0a6b30",
    color4h: "#1f8f4e",
  },
  macd: {
    title: "แมคดี (MACD)",
    caption: "ถือเหรียญเมื่อเส้นเร็วอยู่เหนือเส้นช้า แล้วถือเงินสดเมื่อหลุด",
    href: "#term-macd",
    color1d: "#0b4f8a",
    color4h: "#1d6fbf",
  },
  donchian: {
    title: "กรอบดอนเชียน (Donchian)",
    caption: "ซื้อเมื่อราคาทะลุกรอบสูง ขายเมื่อหลุดกรอบต่ำ",
    href: "#term-donchian",
    color1d: "#8a3d00",
    color4h: "#c46512",
  },
  buy_and_hold: {
    title: "ซื้อแล้วถือเฉยๆ",
    caption: "ซื้อครั้งเดียวตอนเริ่ม แล้วไม่ขาย เป็นตัวเทียบ ไม่ใช่วิธีที่เลือก",
    href: "#term-bh",
    color1d: "#3d4752",
    color4h: "#3d4752",
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

function renderUpdated(data) {
  const list = document.getElementById("updated-list");
  list.replaceChildren();
  COINS.forEach((asset) => {
    const unix = latestPriceUnix(data, asset);
    const item = el("li", "", coinName(asset) + " อัปเดตราคาล่าสุดเมื่อ " + formatUnix(unix));
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
  const banner = document.getElementById("stale");
  const now = nowMs == null ? Date.now() : nowMs;
  const stale = COINS.filter((asset) => priceIsStale(latestPriceUnix(data, asset), now));
  banner.replaceChildren();
  if (!stale.length) {
    banner.hidden = true;
    return stale;
  }
  banner.hidden = false;
  banner.append(el("strong", "", "ข้อมูลราคาเก่ากว่า 8 ชั่วโมง"));
  const list = document.createElement("ul");
  stale.forEach((asset) => {
    list.append(el("li", "", coinName(asset) + " อัปเดตล่าสุดเมื่อ " + formatUnix(latestPriceUnix(data, asset))));
  });
  banner.append(list);
  banner.append(el("p", "", "ตัวเลขของเหรียญที่ขึ้นชื่อนี้ใช้ราคาเก่า อาจไม่ตรงกับราคาตอนนี้ หน้านี้แค่เตือนไว้ ไม่ได้ไปแก้ระบบดึงราคา"));
  return stale;
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

function renderStrategyCard(row, rank, benchmark) {
  const info = strategyInfo(row.strategy, row.timeframe);
  const hold = holdingOf(row);
  const pnl = describePnl(row.value);
  const card = el("article", rank === 1 ? "card best" : "card");
  if (rank === 1) card.append(el("p", "badge", bestBadge(row)));
  else card.append(el("p", "badge", "อันดับ " + rank));
  const title = el("h3");
  const link = el("a", "", info.title);
  link.href = info.href;
  title.append(link);
  card.append(title);
  card.append(el("p", "meta", clockLabel(row.timeframe)));
  card.append(el("p", "caption", info.caption));
  card.append(el("p", "money " + pnl.tone, dollars(row.value)));
  card.append(el("p", "pnl " + pnl.tone, pnl.label));
  card.append(el("p", "", "จากเงินเริ่ม 10,000 ดอลลาร์"));
  const status = el("p", "");
  status.append("ตอนนี้ ");
  status.append(el("span", "pill " + hold.klass, hold.title));
  status.append(" " + hold.caption);
  card.append(status);
  if (benchmark && benchmark.value != null) {
    const gap = describeGap(row.value, benchmark.value);
    card.append(el("p", "versus " + gap.tone, gap.label));
  }
  return card;
}

function renderBenchmarkCard(row) {
  const info = strategyInfo(row.strategy, row.timeframe);
  const hold = holdingOf(row);
  const pnl = describePnl(row.value);
  const card = el("article", "card bench");
  card.append(el("p", "badge bench", "ตัวเทียบ ไม่ได้อยู่ในอันดับ"));
  const title = el("h3");
  const link = el("a", "", info.title);
  link.href = info.href;
  title.append(link);
  card.append(title);
  card.append(el("p", "caption", info.caption));
  card.append(el("p", "money " + pnl.tone, dollars(row.value)));
  card.append(el("p", "pnl " + pnl.tone, pnl.label));
  card.append(el("p", "", "จากเงินเริ่ม 10,000 ดอลลาร์"));
  const status = el("p", "");
  status.append("ตอนนี้ ");
  status.append(el("span", "pill " + hold.klass, hold.title));
  status.append(" " + hold.caption);
  card.append(status);
  return card;
}

function renderSummary(data, staleAssets) {
  const root = document.getElementById("summary-root");
  const grid = el("div", "coin-grid");
  COINS.forEach((asset) => {
    const ranked = rankRows(rowsFor(data, asset));
    const block = el("div", "coin");
    block.append(el("h3", "", coinName(asset)));
    if (staleAssets.indexOf(asset) !== -1) {
      block.append(el("p", "warning-inline", "ราคาของเหรียญนี้เก่ากว่า 8 ชั่วโมง ตัวเลขด้านล่างอาจไม่ทันราคาตอนนี้"));
    }
    block.append(el("p", "coin-lead", coinLead(ranked)));
    const cards = el("div", "cards");
    ranked.rows.forEach((row, index) => {
      cards.append(renderStrategyCard(row, index + 1, ranked.benchmark));
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
    root.replaceChildren(el("p", "", "ยังไม่มีรายการซื้อขาย"));
    return;
  }
  const stack = el("div", "stack");
  trades.forEach((row) => {
    const info = strategyInfo(row.strategy, row.timeframe);
    const result = tradeResult(row);
    const card = el("article", "row-card");
    card.append(el("h3", "", coinName(row.asset) + " · " + info.title));
    card.append(el("p", "meta", clockLabel(row.timeframe)));
    card.append(el("p", "", "ซื้อเมื่อ " + formatStamp(row.entry_date)));
    card.append(el("p", "", row.closed ? "ขายเมื่อ " + formatStamp(row.exit_date) : "ยังไม่ขาย ถือเหรียญอยู่"));
    card.append(el("p", "pnl " + result.tone, result.label));
    stack.append(card);
  });
  root.replaceChildren(stack);
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
    const stack = el("div", "stack");
    const extraStack = el("div", "stack");
    if (!group.length) stack.append(el("p", "", "ไม่มีผลทดสอบของเหรียญนี้"));
    group.forEach((row, index) => {
      const growth = signedPercent(row.cagr);
      const drop = signedPercent(row.max_drawdown);
      const card = el("article", index === 0 ? "row-card best" : "row-card");
      card.append(el("p", "badge" + (index === 0 ? "" : ""), index === 0 ? "อันดับ 1 ของช่วงทดสอบเก่า" : "อันดับ " + (index + 1)));
      card.append(el("h3", "", plainHistoryName(row)));
      card.append(el("p", "meta", clockLabel(row.timeframe)));
      if (growth) {
        const word = growth.raw >= 0 ? "โตเฉลี่ยปีละ " : "หดเฉลี่ยปีละ ";
        card.append(el("p", "pnl " + growth.tone, word + growth.shown + "%"));
      }
      if (drop) card.append(el("p", "bad", "ร่วงจากจุดสูงสุด (drawdown) " + drop.shown + "%"));
      card.append(el("p", "", "ซื้อขาย " + row.n_trades + " ครั้ง"));
      if (STRATEGY_INFO[row.strategy] && row.strategy !== "buy_and_hold") {
        card.append(el("p", "caption", "วิธีนี้มีในเงินสมมติด้านบนด้วย"));
      }
      stack.append(card);

      const more = el("article", "row-card");
      more.append(el("h3", "", coinName(asset) + " · " + plainHistoryName(row) + " · " + clockLabel(row.timeframe)));
      const win = signedPercent(row.win_rate);
      more.append(el("p", "", win ? "รอบที่ได้กำไร " + win.shown + "% ของรอบทั้งหมด" : "ไม่มีอัตราชนะ"));
      const sharpe = row.sharpe == null ? "ไม่มี" : numberText(Number(row.sharpe), 2);
      more.append(el("p", "", "คะแนนความคุ้มความเสี่ยง " + sharpe));
      extraStack.append(more);
    });
    root.append(stack);
    extra.append(el("h3", "", coinName(asset)));
    extra.append(extraStack);
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
    const card = el("article", "row-card");
    card.append(el("h3", "", info.title));
    card.append(el("p", "", row.why_th || ""));
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
    const swatch = el("span", benchmark ? "swatch dashed" : "swatch");
    swatch.style.background = info.color;
    swatch.style.color = info.color;
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

function chartOptions(elNode) {
  return {
    width: elNode.clientWidth || 320,
    height: elNode.clientHeight || 420,
    layout: {
      background: { color: "#ffffff" },
      textColor: "#102017",
      fontFamily: '"Noto Sans Thai", Sarabun, sans-serif',
      fontSize: 18,
    },
    grid: {
      vertLines: { color: "#e1e8e4" },
      horzLines: { color: "#e1e8e4" },
    },
    rightPriceScale: { borderColor: "#5c6b64" },
    timeScale: {
      borderColor: "#5c6b64",
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
  const label = String(text || "");
  const intraday = label.indexOf("4") !== -1;
  const sell = label.indexOf("ขาย") !== -1;
  if (sell && intraday) return "#8a3d00";
  if (sell) return "#9d1c1c";
  if (intraday) return "#0b4f8a";
  return "#0a6b30";
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
  const series = priceChart.addCandlestickSeries({
    upColor: "#0a6b30",
    downColor: "#9d1c1c",
    borderUpColor: "#0a6b30",
    borderDownColor: "#9d1c1c",
    wickUpColor: "#0a6b30",
    wickDownColor: "#9d1c1c",
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
    const series = equityChart.addLineSeries({
      color: info.color,
      lineWidth: key === bestKey ? 4 : 2,
      lineStyle: benchmark ? 2 : 0,
      priceLineVisible: false,
      lastValueVisible: true,
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
