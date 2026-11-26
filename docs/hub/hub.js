"use strict";

// Reads the paper book at ../data/dashboard.json plus docs/hub/data/*.json.
// It only changes how numbers are shown. Equity in the paper file is indexed
// to 100 at the start, and START_DOLLARS matches crypto_lab.assumptions.INITIAL_CASH.
const START_DOLLARS = 10000;
const STALE_MS = 8 * 60 * 60 * 1000;
const LAST_HALVING_MS = Date.UTC(2024, 3, 20);
const HALVING_CYCLE_MS = 210000 * 10 * 60 * 1000;
const MACRO_IDS = ["DFF", "M2SL", "WALCL", "BTC"];
const NAV = [
  { id: "overview", label: "ภาพรวม" },
  { id: "bot", label: "บอทเงินสมมติ" },
  { id: "macro", label: "เศรษฐกิจมหภาค" },
  { id: "news", label: "ข่าว" },
  { id: "study", label: "เรียนและทุน" },
];
const SPECS = [
  { id: "sma_filter", tf: "1d", title: "SMA 200", detail: "เส้นค่าเฉลี่ย 200 วัน", q: "sma เส้นค่าเฉลี่ย" },
  { id: "sma_filter", tf: "4h", title: "SMA 200", detail: "เส้นค่าเฉลี่ย 200 แท่ง · 4h", q: "sma 4h เส้นค่าเฉลี่ย" },
  { id: "macd", tf: "1d", title: "MACD", detail: "12/26/9 · รายวัน", q: "macd แมคดี" },
  { id: "macd", tf: "4h", title: "MACD", detail: "12/26/9 · 4h", q: "macd 4h แมคดี" },
  { id: "donchian", tf: "1d", title: "Donchian", detail: "20/10 · รายวัน", q: "donchian ดอนเชียน" },
  { id: "donchian", tf: "4h", title: "Donchian", detail: "20/10 · 4h", q: "donchian 4h ดอนเชียน" },
];
const DEFAULT_CHECKS = [
  { id: "reading", label: "Reading" },
  { id: "listening", label: "Listening" },
  { id: "writing", label: "Writing" },
  { id: "speaking", label: "Speaking" },
];
const STROKE = { up: "#059669", down: "#DC2626", flat: "#9CA3AF" };

function equityDollars(indexValue) {
  return (Number(indexValue) / 100) * START_DOLLARS;
}

function positionValue(row) {
  if (!row) return null;
  const cash = Number(row.cash);
  const market = Number(row.market_value);
  if (!Number.isFinite(cash) || !Number.isFinite(market)) return null;
  return cash + market;
}

function paperModels(data) {
  const cards = [];
  ["BTC", "ETH"].forEach((asset) => {
    const positions = ((data && data.positions) || []).filter((row) => row.asset === asset);
    const benchRow = positions.find((row) => row.strategy === "buy_and_hold") || null;
    const equity = (data && data.equity && data.equity[asset]) || {};
    SPECS.forEach((spec) => {
      const row = positions.find((item) => item.strategy === spec.id && item.timeframe === spec.tf);
      if (!row) return;
      cards.push({
        asset,
        strategy: spec.id,
        timeframe: spec.tf,
        title: spec.title,
        detail: spec.detail,
        q: spec.q,
        value: positionValue(row),
        side: row.side,
        bench: positionValue(benchRow),
        series: equity[spec.id + "|" + spec.tf] || [],
        benchSeries: equity["buy_and_hold|4h"] || equity["buy_and_hold|1d"] || [],
      });
    });
  });
  return cards;
}

function bestBook(models) {
  let best = null;
  (models || []).forEach((card) => {
    if (card.value == null || !Number.isFinite(card.value)) return;
    if (!best || card.value > best.value) best = card;
  });
  return best;
}

function isStale(unixSeconds, nowMs) {
  if (unixSeconds == null || nowMs == null) return true;
  return nowMs - Number(unixSeconds) * 1000 > STALE_MS;
}

function latestDataUnix(data) {
  const times = [];
  ["BTC", "ETH"].forEach((asset) => {
    const candles = (data && data.candles && data.candles[asset]) || [];
    if (candles.length) times.push(Number(candles[candles.length - 1].time));
  });
  const finite = times.filter((time) => Number.isFinite(time));
  if (!finite.length) return null;
  return Math.min.apply(null, finite);
}

function bangkokHour(nowMs) {
  const hour = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Bangkok",
    hour: "numeric",
    hourCycle: "h23",
  }).format(nowMs);
  return Number(hour);
}

function greeting(nowMs) {
  const hour = bangkokHour(nowMs);
  if (hour < 12) return "สวัสดีตอนเช้า";
  if (hour < 17) return "สวัสดีตอนบ่าย";
  return "สวัสดีตอนเย็น";
}

function formatToday(nowMs) {
  return new Intl.DateTimeFormat("th-TH-u-ca-buddhist-nu-latn", {
    timeZone: "Asia/Bangkok",
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(nowMs);
}

function formatBangkok(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "ไม่ทราบเวลา";
  const text = new Intl.DateTimeFormat("th-TH-u-ca-buddhist-nu-latn", {
    timeZone: "Asia/Bangkok",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
  return text + " น.";
}

function formatIsoDate(iso) {
  if (!iso) return "ไม่ทราบวัน";
  const parts = String(iso).split("-").map(Number);
  if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return "ไม่ทราบวัน";
  return new Intl.DateTimeFormat("th-TH-u-ca-buddhist-nu-latn", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(Date.UTC(parts[0], parts[1] - 1, parts[2], 12));
}

function bangkokDay(nowMs) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Bangkok",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(nowMs);
}

function daysUntil(dateStr, nowMs) {
  if (!dateStr) return null;
  const today = Date.parse(bangkokDay(nowMs) + "T00:00:00Z");
  const target = Date.parse(dateStr + "T00:00:00Z");
  if (!Number.isFinite(today) || !Number.isFinite(target)) return null;
  return Math.round((target - today) / 86400000);
}

function isoWeekKey(nowMs) {
  const day = bangkokDay(nowMs);
  const date = new Date(day + "T00:00:00Z");
  const utc = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNum = utc.getUTCDay() || 7;
  utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((utc - yearStart) / 86400000 + 1) / 7);
  return utc.getUTCFullYear() + "-W" + String(week).padStart(2, "0");
}

function checklistKey(nowMs) {
  return "ielts-" + isoWeekKey(nowMs);
}

function halvingStatus(nowMs) {
  const elapsed = nowMs - LAST_HALVING_MS;
  const daysSince = Math.floor(elapsed / 86400000);
  const nextMs = LAST_HALVING_MS + HALVING_CYCLE_MS;
  const daysUntilNext = Math.ceil((nextMs - nowMs) / 86400000);
  const progress = Math.min(1, Math.max(0, elapsed / HALVING_CYCLE_MS));
  return {
    daysSince,
    daysUntil: daysUntilNext,
    progress,
    nextMs,
    cycleDays: Math.round(HALVING_CYCLE_MS / 86400000),
  };
}

function rangeMs(range) {
  if (range === "day") return 86400000;
  if (range === "month") return 30 * 86400000;
  return 7 * 86400000;
}

function windowLabel(range) {
  if (range === "day") return "1 วัน";
  if (range === "month") return "30 วัน";
  return "7 วัน";
}

function sortedPoints(points) {
  return (points || [])
    .filter((point) => point && Number.isFinite(point.t) && Number.isFinite(point.value))
    .slice()
    .sort((a, b) => a.t - b.t);
}

function slicePoints(points, range) {
  const rows = sortedPoints(points);
  if (!rows.length) return [];
  const last = rows[rows.length - 1];
  const start = last.t - rangeMs(range);
  const sliced = rows.filter((point) => point.t >= start);
  if (sliced.length >= 2) return sliced;
  return rows.slice(Math.max(0, rows.length - 2));
}

function changeOver(points, range) {
  const rows = sortedPoints(points);
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  const cutoff = last.t - rangeMs(range);
  let base = null;
  rows.forEach((point) => {
    if (point.t <= cutoff) base = point;
  });
  if (!base) base = rows[0];
  if (base === last) return { diff: 0, pct: 0, from: last.value, to: last.value, spanDays: 0 };
  const diff = last.value - base.value;
  const pct = base.value === 0 ? null : (diff / base.value) * 100;
  return { diff, pct, from: base.value, to: last.value, spanDays: (last.t - base.t) / 86400000 };
}

function formatTrend(change, kind, range) {
  const windowDays = rangeMs(range) / 86400000;
  const label = change && change.spanDays > windowDays + 1.5 ? "จากจุดก่อนหน้า" : windowLabel(range);
  if (!change) return { tone: "flat", text: "ไม่มีตัวเลข" };
  if (kind === "points") {
    if (Math.abs(change.diff) < 0.005) return { tone: "flat", text: "ทรงตัว · " + label };
    const tone = change.diff > 0 ? "up" : "down";
    const arrow = change.diff > 0 ? "▲" : "▼";
    const sign = change.diff > 0 ? "+" : "−";
    return { tone, text: arrow + " " + sign + Math.abs(change.diff).toFixed(2) + " จุด · " + label };
  }
  if (change.pct == null || Math.abs(change.pct) < 0.05) return { tone: "flat", text: "ทรงตัว · " + label };
  const tone = change.pct > 0 ? "up" : "down";
  const arrow = change.pct > 0 ? "▲" : "▼";
  const sign = change.pct > 0 ? "+" : "−";
  return { tone, text: arrow + " " + sign + Math.abs(change.pct).toFixed(1) + "% · " + label };
}

function formatDollars(value) {
  if (!Number.isFinite(value)) return "—";
  return "$" + Math.round(value).toLocaleString("en-US");
}

function formatMacro(id, value) {
  if (!Number.isFinite(value)) return { headline: "—", unit: "", raw: "" };
  if (id === "DFF") {
    return { headline: value.toFixed(2) + "%", unit: "ต่อปี", raw: "Effective Federal Funds Rate" };
  }
  if (id === "M2SL") {
    return {
      headline: "$" + (value / 1000).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      unit: "ล้านล้านดอลลาร์",
      raw: "FRED " + value.toLocaleString("en-US") + " พันล้านดอลลาร์",
    };
  }
  if (id === "WALCL") {
    return {
      headline: "$" + (value / 1e6).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      unit: "ล้านล้านดอลลาร์",
      raw: "FRED " + value.toLocaleString("en-US") + " ล้านดอลลาร์",
    };
  }
  if (id === "BTC") {
    return { headline: formatDollars(value), unit: "ดอลลาร์", raw: "ปิดรายวัน" };
  }
  return { headline: String(value), unit: "", raw: "" };
}

function pnlLabel(value) {
  if (!Number.isFinite(value)) return { tone: "flat", pct: null, text: "ไม่มีตัวเลข" };
  const diff = value - START_DOLLARS;
  const pct = (diff / START_DOLLARS) * 100;
  if (Math.abs(diff) < 0.5) return { tone: "flat", pct, text: "เท่าทุน" };
  const digits = Math.abs(pct).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (diff > 0) return { tone: "up", pct, text: "กำไร " + digits + "%" };
  return { tone: "down", pct, text: "ขาดทุน " + digits + "%" };
}

function gapLabel(value, benchmark) {
  if (value == null || benchmark == null || !Number.isFinite(value) || !Number.isFinite(benchmark)) {
    return { tone: "flat", text: "ยังเทียบกับซื้อแล้วถือไม่ได้" };
  }
  const diff = value - benchmark;
  if (Math.abs(diff) < 0.5) return { tone: "flat", text: "พอ ๆ กับซื้อแล้วถือ" };
  const amount = Math.abs(Math.round(diff)).toLocaleString("en-US");
  if (diff > 0) return { tone: "up", text: "มากกว่าซื้อแล้วถือ " + amount + " ดอลลาร์" };
  return { tone: "down", text: "น้อยกว่าซื้อแล้วถือ " + amount + " ดอลลาร์" };
}

function holdingBadge(side) {
  if (side === "long") return { tone: "up", text: "ถือเหรียญ" };
  return { tone: "warn", text: "ถือเงินสด" };
}

function equityPoints(series) {
  return sortedPoints((series || []).map((point) => ({ t: Number(point.time) * 1000, value: Number(point.value) })));
}

function macroPoints(row) {
  const points = row && Array.isArray(row.points) ? row.points : [];
  return sortedPoints(points.map((point) => ({
    t: Date.parse(point.date + "T00:00:00Z"),
    value: Number(point.value),
    date: point.date,
  })));
}

function macroRow(macro, id) {
  const row = macro && macro.series && macro.series[id];
  if (!row) return { id, points: [], error: true, meta: null };
  return { id, points: macroPoints(row), error: Boolean(row.error), meta: row };
}

if (typeof document !== "undefined") {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const state = {
    range: "week",
    query: "",
    paper: null,
    macro: null,
    news: null,
    goals: null,
    paintedStudy: false,
    paintedNews: false,
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function pill(tone, text) {
    const node = el("span", "pill " + tone);
    node.append(el("span", "dot"));
    node.append(document.createTextNode(text));
    return node;
  }

  function countUp(node, target, format) {
    if (!Number.isFinite(target) || reduced) {
      node.textContent = format(target);
      return;
    }
    const start = performance.now();
    function tick(now) {
      const progress = Math.min(1, (now - start) / 700);
      const eased = 1 - Math.pow(1 - progress, 3);
      node.textContent = format(target * eased);
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function drawChart(host, values, tone, benchValues, label) {
    const width = 640;
    const height = host.classList.contains("spark") ? 56 : 168;
    const pad = 6;
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("class", "chart");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label || "กราฟ");
    if (!values.length) {
      host.append(svg);
      return;
    }
    const benchOk = benchValues && benchValues.length === values.length && benchValues.every((value) => Number.isFinite(value));
    const pool = values.slice();
    if (benchOk) pool.push.apply(pool, benchValues);
    const rawLo = Math.min.apply(null, pool);
    const rawHi = Math.max.apply(null, pool);
    const rel = Math.abs(rawHi) > 0 ? (rawHi - rawLo) / Math.abs(rawHi) : 0;
    let lo = rawLo;
    let hi = rawHi;
    if (!(hi > lo)) {
      const slack = Math.abs(lo) * 0.02 || 1;
      lo -= slack;
      hi += slack;
    }
    const span = hi - lo;
    function xy(value, index, count) {
      const x = count === 1 ? width / 2 : pad + (index / (count - 1)) * (width - pad * 2);
      const y = pad + (1 - (value - lo) / span) * (height - pad * 2);
      return [x, y];
    }
    const main = values.map((value, index) => xy(value, index, values.length));
    const line = main.map((pair, index) => (index ? "L" : "M") + pair[0].toFixed(1) + " " + pair[1].toFixed(1)).join(" ");
    const color = STROKE[tone] || STROKE.flat;
    if (main.length > 1 && rel >= 0.004 && !host.classList.contains("spark")) {
      const fill = document.createElementNS(svgNS, "path");
      const last = main[main.length - 1];
      const first = main[0];
      fill.setAttribute("d", line + " L" + last[0].toFixed(1) + " " + (height - pad) + " L" + first[0].toFixed(1) + " " + (height - pad) + " Z");
      fill.setAttribute("class", "fill");
      fill.setAttribute("fill", color);
      svg.append(fill);
    }
    if (benchOk) {
      const bench = document.createElementNS(svgNS, "path");
      const d = benchValues.map((value, index) => {
        const pair = xy(value, index, benchValues.length);
        return (index ? "L" : "M") + pair[0].toFixed(1) + " " + pair[1].toFixed(1);
      }).join(" ");
      bench.setAttribute("d", d);
      bench.setAttribute("class", "bench");
      svg.append(bench);
    }
    const path = document.createElementNS(svgNS, "path");
    path.setAttribute("d", line);
    path.setAttribute("class", "line");
    path.setAttribute("stroke", color);
    svg.append(path);
    host.append(svg);
    if (main.length > 1) {
      requestAnimationFrame(() => {
        const length = path.getTotalLength();
        if (!length) {
          path.style.strokeDashoffset = "0";
          return;
        }
        path.style.setProperty("--len", String(length));
        path.style.strokeDasharray = String(length);
        path.style.strokeDashoffset = reduced ? "0" : String(length);
        if (!reduced) requestAnimationFrame(() => path.classList.add("draw"));
      });
    }
  }

  function failNote() {
    return el("p", "fail", "ไม่สามารถอัปเดตได้");
  }

  function setCurrent(id) {
    document.querySelectorAll("[data-nav]").forEach((link) => {
      if (link.getAttribute("data-nav") === id) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    });
    const item = NAV.find((entry) => entry.id === id);
    const crumb = document.getElementById("crumb");
    if (crumb && item) crumb.textContent = item.label;
  }

  function applyFilter() {
    const query = state.query.trim().toLowerCase();
    document.querySelectorAll("[data-q]").forEach((node) => {
      const hay = (node.getAttribute("data-q") || "").toLowerCase();
      node.hidden = Boolean(query) && hay.indexOf(query) === -1;
    });
    document.querySelectorAll(".coin-block").forEach((block) => {
      const cards = Array.from(block.querySelectorAll("[data-q]"));
      block.hidden = cards.length > 0 && cards.every((card) => card.hidden);
    });
    document.querySelectorAll("[data-empty]").forEach((node) => {
      const root = document.getElementById(node.getAttribute("data-empty") + "-root");
      const cards = root ? Array.from(root.querySelectorAll("[data-q]")) : [];
      const any = cards.some((card) => !card.hidden);
      node.hidden = any || !query;
    });
  }

  function renderKpis(animate) {
    const root = document.getElementById("kpi-root");
    root.replaceChildren();
    const models = paperModels(state.paper || {});
    const best = bestBook(models);
    const cards = [];
    if (!state.paper || !best) {
      cards.push({ q: "บอท เงินสมมติ", title: "บอทที่ดีที่สุด", fail: true });
    } else {
      const dollars = equityPoints(best.series).map((point) => ({ t: point.t, value: equityDollars(point.value) }));
      const trend = formatTrend(changeOver(dollars.length ? dollars : [{ t: Date.now(), value: best.value }], state.range), "percent", state.range);
      const pnl = pnlLabel(best.value);
      cards.push({
        q: "บอท เงินสมมติ " + best.asset + " " + best.title + " " + best.detail,
        title: "บอทที่ดีที่สุด",
        headline: formatDollars(best.value),
        number: best.value,
        format: formatDollars,
        unit: best.asset + " · " + best.title + " · " + (best.timeframe === "4h" ? "4h" : "รายวัน"),
        trend,
        extra: pnl.text + " ตั้งแต่เริ่ม",
        extraTone: pnl.tone,
      });
    }
    ["BTC", "DFF"].forEach((id) => {
      const row = macroRow(state.macro, id);
      const meta = row.meta || {};
      const q = id === "BTC" ? "btc bitcoin บิตคอยน์ ราคา" : "dff fed funds ดอกเบี้ย";
      if (!row.points.length) {
        cards.push({ q, title: meta.title_th || (id === "BTC" ? "ราคาบิตคอยน์" : "ดอกเบี้ย Fed Funds"), fail: true });
        return;
      }
      const shown = formatMacro(id, row.points[row.points.length - 1].value);
      const trend = formatTrend(changeOver(row.points, state.range), id === "DFF" ? "points" : "percent", state.range);
      cards.push({
        q,
        title: meta.title_th || id,
        headline: shown.headline,
        number: id === "M2SL" ? row.points[row.points.length - 1].value / 1000 : id === "WALCL" ? row.points[row.points.length - 1].value / 1e6 : row.points[row.points.length - 1].value,
        format: id === "DFF"
          ? (value) => value.toFixed(2) + "%"
          : id === "BTC"
            ? formatDollars
            : (value) => "$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
        unit: shown.unit,
        trend,
        failLine: row.error,
      });
    });
    cards.forEach((card, index) => {
      const node = el("article", "kpi" + (animate ? " arrive" : ""));
      node.dataset.q = card.q;
      if (animate) node.style.animationDelay = Math.min(index, 6) * 40 + "ms";
      node.append(el("p", "kicker", card.title));
      if (card.fail) {
        node.append(failNote());
      } else {
        const value = el("p", "kpi-value", animate ? "" : card.headline);
        node.append(value);
        if (animate && Number.isFinite(card.number)) countUp(value, card.number, card.format);
        else value.textContent = card.headline;
        if (card.unit) node.append(el("p", "unit", card.unit));
        if (card.trend) node.append(el("p", "trend " + card.trend.tone, card.trend.text));
        if (card.extra) node.append(el("p", "sub " + card.extraTone, card.extra));
        if (card.failLine) node.append(failNote());
      }
      root.append(node);
    });
  }

  function renderBot(animate) {
    const root = document.getElementById("bot-root");
    const meta = document.getElementById("bot-meta");
    root.replaceChildren();
    meta.replaceChildren();
    if (!state.paper) {
      root.append(failNote());
      return;
    }
    const unix = latestDataUnix(state.paper);
    const when = unix == null ? "ไม่ทราบเวลา" : formatBangkok(new Date(unix * 1000).toISOString());
    meta.append(el("span", "meta", "อัปเดตล่าสุด " + when));
    if (isStale(unix, Date.now())) {
      const badge = pill("warn", "ข้อมูลเก่า");
      badge.title = "data stale";
      meta.append(badge);
    }
    const models = paperModels(state.paper);
    ["BTC", "ETH"].forEach((asset) => {
      const block = el("div", "coin-block");
      block.append(el("h3", "coin-label", asset));
      const grid = el("div", "cards cards-3");
      models.filter((model) => model.asset === asset).forEach((model, index) => {
        const pnl = pnlLabel(model.value);
        const gap = gapLabel(model.value, model.bench);
        const hold = holdingBadge(model.side);
        const series = equityPoints(model.series);
        const bench = equityPoints(model.benchSeries);
        const sliced = slicePoints(series, state.range);
        const change = formatTrend(changeOver(series, state.range), "percent", state.range);
        const benchByTime = bench;
        const benchValues = sliced.map((point) => {
          let value = null;
          benchByTime.forEach((other) => {
            if (other.t <= point.t) value = other.value;
          });
          return value;
        });
        const card = el("article", "card" + (animate ? " arrive" : ""));
        card.dataset.q = [asset, model.title, model.detail, model.q, hold.text, "ซื้อแล้วถือ"].join(" ").toLowerCase();
        if (animate) card.style.animationDelay = Math.min(index, 8) * 35 + "ms";
        const top = el("div", "card-top");
        const titles = el("div");
        titles.append(el("h3", "", model.title));
        titles.append(el("p", "meta", model.detail));
        top.append(titles);
        top.append(pill(hold.tone, hold.text));
        card.append(top);
        const value = el("p", "big");
        card.append(value);
        if (animate && Number.isFinite(model.value)) countUp(value, model.value, formatDollars);
        else value.textContent = formatDollars(model.value);
        card.append(el("p", "pnl " + pnl.tone, pnl.text + " ตั้งแต่เริ่ม"));
        card.append(el("p", "sub " + gap.tone, gap.text));
        const spark = el("div", "spark");
        drawChart(spark, sliced.map((point) => point.value), change.tone, benchValues, model.title + " เทียบซื้อแล้วถือ");
        card.append(spark);
        const legend = el("p", "legend");
        const mine = el("span", "", "วิธีนี้");
        mine.style.color = STROKE[change.tone] || STROKE.flat;
        legend.append(mine);
        legend.append(el("span", "", "ซื้อแล้วถือ"));
        card.append(legend);
        card.append(el("p", "trend " + change.tone, "ช่วงนี้ " + change.text));
        grid.append(card);
      });
      block.append(grid);
      root.append(block);
    });
    if (!models.length) root.append(failNote());
  }

  function renderMacro(animate) {
    const root = document.getElementById("macro-root");
    root.replaceChildren();
    if (!state.macro) {
      const card = el("article", "card");
      card.dataset.q = "เศรษฐกิจ fred";
      card.append(failNote());
      root.append(card);
    } else {
      MACRO_IDS.forEach((id, index) => {
        const row = macroRow(state.macro, id);
        const meta = row.meta || {};
        const card = el("article", "card" + (animate ? " arrive" : ""));
        card.dataset.q = [id, meta.title_th, meta.title_en, meta.source, "เศรษฐกิจ"].join(" ").toLowerCase();
        if (animate) card.style.animationDelay = Math.min(index, 6) * 40 + "ms";
        const top = el("div", "card-top");
        const titles = el("div");
        titles.append(el("h3", "", meta.title_th || id));
        titles.append(el("p", "meta", (meta.title_en || id) + " · " + (meta.frequency_th || "")));
        top.append(titles);
        if (meta.source) top.append(el("span", "ticker", id));
        card.append(top);
        if (!row.points.length) {
          card.append(failNote());
          root.append(card);
          return;
        }
        const last = row.points[row.points.length - 1];
        const shown = formatMacro(id, last.value);
        const trend = formatTrend(changeOver(row.points, state.range), id === "DFF" ? "points" : "percent", state.range);
        const value = el("p", "big", shown.headline);
        card.append(value);
        card.append(el("p", "unit", shown.unit));
        card.append(el("p", "trend " + trend.tone, trend.text));
        const host = el("div", "chart-host");
        drawChart(host, slicePoints(row.points, state.range).map((point) => point.value), trend.tone, null, meta.title_th || id);
        card.append(host);
        card.append(el("p", "meta", (shown.raw ? shown.raw + " · " : "") + "ข้อมูล ณ " + formatIsoDate(last.date)));
        if (meta.source_url) {
          const link = el("a", "goal-link", meta.source || "แหล่งข้อมูล");
          link.href = meta.source_url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          card.append(link);
        }
        if (row.error) card.append(failNote());
        root.append(card);
      });
    }
    const cycle = halvingStatus(Date.now());
    const card = el("article", "card wide" + (animate ? " arrive" : ""));
    card.dataset.q = "halving bitcoin btc บิตคอยน์ รอบ 4 ปี";
    const body = el("div", "halving");
    const left = el("div");
    left.append(el("p", "kicker", "รอบ Halving ของ Bitcoin"));
    const big = el("p", "big");
    left.append(big);
    if (cycle.daysUntil >= 0) {
      if (animate) countUp(big, cycle.daysUntil, (value) => Math.round(value).toLocaleString("en-US"));
      else big.textContent = cycle.daysUntil.toLocaleString("en-US");
      left.append(el("p", "unit", "วันจนถึงรอบถัดไปโดยประมาณ"));
    } else {
      big.textContent = "เลยกำหนดโดยประมาณ";
    }
    const right = el("div");
    right.append(el("p", "sub flat", "ผ่านมา " + cycle.daysSince.toLocaleString("en-US") + " วัน จาก halving 20 เม.ย. 2024"));
    const track = el("div", "track");
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(Math.round(cycle.progress * 100)));
    const fill = el("div", "fill");
    track.append(fill);
    right.append(track);
    const nextText = new Intl.DateTimeFormat("th-TH-u-ca-buddhist-nu-latn", {
      timeZone: "Asia/Bangkok",
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(cycle.nextMs);
    right.append(el("p", "meta", "รอบถัดไปโดยประมาณ " + nextText + " · คิดจาก 210,000 บล็อก บล็อกละ 10 นาที"));
    body.append(left, right);
    card.append(body);
    root.append(card);
    requestAnimationFrame(() => {
      fill.style.width = Math.round(cycle.progress * 100) + "%";
    });
  }

  function renderNews() {
    const root = document.getElementById("news-root");
    root.replaceChildren();
    const topics = state.news && state.news.topics ? state.news.topics : null;
    if (!topics) {
      const card = el("article", "card");
      card.dataset.q = "ข่าว";
      card.append(failNote());
      root.append(card);
      return;
    }
    ["spacex", "pltr", "macro"].forEach((id) => {
      const topic = topics[id] || { title_th: id, ticker: "", items: [], error: "fetch failed" };
      const card = el("article", "card");
      card.dataset.q = [topic.title_th, topic.ticker, "ข่าว", id].join(" ").toLowerCase();
      const top = el("div", "card-top");
      top.append(el("h3", "", topic.title_th || id));
      if (topic.ticker) top.append(el("span", "ticker", topic.ticker));
      card.append(top);
      const items = Array.isArray(topic.items) ? topic.items.slice(0, 5) : [];
      if (!items.length) {
        card.append(failNote());
        root.append(card);
        return;
      }
      const list = el("ul", "news-list");
      items.forEach((item) => {
        const li = el("li");
        const title = item.link ? el("a", "", item.title) : el("span", "", item.title);
        if (item.link) {
          title.href = item.link;
          title.target = "_blank";
          title.rel = "noopener noreferrer";
          title.append(el("span", "sr-only", " เปิดในแท็บใหม่"));
        }
        li.append(title);
        const bits = [];
        if (item.source) bits.push(item.source);
        bits.push(item.time ? formatBangkok(item.time) : "ไม่ทราบเวลา");
        li.append(el("p", "meta", bits.join(" · ")));
        list.append(li);
      });
      card.append(list);
      if (topic.error) card.append(failNote());
      root.append(card);
    });
  }

  function loadChecks() {
    try {
      const raw = localStorage.getItem("grok-hub-" + checklistKey(Date.now()));
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function saveChecks(checks) {
    try {
      localStorage.setItem("grok-hub-" + checklistKey(Date.now()), JSON.stringify(checks));
    } catch (error) {
      return;
    }
  }

  function renderStudy(animate) {
    const root = document.getElementById("study-root");
    root.replaceChildren();
    const goals = state.goals && Array.isArray(state.goals.goals) ? state.goals.goals : null;
    if (!goals) {
      const card = el("article", "card");
      card.dataset.q = "ทุน ielts";
      card.append(failNote());
      root.append(card);
    } else {
      goals.forEach((goal, index) => {
        const card = el("article", "card" + (animate ? " arrive" : ""));
        card.dataset.q = [goal.title, goal.note, "ทุน", "ielts", "เรียน"].join(" ").toLowerCase();
        if (animate) card.style.animationDelay = index * 40 + "ms";
        card.append(el("h3", "", goal.title));
        if (goal.note) card.append(el("p", "meta", goal.note));
        const days = daysUntil(goal.date, Date.now());
        if (days == null) {
          card.append(el("p", "big", "ตั้งวันสอบ"));
        } else if (days > 0) {
          const big = el("p", "big");
          card.append(big);
          if (animate) countUp(big, days, (value) => Math.max(0, Math.round(value)).toLocaleString("en-US"));
          else big.textContent = String(days);
          card.append(el("p", "unit", "วัน · " + formatIsoDate(goal.date)));
        } else if (days === 0) {
          card.append(el("p", "big", "วันนี้"));
        } else {
          card.append(el("p", "big", String(Math.abs(days))));
          card.append(el("p", "trend warn", "เลยมาแล้ว " + Math.abs(days) + " วัน"));
        }
        if (goal.link) {
          const link = el("a", "goal-link", "เปิดลิงก์");
          link.href = goal.link;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          card.append(link);
        }
        root.append(card);
      });
    }
    const checks = state.goals && Array.isArray(state.goals.checklist) && state.goals.checklist.length
      ? state.goals.checklist
      : DEFAULT_CHECKS;
    const saved = loadChecks();
    const card = el("article", "card");
    card.dataset.q = "ielts reading listening writing speaking เช็กลิสต์ เรียน";
    card.append(el("h3", "", "เช็กลิสต์ IELTS สัปดาห์นี้"));
    card.append(el("p", "meta", "ติ๊กแล้วเก็บในเบราว์เซอร์นี้เท่านั้น และเริ่มใหม่ทุกสัปดาห์"));
    const grid = el("div", "checks");
    checks.forEach((item) => {
      const button = el("button", "check");
      button.type = "button";
      button.dataset.id = item.id;
      const on = Boolean(saved[item.id]);
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.append(el("span", "mark"));
      button.append(document.createTextNode(item.label));
      button.addEventListener("click", () => {
        const next = button.getAttribute("aria-pressed") !== "true";
        button.setAttribute("aria-pressed", next ? "true" : "false");
        const current = loadChecks();
        current[item.id] = next;
        saveChecks(current);
      });
      grid.append(button);
    });
    card.append(grid);
    root.append(card);
  }

  function renderAll(animate) {
    renderKpis(animate);
    renderBot(animate);
    renderMacro(animate);
    if (!state.paintedNews) {
      renderNews();
      state.paintedNews = true;
    }
    if (!state.paintedStudy) {
      renderStudy(animate);
      state.paintedStudy = true;
    }
    applyFilter();
    const boot = document.getElementById("boot");
    if (boot) boot.hidden = true;
  }

  async function loadJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(url);
    return response.json();
  }

  function syncSeg() {
    document.querySelectorAll(".seg button").forEach((button) => {
      button.setAttribute("aria-pressed", button.getAttribute("data-range") === state.range ? "true" : "false");
    });
  }

  function tickClock() {
    const greet = document.getElementById("greet");
    const today = document.getElementById("today");
    if (greet) greet.textContent = greeting(Date.now());
    if (today) today.textContent = formatToday(Date.now());
  }

  async function main() {
    tickClock();
    setCurrent("overview");
    window.setInterval(tickClock, 60000);
    document.querySelectorAll(".seg button").forEach((button) => {
      button.addEventListener("click", () => {
        state.range = button.getAttribute("data-range");
        syncSeg();
        renderKpis(false);
        renderBot(false);
        renderMacro(false);
        applyFilter();
      });
    });
    const search = document.getElementById("search");
    search.addEventListener("input", () => {
      state.query = search.value;
      applyFilter();
    });
    search.form.addEventListener("submit", (event) => event.preventDefault());
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        search.focus();
        search.select();
      }
    });
    document.querySelectorAll("[data-nav]").forEach((link) => {
      link.addEventListener("click", () => setCurrent(link.getAttribute("data-nav")));
    });
    const sections = NAV.map((item) => document.getElementById(item.id)).filter(Boolean);
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) setCurrent(entry.target.id);
        });
      }, { rootMargin: "-45% 0px -50% 0px", threshold: 0.01 });
      sections.forEach((section) => observer.observe(section));
    }
    const [paper, macro, news, goals] = await Promise.all([
      loadJson("../data/dashboard.json").catch(() => null),
      loadJson("data/macro.json").catch(() => null),
      loadJson("data/news.json").catch(() => null),
      loadJson("data/goals.json").catch(() => null),
    ]);
    state.paper = paper;
    state.macro = macro;
    state.news = news;
    state.goals = goals;
    renderAll(true);
    if (!paper && !macro && !news && !goals) {
      const boot = document.getElementById("boot");
      if (boot) {
        boot.hidden = false;
        boot.textContent = "ไม่สามารถอัปเดตได้";
      }
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    START_DOLLARS,
    STALE_MS,
    SPECS,
    equityDollars,
    positionValue,
    paperModels,
    bestBook,
    isStale,
    latestDataUnix,
    greeting,
    formatToday,
    formatBangkok,
    formatIsoDate,
    daysUntil,
    isoWeekKey,
    checklistKey,
    halvingStatus,
    rangeMs,
    slicePoints,
    changeOver,
    formatTrend,
    formatDollars,
    formatMacro,
    pnlLabel,
    gapLabel,
    holdingBadge,
  };
}
