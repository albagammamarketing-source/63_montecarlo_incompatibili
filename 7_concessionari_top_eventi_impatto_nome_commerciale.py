from __future__ import annotations

try:
    import pandas as pd
except ImportError:
    print("Installa pandas: pip install pandas")
    raise

import os
from pathlib import Path


# =========================================================
# CONFIGURAZIONE
# =========================================================
SCRIPT_VERSION = "7_top_eventi_con_compatibilita_v1"

PROJECT_DIR = Path(
    os.getenv("PIPELINE_PROJECT_PATH", str(Path(__file__).resolve().parent))
).resolve()

BASE_PATH = Path(
    os.getenv("PIPELINE_BASE_PATH", str(PROJECT_DIR / ".runtime_output"))
).resolve()
BASE_PATH.mkdir(parents=True, exist_ok=True)
# Preferisce il file arricchito dallo script 3b.
INPUT_TICKET_COMPAT = BASE_PATH / "4b_concessionari_ticket_eventi_compatibilita.csv"
INPUT_TICKET_FALLBACK = BASE_PATH / "4_concessionari_ticket_eventi_allineato.csv"

OUT_TOP20_PER_CONCESSIONARIO = BASE_PATH / "16_top20_eventi_impatto_per_concessionario.csv"
OUT_TOP20_PER_NOME_COMM = BASE_PATH / "17_top20_eventi_impatto_per_nome_commerciale.csv"
OUT_EVENTI_COMPLETO = BASE_PATH / "18_eventi_impatto_completo.csv"

TOP_N = 20

# opzionale: filtri
CONCESSIONARIO = None       # es. "ADMIRAL"
NOME_COMMERCIALE = None     # es. "NOME PUNTO"


# =========================================================
# UTILS
# =========================================================
def scegli_input_ticket() -> Path:
    if INPUT_TICKET_COMPAT.exists():
        return INPUT_TICKET_COMPAT
    return INPUT_TICKET_FALLBACK


def leggi_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File non trovato: {path}")

    try:
        df = pd.read_csv(path, sep=";", dtype=str)
    except Exception:
        df = pd.read_csv(path, sep=None, engine="python", dtype=str)

    df.columns = (
        df.columns
        .str.replace("\ufeff", "", regex=False)
        .str.replace("ï»¿", "", regex=False)
        .str.strip()
        .str.lower()
    )

    return df.fillna("")


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


def scrivi_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(
        path,
        sep=";",
        index=False,
        encoding="utf-8-sig",
        decimal=",",
    )


def assicurati_colonna(df: pd.DataFrame, col: str, default: str = "") -> pd.DataFrame:
    if col not in df.columns:
        df[col] = default
    return df


# =========================================================
# LETTURA E PULIZIA
# =========================================================
def leggi_ticket() -> pd.DataFrame:
    input_ticket = scegli_input_ticket()
    df = leggi_csv(input_ticket)

    print(f"Lettura ticket da: {input_ticket}")
    if input_ticket == INPUT_TICKET_COMPAT:
        print("✅ Uso file con compatibilità esiti generato dallo script 3b")
    else:
        print("⚠ File compatibilità non trovato: uso fallback allineato senza flag compatibilità")

    print(f"Righe lette dal CSV originale: {len(df)}")
    print(f"Colonne trovate: {list(df.columns)}")

    required = {
        "concessionario",
        "id_ticket",
        "id_evento",
        "evento_descrizione",
        "quota_evento",
        "importo_pagato",
        "importo_vincita_potenziale",
    }

    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Colonne mancanti nel file input: {missing}")

    # Colonne storiche/di base.
    for col in [
        "nome_commerciale",
        "codice_fiscale",
        "cod_stato_esito",
        "des_stato",
        "des_sport",
        "des_manif",
        "des_avv",
        "des_scom",
        "des_eve",
        "des_vin",
        "match_key",
        "esito_key_matrice",
    ]:
        df = assicurati_colonna(df, col, "")

    # Colonne compatibilità: se si usa fallback vengono valorizzate in modo neutro.
    defaults_compat = {
        "compatibilita_ticket": "NON_DISPONIBILE",
        "flag_incompatibile": "0",
        "flag_correlato": "0",
        "flag_non_mappato": "0",
        "flag_escludi_montecarlo": "0",
        "mapping_esito": "NON_DISPONIBILE",
        "famiglia_matrice": "",
        "esito_matrice": "",
        "id_esito_matrice": "",
        "motivo_mapping": "",
        "motivo_compatibilita": "",
        "num_coppie_correlate": "0",
        "num_coppie_incompatibili": "0",
        "num_coppie_non_mappate": "0",
        "fattore_correzione_prob": "1",
    }
    for col, default in defaults_compat.items():
        df = assicurati_colonna(df, col, default)

    # Normalizzazione stringhe.
    str_cols = [
        "concessionario",
        "id_ticket",
        "id_evento",
        "nome_commerciale",
        "codice_fiscale",
        "evento_descrizione",
        "des_stato",
        "cod_stato_esito",
        "des_sport",
        "des_manif",
        "des_avv",
        "des_scom",
        "des_eve",
        "des_vin",
        "match_key",
        "esito_key_matrice",
        "compatibilita_ticket",
        "mapping_esito",
        "famiglia_matrice",
        "esito_matrice",
        "id_esito_matrice",
        "motivo_mapping",
        "motivo_compatibilita",
    ]
    for col in str_cols:
        df[col] = df[col].astype(str).str.strip()

    df["concessionario"] = df["concessionario"].str.upper()
    df["des_stato"] = df["des_stato"].str.upper()
    df["compatibilita_ticket"] = df["compatibilita_ticket"].str.upper()
    df["mapping_esito"] = df["mapping_esito"].str.upper()

    df["quota_evento"] = converti_numero_italiano(df["quota_evento"])
    df["importo_pagato"] = converti_numero_italiano(df["importo_pagato"])
    df["importo_vincita_potenziale"] = converti_numero_italiano(df["importo_vincita_potenziale"])

    for col in [
        "flag_incompatibile",
        "flag_correlato",
        "flag_non_mappato",
        "flag_escludi_montecarlo",
        "num_coppie_correlate",
        "num_coppie_incompatibili",
        "num_coppie_non_mappate",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["fattore_correzione_prob"] = pd.to_numeric(
        df["fattore_correzione_prob"], errors="coerce"
    ).fillna(1.0)

    filtro_conc = str(CONCESSIONARIO).strip().upper() if CONCESSIONARIO else ""
    filtro_nome = str(NOME_COMMERCIALE).strip() if NOME_COMMERCIALE else ""

    if filtro_conc:
        df = df[df["concessionario"] == filtro_conc].copy()

    if filtro_nome:
        df = df[df["nome_commerciale"] == filtro_nome].copy()

    df = df[
        (df["concessionario"] != "") &
        (df["id_ticket"] != "") &
        (df["id_evento"] != "") &
        (df["evento_descrizione"] != "") &
        (df["quota_evento"].notna()) &
        (df["quota_evento"] > 1)
    ].copy()

    if "ticket_key" not in df.columns:
        df["ticket_key"] = df["concessionario"] + "||" + df["id_ticket"]
    else:
        df["ticket_key"] = df["ticket_key"].astype(str).str.strip()
        df.loc[df["ticket_key"] == "", "ticket_key"] = (
            df["concessionario"] + "||" + df["id_ticket"]
        )

    print(f"Righe dopo filtri: {len(df)}")
    print(f"Ticket esclusi Monte Carlo presenti nel file: {df[['concessionario', 'id_ticket', 'flag_escludi_montecarlo']].drop_duplicates()['flag_escludi_montecarlo'].sum()}")

    if "compatibilita_ticket" in df.columns:
        print("\nDistribuzione compatibilita_ticket:")
        print(
            df[["concessionario", "id_ticket", "compatibilita_ticket"]]
            .drop_duplicates()
            ["compatibilita_ticket"]
            .value_counts(dropna=False)
            .to_string()
        )

    return df


# =========================================================
# CALCOLO IMPATTO EVENTO
# =========================================================
def calcola_impatto_eventi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Per evitare doppio conteggio dello stesso ticket sullo stesso evento.
    base = df.drop_duplicates(
        subset=["concessionario", "nome_commerciale", "id_evento", "ticket_key"]
    ).copy()

    # Probabilità implicita evento: utile per ordinare anche per rischio probabilistico.
    base["prob_implicita_evento"] = 1.0 / base["quota_evento"]

    group_cols = [
        "concessionario",
        "nome_commerciale",
        "id_evento",
        "evento_descrizione",
    ]

    # Conteggi compatibilità per evento. I flag sono a livello ticket, ma aggregati sull'evento
    # indicano quanta esposizione dell'evento ricade in ticket problematici/non mappati.
    out = (
        base.groupby(group_cols, dropna=False)
        .agg(
            quota_media=("quota_evento", "mean"),
            quota_min=("quota_evento", "min"),
            quota_max=("quota_evento", "max"),
            prob_implicita_media=("prob_implicita_evento", "mean"),
            num_ticket_coinvolti=("ticket_key", "nunique"),
            num_righe_evento=("ticket_key", "count"),
            importo_pagato_esposto=("importo_pagato", "sum"),
            payout_potenziale_esposto=("importo_vincita_potenziale", "sum"),
            payout_potenziale_massimo_ticket=("importo_vincita_potenziale", "max"),
            ticket_esclusi_montecarlo=("flag_escludi_montecarlo", "sum"),
            ticket_incompatibili=("compatibilita_ticket", lambda s: int((s == "INCOMPATIBILE").sum())),
            ticket_correlati=("compatibilita_ticket", lambda s: int((s == "CORRELATO").sum())),
            ticket_misti=("compatibilita_ticket", lambda s: int((s == "MISTO").sum())),
            ticket_non_mappati=("compatibilita_ticket", lambda s: int((s == "NON_MAPPATO").sum())),
            ticket_compatibili=("compatibilita_ticket", lambda s: int((s == "COMPATIBILE").sum())),
            righe_esito_mappato=("mapping_esito", lambda s: int((s == "MAPPATO").sum())),
            righe_esito_non_mappato=("mapping_esito", lambda s: int((s == "NON_MAPPATO").sum())),
            num_famiglie_matrice=("famiglia_matrice", lambda s: int(pd.Series([x for x in s if str(x).strip() != ""]).nunique())),
            num_esiti_matrice=("id_esito_matrice", lambda s: int(pd.Series([x for x in s if str(x).strip() != ""]).nunique())),
        )
        .reset_index()
    )

    # Esposizione dei soli ticket incompatibili/non mappati sull'evento.
    esposizioni = (
        base.assign(
            payout_incompatibile=base["importo_vincita_potenziale"] * (base["compatibilita_ticket"] == "INCOMPATIBILE").astype(int),
            payout_non_mappato=base["importo_vincita_potenziale"] * (base["compatibilita_ticket"] == "NON_MAPPATO").astype(int),
            payout_misto=base["importo_vincita_potenziale"] * (base["compatibilita_ticket"] == "MISTO").astype(int),
            payout_correlato=base["importo_vincita_potenziale"] * (base["compatibilita_ticket"] == "CORRELATO").astype(int),
        )
        .groupby(group_cols, dropna=False)
        .agg(
            payout_incompatibile=("payout_incompatibile", "sum"),
            payout_non_mappato=("payout_non_mappato", "sum"),
            payout_misto=("payout_misto", "sum"),
            payout_correlato=("payout_correlato", "sum"),
        )
        .reset_index()
    )

    out = out.merge(esposizioni, on=group_cols, how="left")

    # Indicatore sintetico: quanto può pesare l'evento nella distribuzione Monte Carlo.
    # Più payout potenziale e più probabilità implicita = più impatto atteso.
    out["impatto_atteso_stimato"] = (
        out["payout_potenziale_esposto"] * out["prob_implicita_media"]
    )

    # Indicatore operativo aggiuntivo: esposizione in ticket problematici/non mappati.
    out["impatto_compatibilita_stimato"] = (
        out["payout_incompatibile"] * 1.00 +
        out["payout_misto"] * 0.50 +
        out["payout_non_mappato"] * 0.20 +
        out["payout_correlato"] * 0.10
    )

    # Percentuali su evento.
    out["pct_ticket_esclusi_montecarlo"] = (
        out["ticket_esclusi_montecarlo"] / out["num_ticket_coinvolti"].replace(0, pd.NA) * 100
    ).fillna(0)
    out["pct_ticket_non_mappati"] = (
        out["ticket_non_mappati"] / out["num_ticket_coinvolti"].replace(0, pd.NA) * 100
    ).fillna(0)
    out["pct_righe_esito_non_mappato"] = (
        out["righe_esito_non_mappato"] /
        (out["righe_esito_mappato"] + out["righe_esito_non_mappato"]).replace(0, pd.NA) * 100
    ).fillna(0)

    # Peso relativo all'interno del nome commerciale.
    tot_nome = (
        out.groupby(["concessionario", "nome_commerciale"], dropna=False)["payout_potenziale_esposto"]
        .transform("sum")
    )
    out["peso_pct_su_nome_commerciale"] = (
        out["payout_potenziale_esposto"] / tot_nome.replace(0, pd.NA) * 100
    )

    # Peso relativo all'interno del concessionario.
    tot_conc = (
        out.groupby(["concessionario"], dropna=False)["payout_potenziale_esposto"]
        .transform("sum")
    )
    out["peso_pct_su_concessionario"] = (
        out["payout_potenziale_esposto"] / tot_conc.replace(0, pd.NA) * 100
    )

    numeric_cols = [
        "quota_media",
        "quota_min",
        "quota_max",
        "prob_implicita_media",
        "importo_pagato_esposto",
        "payout_potenziale_esposto",
        "payout_potenziale_massimo_ticket",
        "impatto_atteso_stimato",
        "impatto_compatibilita_stimato",
        "peso_pct_su_nome_commerciale",
        "peso_pct_su_concessionario",
        "pct_ticket_esclusi_montecarlo",
        "pct_ticket_non_mappati",
        "pct_righe_esito_non_mappato",
        "payout_incompatibile",
        "payout_non_mappato",
        "payout_misto",
        "payout_correlato",
    ]

    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).round(6)

    out = out.sort_values(
        by=[
            "concessionario",
            "nome_commerciale",
            "payout_potenziale_esposto",
            "impatto_atteso_stimato",
            "impatto_compatibilita_stimato",
            "num_ticket_coinvolti",
        ],
        ascending=[True, True, False, False, False, False],
    ).reset_index(drop=True)

    return out


def crea_top20_per_concessionario(eventi: pd.DataFrame) -> pd.DataFrame:
    return (
        eventi.sort_values(
            by=[
                "concessionario",
                "payout_potenziale_esposto",
                "impatto_atteso_stimato",
                "impatto_compatibilita_stimato",
            ],
            ascending=[True, False, False, False],
        )
        .groupby("concessionario", dropna=False)
        .head(TOP_N)
        .reset_index(drop=True)
    )


def crea_top20_per_nome_commerciale(eventi: pd.DataFrame) -> pd.DataFrame:
    return (
        eventi.sort_values(
            by=[
                "concessionario",
                "nome_commerciale",
                "payout_potenziale_esposto",
                "impatto_atteso_stimato",
                "impatto_compatibilita_stimato",
            ],
            ascending=[True, True, False, False, False],
        )
        .groupby(["concessionario", "nome_commerciale"], dropna=False)
        .head(TOP_N)
        .reset_index(drop=True)
    )


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    filtro_nome = (
        "TUTTI"
        if NOME_COMMERCIALE is None or str(NOME_COMMERCIALE).strip() == ""
        else str(NOME_COMMERCIALE).strip()
    )
    filtro_conc = (
        "TUTTI"
        if CONCESSIONARIO is None or str(CONCESSIONARIO).strip() == ""
        else str(CONCESSIONARIO).strip().upper()
    )

    print("=" * 80)
    print("ANALISI TOP EVENTI IMPATTO - CON COMPATIBILITA ESITI")
    print(f"Versione script: {SCRIPT_VERSION}")
    print("=" * 80)
    print(f"Base path: {BASE_PATH}")
    print(f"Input preferito: {INPUT_TICKET_COMPAT}")
    print(f"Fallback: {INPUT_TICKET_FALLBACK}")
    print(f"Filtro concessionario: {filtro_conc}")
    print(f"Filtro nome_commerciale: {filtro_nome}")
    print("=" * 80)

    df = leggi_ticket()

    if df.empty:
        print("⚠ Nessun dato valido trovato nel file ticket")
        return

    print(f"\nRighe ticket-evento lette: {len(df)}")
    print(f"Ticket unici: {df[['concessionario', 'id_ticket']].drop_duplicates().shape[0]}")
    print(f"Eventi unici: {df[['concessionario', 'id_evento']].drop_duplicates().shape[0]}")

    eventi = calcola_impatto_eventi(df)
    top20_conc = crea_top20_per_concessionario(eventi)
    top20_nome = crea_top20_per_nome_commerciale(eventi)

    scrivi_csv(eventi, OUT_EVENTI_COMPLETO)
    scrivi_csv(top20_conc, OUT_TOP20_PER_CONCESSIONARIO)
    scrivi_csv(top20_nome, OUT_TOP20_PER_NOME_COMM)

    print("\n✅ FILE CREATI:")
    print(OUT_EVENTI_COMPLETO)
    print(OUT_TOP20_PER_CONCESSIONARIO)
    print(OUT_TOP20_PER_NOME_COMM)

    print(f"\nRighe eventi complete: {len(eventi)}")
    print(f"Righe top20 concessionario: {len(top20_conc)}")
    print(f"Righe top20 nome_commerciale: {len(top20_nome)}")

    if not top20_conc.empty:
        print("\nPrimi 10 eventi più impattanti per payout potenziale esposto:")
        cols = [
            "concessionario",
            "id_evento",
            "evento_descrizione",
            "quota_media",
            "num_ticket_coinvolti",
            "payout_potenziale_esposto",
            "impatto_atteso_stimato",
            "ticket_esclusi_montecarlo",
            "ticket_incompatibili",
            "ticket_non_mappati",
            "pct_righe_esito_non_mappato",
        ]
        print(top20_conc[cols].head(10).to_string(index=False))

    print("\nRiepilogo compatibilità su eventi:")
    print(f"Eventi con almeno 1 ticket incompatibile: {int((eventi['ticket_incompatibili'] > 0).sum())}")
    print(f"Eventi con almeno 1 ticket escluso MC: {int((eventi['ticket_esclusi_montecarlo'] > 0).sum())}")
    print(f"Eventi con almeno 1 ticket non mappato: {int((eventi['ticket_non_mappati'] > 0).sum())}")


if __name__ == "__main__":
    main()
