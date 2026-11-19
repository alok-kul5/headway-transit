// Renders the dashboard from the JSON files the pipeline exports (data/*.json).

const MODE_ORDER = ["Bus", "Subway", "Light rail", "Commuter rail", "Ferry"];
const PRECIP_ORDER = ["dry", "light rain", "heavy rain", "snow"];

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const modeColor = (mode) => css(`--s${MODE_ORDER.indexOf(mode) + 1}`) || css("--ink-3");
const fmt = (v, d = 1) => (v == null ? "–" : Number(v).toFixed(d));
const signed = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)}`);
const boston = (ts, opts) => new Date(ts * 1000).toLocaleString("en-US", { timeZone: "America/New_York", ...opts });

async function load(name) {
  const r = await fetch(`data/${name}.json`, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${name}: ${r.status}`);
  return r.json();
}

function baseOptions(extra = {}) {
  const grid = css("--grid");
  const ink = css("--ink-2");
  return {
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { backgroundColor: css("--ink"), titleColor: css("--surface"), bodyColor: css("--surface"), padding: 10, cornerRadius: 6 },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: ink }, border: { color: css("--line") } },
      y: { grid: { color: grid }, ticks: { color: ink }, border: { display: false } },
    },
    ...extra,
  };
}

function kpis(s) {
  const tiles = [
    ["On time", `${fmt(s.on_time_pct)}%`, "1 min early to 5 min late"],
    ["Median delay", `${signed(s.median_delay_min)} min`, `90th percentile ${signed(s.p90_delay_min)} min`],
    ["Late (5+ min)", `${fmt(s.late_pct)}%`, "of vehicles observed"],
    ["Observations", Number(s.observations).toLocaleString(), `${s.snapshots} snapshots · ${s.routes} routes · ${s.days} days`],
  ];
  document.getElementById("kpis").innerHTML = tiles
    .map(([l, v, sub]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`)
    .join("");
  const range = s.first_snapshot_ts
    ? `${boston(s.first_snapshot_ts, { month: "short", day: "numeric" })} – ${boston(s.last_snapshot_ts, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} Boston time`
    : "";
  document.getElementById("updated").textContent = `Data from ${range}.`;
}

function timeline(rows) {
  const accent = css("--s1");
  new Chart(document.getElementById("timeline"), {
    type: "line",
    data: {
      datasets: [{
        label: "On time",
        data: rows.map((r) => ({ x: r.snapshot_ts * 1000, y: r.on_time_pct, r })),
        borderColor: accent, borderWidth: 2, pointRadius: rows.length > 60 ? 0 : 3, pointHoverRadius: 5,
        pointBackgroundColor: accent, tension: 0.2,
      }],
    },
    options: baseOptions({
      parsing: false,
      scales: {
        x: {
          type: "linear", grid: { display: false }, border: { color: css("--line") },
          ticks: { color: css("--ink-2"), maxTicksLimit: 7, callback: (v) => boston(v / 1000, { month: "short", day: "numeric", hour: "numeric" }) },
        },
        y: { min: 0, max: 100, grid: { color: css("--grid") }, border: { display: false }, ticks: { color: css("--ink-2"), callback: (v) => `${v}%` } },
      },
      plugins: {
        ...baseOptions().plugins,
        tooltip: {
          ...baseOptions().plugins.tooltip,
          callbacks: {
            title: (items) => boston(items[0].raw.x / 1000, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
            label: (item) => {
              const r = item.raw.r;
              return [
                `On time: ${fmt(r.on_time_pct)}%`,
                `Median delay: ${signed(r.median_delay_min)} min`,
                `Vehicles: ${r.vehicles}`,
                `Weather: ${fmt(r.temperature_c)}°C, ${fmt(r.precipitation_mm)} mm rain`,
              ];
            },
          },
        },
      },
    }),
  });
}

function hourly(rows) {
  const modes = MODE_ORDER.filter((m) => rows.some((r) => r.mode === m && r.observations >= 10));
  document.getElementById("hourly-legend").innerHTML = modes
    .map((m) => `<span><i style="background:${modeColor(m)}"></i>${m}</span>`)
    .join("");
  const hours = [...Array(24).keys()];
  new Chart(document.getElementById("hourly"), {
    type: "line",
    data: {
      labels: hours.map((h) => (h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`)),
      datasets: modes.map((m) => ({
        label: m,
        data: hours.map((h) => {
          const r = rows.find((x) => x.mode === m && x.local_hour === h && x.observations >= 10);
          return r ? r.median_delay_min : null;
        }),
        borderColor: modeColor(m), backgroundColor: modeColor(m), borderWidth: 2,
        pointRadius: 2, pointHoverRadius: 5, spanGaps: true, tension: 0.25,
      })),
    },
    options: baseOptions({
      scales: {
        ...baseOptions().scales,
        y: { ...baseOptions().scales.y, ticks: { color: css("--ink-2"), callback: (v) => `${v} min` } },
      },
      plugins: {
        ...baseOptions().plugins,
        tooltip: { ...baseOptions().plugins.tooltip, callbacks: { label: (i) => `${i.dataset.label}: ${signed(i.raw)} min` } },
      },
    }),
  });
}

function bars(canvasId, labels, values, { color, suffix = "%", max, counts, tooltipLabel }) {
  new Chart(document.getElementById(canvasId), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values, backgroundColor: color, borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "bottom",
        maxBarThickness: 56, categoryPercentage: 0.7,
      }],
    },
    options: baseOptions({
      interaction: { mode: "nearest", intersect: false, axis: "x" },
      scales: {
        ...baseOptions().scales,
        y: { ...baseOptions().scales.y, min: 0, max, ticks: { color: css("--ink-2"), callback: (v) => `${v}${suffix}` } },
      },
      plugins: {
        ...baseOptions().plugins,
        tooltip: {
          ...baseOptions().plugins.tooltip,
          callbacks: { label: tooltipLabel || ((i) => `${fmt(i.raw)}${suffix}${counts ? ` (${counts[i.dataIndex].toLocaleString()} obs.)` : ""}`) },
        },
      },
    }),
  });
}

function modes(rows) {
  const ordered = MODE_ORDER.map((m) => rows.find((r) => r.mode === m)).filter(Boolean);
  bars("modes", ordered.map((r) => r.mode), ordered.map((r) => r.on_time_pct), {
    color: ordered.map((r) => modeColor(r.mode)), max: 100, counts: ordered.map((r) => r.observations),
  });
}

function weatherChart(rows) {
  const bus = rows.filter((r) => r.dimension === "precipitation" && r.mode === "Bus" && PRECIP_ORDER.includes(r.bucket));
  const ordered = PRECIP_ORDER.map((b) => bus.find((r) => r.bucket === b)).filter(Boolean);
  bars("weather", ordered.map((r) => r.bucket), ordered.map((r) => r.on_time_pct), {
    color: css("--s1"), max: 100, counts: ordered.map((r) => r.observations),
    tooltipLabel: (i) => {
      const r = ordered[i.dataIndex];
      return [`On time: ${fmt(r.on_time_pct)}%`, `Median delay: ${signed(r.median_delay_min)} min`, `${r.observations.toLocaleString()} obs. over ${r.hours_observed} hours`];
    },
  });
  const wet = ordered.filter((r) => r.bucket !== "dry").reduce((n, r) => n + r.hours_observed, 0);
  document.getElementById("weather-caveat").textContent = wet < 24
    ? `Only ${wet} wet hours observed so far, so treat the rain bars as early signals, not results.`
    : `${wet} wet hours observed.`;
}

function histogram(rows) {
  const labels = rows.map((r) => (r.minute <= -5 ? "≤−5" : r.minute >= 20 ? "20+" : String(r.minute)));
  const total = rows.reduce((n, r) => n + r.observations, 0);
  const late = css("--s2");
  const ok = css("--s1");
  bars("histogram", labels, rows.map((r) => (100 * r.observations) / total), {
    color: rows.map((r) => (r.minute >= 5 ? late : ok)),
    tooltipLabel: (i) => `${fmt(i.raw)}% of vehicles (${rows[i.dataIndex].observations.toLocaleString()})`,
  });
}

function routes(rows) {
  const top = rows.slice(0, 15);
  const maxDelay = Math.max(1, ...top.map((r) => r.median_delay_min));
  document.getElementById("routes").innerHTML = top
    .map((r) => `<tr>
      <td><span class="swatch" style="background:${modeColor(r.mode)}"></span>${r.route_name}</td>
      <td>${r.mode}</td>
      <td class="num"><span class="bar" style="width:${Math.max(2, (60 * Math.max(0, r.median_delay_min)) / maxDelay)}px"></span>${signed(r.median_delay_min)} min</td>
      <td class="num">${signed(r.p90_delay_min)} min</td>
      <td class="num">${fmt(r.on_time_pct)}%</td>
      <td class="num">${r.observations.toLocaleString()}</td></tr>`)
    .join("") || `<tr><td colspan="6">Not enough data yet.</td></tr>`;
}

(async () => {
  try {
    const [summary, timelineRows, hourlyRows, modeRows, weatherRows, histRows, routeRows] = await Promise.all(
      ["summary", "timeline", "hourly", "by_mode", "weather", "delay_histogram", "routes"].map(load),
    );
    kpis(summary);
    timeline(timelineRows);
    hourly(hourlyRows);
    modes(modeRows);
    weatherChart(weatherRows);
    histogram(histRows);
    routes(routeRows);
  } catch (err) {
    document.getElementById("updated").textContent = `Could not load data (${err.message}).`;
  }
})();
