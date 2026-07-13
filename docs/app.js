/* VeyraQuant dashboard - vanilla JS, no build step.
   Reads docs/data/*.json exported by the nightly pipeline. */
"use strict";

const I18N = {
  zh: {
    "title": "VeyraQuant 仪表盘",
    "sample": "样例数据",
    "sec.market": "市场滤镜",
    "sec.funnel": "审批漏斗",
    "sec.armed": "冻结计划（盘中触发状态）",
    "sec.actions": "今日批准计划",
    "sec.contrib": "评分贡献",
    "sec.watch": "观察 / 延后",
    "sec.risk": "风险动作",
    "sec.rejected": "被拒计划",
    "sec.notes": "系统备注与决策复盘",
    "stale": "数据可能已过期：最近一次生成于 {h} 小时前。",
    "empty.risk": "今日没有风险动作。",
    "empty.rejected": "今日没有被拒计划。",
    "risk.reason": "风险原因", "risk.position": "持仓上下文", "risk.posture": "建议姿态",
    "rej.why": "拒绝原因", "rej.blocked": "拦截条件",
    "legend.pos": "正贡献",
    "legend.neg": "负贡献",
    "disclaimer": "不连接券商 API。不自动下单。不构成投资建议。所有交易计划需要人工复核。",
    "empty.data": "暂无数据 — 等待第一次夜间导出后自动生成。",
    "empty.armed": "当前没有冻结中的计划。",
    "empty.actions": "今日没有批准的交易计划。",
    "empty.watch": "今日没有观察 / 延后标的。",
    "empty.notes": "暂无备注。",
    "market_score": "市场分",
    "posture": "交易姿态",
    "funnel.approved": "批准", "funnel.deferred": "延后", "funnel.watchlist": "观察",
    "funnel.risk": "风控", "funnel.rejected": "拒绝",
    "plan.entry": "入场区", "plan.stop": "止损", "plan.targets": "目标",
    "plan.budget": "风险预算", "plan.trigger": "触发", "plan.cancel": "取消条件",
    "plan.expires": "有效期至", "plan.score": "评分",
    "case.bull": "看多理由", "case.bear": "关注风险",
    "chart.stop": "止损", "chart.entry": "入场区", "chart.t1": "T1", "chart.t2": "T2",
    "contrib.base": "基础分",
    "ev.title": "证据明细",
    "sec.health": "系统健康",
    "health.last_run": "最近夜间运行", "health.duration": "耗时",
    "health.symbols": "标的 成功/缓存/失败", "health.email": "邮件",
    "health.export": "导出", "health.alerts": "触发提醒",
    "health.heartbeat": "盘中心跳", "health.checked": "检查计划",
    "health.yes": "已发送", "health.no": "未发送", "health.ok": "正常", "health.fail": "失败",
    "empty.health": "暂无运行记录 — 等待首次夜间运行。",
    "th.symbol": "标的", "th.rating": "评级", "th.score": "评分",
    "th.state": "状态", "th.why": "原因",
    "status.armed": "待触发", "status.triggered": "已触发",
    "status.invalidated": "已作废", "status.expired": "已过期",
    "pos.pct": "仓位", "loss.pct": "最大亏损",
  },
  en: {
    "title": "VeyraQuant Cockpit",
    "sample": "sample data",
    "sec.market": "Market filter",
    "sec.funnel": "Approval funnel",
    "sec.armed": "Armed plans (intraday trigger state)",
    "sec.actions": "Approved plans today",
    "sec.contrib": "Score contributions",
    "sec.watch": "Watch / deferred",
    "sec.risk": "Risk actions",
    "sec.rejected": "Rejected plans",
    "sec.notes": "System notes & decision review",
    "stale": "Data may be stale: last generated {h} hours ago.",
    "empty.risk": "No risk actions today.",
    "empty.rejected": "No rejected plans today.",
    "risk.reason": "risk reason", "risk.position": "position", "risk.posture": "suggested posture",
    "rej.why": "why rejected", "rej.blocked": "blocked by",
    "legend.pos": "positive",
    "legend.neg": "negative",
    "disclaimer": "No broker API. No automatic orders. Not investment advice. Every trade plan requires human review.",
    "empty.data": "No data yet - generated automatically after the first nightly export.",
    "empty.armed": "No armed plans right now.",
    "empty.actions": "No approved trade plans today.",
    "empty.watch": "No watch / deferred names today.",
    "empty.notes": "No notes.",
    "market_score": "market score",
    "posture": "posture",
    "funnel.approved": "approved", "funnel.deferred": "deferred", "funnel.watchlist": "watch",
    "funnel.risk": "risk", "funnel.rejected": "rejected",
    "plan.entry": "entry zone", "plan.stop": "stop", "plan.targets": "targets",
    "plan.budget": "risk budget", "plan.trigger": "trigger", "plan.cancel": "cancel",
    "plan.expires": "expires", "plan.score": "score",
    "case.bull": "why now", "case.bear": "watch risk",
    "chart.stop": "STOP", "chart.entry": "ENTRY", "chart.t1": "T1", "chart.t2": "T2",
    "contrib.base": "base score",
    "ev.title": "Evidence",
    "sec.health": "System health",
    "health.last_run": "Last nightly run", "health.duration": "duration",
    "health.symbols": "symbols live/cache/failed", "health.email": "email",
    "health.export": "export", "health.alerts": "alerts",
    "health.heartbeat": "intraday heartbeat", "health.checked": "plans checked",
    "health.yes": "sent", "health.no": "not sent", "health.ok": "ok", "health.fail": "failed",
    "empty.health": "No runs recorded yet - waiting for the first nightly run.",
    "th.symbol": "Symbol", "th.rating": "Rating", "th.score": "Score",
    "th.state": "State", "th.why": "Why",
    "status.armed": "armed", "status.triggered": "triggered",
    "status.invalidated": "invalidated", "status.expired": "expired",
    "pos.pct": "position", "loss.pct": "max loss",
  },
};

let lang = localStorage.getItem("vq-lang") || "zh";
let cache = { brief: null, armed: null, health: null };

const $ = (id) => document.getElementById(id);
const t = (key) => (I18N[lang] && I18N[lang][key]) || I18N.zh[key] || key;
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const fmt = (value, digits = 2) =>
  value === null || value === undefined || Number.isNaN(Number(value))
    ? "NA"
    : Number(value).toFixed(digits);

function applyI18n() {
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  $("lang-zh").classList.toggle("on", lang === "zh");
  $("lang-en").classList.toggle("on", lang === "en");
  $("lang-zh").setAttribute("aria-pressed", String(lang === "zh"));
  $("lang-en").setAttribute("aria-pressed", String(lang === "en"));
}

function setLang(next) {
  lang = next;
  localStorage.setItem("vq-lang", next);
  applyI18n();
  render();
}

/* ---------- renderers ---------- */

function render() {
  const brief = cache.brief;
  if (!brief) {
    $("regime").innerHTML = `<p class="empty">${esc(t("empty.data"))}</p>`;
    ["chips", "mkt-lines", "funnel", "actions", "contrib", "watch", "risk", "rejected"].forEach(
      (id) => ($(id).innerHTML = ""));
    renderArmed(cache.armed);
    renderHealth(cache.health);
    return;
  }
  $("sample-badge").hidden = !brief.sample;
  $("stamp").textContent = brief.dual_time || brief.date || "";
  renderStale(brief);
  renderRegime(brief);
  renderFunnel(brief.summary || {});
  renderArmed(cache.armed);
  renderActions(brief);
  renderContrib(brief);
  renderWatch(brief);
  renderRisk(brief);
  renderRejected(brief);
  renderNotes(brief);
  renderHealth(cache.health);
}

/* Stale detection: the nightly export lands once per trading day, so on
   weekdays anything older than 30h is suspicious; across the weekend the
   gap legitimately stretches, so Sun/Mon get a 78h allowance. Sample seed
   data is exempt - it is documentation, not a feed. */
function renderStale(brief) {
  const node = $("stale");
  node.hidden = true;
  if (brief.sample || !brief.generated_at) return;
  const generated = Date.parse(brief.generated_at);
  if (Number.isNaN(generated)) return;
  const ageHours = (Date.now() - generated) / 3_600_000;
  const day = new Date().getDay(); // 0 Sun .. 6 Sat
  const allowance = day === 0 || day === 1 || day === 6 ? 78 : 30;
  if (ageHours > allowance) {
    node.textContent = t("stale").replace("{h}", String(Math.round(ageHours)));
    node.hidden = false;
  }
}

function regimePillClass(label) {
  if (label === "风险偏好") return "on";
  if (label === "风险规避") return "off";
  return "mid";
}

function renderRegime(brief) {
  const market = brief.market || {};
  const posture = (brief.summary || {}).trading_posture || "";
  $("regime").innerHTML = `
    <span class="label">${esc(market.label || "?")}</span>
    <span class="pill ${regimePillClass(market.label)}">${esc(t("market_score"))} ${fmt(market.score, 1)}</span>
    <span class="posture">${esc(t("posture"))}: ${esc(posture)}</span>`;

  const chips = [];
  for (const symbol of ["SPY", "QQQ", "SMH", "^VIX"]) {
    const snap = (market.snapshots || {})[symbol];
    if (!snap || snap.last === null || snap.last === undefined) continue;
    let perf = "";
    if (snap.perf20 !== null && snap.perf20 !== undefined) {
      const cls = snap.perf20 >= 0 ? "up" : "down";
      perf = ` <span class="${cls}">${snap.perf20 >= 0 ? "+" : ""}${fmt(snap.perf20)}%</span>`;
    }
    chips.push(`<div class="chip"><span class="sym">${esc(symbol)}</span><br>
      <span class="px">${fmt(snap.last)}</span>${perf}</div>`);
  }
  $("chips").innerHTML = chips.join("");

  const lines = (market.reasons || []).map((item) => `<li>${esc(item)}</li>`)
    .concat((market.risks || []).map((item) => `<li class="risk">! ${esc(item)}</li>`));
  $("mkt-lines").innerHTML = lines.join("");
}

function renderFunnel(summary) {
  const tiles = [
    ["approved", summary.approved], ["deferred", summary.deferred],
    ["watchlist", summary.watchlist], ["risk", summary.risk_actions],
    ["rejected", summary.rejected],
  ];
  $("funnel").innerHTML = tiles
    .map(([key, count]) =>
      `<div class="tile"><b>${count ?? 0}</b><span>${esc(t("funnel." + key))}</span></div>`)
    .join("");
}

function renderArmed(armed) {
  const plans = (armed && armed.plans) || [];
  if (!plans.length) {
    $("armed").innerHTML = `<p class="empty">${esc(t("empty.armed"))}</p>`;
    return;
  }
  $("armed").innerHTML = plans
    .map((plan) => {
      const status = plan.status || "armed";
      const resolved = plan.resolved_price !== undefined && plan.resolved_price !== null
        ? ` @ ${fmt(plan.resolved_price)}` : "";
      return `<div class="plan-row">
        <div class="plan-head">
          <span class="sym">${esc(plan.symbol)}</span>
          <span class="kind">${esc(plan.plan_kind || "")} · ${esc(plan.setup_type || "")}</span>
          <span class="status ${esc(status)}">${esc(t("status." + status))}${resolved}</span>
        </div>
        <div class="levels">
          ${esc(t("plan.entry"))} <b>${fmt(plan.entry_low)} – ${fmt(plan.entry_high)}</b> ·
          ${esc(t("plan.stop"))} <b>${fmt(plan.stop_price)}</b> ·
          ${esc(t("plan.targets"))} <b>${fmt(plan.target1)} / ${fmt(plan.target2)}</b> ·
          ${esc(t("plan.expires"))} <b>${esc(plan.expires_date || "?")}</b>
        </div>
      </div>`;
    })
    .join("");
}

function renderActions(brief) {
  const approved = (brief.results || []).filter(
    (item) => item.portfolio_decision === "approved");
  if (!approved.length) {
    $("actions").innerHTML = `<p class="empty">${esc(t("empty.actions"))}</p>`;
    return;
  }
  $("actions").innerHTML = approved
    .map((item) => {
      const plan = item.plan || {};
      return `<div class="action">
        <div class="plan-head">
          <span class="sym">${esc(item.symbol)}</span>
          <span class="kind">${esc(item.rating)} / ${esc(item.action)} · ${esc(t("plan.score"))} ${item.score}</span>
        </div>
        ${priceLadderSVG(plan)}
        <dl class="kv">
          <dt>${esc(t("plan.entry"))}</dt><dd>${esc(plan.entry_zone || "NA")}</dd>
          <dt>${esc(t("plan.stop"))} / ${esc(t("plan.targets"))}</dt>
          <dd>${esc(plan.stop || "NA")} · ${esc(plan.targets || "NA")}</dd>
          <dt>${esc(t("plan.budget"))}</dt>
          <dd>${esc(t("pos.pct"))} ${fmt(plan.position_pct)}% · ${esc(t("loss.pct"))} ${fmt(plan.max_loss_pct)}% · RR ${fmt(plan.rr, 2)}</dd>
          <dt>${esc(t("plan.trigger"))}</dt><dd>${esc(plan.trigger || "")}</dd>
          <dt>${esc(t("plan.cancel"))}</dt><dd>${esc(plan.cancel || "")}</dd>
        </dl>
        <p class="case bull"><span class="tag">${esc(t("case.bull"))}:</span> ${esc((item.bull_case || []).join(" · "))}</p>
        <p class="case bear"><span class="tag">${esc(t("case.bear"))}:</span> ${esc((item.bear_case || []).join(" · "))}</p>
      </div>`;
    })
    .join("");
}

function renderContrib(brief) {
  const ranked = (brief.results || [])
    .slice()
    .sort((a, b) => (b.score || 0) - (a.score || 0))
    .slice(0, 6);
  if (!ranked.length) {
    $("contrib").innerHTML = `<p class="empty">${esc(t("empty.data"))}</p>`;
    return;
  }
  $("contrib").innerHTML = ranked
    .map((item, index) => {
      const open = item.portfolio_decision === "approved" || index === 0 ? " open" : "";
      return `<details class="contrib"${open}>
        <summary><b>${esc(item.symbol)}</b>
          <span>${esc(item.signal_type || item.action)}</span>
          <span class="sc">${esc(t("plan.score"))} ${item.score}</span></summary>
        ${contribBarsSVG(item.contributions || {})}
        ${evidenceListHTML(item.evidence || [])}
      </details>`;
    })
    .join("");
}

function renderWatch(brief) {
  const rows = (brief.results || []).filter((item) =>
    item.portfolio_decision === "deferred" ||
    (item.portfolio_decision === "watchlist" && ["WATCH", "WAIT"].includes(item.action)));
  if (!rows.length) {
    $("watch").innerHTML = `<p class="empty">${esc(t("empty.watch"))}</p>`;
    return;
  }
  const body = rows
    .map((item) => `<tr>
      <td><b>${esc(item.symbol)}</b></td>
      <td>${esc(item.rating)}</td>
      <td>${item.score}</td>
      <td>${esc(item.portfolio_decision)}</td>
      <td>${esc(item.portfolio_reason || "")}</td>
    </tr>`)
    .join("");
  $("watch").innerHTML = `<table class="tbl">
    <thead><tr><th>${esc(t("th.symbol"))}</th><th>${esc(t("th.rating"))}</th>
    <th>${esc(t("th.score"))}</th><th>${esc(t("th.state"))}</th><th>${esc(t("th.why"))}</th></tr></thead>
    <tbody>${body}</tbody></table>`;
}

function renderRisk(brief) {
  const rows = (brief.results || []).filter((item) => item.action === "RISK_REDUCE");
  if (!rows.length) {
    $("risk").innerHTML = `<p class="empty">${esc(t("empty.risk"))}</p>`;
    return;
  }
  $("risk").innerHTML = rows
    .map((item) => `<div class="plan-row">
      <div class="plan-head">
        <span class="sym">${esc(item.symbol)}</span>
        <span class="kind">${esc(item.rating)} · ${esc(t("plan.score"))} ${item.score}</span>
        <span class="status invalidated">${esc(item.action)}</span>
      </div>
      <div class="levels">
        ${esc(t("risk.reason"))}: <b>${esc((item.bear_case || item.risks || []).slice(0, 2).join(" · "))}</b><br>
        ${esc(t("risk.position"))}: ${esc(item.position_context || "")} ·
        ${esc(t("risk.posture"))}: <b>${esc(item.suggested_posture || "")}</b><br>
        ${esc(item.portfolio_reason || "")}
      </div>
    </div>`)
    .join("");
}

function renderRejected(brief) {
  const rows = (brief.results || []).filter((item) => item.action === "REJECT");
  if (!rows.length) {
    $("rejected").innerHTML = `<p class="empty">${esc(t("empty.rejected"))}</p>`;
    return;
  }
  $("rejected").innerHTML = rows
    .map((item) => `<div class="plan-row">
      <div class="plan-head">
        <span class="sym">${esc(item.symbol)}</span>
        <span class="kind">${esc(t("plan.score"))} ${item.score}</span>
        <span class="status expired">${esc(item.action)}</span>
      </div>
      <div class="levels">
        ${esc(t("rej.why"))}: <b>${esc((item.risks || item.bear_case || []).slice(0, 2).join(" · "))}</b><br>
        ${esc(t("rej.blocked"))}: ${esc((item.suppressed_by || []).join(", ") || "—")}
      </div>
    </div>`)
    .join("");
}

function renderNotes(brief) {
  const items = [].concat(brief.portfolio_notes || [], brief.review_notes || []);
  $("notes").innerHTML = items.length
    ? items.map((item) => `<li>${esc(item)}</li>`).join("")
    : `<li class="empty">${esc(t("empty.notes"))}</li>`;
}

/* Traceable evidence behind the score: code chip, text, signed points. */
function evidenceListHTML(evidence) {
  if (!evidence.length) return "";
  const rows = evidence
    .map((item) => {
      const cls = item.polarity === "risk" ? "neg" : item.polarity === "reason" ? "pos" : "mut";
      const pts =
        item.points === null || item.points === undefined
          ? ""
          : `<span class="pts">${item.points >= 0 ? "+" : ""}${fmt(item.points, 1)}</span>`;
      const value =
        item.value === null || item.value === undefined ? "" : ` <span class="val">(${esc(item.value)})</span>`;
      return `<li class="${cls}"><i></i><code>${esc(item.code)}</code> ${esc(item.text)}${value}${pts}</li>`;
    })
    .join("");
  return `<details class="ev"><summary>${esc(t("ev.title"))} (${evidence.length})</summary>
    <ul class="ev-list">${rows}</ul></details>`;
}

function renderHealth(health) {
  const node = $("health");
  if (!node) return;
  if (!health || !health.run_id) {
    node.innerHTML = `<p class="empty">${esc(t("empty.health"))}</p>`;
    return;
  }
  const badge = (ok, yes, no) =>
    ok === null || ok === undefined
      ? `<span class="status expired">NA</span>`
      : ok
        ? `<span class="status triggered">${esc(yes)}</span>`
        : `<span class="status invalidated">${esc(no)}</span>`;
  const beat = health.intraday_heartbeat;
  const beatLine = beat
    ? `<div class="levels">${esc(t("health.heartbeat"))}: ${esc(beat.finished_at || "")} ·
       ${esc(t("health.checked"))} <b>${beat.checked_plans ?? 0}</b> ·
       transitions <b>${beat.transitions ?? 0}</b></div>`
    : "";
  node.innerHTML = `
    <div class="levels">
      ${esc(t("health.last_run"))}: <b>${esc(health.finished_at || "")}</b> ·
      ${esc(t("health.duration"))} <b>${fmt(health.duration_seconds, 1)}s</b><br>
      ${esc(t("health.symbols"))}: <b>${health.symbols_live ?? 0}/${health.symbols_cache ?? 0}/${health.symbols_failed ?? 0}</b> ·
      ${esc(t("health.alerts"))} <b>${health.alerts_sent ?? 0}</b> ·
      ${esc(t("health.email"))} ${badge(health.email_sent, t("health.yes"), t("health.no"))}
      ${esc(t("health.export"))} ${badge(health.export_ok, t("health.ok"), t("health.fail"))}
    </div>${beatLine}`;
}

/* ---------- charts (inline SVG, palette roles from CSS vars) ---------- */

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/* Signed horizontal bars, diverging blue/red, zero baseline, 4px rounded
   data-ends, value labels at bar ends. "base" is a constant offset, not a
   judgment - shown as a footnote instead of dwarfing the real signal. */
function contribBarsSVG(contributions) {
  const entries = Object.entries(contributions)
    .filter(([key, value]) => key !== "base" && value !== null && Math.abs(value) >= 0.05)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const base = contributions.base;
  if (!entries.length) return `<p class="contrib-note">NA</p>`;

  const width = 640, rowH = 22, labelW = 150, valueW = 52;
  const height = entries.length * rowH + 8;
  const plotW = width - labelW - valueW;
  // One px-per-unit scale for BOTH signs: equal magnitudes must render as
  // equal lengths, so the axis sits where the negative extent ends.
  const negMax = Math.max(0, ...entries.filter(([, v]) => v < 0).map(([, v]) => -v));
  const posMax = Math.max(0, ...entries.filter(([, v]) => v >= 0).map(([, v]) => v));
  const unit = (plotW - 16) / ((negMax + posMax) || 1);
  const axisX = labelW + 8 + negMax * unit;

  const pos = cssVar("--pos"), neg = cssVar("--neg");
  const muted = cssVar("--muted"), ink2 = cssVar("--ink-2"), baseline = cssVar("--baseline");

  let bars = "";
  entries.forEach(([key, value], index) => {
    const y = index * rowH + 6;
    const h = 12, r = 4;
    const len = Math.max(1.5, Math.abs(value) * unit);
    const color = value >= 0 ? pos : neg;
    const path = value >= 0
      ? `M${axisX},${y} h${Math.max(0, len - r)} q${r},0 ${r},${r} v${h - 2 * r} q0,${r} -${r},${r} h-${Math.max(0, len - r)} z`
      : `M${axisX},${y} h-${Math.max(0, len - r)} q-${r},0 -${r},${r} v${h - 2 * r} q0,${r} ${r},${r} h${Math.max(0, len - r)} z`;
    const valueX = value >= 0 ? axisX + len + 5 : axisX - len - 5;
    const anchor = value >= 0 ? "start" : "end";
    bars += `<g><title>${esc(key)}: ${value >= 0 ? "+" : ""}${fmt(value, 1)}</title>
      <text x="${labelW - 8}" y="${y + h - 2}" text-anchor="end" font-size="11" fill="${muted}">${esc(key)}</text>
      <path d="${path}" fill="${color}"></path>
      <text x="${valueX}" y="${y + h - 2}" text-anchor="${anchor}" font-size="10.5" fill="${ink2}"
        style="font-variant-numeric:tabular-nums">${value >= 0 ? "+" : ""}${fmt(value, 1)}</text></g>`;
  });

  const note = base !== undefined && base !== null
    ? `<p class="contrib-note">${esc(t("contrib.base"))}: +${fmt(base, 0)}</p>` : "";
  return `<svg class="contrib-svg" viewBox="0 0 ${width} ${height}" role="img">
    <line x1="${axisX}" y1="2" x2="${axisX}" y2="${height - 2}" stroke="${baseline}" stroke-width="1"></line>
    ${bars}</svg>${note}`;
}

/* Price ladder: stop / entry zone / targets on one linear price axis.
   Status colors carry state and every marker has a text label. */
function priceLadderSVG(plan) {
  const stop = plan.stop_price, lo = plan.entry_low, hi = plan.entry_high;
  const t1 = plan.target1, t2 = plan.target2;
  if ([stop, lo, hi].some((value) => value === null || value === undefined)) return "";
  const points = [stop, lo, hi, t1, t2].filter((value) => value !== null && value !== undefined);
  const min = Math.min(...points), max = Math.max(...points);
  const pad = (max - min) * 0.06 || 1;
  const width = 640, height = 84, left = 14, right = 14, axisY = 46;
  const scale = (value) =>
    left + ((value - (min - pad)) / ((max + pad) - (min - pad))) * (width - left - right);

  const critical = cssVar("--critical"), good = cssVar("--good-text") || cssVar("--good");
  const zone = cssVar("--zone"), posColor = cssVar("--pos");
  const baseline = cssVar("--baseline"), muted = cssVar("--muted"), ink = cssVar("--ink");

  const tick = (value, color, label, above) => {
    const x = scale(value);
    const textY = above ? axisY - 22 : axisY + 26;
    const priceY = above ? axisY - 10 : axisY + 38;
    return `<line x1="${x}" y1="${axisY - 7}" x2="${x}" y2="${axisY + 7}" stroke="${color}" stroke-width="2"></line>
      <text x="${x}" y="${textY}" text-anchor="middle" font-size="10" font-weight="600" fill="${color}">${esc(label)}</text>
      <text x="${x}" y="${priceY}" text-anchor="middle" font-size="10" fill="${muted}"
        style="font-variant-numeric:tabular-nums">${fmt(value)}</text>`;
  };

  const zoneX = scale(lo), zoneW = Math.max(2, scale(hi) - zoneX);
  let svg = `<svg class="ladder-svg" viewBox="0 0 ${width} ${height}" role="img">
    <line x1="${left}" y1="${axisY}" x2="${width - right}" y2="${axisY}" stroke="${baseline}" stroke-width="1"></line>
    <rect x="${zoneX}" y="${axisY - 9}" width="${zoneW}" height="18" fill="${zone}"
      stroke="${posColor}" stroke-width="1" rx="3"></rect>
    <text x="${zoneX + zoneW / 2}" y="${axisY - 14}" text-anchor="middle" font-size="10"
      font-weight="600" fill="${ink}">${esc(t("chart.entry"))} ${fmt(lo)}–${fmt(hi)}</text>
    ${tick(stop, critical, t("chart.stop"), false)}`;
  if (t1 !== null && t1 !== undefined) svg += tick(t1, good, t("chart.t1"), false);
  if (t2 !== null && t2 !== undefined) svg += tick(t2, good, t("chart.t2"), false);
  svg += `</svg>`;
  return svg;
}

/* ---------- boot ---------- */

async function fetchJSON(path) {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    return null;
  }
}

async function boot() {
  applyI18n();
  $("lang-zh").addEventListener("click", () => setLang("zh"));
  $("lang-en").addEventListener("click", () => setLang("en"));
  const [brief, armed, health] = await Promise.all([
    fetchJSON("data/latest.json"),
    fetchJSON("data/armed_plans.json"),
    fetchJSON("data/health.json"),
  ]);
  cache = { brief, armed, health };
  render();
}

boot();
