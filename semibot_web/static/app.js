const state = {
  reports: [],
  current: null,
  liveTimer: null,
  reportTimer: null,
  balanceTimer: null,
  balanceLoading: false,
  activeMarket: "domestic",
};

const BALANCE_REFRESH_MS = 60_000;
const REPORT_REFRESH_MS = 15_000;
const MOBILE_QUERY = "(max-width: 760px)";

const $ = (id) => document.getElementById(id);
const markets = {
  domestic: { label: "국내", report: "live_trading", currency: "KRW" },
  overseas: { label: "해외", report: "live_trading_overseas", currency: "USD" },
  nasdaq_surge: { label: "나스닥 급등주", report: "live_trading_nasdaq_surge", currency: "USD" },
  domestic_surge: { label: "국내 급등주", report: "live_trading_domestic_surge", currency: "KRW" },
  domestic_etf: { label: "국내ETF", report: "live_trading_domestic_etf", currency: "KRW" },
};

async function getJSON(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || response.statusText);
  return data;
}

function money(value, currency = "KRW") {
  const number = Number(value || 0);
  if (currency === "KRW") {
    return `${number.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}원`;
  }
  return `${number.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} ${currency}`;
}

function signedMoney(value, currency = "KRW") {
  const number = Number(value || 0);
  const sign = number > 0 ? "+" : "";
  return `${sign}${money(number, currency)}`;
}

function pct(value) {
  const number = Number(value || 0);
  const cls = number >= 0 ? "good" : "bad";
  return `<span class="${cls}">${number.toFixed(2)}%</span>`;
}

function number(value) {
  return Number(value || 0).toLocaleString("ko-KR", { maximumFractionDigits: 2 });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadReports() {
  const data = await getJSON("/api/reports");
  state.reports = data.reports;
  const select = $("reportSelect");
  select.innerHTML = "";
  for (const report of state.reports) {
    const option = document.createElement("option");
    option.value = report.name;
    option.textContent = report.label;
    select.appendChild(option);
  }
  if (state.reports.length) {
    const preferred = markets[state.activeMarket].report;
    if (state.reports.some((report) => report.name === preferred)) {
      select.value = preferred;
    }
    await loadReport(select.value || state.reports[0].name);
  }
}

async function loadReport(name) {
  const report = await getJSON(`/api/report?name=${encodeURIComponent(name)}`);
  state.current = report;
  renderReport(report);
}

function renderReport(report) {
  const metrics = report.metrics || {};
  const current = report.current || {};
  const daily = report.daily_summary || {};
  const reportMarket = Object.keys(markets).find((market) => markets[market].report === report.name);
  const currency = reportMarket ? marketCurrency(reportMarket) : "KRW";
  $("reportTitle").textContent = report.label || report.name;
  $("metricEquity").textContent = money(metrics.final_equity, currency);
  $("metricReturn").innerHTML = pct(metrics.total_return_pct);
  $("metricEntryLimit").textContent = entryLimitText(daily);
  $("metricDailyPnl").textContent = signedMoney(daily.pnl_amount, currency);
  $("metricDailyPnl").className = Number(daily.pnl_amount || 0) >= 0 ? "good" : "bad";
  $("metricDailyReturn").innerHTML = pct(daily.return_pct);
  $("metricDrawdown").innerHTML = pct(metrics.max_drawdown_pct);
  $("metricTrades").textContent = number(metrics.trades);
  $("metricWinRate").innerHTML = pct(metrics.sell_win_rate_pct);
  $("metricCost").textContent = money(metrics.explicit_trade_cost, currency);
  $("currentStatus").innerHTML = [
    `기준: ${current.time || "-"}`,
    `현금: ${money(current.cash, currency)}`,
    current.open_symbol ? `보유: ${current.open_symbol} ${current.open_shares}주` : "보유: 없음",
  ].join("<br />");

  renderTrades(report.trades || []);
  renderEquityChart(report.equity_curve || []);
  renderPnlChart(report.trades || []);
  renderDailyPnlChart(report.daily_pnl || []);
  renderToneSummary(report.tone_summary || {});
}

function entryLimitText(daily) {
  const limit = Number(daily.entry_limit || 0);
  if (!limit) return "-";
  const remaining = Math.max(0, Number(daily.entry_remaining || 0));
  return `${remaining.toLocaleString("ko-KR")} / ${limit.toLocaleString("ko-KR")}회`;
}

function toneLabel(tone) {
  const key = String(tone || "neutral").toLowerCase();
  if (key === "aggressive") return "공격";
  if (key === "conservative") return "보수";
  if (key === "premarket") return "프리장";
  return "중립";
}

function applyToneBadge(tone) {
  const badge = $("strategyToneBadge");
  const normalized = String(tone || "neutral").toLowerCase();
  badge.classList.remove("aggressive", "neutral", "conservative", "premarket");
  badge.classList.add(normalized);
  badge.textContent = toneLabel(normalized);
}

function renderToneSummary(summary) {
  const latestTone = String(summary.latest_tone || "neutral").toLowerCase();
  $("toneNow").textContent = `${toneLabel(latestTone)} (${summary.profile_mode || "auto"})`;
  $("toneSwitches").textContent = `${Number(summary.tone_switches || 0).toLocaleString("ko-KR")}회`;
  $("toneReentryBlocks").textContent = `${Number(summary.stop_loss_reentry_blocks || 0).toLocaleString("ko-KR")}회`;
  $("toneAvoidedLoss").textContent = marketMoney(summary.estimated_avoided_loss || 0);
  const counts = summary.tone_counts || {};
  const labels = ["aggressive", "neutral", "conservative"]
    .map((tone) => `${toneLabel(tone)} ${Number(counts[tone] || 0)}회`)
    .join(" / ");
  $("toneSummaryMeta").textContent = labels || "집계 데이터 없음";
}

function renderTrades(trades) {
  const rows = trades.slice(-120).reverse();
  $("tradeSummary").textContent = `${trades.length.toLocaleString("ko-KR")}건`;
  $("tradesBody").innerHTML = rows
    .map((trade) => {
      const pnl = Number(trade.realized_pnl || 0);
      return `<tr>
        <td data-label="시간">${trade.timestamp || trade.date || ""}</td>
        <td data-label="구분">${trade.action || ""}</td>
        <td data-label="종목">${trade.symbol || ""}</td>
        <td data-label="수량">${number(trade.shares)}</td>
        <td data-label="가격">${number(trade.price)}</td>
        <td data-label="실현손익" class="${pnl >= 0 ? "good" : "bad"}">${number(pnl)}</td>
        <td data-label="사유">${trade.reason || ""}</td>
      </tr>`;
    })
    .join("");
}

function renderEquityChart(points) {
  const values = points.map((point) => Number(point.equity || 0)).filter(Boolean);
  const labels = points.map((point) => point.datetime || point.date || "");
  $("equityRange").textContent = labels.length ? `${labels[0]} ~ ${labels[labels.length - 1]}` : "";
  drawLineChart($("equityChart"), values, { color: "#1463ff", fill: "rgba(20, 99, 255, 0.10)" });
}

function renderPnlChart(trades) {
  const sells = trades.filter((trade) => String(trade.action || "").startsWith("SELL"));
  const values = sells.map((trade) => Number(trade.realized_pnl || 0));
  drawBarChart($("pnlChart"), values);
}

function renderDailyPnlChart(days) {
  const values = days.map((day) => Number(day.pnl_amount || 0));
  $("dailyPnlRange").textContent = days.length ? `${days[0].date} ~ ${days[days.length - 1].date}` : "";
  drawBarChart($("dailyPnlChart"), values);
}

function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  // rect.width가 0이면 부모 요소 너비로 폴백 (details 닫힌 상태 등)
  const logicalWidth = rect.width || canvas.parentElement?.getBoundingClientRect().width || 300;
  const logicalHeight = rect.height || Number(canvas.getAttribute("height") || 260);
  canvas.width = Math.max(1, Math.floor(logicalWidth * ratio));
  canvas.height = Math.max(1, Math.floor(logicalHeight * ratio));
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  return { ctx, width: logicalWidth, height: logicalHeight };
}

function drawLineChart(canvas, values, options) {
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  drawAxes(ctx, width, height);
  if (values.length < 2) return;
  const pad = 28;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (idx) => pad + (idx / (values.length - 1)) * (width - pad * 2);
  const y = (value) => height - pad - ((value - min) / span) * (height - pad * 2);

  ctx.beginPath();
  values.forEach((value, idx) => {
    const px = x(idx);
    const py = y(value);
    if (idx === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.strokeStyle = options.color;
  ctx.lineWidth = 2;
  ctx.stroke();

  // fill 영역은 경로를 새로 시작해 선 경로와 분리한다
  ctx.beginPath();
  values.forEach((value, idx) => {
    const px = x(idx);
    const py = y(value);
    if (idx === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.lineTo(x(values.length - 1), height - pad);
  ctx.lineTo(x(0), height - pad);
  ctx.closePath();
  ctx.fillStyle = options.fill;
  ctx.fill();
  drawScale(ctx, min, max, width, height);
}

function drawBarChart(canvas, values) {
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  drawAxes(ctx, width, height);
  if (!values.length) return;
  const pad = 28;
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1);
  const zero = height / 2;
  const barWidth = Math.max(2, (width - pad * 2) / values.length - 3);
  values.forEach((value, idx) => {
    const x = pad + idx * ((width - pad * 2) / values.length);
    const barHeight = (Math.abs(value) / maxAbs) * (height / 2 - pad);
    ctx.fillStyle = value >= 0 ? "#0b8f5a" : "#c43d3d";
    ctx.fillRect(x, value >= 0 ? zero - barHeight : zero, barWidth, barHeight);
  });
  ctx.strokeStyle = "#aeb8c7";
  ctx.beginPath();
  ctx.moveTo(pad, zero);
  ctx.lineTo(width - pad, zero);
  ctx.stroke();
}

function drawAxes(ctx, width, height) {
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#e3e8f1";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = 28 + i * ((height - 56) / 3);
    ctx.beginPath();
    ctx.moveTo(28, y);
    ctx.lineTo(width - 28, y);
    ctx.stroke();
  }
}

function drawScale(ctx, min, max, width, height) {
  ctx.fillStyle = "#687386";
  ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillText(Math.round(max).toLocaleString("ko-KR"), 32, 20);
  ctx.fillText(Math.round(min).toLocaleString("ko-KR"), 32, height - 8);
}

async function loadKeyStatus() {
  const status = await getJSON(apiPath("/api/kis/keys"));
  $("keyStatus").textContent = status.configured
    ? `${marketLabel()} 저장됨: ${status.app_key_masked}${status.token_configured ? " / 토큰 있음" : " / 토큰 없음"}`
    : `${marketLabel()} 저장된 키 없음`;
  $("baseUrl").value = status.base_url || "https://openapi.koreainvestment.com:9443";
}

async function saveKeys() {
  const payload = {
    market: state.activeMarket,
    app_key: $("appKey").value,
    app_secret: $("appSecret").value,
    access_token: $("accessToken").value,
    base_url: $("baseUrl").value || "https://openapi.koreainvestment.com:9443",
  };
  const status = await getJSON(apiPath("/api/kis/keys"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  $("appKey").value = "";
  $("appSecret").value = "";
  $("accessToken").value = "";
  $("keyStatus").textContent = `${marketLabel()} 저장됨: ${status.app_key_masked}${status.token_configured ? " / 토큰 있음" : " / 토큰 없음"}`;
  refreshBalance({ silent: true }).catch((error) => console.error(error));
}

async function loadLiveConfig() {
  const config = await getJSON(apiPath("/api/live/config"));
  $("liveMode").value = config.mode || "paper";
  $("accountNo").value = config.account_no || "";
  $("productCode").value = config.product_code || "01";
  $("overseasPremarketEnabled").checked = Boolean(config.overseas_premarket_enabled);
  $("seedCapital").value = Math.round(Number(config.seed_capital || 1000000));
  $("maxPositions").value = Number(config.max_positions || 3);
  $("seedBalanceMax").checked = config.seed_source === "balance_max";
  $("autoStartTrading").checked = Boolean(config.auto_start);
  renderMarketFields();
  updateSeedInputState();
}

function liveConfigPayload() {
  const seed = Number($("seedCapital").value || 0);
  if (!Number.isFinite(seed) || seed <= 0) {
    throw new Error("시드는 0보다 큰 금액으로 입력하세요.");
  }
  const maxPositions = Math.max(1, Math.floor(Number($("maxPositions").value || 3)));
  return {
    market: state.activeMarket,
    mode: $("liveMode").value,
    account_no: $("accountNo").value.trim(),
    product_code: $("productCode").value.trim() || "01",
    exchange_code: "NASD",
    price_exchange_code: "NAS",
    currency: markets[state.activeMarket].currency,
    overseas_premarket_enabled: $("overseasPremarketEnabled").checked,
    seed_capital: seed,
    max_positions: maxPositions,
    seed_source: $("seedBalanceMax").checked ? "balance_max" : "manual",
    auto_start: $("autoStartTrading").checked,
    auto_select: true,
  };
}

async function saveLiveConfig(confirmAutoStart = true) {
  if (confirmAutoStart && $("liveMode").value === "live" && $("autoStartTrading").checked) {
    const ok = confirm(`${marketLabel()} 실전 주문 모드에서 자동시작을 켜면 NAS 재부팅이나 컨테이너 재시작 후 조건 충족 시 실제 주문이 전송될 수 있습니다. 저장할까요?`);
    if (!ok) return null;
  }
  const config = await getJSON(apiPath("/api/live/config"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(liveConfigPayload()),
  });
  const seedText = config.seed_source === "balance_max" ? `잔고 최대 사용 (${marketMoney(config.seed_capital)} 예비값)` : marketMoney(config.seed_capital);
  const target = state.activeMarket === "overseas"
    ? `${config.overseas_premarket_enabled ? "프리장 포함 " : ""}NASDAQ 자동선별`
    : state.activeMarket === "nasdaq_surge"
      ? `${config.overseas_premarket_enabled ? "프리장 포함 " : ""}나스닥 급등주 자동선별`
    : state.activeMarket === "domestic_surge"
      ? "급등주 자동선별"
    : state.activeMarket === "domestic_etf"
      ? "1배 ETF 자동선별"
    : "시장 자동선별";
  $("liveStatus").textContent = `${marketLabel()} 설정 저장됨: ${config.mode}, 시드 ${seedText}, 동시보유 최대 ${config.max_positions || 3}종목, 자동시작 ${config.auto_start ? "켜짐" : "꺼짐"}, ${target}`;
  refreshBalance({ silent: true }).catch((error) => console.error(error));
  return config;
}

async function loadLiveStatus() {
  const status = await getJSON(apiPath("/api/live/status"));
  const position = status.position || {};
  const positions = Array.isArray(status.positions) ? status.positions : (position.symbol ? [position] : []);
  const activeSymbols = status.active_symbols || [];
  const maxPositions = Number(status.max_positions || $("maxPositions").value || 3);
  const barMinutes = Number(status.bar_minutes || 5);
  const daily = status.daily_summary || {};
  const pieces = [
    `${marketLabel()} ${status.running ? "실행 중" : "대기 중"}`,
    `모드: ${status.mode || $("liveMode").value || "paper"}`,
    `시드: ${status.seed_source === "balance_max" ? "잔고 최대 " : ""}${marketMoney(status.seed_capital || $("seedCapital").value || 0)}`,
    `자동시작: ${status.auto_start ? "켜짐" : "꺼짐"}`,
    `선별: ${status.selector_message || status.selector || "-"}`,
    `추적: ${activeSymbols.length}종목`,
    `동시보유: ${positions.length}/${maxPositions}종목`,
    daily.entry_limit ? `진입: ${entryLimitText(daily)}` : "",
    daily.date ? `일일손익: ${signedMoney(daily.pnl_amount, marketCurrency())} (${Number(daily.return_pct || 0).toFixed(2)}%)` : "",
    `${barMinutes}분봉: ${Number(status.bar_count || 0).toLocaleString("ko-KR")}개`,
    `주문기록: ${Number(status.orders || 0).toLocaleString("ko-KR")}건`,
  ].filter(Boolean);
  if (status.bar_min_ready) {
    pieces.push(`봉준비: ${Number(status.bar_ready_symbols || 0).toLocaleString("ko-KR")}/${activeSymbols.length}종목(${status.bar_min_ready}봉)`);
  }
  if (status.price_error_count) {
    pieces.push(`현재가 실패: ${Number(status.price_error_count).toLocaleString("ko-KR")}종목`);
  }
  if (status.token_status && status.token_status !== "대기") {
    pieces.push(`토큰: ${status.token_status}`);
  }
  pieces.push(`프로파일: ${status.strategy_profile_mode || "auto"}`);
  if (status.strategy_tone) pieces.push(`톤: ${toneLabel(status.strategy_tone)}`);
  if (status.session_label) pieces.push(`세션: ${status.session_label}`);
  if (status.last_tick) pieces.push(`최근: ${status.last_tick}`);
  if (positions.length) {
    pieces.push(`보유: ${positions.map((item) => `${item.symbol} ${item.shares}주`).join(", ")}`);
  }
  if (status.last_error) pieces.push(`오류: ${status.last_error}`);
  $("liveStatus").textContent = pieces.join(" / ");
  applyToneBadge(status.strategy_tone);
  renderCurrentDecision(status);
  return status;
}

function renderCurrentDecision(status) {
  const message = status.trade_message || "-";
  const meta = [
    marketLabel(),
    status.session_label || "",
    status.last_tick ? `최근 ${status.last_tick}` : "",
  ].filter(Boolean);
  $("decisionCurrent").textContent = message;
  $("decisionMeta").textContent = meta.join(" / ") || "대기 중";
}

async function loadDecisionHistory() {
  const data = await getJSON(`${apiPath("/api/live/decisions")}&limit=80`, { cache: "no-store" });
  renderDecisionHistory(data.decisions || []);
  return data;
}

async function refreshSelectedReport() {
  const select = $("reportSelect");
  if (!select.value) return null;
  return loadReport(select.value);
}

function renderDecisionHistory(decisions) {
  const rows = decisions.slice().reverse();
  $("decisionHistory").innerHTML = rows.length
    ? rows.map((decision) => decisionRowHTML(decision)).join("")
    : `<div class="decision-item"><div class="decision-message">아직 기록된 판단 로그가 없습니다.</div></div>`;
}

function decisionRowHTML(decision) {
  const detail = decisionDetail(decision);
  return `<div class="decision-item">
    <div class="decision-time">${escapeHtml(decision.timestamp || "-")}</div>
    <div class="decision-event">${escapeHtml(decisionEventLabel(decision.event))}</div>
    <div class="decision-message">
      ${escapeHtml(decisionMessage(decision))}
      ${detail ? `<div class="decision-detail">${escapeHtml(detail)}</div>` : ""}
    </div>
  </div>`;
}

function decisionEventLabel(event) {
  const labels = {
    cycle: "주기 점검",
    entry_rejected: "진입 보류",
    entry_skip: "진입 제외",
    order_submitted: "주문 제출",
    order_failed: "주문 실패",
    market_wait: "시장 대기",
    token_ready: "토큰 확인",
    error: "오류",
    parse_error: "로그 오류",
  };
  return labels[event] || event || "-";
}

function decisionMessage(decision) {
  if (decision.event === "cycle") {
    return decision.trade_message || "상태 점검";
  }
  if (decision.event === "entry_rejected") {
    const rejected = Array.isArray(decision.rejected) ? decision.rejected : [];
    if (!rejected.length) return "매수 조건을 만족한 종목 없음";
    return rejected.slice(0, 5).map((item) => `${item.symbol}: ${item.reason}`).join(" / ");
  }
  if (decision.event === "entry_skip") {
    const symbol = decision.symbol ? `${decision.symbol}: ` : "";
    return `${symbol}${decision.reason || "진입 제외"}`;
  }
  if (decision.event === "order_submitted" || decision.event === "order_failed") {
    const side = decision.side ? String(decision.side).toUpperCase() : "ORDER";
    const symbol = decision.symbol || "";
    const shares = decision.shares ? `${decision.shares}주` : "";
    const price = decision.price ? `@ ${number(decision.price)}` : "";
    const reason = decision.reason ? `(${decision.reason})` : "";
    return [side, symbol, shares, price, reason].filter(Boolean).join(" ");
  }
  if (decision.event === "market_wait") return decision.reason || "시장 대기";
  if (decision.event === "token_ready") return "Access Token 확인 완료";
  if (decision.event === "error") return decision.error || "오류 발생";
  return decision.message || decision.reason || decision.event || "-";
}

function decisionDetail(decision) {
  if (decision.event === "cycle") {
    const active = Array.isArray(decision.active_symbols) ? decision.active_symbols.length : 0;
    const positions = Array.isArray(decision.positions) ? decision.positions.length : (decision.position?.symbol ? 1 : 0);
    const errors = Array.isArray(decision.price_errors) ? decision.price_errors.length : 0;
    return `추적 ${active}종목 / 보유 ${positions}종목 / 현재가 실패 ${errors}건`;
  }
  if (decision.event === "entry_rejected" && Array.isArray(decision.rejected) && decision.rejected.length > 5) {
    return `외 ${decision.rejected.length - 5}종목`;
  }
  if (decision.event === "entry_skip" && decision.reason === "daily_trade_limit") {
    return `오늘 진입 ${decision.entries || 0}/${decision.max_trades_per_day || "-"}회`;
  }
  if (decision.event === "entry_skip" && decision.reason === "max_positions") {
    return `동시보유 ${decision.positions || 0}/${decision.max_positions || "-"}종목`;
  }
  if (decision.event === "order_failed") {
    return orderResponseMessage(decision.response);
  }
  return "";
}

function orderResponseMessage(response) {
  if (!response || typeof response !== "object") return "";
  return response.msg1 || response.msg_cd || JSON.stringify(response);
}

async function startLive() {
  const saved = await saveLiveConfig(false);
  if (!saved) return;
  const mode = $("liveMode").value;
  if (mode === "live") {
    const ok = confirm(`${marketLabel()} 실전 주문 모드입니다. 조건 충족 시 실제 매수/매도 주문이 전송됩니다. 시작할까요?`);
    if (!ok) return;
  }
  const status = await getJSON(apiPath("/api/live/start"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ market: state.activeMarket }),
  });
  if (!status.running && status.message) {
    $("liveStatus").textContent = status.message;
  } else {
    await loadLiveStatus();
  }
  await Promise.all([loadReports(), loadDecisionHistory()]);
  refreshBalance({ silent: true }).catch((error) => console.error(error));
}

async function stopLive() {
  await getJSON(apiPath("/api/live/stop"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ market: state.activeMarket }),
  });
  await Promise.all([loadLiveStatus(), loadDecisionHistory()]);
}

async function refreshBalance(options = {}) {
  if (state.balanceLoading) return null;
  state.balanceLoading = true;
  const previousText = $("balanceStatus").textContent;
  if (!options.silent) {
    $("balanceStatus").textContent = "조회 중...";
  }
  try {
    const data = await getJSON(apiPath("/api/kis/balance"), { cache: "no-store" });
    renderBalance(data);
    return data;
  } catch (error) {
    if (!options.silent) {
      $("balanceStatus").textContent = `잔고 조회 실패: ${error.message}`;
      clearBalanceValues();
    } else if (!previousText || previousText === "계좌 설정 저장 후 조회" || previousText === "조회 중...") {
      $("balanceStatus").textContent = `자동 새로고침 실패: ${error.message}`;
    }
    throw error;
  } finally {
    state.balanceLoading = false;
  }
}

function renderBalance(data) {
  if (!data.ok) {
    $("balanceStatus").textContent = balanceErrorMessage(data);
    clearBalanceValues();
    return;
  }
  const suffix = isOverseasMarket() ? ` / ${data.exchange_code || "-"} ${data.currency || marketCurrency()}` : "";
  $("balanceStatus").textContent = `${data.account_no_masked || "-"}-${data.product_code || "01"}${suffix} / ${data.fetched_at || ""}`;
  $("balanceCash").textContent = marketMoney(data.cash);
  $("balanceWithdrawable").textContent = marketMoney(data.withdrawable_cash);
  $("balanceTotal").textContent = marketMoney(data.total_evaluation);
  if ($("seedBalanceMax").checked && Number(data.max_seed_capital || 0) > 0) {
    $("seedCapital").value = Math.round(Number(data.max_seed_capital));
  }
  const pnl = Number(data.profit_loss || 0);
  $("balancePnl").textContent = signedMoney(pnl, marketCurrency());
  $("balancePnl").className = pnl >= 0 ? "good" : "bad";
}

function clearBalanceValues() {
  $("balanceCash").textContent = "-";
  $("balanceWithdrawable").textContent = "-";
  $("balanceTotal").textContent = "-";
  $("balancePnl").textContent = "-";
  $("balancePnl").className = "";
}

function balanceErrorMessage(data) {
  const message = data.message || "잔고 조회 실패";
  return data.msg_cd ? `${data.msg_cd}: ${message}` : message;
}

function updateSeedInputState() {
  const usingBalance = $("seedBalanceMax").checked;
  $("seedCapital").disabled = usingBalance;
  $("seedCapital").title = usingBalance ? "자동매매 시작 시 최신 잔고를 조회해 시드로 사용합니다." : "";
}

function apiPath(path) {
  return `${path}?market=${encodeURIComponent(state.activeMarket)}`;
}

function marketLabel() {
  return markets[state.activeMarket].label;
}

function marketCurrency(market = state.activeMarket) {
  if (market === "overseas" || market === "nasdaq_surge") return "USD";
  return "KRW";
}

function marketMoney(value) {
  return money(value, marketCurrency());
}

function setupMobilePanels() {
  const media = window.matchMedia(MOBILE_QUERY);
  const syncPanels = () => {
    document.querySelectorAll("[data-mobile-default='closed']").forEach((panel) => {
      panel.open = !media.matches;
    });
  };
  syncPanels();
  if (media.addEventListener) {
    media.addEventListener("change", syncPanels);
  } else {
    media.addListener(syncPanels);
  }
}

function renderMarketFields() {
  const overseas = isOverseasMarket();
  document.querySelectorAll(".overseas-only").forEach((element) => {
    element.hidden = !overseas;
  });
  $("balanceTitle").textContent = overseas
    ? state.activeMarket === "nasdaq_surge" ? "나스닥 급등주 계좌 잔고" : "해외계좌 잔고"
    : state.activeMarket === "domestic_surge"
      ? "국내 급등주 계좌 잔고"
      : state.activeMarket === "domestic_etf"
        ? "국내ETF 계좌 잔고"
        : "실계좌 잔고";
  $("startLiveButton").textContent = `${marketLabel()} 자동매매 시작`;
}

function isOverseasMarket(market = state.activeMarket) {
  return market === "overseas" || market === "nasdaq_surge";
}

async function switchMarket(market) {
  state.activeMarket = market;
  document.querySelectorAll("[data-market-tab]").forEach((button) => {
    const active = button.dataset.marketTab === market;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  renderMarketFields();
  await Promise.all([loadKeyStatus(), loadLiveConfig(), loadLiveStatus(), loadReports(), loadDecisionHistory()]);
  refreshBalance({ silent: true }).catch((error) => console.error(error));
}

window.addEventListener("resize", () => {
  if (state.current) renderReport(state.current);
});

$("reportSelect").addEventListener("change", (event) => loadReport(event.target.value));
$("refreshButton").addEventListener("click", loadReports);
document.querySelectorAll("[data-market-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    switchMarket(button.dataset.marketTab).catch((error) => alert(error.message));
  });
});
$("saveKeysButton").addEventListener("click", () => {
  saveKeys().catch((error) => alert(error.message));
});
$("saveLiveConfigButton").addEventListener("click", () => {
  saveLiveConfig().catch((error) => alert(error.message));
});
$("startLiveButton").addEventListener("click", () => {
  startLive().catch((error) => alert(error.message));
});
$("stopLiveButton").addEventListener("click", () => {
  stopLive().catch((error) => alert(error.message));
});
$("refreshBalanceButton").addEventListener("click", () => {
  refreshBalance().catch((error) => {
    alert(error.message);
  });
});
$("seedBalanceMax").addEventListener("change", () => {
  updateSeedInputState();
  if ($("seedBalanceMax").checked) {
    refreshBalance().catch((error) => {
      console.error(error);
    });
  }
});

setupMobilePanels();
renderMarketFields();
Promise.all([loadReports(), loadKeyStatus(), loadLiveConfig(), loadLiveStatus(), loadDecisionHistory()])
  .then(() => refreshBalance({ silent: true }).catch((error) => console.error(error)))
  .catch((error) => {
    console.error(error);
    alert(error.message);
  });

state.liveTimer = window.setInterval(() => {
  Promise.all([loadLiveStatus(), loadDecisionHistory()]).catch((error) => console.error(error));
}, 5000);

state.reportTimer = window.setInterval(() => {
  refreshSelectedReport().catch((error) => console.error(error));
}, REPORT_REFRESH_MS);

state.balanceTimer = window.setInterval(() => {
  refreshBalance({ silent: true }).catch((error) => console.error(error));
}, BALANCE_REFRESH_MS);
