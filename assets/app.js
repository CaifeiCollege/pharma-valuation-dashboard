const state = { data: null, sort: "category", selected: null };
const els = {
  status: document.getElementById("status"),
  coverage: document.getElementById("coverage"),
  overview: document.getElementById("overview"),
  grid: document.getElementById("category-grid"),
  sort: document.getElementById("sort-select"),
  drawer: document.getElementById("chart-drawer"),
  close: document.getElementById("chart-close"),
  title: document.getElementById("chart-title"),
  meta: document.getElementById("chart-meta"),
  canvas: document.getElementById("history-chart"),
  tooltip: document.getElementById("chart-tooltip"),
  summary: document.getElementById("chart-summary"),
};

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char]));
const formatPe = (value) => value == null ? "—" : Number(value).toFixed(2) + "×";
const formatPct = (value) => value == null ? "—" : Number(value).toFixed(2) + "%";
const bandClass = (record) => {
  if (record.freshness === "unavailable") return "band-na";
  if (record.percentile < 20) return "band-low";
  if (record.percentile < 50) return "band-mid";
  if (record.percentile < 80) return "band-high";
  return "band-hot";
};

function validateSnapshot(data) {
  if (!data || data.schema_version !== 1 || !Array.isArray(data.indices)) {
    throw new Error("数据格式不兼容");
  }
  return data;
}

function latestDate(records) {
  return records.map((item) => item.as_of).filter(Boolean).sort().at(-1) || null;
}

function updateFreshness(data) {
  const asOf = latestDate(data.indices);
  if (!asOf) {
    els.status.textContent = "暂无可用估值数据";
    els.status.classList.add("danger");
    return;
  }
  const age = Math.max(0, Math.floor((Date.now() - new Date(asOf + "T00:00:00+08:00")) / 86400000));
  const { current, stale, unavailable } = data.summary;
  els.status.textContent = `数据日期 ${asOf} · 当前 ${current} · 沿用 ${stale} · 暂缺 ${unavailable}`;
  els.status.classList.toggle("warning", age > 3 && age <= 7);
  els.status.classList.toggle("danger", age > 7);
  if (age > 7) els.status.textContent += ` · 已超过${age}天，请谨慎参考`;
  else if (age > 3) els.status.textContent += ` · 已${age}天未更新`;
}

function renderOverview(data) {
  const available = data.indices.filter((item) => item.freshness !== "unavailable");
  const broad = available.find((item) => item.code === "000933");
  const innovation = available.find((item) => item.code === "931409");
  const lowest = [...available].sort((a, b) => a.percentile - b.percentile)[0];
  const cards = [
    broad && { label: "中证医药 PE-TTM", value: formatPe(broad.pe_ttm), context: `十年百分位 ${formatPct(broad.percentile)}` },
    innovation && { label: "SHS创新药 PE-TTM", value: formatPe(innovation.pe_ttm), context: `十年百分位 ${formatPct(innovation.percentile)}` },
    lowest && { label: "当前百分位最低", value: lowest.category, context: `${lowest.name} · ${formatPct(lowest.percentile)}` },
  ].filter(Boolean);
  els.overview.innerHTML = cards.map((card) => `
    <article class="overview-card">
      <p class="overview-label">${escapeHtml(card.label)}</p>
      <p class="overview-value">${escapeHtml(card.value)}</p>
      <p class="overview-context">${escapeHtml(card.context)}</p>
    </article>`).join("");
  els.coverage.textContent = `同口径覆盖 ${available.length}/${data.indices.length} 个指数`;
}

function sortedRecords(records) {
  const result = [...records];
  if (state.sort === "percentile-asc") {
    result.sort((a, b) => (a.percentile ?? Infinity) - (b.percentile ?? Infinity));
  } else if (state.sort === "percentile-desc") {
    result.sort((a, b) => (b.percentile ?? -Infinity) - (a.percentile ?? -Infinity));
  }
  return result;
}

function cardMarkup(record, index) {
  const available = record.freshness !== "unavailable" && record.history.length;
  const tag = available ? "button" : "article";
  const attrs = available ? `type="button" data-index="${index}" aria-label="查看${escapeHtml(record.name)}历史PE走势"` : "";
  const statusText = record.freshness === "stale" ? "沿用旧值" : record.band;
  return `<${tag} class="sector-card ${record.freshness}-card" ${attrs}>
    <div class="sector-top">
      <div><p class="category-name">${escapeHtml(record.category)} · ${escapeHtml(record.code)}</p><p class="index-name">${escapeHtml(record.name)}</p></div>
      <span class="badge ${bandClass(record)}">${escapeHtml(statusText)}</span>
    </div>
    <div class="metric-row">
      <div><span class="metric-label">PE-TTM</span><span class="metric-value">${formatPe(record.pe_ttm)}</span></div>
      <div><span class="metric-label">十年百分位</span><span class="metric-value">${formatPct(record.percentile)}</span></div>
    </div>
    <div class="percent-bar" aria-hidden="true"><span style="width:${record.percentile ?? 0}%"></span></div>
    <div class="card-foot"><span>${record.as_of ? `截至 ${escapeHtml(record.as_of)}` : "同口径数据暂缺"}</span><span>${record.observations ? `${record.observations}个样本` : ""}</span></div>
    ${record.note ? `<p class="card-note">${escapeHtml(record.note)}</p>` : ""}
  </${tag}>`;
}

function renderGrid() {
  const records = sortedRecords(state.data.indices);
  els.grid.innerHTML = records.map(cardMarkup).join("");
  els.grid.querySelectorAll("button[data-index]").forEach((button) => {
    button.addEventListener("click", () => openChart(records[Number(button.dataset.index)]));
  });
}

function percentileValue(values, percentile) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * percentile))];
}

function chartPoints(history, limit = 500) {
  if (history.length <= limit) return history;
  const step = (history.length - 1) / (limit - 1);
  return Array.from({ length: limit }, (_, i) => history[Math.round(i * step)]);
}

function drawChart(record) {
  const canvas = els.canvas;
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  const pad = { left: 48, right: 18, top: 24, bottom: 34 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const points = chartPoints(record.history);
  const values = record.history.map((point) => point.pe);
  const p20 = percentileValue(values, .2);
  const p80 = percentileValue(values, .8);
  const min = Math.min(...values, p20) * .94;
  const max = Math.max(...values, p80) * 1.06;
  const xAt = (i) => pad.left + (points.length === 1 ? 0 : i * plotW / (points.length - 1));
  const yAt = (value) => pad.top + (max - value) * plotH / (max - min || 1);

  ctx.clearRect(0, 0, width, height);
  ctx.font = '12px system-ui, "Microsoft YaHei"';
  ctx.textBaseline = "middle";
  ctx.strokeStyle = "#d9d5ca";
  ctx.fillStyle = "#68716c";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const value = min + (max - min) * i / 4;
    const y = yAt(value);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.textAlign = "right"; ctx.fillText(value.toFixed(0), pad.left - 8, y);
  }
  [[p20, "20%线", "#26745a"], [p80, "80%线", "#a55c18"]].forEach(([value, label, color]) => {
    const y = yAt(value);
    ctx.save(); ctx.setLineDash([5, 5]); ctx.strokeStyle = color;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke(); ctx.restore();
    ctx.fillStyle = color; ctx.textAlign = "left"; ctx.fillText(`${label} ${value.toFixed(1)}`, pad.left + 5, y - 10);
  });
  ctx.strokeStyle = "#315f75"; ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = xAt(index); const y = yAt(point.pe);
    if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#68716c"; ctx.textAlign = "center";
  const yearMarks = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  yearMarks.forEach((index) => ctx.fillText(points[index].date.slice(0, 7), xAt(index), height - 12));

  const last = points.at(-1);
  ctx.fillStyle = "#315f75"; ctx.beginPath(); ctx.arc(xAt(points.length - 1), yAt(last.pe), 4, 0, Math.PI * 2); ctx.fill();
  canvas._chart = { points, xAt, yAt, pad, plotW };
}

function openChart(record) {
  state.selected = record;
  els.title.textContent = `${record.name} 历史PE`;
  els.meta.textContent = `${record.code} · ${record.history_start} 至 ${record.as_of}`;
  const values = record.history.map((point) => point.pe);
  els.summary.textContent = `当前 ${formatPe(record.pe_ttm)}，十年百分位 ${formatPct(record.percentile)}；历史区间 ${Math.min(...values).toFixed(2)}×–${Math.max(...values).toFixed(2)}×。`;
  els.drawer.showModal();
  requestAnimationFrame(() => drawChart(record));
}

function showTooltip(event) {
  const chart = els.canvas._chart;
  if (!chart) return;
  const rect = els.canvas.getBoundingClientRect();
  const clientX = event.touches?.[0]?.clientX ?? event.clientX;
  const x = Math.max(chart.pad.left, Math.min(rect.width - 18, clientX - rect.left));
  const index = Math.round((x - chart.pad.left) / chart.plotW * (chart.points.length - 1));
  const point = chart.points[Math.max(0, Math.min(chart.points.length - 1, index))];
  els.tooltip.textContent = `${point.date} · ${Number(point.pe).toFixed(2)}×`;
  els.tooltip.style.left = `${chart.xAt(index)}px`;
  els.tooltip.style.top = `${chart.yAt(point.pe)}px`;
  els.tooltip.hidden = false;
}

async function init() {
  try {
    const response = await fetch("data/valuations.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = validateSnapshot(await response.json());
    updateFreshness(state.data);
    renderOverview(state.data);
    renderGrid();
  } catch (error) {
    els.status.textContent = "数据读取失败，请稍后刷新";
    els.status.classList.add("danger");
    els.grid.innerHTML = `<p class="error-box">暂时无法读取估值快照。已发布页面不会直接请求上游接口，请稍后再试。</p>`;
  }
}

els.sort.addEventListener("change", (event) => { state.sort = event.target.value; renderGrid(); });
els.close.addEventListener("click", () => els.drawer.close());
els.drawer.addEventListener("click", (event) => { if (event.target === els.drawer) els.drawer.close(); });
els.canvas.addEventListener("pointermove", showTooltip);
els.canvas.addEventListener("pointerleave", () => { els.tooltip.hidden = true; });
window.addEventListener("resize", () => { if (els.drawer.open && state.selected) drawChart(state.selected); });
init();
