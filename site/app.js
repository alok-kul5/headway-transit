// "How late is the T?": renders the exported marts (data/*.json) with motion.

const MODE_ORDER = ["Bus", "Subway", "Light rail", "Commuter rail", "Ferry"];
// Line colours as data. Bus yellow is darkened for lines on light paper.
const MODE_LINE = { Bus: "#d9a400", Subway: "#da291c", "Light rail": "#00843d", "Commuter rail": "#80276c", Ferry: "#006f85" };
const PRECIP_ORDER = ["dry", "light rain", "heavy rain", "snow"];
const $ = (s) => document.querySelector(s);
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const fmt = (v, d = 1) => (v == null ? "–" : Number(v).toFixed(d));
const signed = (v) => (v == null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(Number(v)).toFixed(1)}`);
const boston = (ts, o) => new Date(ts * 1000).toLocaleString("en-US", { timeZone: "America/New_York", ...o });
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

async function load(name) {
  const r = await fetch(`data/${name}.json`, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${name}: ${r.status}`);
  return r.json();
}

/* Count a number up to its value when it scrolls into view. */
function countUp(el, to, dec = 0, ms = 1400) {
  if (reduced() || to == null) { el.textContent = fmt(to, dec); return; }
  const from = Number(el.dataset.shown ?? 0), t0 = performance.now();
  el.dataset.shown = to;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / ms), e = 1 - (1 - k) ** 4;
    el.textContent = (from + (to - from) * e).toFixed(dec);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* Reveal on scroll; staggered by position within each section. */
const io = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); e.target.dispatchEvent(new Event("revealed")); io.unobserve(e.target); }
}, { threshold: 0.18 });
function watch(el, i = 0) { el.style.setProperty("--d", `${i * 90}ms`); io.observe(el); }

function bulletFor(routeName, color) {
  const c = color || "#555";
  const light = ["#FFC72C", "#ffc72c"].includes(c);
  const label = routeName.replace(/ Line$/, "").replace(/^Green-/, "GL ").slice(0, 8);
  return `<span class="bullet ${light ? "dark-ink" : ""}" style="background:${esc(c)}">${esc(label)}</span>`;
}

function hero(summary, nowModes, nowLate) {
  const vehicles = nowModes.reduce((n, m) => n + m.vehicles, 0);
  const onTime = vehicles ? nowModes.reduce((n, m) => n + (m.on_time_pct * m.vehicles) / 100, 0) / vehicles * 100 : summary.on_time_pct;
  const big = $("#big-pct");
  $(".hero-card").addEventListener("revealed", () => countUp(big, Math.round(onTime), 0, 1600), { once: true });
  const worst = nowLate[0];
  $("#hero-sub").textContent = worst
    ? `${vehicles.toLocaleString()} vehicles in the latest snapshot. Worst right now: ${worst.route_name} at ${worst.stop_name}, ${Math.round(worst.delay_min)} minutes behind.`
    : "Waiting for the next snapshot.";
  const last = nowLate[0]?.snapshot_ts ?? summary.last_snapshot_ts;
  $("#board-time").textContent = last ? boston(last, { weekday: "short", hour: "numeric", minute: "2-digit" }) + " in Boston" : "";
  if (last) {
    const mins = Math.max(0, Math.round((Date.now() / 1000 - last) / 60));
    const ago = mins < 60 ? `${mins} min ago` : mins < 1440 ? `${Math.round(mins / 60)} h ago` : `${Math.round(mins / 1440)} d ago`;
    $("#live").hidden = false;
    $("#live").classList.toggle("stale", mins > 90);
    $("#live-text").textContent = `${mins > 90 ? "Last snapshot" : "Live"} · ${ago}`;
  }
  $("#footer-note").insertAdjacentHTML("afterbegin",
    `${summary.snapshots} snapshots, ${Number(summary.observations).toLocaleString()} observations of ${summary.routes} routes since ${boston(summary.first_snapshot_ts, { month: "short", day: "numeric" })}. `);
}

function board(rows) {
  $("#board").innerHTML = rows.slice(0, 8).map((r, i) => {
    const dir = r.direction_id === 1 ? "inbound" : "outbound";
    return `<li class="board-row" style="--i:${i}">
      ${bulletFor(r.route_name, r.route_color)}
      <span class="board-stop"><strong>${esc(r.stop_name ?? "Next stop")}</strong><span>${esc(r.mode)} · ${dir}</span></span>
      <span class="board-late ${r.delay_min >= 15 ? "very" : ""}">+${Math.round(r.delay_min)}<small>min</small></span>
    </li>`;
  }).join("") || `<li class="board-row" style="--i:0"><span></span><span class="board-stop"><strong>No vehicles in the latest snapshot</strong></span><span></span></li>`;
}

function fleet(nowModes, byMode) {
  const src = nowModes.length ? nowModes : byMode;
  document.querySelectorAll("[data-stat]").forEach((el) => {
    const m = src.find((r) => r.mode === el.dataset.stat);
    el.textContent = m ? `${Math.round(m.on_time_pct)}% on time` : "–";
  });
}

function modes(nowModes, byMode) {
  const src = nowModes.length ? nowModes : byMode;
  const list = MODE_ORDER.map((m) => src.find((r) => r.mode === m)).filter(Boolean);
  const row = $("#mode-row");
  row.style.setProperty("--n", list.length);
  row.innerHTML = list.map((m, i) => `<article class="mode" data-mode="${m.mode}" style="--i:${i}">
      <h3 class="mode-name">${m.mode}</h3>
      <p class="mode-pct"><span data-to="${m.on_time_pct}">0</span><small>%</small></p>
      <p class="mode-meta">on time · median ${signed(m.median_delay_min)} min${m.vehicles ? ` · ${m.vehicles} vehicles` : ""}</p>
    </article>`).join("");
  row.querySelectorAll(".mode").forEach((el) => {
    io.observe(el);
    el.addEventListener("revealed", () => countUp(el.querySelector("[data-to]"), Math.round(Number(el.querySelector("[data-to]").dataset.to)), 0, 1300), { once: true });
  });
}

/* Charts: Chart.js with ink axes, line colours as data, and entrance animations. */
function base(extra = {}) {
  const ink = css("--ink-2"), grid = css("--paper");
  return {
    maintainAspectRatio: false,
    animation: reduced() ? false : { duration: 1400, easing: "easeOutQuart" },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { backgroundColor: css("--ink"), titleColor: css("--paper"), bodyColor: css("--paper"), padding: 10, cornerRadius: 10, displayColors: false },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: ink, font: { family: "Geist Mono", size: 11 } }, border: { display: false } },
      y: { grid: { color: grid, lineWidth: 2 }, ticks: { color: ink, font: { family: "Geist Mono", size: 11 } }, border: { display: false } },
    },
    ...extra,
  };
}
function whenVisible(canvas, draw) {
  const fig = canvas.closest(".panel");
  if (fig.classList.contains("in")) draw();
  else fig.addEventListener("revealed", draw, { once: true });
}

function timeline(rows) {
  const c = $("#timeline");
  whenVisible(c, () => new Chart(c, {
    type: "line",
    data: { datasets: [{ data: rows.map((r) => ({ x: r.snapshot_ts * 1000, y: r.on_time_pct, r })), borderColor: css("--ink"), backgroundColor: "#ffc72c55",
      fill: "origin", borderWidth: 3, pointRadius: rows.length > 40 ? 0 : 4, pointBackgroundColor: css("--ink"), pointHoverRadius: 7, tension: 0.25 }] },
    options: base({
      parsing: false,
      scales: {
        x: { type: "linear", grid: { display: false }, border: { display: false },
          ticks: { color: css("--ink-2"), maxTicksLimit: 5, maxRotation: 0, callback: (v) => boston(v / 1000, { hour: "numeric", minute: "2-digit" }) } },
        y: { min: 0, max: 100, grid: { color: css("--paper"), lineWidth: 2 }, border: { display: false }, ticks: { color: css("--ink-2"), stepSize: 25, callback: (v) => `${v}%` } },
      },
      plugins: { ...base().plugins, tooltip: { ...base().plugins.tooltip, callbacks: {
        title: (it) => boston(it[0].raw.x / 1000, { weekday: "short", hour: "numeric", minute: "2-digit" }),
        label: (it) => [`On time ${fmt(it.raw.r.on_time_pct)}%`, `Median delay ${signed(it.raw.r.median_delay_min)} min`, `${it.raw.r.vehicles} vehicles`],
      } } },
    }),
  }));
}

function hourly(rows) {
  const modesPresent = MODE_ORDER.filter((m) => rows.some((r) => r.mode === m && r.observations >= 10));
  $("#hourly-legend").innerHTML = modesPresent.map((m) => `<span><i style="background:${MODE_LINE[m]}"></i>${m}</span>`).join("");
  const hours = [...Array(24).keys()];
  const c = $("#hourly");
  whenVisible(c, () => new Chart(c, {
    type: "line",
    data: {
      labels: hours.map((h) => (h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`)),
      datasets: modesPresent.map((m) => ({
        label: m, borderColor: MODE_LINE[m], backgroundColor: MODE_LINE[m], borderWidth: 3, pointRadius: 3, pointHoverRadius: 6, spanGaps: true, tension: 0.3,
        data: hours.map((h) => rows.find((r) => r.mode === m && r.local_hour === h && r.observations >= 10)?.median_delay_min ?? null),
      })),
    },
    options: base({
      scales: {
        x: { ...base().scales.x, ticks: { ...base().scales.x.ticks, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
        y: { ...base().scales.y, ticks: { ...base().scales.y.ticks, callback: (v) => `${v} min` } },
      },
      plugins: { ...base().plugins, tooltip: { ...base().plugins.tooltip, displayColors: true, callbacks: { label: (i) => `${i.dataset.label}: ${signed(i.raw)} min` } } },
    }),
  }));
}

function bars(canvas, labels, values, colors, label, max) {
  whenVisible(canvas, () => new Chart(canvas, {
    type: "bar",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderRadius: 8, borderSkipped: false, maxBarThickness: 64 }] },
    options: base({
      interaction: { mode: "nearest", intersect: false, axis: "x" },
      scales: {
        x: { ...base().scales.x, ticks: { ...base().scales.x.ticks, maxRotation: 0, autoSkip: true } },
        y: { ...base().scales.y, min: 0, max, ticks: { ...base().scales.y.ticks, callback: (v) => `${v}%` } },
      },
      plugins: { ...base().plugins, tooltip: { ...base().plugins.tooltip, callbacks: { label } } },
    }),
  }));
}

function histogram(rows) {
  const total = rows.reduce((n, r) => n + r.observations, 0) || 1;
  bars($("#histogram"), rows.map((r) => (r.minute <= -5 ? "≤−5" : r.minute >= 20 ? "20+" : String(r.minute))),
    rows.map((r) => (100 * r.observations) / total),
    rows.map((r) => (r.minute >= 5 ? css("--red") : r.minute >= -1 ? css("--ink") : css("--ink-3"))),
    (i) => `${fmt(i.raw)}% of vehicles (${rows[i.dataIndex].observations.toLocaleString()})`);
}

function weather(rows) {
  const bus = PRECIP_ORDER.map((b) => rows.find((r) => r.dimension === "precipitation" && r.mode === "Bus" && r.bucket === b)).filter(Boolean);
  bars($("#weather"), bus.map((r) => r.bucket), bus.map((r) => r.on_time_pct), bus.map((r) => (r.bucket === "dry" ? "#d9a400" : css("--blue"))),
    (i) => [`On time ${fmt(bus[i.dataIndex].on_time_pct)}%`, `${bus[i.dataIndex].hours_observed} hours observed`], 100);
  const wet = bus.filter((r) => r.bucket !== "dry").reduce((n, r) => n + r.hours_observed, 0);
  $("#weather-caveat").textContent = wet < 24 ? `Only ${wet} wet hours so far, so the rain bars are early signals, not results.` : `${wet} wet hours observed.`;
}

function routes(rows) {
  const top = rows.slice(0, 15);
  const max = Math.max(1, ...top.map((r) => r.median_delay_min));
  $("#routes-body").innerHTML = top.map((r, i) => `<tr>
      <td><span class="route-cell">${bulletFor(r.route_name, r.route_color)}${esc(r.route_name)}</span></td>
      <td>${esc(r.mode)}</td>
      <td class="num"><span class="delay-bar" style="width:${Math.max(4, (90 * Math.max(0, r.median_delay_min)) / max)}px; --i:${i}"></span>${signed(r.median_delay_min)} min</td>
      <td class="num">${signed(r.p90_delay_min)} min</td>
      <td class="num">${fmt(r.on_time_pct)}%</td>
      <td class="num">${r.observations.toLocaleString()}</td></tr>`).join("")
    || `<tr><td colspan="6">Not enough observations yet.</td></tr>`;
}

(async () => {
  document.querySelectorAll(".reveal").forEach((el) => {
    const siblings = [...el.parentElement.querySelectorAll(":scope > .reveal")];
    watch(el, Math.max(0, siblings.indexOf(el)));
  });
  try {
    const [summary, nowModes, nowLate, byMode, timelineRows, hourlyRows, weatherRows, histRows, routeRows] = await Promise.all(
      ["summary", "now_modes", "now_late", "by_mode", "timeline", "hourly", "weather", "delay_histogram", "routes"].map((n) => load(n).catch(() => [])),
    );
    hero(summary, nowModes, nowLate);
    board(nowLate);
    modes(nowModes, byMode);
    fleet(nowModes, byMode);
    const ready = () => { timeline(timelineRows); hourly(hourlyRows); histogram(histRows); weather(weatherRows); };
    if (window.Chart) ready(); else addEventListener("load", ready, { once: true });
    routes(routeRows);
  } catch (err) {
    $("#hero-sub").textContent = `Could not load data (${err.message}).`;
  }
})();
