const state = {
  reports: [],
  current: null,
  liveTimer: null,
  activeMarket: "domestic",
};

const $ = (id) => document.getElementById(id);
const markets = {
  domestic: { label: "국내", report: "live_trading", currency: "KRW" },
  overseas: { label: "해외", report: "live_trading_overseas", currency: "USD" },
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
  const currency = report.name === markets.overseas.report ? marketCurrency("overseas") : "KRW";
  $("reportTitle").textContent = report.label || report.name;
  $("metricEquity").textContent = money(metrics.final_equity, currency);
  $("metricReturn").innerHTML = pct(metrics.total_return_pct);
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
}

function renderTrades(trades) {
  const rows = trades.slice(-120).reverse();
  $("tradeSummary").textContent = `${trades.length.toLocaleString("ko-KR")}건`;
  $("tradesBody").innerHTML = rows
    .map((trade) => {
      const pnl = Number(trade.realized_pnl || 0);
      return `<tr>
        <td>${trade.timestamp || trade.date || ""}</td>
        <td>${trade.action || ""}</td>
        <td>${trade.symbol || ""}</td>
        <td>${number(trade.shares)}</td>
        <td>${number(trade.price)}</td>
        <td class="${pnl >= 0 ? "good" : "bad"}">${number(pnl)}</td>
        <td>${trade.reason || ""}</td>
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

function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(Number(canvas.getAttribute("height") || 260) * ratio));
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  return { ctx, width: rect.width, height: Number(canvas.getAttribute("height") || 260) };
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

  ctx.lineTo(width - pad, height - pad);
  ctx.lineTo(pad, height - pad);
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
}

async function loadLiveConfig() {
  const config = await getJSON(apiPath("/api/live/config"));
  $("liveMode").value = config.mode || "paper";
  $("accountNo").value = config.account_no || "";
  $("productCode").value = config.product_code || "01";
  $("exchangeCode").value = config.exchange_code || "NASD";
  $("priceExchangeCode").value = config.price_exchange_code || "NAS";
  $("currency").value = config.currency || markets[state.activeMarket].currency;
  $("overseasPremarketEnabled").checked = Boolean(config.overseas_premarket_enabled);
  $("seedCapital").value = Math.round(Number(config.seed_capital || 1000000));
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
  return {
    market: state.activeMarket,
    mode: $("liveMode").value,
    account_no: $("accountNo").value.trim(),
    product_code: $("productCode").value.trim() || "01",
    exchange_code: $("exchangeCode").value.trim().toUpperCase() || "NASD",
    price_exchange_code: $("priceExchangeCode").value.trim().toUpperCase() || "NAS",
    currency: $("currency").value.trim().toUpperCase() || markets[state.activeMarket].currency,
    overseas_premarket_enabled: $("overseasPremarketEnabled").checked,
    seed_capital: seed,
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
    : "시장 자동선별";
  $("liveStatus").textContent = `${marketLabel()} 설정 저장됨: ${config.mode}, 시드 ${seedText}, 자동시작 ${config.auto_start ? "켜짐" : "꺼짐"}, ${target}`;
  return config;
}

async function loadLiveStatus() {
  const status = await getJSON(apiPath("/api/live/status"));
  const position = status.position || {};
  const activeSymbols = status.active_symbols || [];
  const pieces = [
    `${marketLabel()} ${status.running ? "실행 중" : "대기 중"}`,
    `모드: ${status.mode || $("liveMode").value || "paper"}`,
    `시드: ${status.seed_source === "balance_max" ? "잔고 최대 " : ""}${marketMoney(status.seed_capital || $("seedCapital").value || 0)}`,
    `자동시작: ${status.auto_start ? "켜짐" : "꺼짐"}`,
    `선별: ${status.selector_message || status.selector || "-"}`,
    `추적: ${activeSymbols.length}종목`,
    `주문기록: ${Number(status.orders || 0).toLocaleString("ko-KR")}건`,
  ];
  if (status.session_label) pieces.push(`세션: ${status.session_label}`);
  if (status.last_tick) pieces.push(`최근: ${status.last_tick}`);
  if (position.symbol) pieces.push(`보유: ${position.symbol} ${position.shares}주`);
  if (status.last_error) pieces.push(`오류: ${status.last_error}`);
  $("liveStatus").textContent = pieces.join(" / ");
  $("tradeReasonStatus").textContent = `매수대기 사유: ${status.trade_message || "-"}`;
  return status;
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
  await loadReports();
}

async function stopLive() {
  await getJSON(apiPath("/api/live/stop"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ market: state.activeMarket }),
  });
  await loadLiveStatus();
}

async function refreshBalance() {
  $("balanceStatus").textContent = "조회 중...";
  const data = await getJSON(apiPath("/api/kis/balance"), { cache: "no-store" });
  renderBalance(data);
}

function renderBalance(data) {
  if (!data.ok) {
    $("balanceStatus").textContent = balanceErrorMessage(data);
    clearBalanceValues();
    return;
  }
  const suffix = state.activeMarket === "overseas" ? ` / ${data.exchange_code || "-"} ${data.currency || marketCurrency()}` : "";
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
  if (market === "overseas") return ($("currency")?.value || markets.overseas.currency).trim().toUpperCase();
  return "KRW";
}

function marketMoney(value) {
  return money(value, marketCurrency());
}

function renderMarketFields() {
  const overseas = state.activeMarket === "overseas";
  document.querySelectorAll(".overseas-only").forEach((element) => {
    element.hidden = !overseas;
  });
  $("balanceTitle").textContent = overseas ? "해외계좌 잔고" : "실계좌 잔고";
  $("startLiveButton").textContent = `${marketLabel()} 자동매매 시작`;
}

async function switchMarket(market) {
  state.activeMarket = market;
  document.querySelectorAll("[data-market-tab]").forEach((button) => {
    const active = button.dataset.marketTab === market;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  renderMarketFields();
  await Promise.all([loadKeyStatus(), loadLiveConfig(), loadLiveStatus(), loadReports()]);
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
    $("balanceStatus").textContent = `잔고 조회 실패: ${error.message}`;
    clearBalanceValues();
    alert(error.message);
  });
});
$("seedBalanceMax").addEventListener("change", () => {
  updateSeedInputState();
  if ($("seedBalanceMax").checked) {
    refreshBalance().catch((error) => {
      $("balanceStatus").textContent = `잔고 조회 실패: ${error.message}`;
      clearBalanceValues();
      console.error(error);
    });
  }
});

renderMarketFields();
Promise.all([loadReports(), loadKeyStatus(), loadLiveConfig(), loadLiveStatus()]).catch((error) => {
  console.error(error);
  alert(error.message);
});

state.liveTimer = window.setInterval(() => {
  loadLiveStatus().catch((error) => console.error(error));
}, 5000);
