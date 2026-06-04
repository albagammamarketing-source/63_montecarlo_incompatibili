from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
except ImportError:
    print("Installa scikit-learn: pip install scikit-learn")
    raise


# =========================================================
# PATH
# =========================================================
PROJECT_DIR = Path(
    os.getenv("PIPELINE_PROJECT_PATH", str(Path(__file__).resolve().parent))
).resolve()

BASE_PATH = Path(
    os.getenv("PIPELINE_BASE_PATH", str(PROJECT_DIR / ".runtime_output"))
).resolve()
BASE_PATH.mkdir(parents=True, exist_ok=True)
INPUT_FILE = BASE_PATH / "13_concessionari_montecarlo_per_nome_commerciale.csv"
INPUT_COMPATIBILITA = BASE_PATH / "18_concessionari_riepilogo_compatibilita.csv"

OUT_CLUSTER = BASE_PATH / "20_concessionari_cluster_commerciali.csv"
OUT_SUMMARY = BASE_PATH / "21_concessionari_cluster_summary.csv"

SCRIPT_VERSION = "6_cluster_con_compatibilita_v1"


# =========================================================
# PARAMETRI
# =========================================================
N_CLUSTER = 4
RANDOM_STATE = 42

# Peso della qualità compatibilità nel risk score commerciale.
# Non modifica il clustering base in modo aggressivo, ma aumenta il ranking rischio
# per punti vendita con molti ticket non mappati/misti/incompatibili.
PESO_COMPAT_INCOMPATIBILI = 5000.0
PESO_COMPAT_MISTI = 1500.0
PESO_COMPAT_NON_MAPPATI = 750.0
PESO_COMPAT_ESCLUSI_MC = 5000.0


# =========================================================
# LETTURA CSV
# =========================================================
def leggi_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File non trovato: {path}")

    try:
        df = pd.read_csv(path, sep=";", decimal=",", dtype=str)
    except Exception:
        df = pd.read_csv(path, sep=";", dtype=str)

    df.columns = (
        df.columns
        .str.replace("\ufeff", "", regex=False)
        .str.replace("ï»¿", "", regex=False)
        .str.strip()
        .str.lower()
    )

    return df.fillna("")


# =========================================================
# NUMERI
# =========================================================
def converti_numero_italiano(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()

    s = (
        s.str.replace("€", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("\u00a0", "", regex=False)
    )

    mask_virgola = s.str.contains(",", regex=False)

    s2 = s.copy()
    s2.loc[mask_virgola] = (
        s2.loc[mask_virgola]
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )

    return pd.to_numeric(s2, errors="coerce")


def normalizza_numeri(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    colonne_numeriche = [
        "payout_medio",
        "payout_mediana",
        "payout_p90",
        "payout_p95",
        "payout_p99",
        "payout_massimo_osservato",
        "ticket_vincenti_medio",
        "ticket_vincenti_massimo",
        "num_ticket",
        "ticket_compatibili",
        "ticket_correlati",
        "ticket_misti",
        "ticket_non_mappati",
        "ticket_incompatibili",
        "ticket_esclusi_montecarlo",
        "importo_pagato_totale",
        "payout_potenziale_totale",
        "pct_incompatibili",
        "pct_non_mappati",
        "pct_correlati_misti",
    ]

    for col in colonne_numeriche:
        if col in df.columns:
            df[col] = converti_numero_italiano(df[col]).fillna(0)

    required = [
        "payout_medio",
        "payout_mediana",
        "payout_p90",
        "payout_p95",
        "payout_p99",
        "payout_massimo_osservato",
        "ticket_vincenti_medio",
        "ticket_vincenti_massimo",
    ]

    for col in required:
        if col not in df.columns:
            raise ValueError(f"Colonna mancante nel file input: {col}")

    return df


# =========================================================
# COMPATIBILITA
# =========================================================
def aggiungi_compatibilita(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Colonne di default se il file 18 non esiste o non è utilizzabile.
    default_cols = {
        "num_ticket_compat": 0,
        "ticket_compatibili": 0,
        "ticket_correlati": 0,
        "ticket_misti": 0,
        "ticket_non_mappati": 0,
        "ticket_incompatibili": 0,
        "ticket_esclusi_montecarlo": 0,
        "importo_pagato_totale_compat": 0.0,
        "payout_potenziale_totale_compat": 0.0,
        "pct_incompatibili": 0.0,
        "pct_non_mappati": 0.0,
        "pct_correlati_misti": 0.0,
    }

    if not INPUT_COMPATIBILITA.exists():
        print(f"⚠ File compatibilità non trovato: {INPUT_COMPATIBILITA}")
        print("   Procedo con cluster Monte Carlo standard senza arricchimento compatibilità.")
        for col, val in default_cols.items():
            df[col] = val
        return df

    comp = leggi_csv(INPUT_COMPATIBILITA)

    required = {"concessionario", "nome_commerciale"}
    if not required.issubset(comp.columns):
        print("⚠ File compatibilità presente ma senza colonne chiave concessionario/nome_commerciale.")
        print("   Procedo con cluster Monte Carlo standard senza arricchimento compatibilità.")
        for col, val in default_cols.items():
            df[col] = val
        return df

    comp["concessionario"] = comp["concessionario"].astype(str).str.strip().str.upper()
    comp["nome_commerciale"] = comp["nome_commerciale"].astype(str).str.strip()

    numeric_cols = [
        "num_ticket",
        "ticket_compatibili",
        "ticket_correlati",
        "ticket_misti",
        "ticket_non_mappati",
        "ticket_incompatibili",
        "ticket_esclusi_montecarlo",
        "importo_pagato_totale",
        "payout_potenziale_totale",
        "pct_incompatibili",
        "pct_non_mappati",
        "pct_correlati_misti",
    ]

    for col in numeric_cols:
        if col not in comp.columns:
            comp[col] = 0
        comp[col] = converti_numero_italiano(comp[col]).fillna(0)

    comp = comp.rename(columns={
        "num_ticket": "num_ticket_compat",
        "importo_pagato_totale": "importo_pagato_totale_compat",
        "payout_potenziale_totale": "payout_potenziale_totale_compat",
    })

    keep_cols = [
        "concessionario",
        "nome_commerciale",
        "num_ticket_compat",
        "ticket_compatibili",
        "ticket_correlati",
        "ticket_misti",
        "ticket_non_mappati",
        "ticket_incompatibili",
        "ticket_esclusi_montecarlo",
        "importo_pagato_totale_compat",
        "payout_potenziale_totale_compat",
        "pct_incompatibili",
        "pct_non_mappati",
        "pct_correlati_misti",
    ]

    df["concessionario"] = df["concessionario"].astype(str).str.strip().str.upper()
    df["nome_commerciale"] = df["nome_commerciale"].astype(str).str.strip()

    out = df.merge(
        comp[keep_cols],
        on=["concessionario", "nome_commerciale"],
        how="left",
    )

    for col, val in default_cols.items():
        if col not in out.columns:
            out[col] = val
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(val)

    return out


# =========================================================
# FEATURE ENGINEERING
# =========================================================
def prepara_feature(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()

    df["tail_ratio_p99_medio"] = np.where(
        df["payout_medio"] > 0,
        df["payout_p99"] / df["payout_medio"],
        0
    )

    df["tail_spread_p99_p95"] = df["payout_p99"] - df["payout_p95"]
    df["tail_spread_p95_mediana"] = df["payout_p95"] - df["payout_mediana"]

    df["max_ratio_payout_medio"] = np.where(
        df["payout_medio"] > 0,
        df["payout_massimo_osservato"] / df["payout_medio"],
        0
    )

    df["ticket_win_ratio_max_medio"] = np.where(
        df["ticket_vincenti_medio"] > 0,
        df["ticket_vincenti_massimo"] / df["ticket_vincenti_medio"],
        0
    )

    df["compat_risk_score"] = (
        df["ticket_incompatibili"] * PESO_COMPAT_INCOMPATIBILI +
        df["ticket_esclusi_montecarlo"] * PESO_COMPAT_ESCLUSI_MC +
        df["ticket_misti"] * PESO_COMPAT_MISTI +
        df["ticket_non_mappati"] * PESO_COMPAT_NON_MAPPATI / 100.0 +
        df["pct_non_mappati"] * 10.0 +
        df["pct_correlati_misti"] * 25.0
    )

    df = df.replace([np.inf, -np.inf], np.nan).fillna(0)

    features = [
        "payout_medio",
        "payout_mediana",
        "payout_p90",
        "payout_p95",
        "payout_p99",
        "payout_massimo_osservato",
        "ticket_vincenti_medio",
        "ticket_vincenti_massimo",
        "tail_ratio_p99_medio",
        "tail_spread_p99_p95",
        "tail_spread_p95_mediana",
        "max_ratio_payout_medio",
        "ticket_win_ratio_max_medio",
        # Variabili compatibilità: pesano nel clustering come qualità/rischio dati.
        "ticket_incompatibili",
        "ticket_esclusi_montecarlo",
        "ticket_misti",
        "ticket_non_mappati",
        "pct_non_mappati",
        "pct_correlati_misti",
        "compat_risk_score",
    ]

    X = df[features].copy()

    return df, X


# =========================================================
# CLUSTER
# =========================================================
def clusterizza(df: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    n_cluster_effettivi = min(N_CLUSTER, len(df))

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(
        n_clusters=n_cluster_effettivi,
        random_state=RANDOM_STATE,
        n_init=10
    )

    df["cluster"] = kmeans.fit_predict(X_scaled)

    return df


# =========================================================
# LABEL CLUSTER
# =========================================================
def assegna_label_cluster(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()

    summary = (
        df.groupby("cluster", dropna=False)
        .agg(
            num_commerciali=("nome_commerciale", "count"),
            payout_medio_mean=("payout_medio", "mean"),
            payout_mediana_mean=("payout_mediana", "mean"),
            payout_p95_mean=("payout_p95", "mean"),
            payout_p99_mean=("payout_p99", "mean"),
            payout_massimo_mean=("payout_massimo_osservato", "mean"),
            ticket_vincenti_medio_mean=("ticket_vincenti_medio", "mean"),
            ticket_vincenti_massimo_mean=("ticket_vincenti_massimo", "mean"),
            tail_ratio_mean=("tail_ratio_p99_medio", "mean"),
            tail_spread_mean=("tail_spread_p99_p95", "mean"),
            compat_risk_score_mean=("compat_risk_score", "mean"),
            ticket_incompatibili_sum=("ticket_incompatibili", "sum"),
            ticket_esclusi_montecarlo_sum=("ticket_esclusi_montecarlo", "sum"),
            ticket_misti_sum=("ticket_misti", "sum"),
            ticket_non_mappati_sum=("ticket_non_mappati", "sum"),
            pct_non_mappati_mean=("pct_non_mappati", "mean"),
            pct_correlati_misti_mean=("pct_correlati_misti", "mean"),
        )
        .reset_index()
    )

    summary["risk_score_cluster"] = (
        summary["payout_p99_mean"] * 0.40 +
        summary["payout_p95_mean"] * 0.25 +
        summary["payout_massimo_mean"] * 0.20 +
        summary["tail_ratio_mean"] * 1000 * 0.10 +
        summary["ticket_vincenti_massimo_mean"] * 100 * 0.05 +
        summary["compat_risk_score_mean"] * 0.10
    )

    summary = summary.sort_values(
        by="risk_score_cluster",
        ascending=True
    ).reset_index(drop=True)

    labels_base = [
        "SAFE",
        "WATCH",
        "RISKY",
        "EXTREME",
    ]

    labels = labels_base[:len(summary)]

    cluster_label_map = dict(zip(summary["cluster"], labels))

    df["cluster_label"] = df["cluster"].map(cluster_label_map)
    summary["cluster_label"] = summary["cluster"].map(cluster_label_map)

    return df, summary


# =========================================================
# RISK SCORE COMMERCIALE
# =========================================================
def calcola_risk_score_commerciale(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["risk_score_montecarlo"] = (
        df["payout_p99"] * 0.40 +
        df["payout_p95"] * 0.25 +
        df["payout_massimo_osservato"] * 0.20 +
        df["tail_ratio_p99_medio"] * 1000 * 0.10 +
        df["ticket_vincenti_massimo"] * 100 * 0.05
    )

    df["risk_score_commerciale"] = (
        df["risk_score_montecarlo"] +
        df["compat_risk_score"]
    )

    df = df.sort_values(
        by=[
            "cluster_label",
            "risk_score_commerciale",
            "payout_p99",
            "payout_massimo_osservato",
        ],
        ascending=[
            True,
            False,
            False,
            False,
        ]
    ).reset_index(drop=True)

    return df


# =========================================================
# SALVATAGGIO
# =========================================================
def salva_output(df: pd.DataFrame, summary: pd.DataFrame) -> None:
    df.to_csv(
        OUT_CLUSTER,
        sep=";",
        index=False,
        encoding="utf-8-sig",
        decimal=","
    )

    summary.to_csv(
        OUT_SUMMARY,
        sep=";",
        index=False,
        encoding="utf-8-sig",
        decimal=","
    )

    print("\n✅ FILE CREATI:")
    print(OUT_CLUSTER)
    print(OUT_SUMMARY)


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    print("=" * 80)
    print("CLUSTER COMMERCIALI - RISCHIO MONTE CARLO + COMPATIBILITA")
    print(f"Versione script: {SCRIPT_VERSION}")
    print("=" * 80)
    print(f"Input Monte Carlo: {INPUT_FILE}")
    print(f"Input compatibilità: {INPUT_COMPATIBILITA}")
    print(f"Output cluster: {OUT_CLUSTER}")
    print(f"Output summary: {OUT_SUMMARY}")
    print("=" * 80)

    df = leggi_csv(INPUT_FILE)

    print(f"Righe lette: {len(df)}")
    print(f"Colonne trovate: {list(df.columns)}")

    if df.empty:
        print("⚠ File input vuoto")
        return

    required = {
        "concessionario",
        "nome_commerciale",
        "payout_medio",
        "payout_mediana",
        "payout_p90",
        "payout_p95",
        "payout_p99",
        "payout_massimo_osservato",
        "ticket_vincenti_medio",
        "ticket_vincenti_massimo",
    }

    if not required.issubset(df.columns):
        mancanti = sorted(required - set(df.columns))
        raise ValueError(f"Colonne mancanti nel file input: {mancanti}")

    df = aggiungi_compatibilita(df)
    df = normalizza_numeri(df)

    print("\nDistribuzione compatibilità aggregata nei commerciali:")
    print(f"Ticket incompatibili: {int(df['ticket_incompatibili'].sum())}")
    print(f"Ticket esclusi Monte Carlo: {int(df['ticket_esclusi_montecarlo'].sum())}")
    print(f"Ticket misti: {int(df['ticket_misti'].sum())}")
    print(f"Ticket non mappati: {int(df['ticket_non_mappati'].sum())}")

    df, X = prepara_feature(df)
    df = clusterizza(df, X)
    df, summary = assegna_label_cluster(df)
    df = calcola_risk_score_commerciale(df)

    salva_output(df, summary)

    print("\nDistribuzione cluster:")
    print(df["cluster_label"].value_counts().to_string())

    print("\nTop 10 commerciali per risk_score:")
    colonne_preview = [
        "concessionario",
        "nome_commerciale",
        "cluster_label",
        "risk_score_commerciale",
        "risk_score_montecarlo",
        "compat_risk_score",
        "payout_medio",
        "payout_p95",
        "payout_p99",
        "payout_massimo_osservato",
        "ticket_incompatibili",
        "ticket_esclusi_montecarlo",
        "ticket_misti",
        "ticket_non_mappati",
        "pct_non_mappati",
    ]

    print(df[colonne_preview].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
