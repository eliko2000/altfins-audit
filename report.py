"""Aggregate forward-return evaluations into a quality report."""
import pandas as pd  # type: ignore
from tabulate import tabulate  # type: ignore

import db


def load_data():
    conn = db.connect()
    sigs = pd.read_sql_query(
        "SELECT signal_id, posted_at, category, symbol, side, "
        "last_price, target_pct, target_price, signal_type "
        "FROM signals", conn,
    )
    rets = pd.read_sql_query("SELECT * FROM returns", conn)
    base = pd.read_sql_query("SELECT * FROM baseline_returns", conn)
    return sigs, rets, base


def summarize(sigs: pd.DataFrame, rets: pd.DataFrame, base: pd.DataFrame) -> None:
    print(f"\nTotal signals parsed:     {len(sigs)}")
    print("\nBy category:")
    print(tabulate(sigs["category"].value_counts().reset_index().values,
                   headers=["category", "count"]))

    evaluable = sigs[sigs["category"].isin(["directional", "target"])]
    print(f"\nEvaluable signals:        {len(evaluable)}")
    if evaluable.empty:
        return

    side_counts = evaluable["side"].value_counts()
    print(f"  long:                   {side_counts.get('long', 0)}")
    print(f"  short:                  {side_counts.get('short', 0)}")

    df = rets.merge(sigs[["signal_id", "side", "category"]], on="signal_id", how="left")
    df = df[df["fwd_return"].notna()]

    df["signed_return"] = df.apply(
        lambda r: r["fwd_return"] if r["side"] == "long" else -r["fwd_return"],
        axis=1,
    )

    def _table(name: str, signal_df: pd.DataFrame, base_df: pd.DataFrame) -> None:
        if signal_df.empty:
            return
        print(f"\n=== {name} ===")
        rows = []
        for h in sorted(signal_df["horizon_hours"].unique()):
            sub = signal_df[signal_df["horizon_hours"] == h]
            n = len(sub)
            if n == 0:
                continue
            acc = sub["direction_correct"].mean()
            signed_mean = sub["signed_return"].mean()
            signed_med = sub["signed_return"].median()
            b = base_df[base_df["horizon_hours"] == h]
            b_mean = b["fwd_return"].mean() if not b.empty else 0
            b_med = b["fwd_return"].median() if not b.empty else 0
            rows.append([
                (f"+{h}h" if h < 24 else f"+{h//24}d"), n,
                f"{acc:.1%}",
                f"{signed_mean*100:+.2f}%",
                f"{signed_med*100:+.2f}%",
                f"{b_mean*100:+.2f}%",
                f"{b_med*100:+.2f}%",
                f"{(signed_mean - b_mean)*100:+.2f}%",
            ])
        print(tabulate(
            rows,
            headers=["horizon", "n", "dir_acc",
                     "signal mean", "signal med",
                     "baseline mean", "baseline med", "alpha"],
        ))

    _table("Overall: forward returns vs baseline", df, base)
    _table("Long calls only", df[df["side"] == "long"], base)
    _table("Short calls only", df[df["side"] == "short"], base)

    # Regime split — naive month-based, using BTC as proxy
    sigs2 = sigs.copy()
    sigs2["posted_dt"] = pd.to_datetime(sigs2["posted_at"], utc=True)
    sigs2["year_half"] = sigs2["posted_dt"].dt.year.astype(str) + "-H" + \
        ((sigs2["posted_dt"].dt.month > 6).astype(int) + 1).astype(str)
    df2 = df.merge(sigs2[["signal_id", "year_half"]], on="signal_id", how="left")
    print("\n=== By half-year (24h horizon) ===")
    rows = []
    for hy in sorted(df2["year_half"].dropna().unique()):
        sub = df2[(df2["year_half"] == hy) & (df2["horizon_hours"] == 24)]
        if sub.empty:
            continue
        rows.append([hy, len(sub), f"{sub['direction_correct'].mean():.1%}",
                     f"{sub['signed_return'].mean()*100:+.2f}%"])
    print(tabulate(rows, headers=["period", "n", "dir_acc", "signal mean (24h)"]))

    # Target-alert specific
    targets = sigs[sigs["category"] == "target"]
    if not targets.empty:
        tdf = rets.merge(targets[["signal_id", "side", "target_pct"]],
                         on="signal_id", how="inner")
        tdf = tdf[tdf["target_hit_pathwise"].notna()]
        print(f"\n=== Target alerts (n={len(targets)}) ===")
        rows = []
        for h in sorted(tdf["horizon_hours"].unique()):
            sub = tdf[tdf["horizon_hours"] == h]
            if sub.empty:
                continue
            hit = sub["target_hit_pathwise"].mean()
            rows.append([(f"+{h}h" if h < 24 else f"+{h//24}d"), len(sub), f"{hit:.1%}"])
        print(tabulate(rows, headers=["horizon", "n", "target_hit_rate"]))

    # By signal_type breakdown (top types only)
    print("\n=== Top signal_type buckets (24h horizon) ===")
    types = sigs[sigs["category"].isin(["directional", "target"])]["signal_type"]
    if types.notna().any():
        seven = df[df["horizon_hours"] == 24].merge(
            sigs[["signal_id", "signal_type"]], on="signal_id", how="left",
        )
        seven = seven[seven["signal_type"].notna()]
        grp = seven.groupby("signal_type").agg(
            n=("fwd_return", "count"),
            dir_acc=("direction_correct", "mean"),
            mean_signed=("fwd_return", lambda s: s.mean()),
        ).sort_values("n", ascending=False).head(8)
        if not grp.empty:
            print(tabulate(
                [(t[:50], r["n"], f"{r['dir_acc']:.1%}",
                  f"{r['mean_signed']*100:+.2f}%")
                 for t, r in grp.iterrows()],
                headers=["signal_type", "n", "dir_acc", "mean fwd"],
            ))

    # OOS coverage / data gaps
    nodata = rets[rets["note"].notna()]
    if not nodata.empty:
        print(f"\nData gaps: {len(nodata)} rows with missing OHLCV "
              f"(likely non-Binance USDT pairs)")


def main() -> None:
    sigs, rets, base = load_data()
    if sigs.empty:
        print("No signals — run parse first.")
        return
    summarize(sigs, rets, base)


if __name__ == "__main__":
    main()
