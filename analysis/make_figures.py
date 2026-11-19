"""Regenerate the figures and headline numbers used in analysis/REPORT.md.

    python scripts/pull_data.py                                          # snapshots from the data branch
    dagster job execute -m transit_pipeline.definitions -j collect_and_build
    python analysis/make_figures.py                                      # reads data/warehouse.duckdb

Writes analysis/figures/*.png and analysis/numbers.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = Path(os.getenv("TRANSIT_WAREHOUSE", ROOT / "data" / "warehouse.duckdb"))
OUT = Path(__file__).resolve().parent / "figures"

# Categorical palette (validated for colour-vision deficiency), fixed order by mode.
MODES = ["Bus", "Subway", "Light rail", "Commuter rail", "Ferry"]
COLORS = dict(zip(MODES, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"], strict=True))
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#ecebe6"

plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "figure.dpi": 130, "savefig.bbox": "tight",
})


def q(con, sql):
    return con.execute(sql).df()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    numbers: dict = {}

    s = q(con, """select count(*) n, count(distinct snapshot_ts) snaps, count(distinct route_id) routes,
                  min(snapshot_local) first, max(snapshot_local) last,
                  median(delay_min) med, quantile_cont(delay_min, .9) p90,
                  avg(is_on_time::int) on_time, avg(is_late::int) late
                  from marts.fct_delay_observations""").iloc[0]
    numbers["overall"] = {k: (str(v) if k in ("first", "last") else float(v)) for k, v in s.items()}

    # 1. Delay by hour of day, per mode (weekdays only, so rush hours line up).
    h = q(con, """select local_hour, mode, median(delay_min) med, count(*) n
                  from marts.fct_delay_observations where not is_weekend group by all having count(*) >= 15""")
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    for mode in MODES:
        d = h[h["mode"] == mode].sort_values("local_hour")
        if len(d) >= 3:
            ax.plot(d["local_hour"], d["med"], color=COLORS[mode], lw=2, label=mode)
            ax.annotate(mode, (d["local_hour"].iloc[-1], d["med"].iloc[-1]), xytext=(4, 0),
                        textcoords="offset points", color=MUTED, fontsize=8, va="center")
    ax.set_xlabel("Hour of day (Boston, weekdays)")
    ax.set_ylabel("Median delay (min)")
    ax.set_xticks(range(0, 24, 3))
    ax.legend(frameon=False, ncol=5, loc="upper left", bbox_to_anchor=(0, 1.15), fontsize=8)
    fig.savefig(OUT / "delay_by_hour.png")
    plt.close(fig)
    numbers["by_hour"] = h.to_dict("records")

    # 2. On-time share by mode.
    m = q(con, """select mode, count(*) n, avg(is_on_time::int)*100 on_time, median(delay_min) med,
                  quantile_cont(delay_min, .9) p90 from marts.fct_delay_observations group by mode""")
    m = m.set_index("mode").reindex([x for x in MODES if x in set(m["mode"])]).reset_index()
    fig, ax = plt.subplots(figsize=(6, 3.2))
    bars = ax.bar(m["mode"], m["on_time"], color=[COLORS[x] for x in m["mode"]], width=0.6)
    ax.bar_label(bars, labels=[f"{v:.0f}%" for v in m["on_time"]], padding=3, color=INK, fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_ylabel("On time (%)")
    fig.savefig(OUT / "on_time_by_mode.png")
    plt.close(fig)
    numbers["by_mode"] = m.to_dict("records")

    # 3. Distribution of delays.
    d = q(con, """select greatest(-5, least(20, floor(delay_min)))::int as minute, count(*) as n
                  from marts.fct_delay_observations group by 1 order by 1""")
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.bar(d["minute"], 100 * d["n"] / d["n"].sum(), color=["#eb6834" if x >= 5 else "#2a78d6" for x in d["minute"]], width=0.8)
    ax.set_xlabel("Delay (min); -5 and 20 include everything beyond")
    ax.set_ylabel("Share of vehicles (%)")
    fig.savefig(OUT / "delay_distribution.png")
    plt.close(fig)

    # 4. Weather: buses only, to keep the mode mix constant.
    w = q(con, """select precip_band, temp_band, count(*) n, count(distinct strftime(snapshot_local, '%Y-%m-%d %H')) as hours_observed,
                  avg(is_on_time::int)*100 on_time, median(delay_min) med
                  from marts.fct_delay_observations where mode = 'Bus' group by grouping sets ((precip_band), (temp_band))""")
    numbers["weather_bus"] = w.to_dict("records")

    # 5. Worst routes with enough observations.
    r = q(con, """select route_name, mode, observations, median_delay_min, p90_delay_min, on_time_pct
                  from marts.agg_route_performance where observations >= 40 order by median_delay_min desc limit 10""")
    numbers["worst_routes"] = r.to_dict("records")
    b = q(con, """select route_name, mode, observations, median_delay_min, on_time_pct
                  from marts.agg_route_performance where observations >= 40 order by on_time_pct desc limit 5""")
    numbers["best_routes"] = b.to_dict("records")

    (Path(__file__).parent / "numbers.json").write_text(json.dumps(numbers, indent=2, default=str))
    print(json.dumps(numbers["overall"], indent=2))
    print(f"wrote {len(list(OUT.glob('*.png')))} figures to {OUT}")


if __name__ == "__main__":
    main()
