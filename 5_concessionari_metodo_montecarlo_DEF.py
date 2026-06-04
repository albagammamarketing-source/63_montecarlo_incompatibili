from __future__ import annotations

try:
    import pandas as pd
except ImportError:
    print("Installa pandas")
    raise

try:
    import numpy as np
except ImportError:
    print("Installa numpy")
    raise

import hashlib
import hmac
import os
from pathlib import Path
import re


# =========================================================
# VERSIONE
# =========================================================
SCRIPT_VERSION = "5_montecarlo_con_compatibilita_v2_eventi_medi_cf"


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
# Input preferito: file prodotto dallo script 3b.
FILE_TICKET_COMPAT = BASE_PATH / "4b_concessionari_ticket_eventi_compatibilita.csv"

# Fallback: file allineato prodotto dallo script 2.
FILE_TICKET_FALLBACK = BASE_PATH / "4_concessionari_ticket_eventi_allineato.csv"

OUT_TICKET_PROB = BASE_PATH / "9_concessionari_ticket_probabilistico.csv"
OUT_RIEPILOGO_COMM = BASE_PATH / "10_concessionari_riepilogo_probabilistico_per_nome_commerciale.csv"
OUT_SIM = BASE_PATH / "11_concessionari_montecarlo_simulazioni.csv"
OUT_STATS = BASE_PATH / "12_concessionari_montecarlo_statistiche.csv"
OUT_PER_CONC = BASE_PATH / "13_concessionari_montecarlo_per_concessionario.csv"
OUT_PER_COMM = BASE_PATH / "13_concessionari_montecarlo_per_nome_commerciale.csv"
OUT_PER_COMM_CF_PRIVATO = BASE_PATH / "13_concessionari_montecarlo_nomecommerciale_cf_PRIVATO.csv"
OUT_PER_COMM_CLIENTE_ID = BASE_PATH / "13_concessionari_montecarlo_nomecommerciale_cliente_id.csv"
OUT_TOP_TICKET = BASE_PATH / "14_concessionari_top_ticket_rischio.csv"
OUT_EVENTI = BASE_PATH / "15_concessionari_eventi_probabilita_drift.csv"
OUT_MC_TICKET_INFO = BASE_PATH / "15b_concessionari_montecarlo_ticket_info_compatibilita.csv"


# =========================================================
# PARAMETRI
# =========================================================
NOME_COMMERCIALE = None
CONCESSIONARIO = None
TOP_N = 100

N_SIM = 5000
SEED = 42

SOGLIE_PAYOUT = [10000, 25000, 50000, 100000]

DRIFT_POWER = 0.5
SHOCK_FACTOR = 1.10

PROB_MIN = 0.000001
PROB_MAX = 0.999999

# Se True, i ticket con flag_escludi_montecarlo=1 non possono vincere in nessuna iterazione.
ESCLUDI_INCOMPATIBILI_DA_MONTECARLO = True

# Il CF viene usato nel calcolo interno, ma non deve comparire negli output pubblici.
SALVA_OUTPUT_PRIVATO_CF = (
    os.getenv("PIPELINE_SAVE_PRIVATE_CF_OUTPUT", "false").strip().lower()
    in {"1", "true", "yes", "si"}
)

PSEUDONYM_SECRET = os.getenv("PIPELINE_PSEUDONYM_SECRET", "").strip()


# =========================================================
# UTILS
# =========================================================
def normalizza_descrizione(s):
    s = str(s).lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("amichevoli squadre nazionali", "amichevoli")
    s = re.sub(r"\s*\|\s*", "|", s)
    return s


def make_ticket_key(concessionario: str, id_ticket: str) -> str:
    return f"{concessionario}||{id_ticket}"


def make_event_key(concessionario: str, evento_descrizione_norm: str) -> str:
    return f"{concessionario}||{evento_descrizione_norm}"


def scegli_file_ticket() -> Path:
    if FILE_TICKET_COMPAT.exists():
        return FILE_TICKET_COMPAT
    return FILE_TICKET_FALLBACK


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


def normalizza_flag(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0).astype(int)


def scrivi_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(
        path,
        sep=";",
        index=False,
        encoding="utf-8-sig",
        decimal=",",
        header=True
    )


def parse_data_ora_vend(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()

    dt = pd.to_datetime(s, format="%Y%m%d %H:%M:%S", errors="coerce")

    mask = dt.isna()
    if mask.any():
        dt2 = pd.to_datetime(s[mask], errors="coerce", dayfirst=False)
        dt.loc[mask] = dt2

    return dt


def aggiungi_colonne_compatibilita_default(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    default_text = {
        "compatibilita_ticket": "NON_CONTROLLATO",
        "motivo_compatibilita": "file compatibilita non disponibile o colonne assenti",
        "mapping_esito": "NON_CONTROLLATO",
        "famiglia_matrice": "",
        "esito_matrice": "",
        "id_esito_matrice": "",
        "motivo_mapping": "",
    }

    default_num = {
        "flag_incompatibile": 0,
        "flag_correlato": 0,
        "flag_non_mappato": 0,
        "flag_escludi_montecarlo": 0,
        "num_match_controllati": 0,
        "num_esiti_ticket": 0,
        "num_esiti_non_mappati": 0,
        "num_coppie_totali": 0,
        "num_coppie_compatibili": 0,
        "num_coppie_correlate": 0,
        "num_coppie_incompatibili": 0,
        "num_coppie_non_mappate": 0,
        "fattore_correzione_prob": 1.0,
    }

    for col, value in default_text.items():
        if col not in df.columns:
            df[col] = value
        df[col] = df[col].fillna("").astype(str).str.strip()
        if col == "compatibilita_ticket":
            df[col] = df[col].replace("", "NON_CONTROLLATO")

    for col, value in default_num.items():
        if col not in df.columns:
            df[col] = value
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(value)

    for col in ["flag_incompatibile", "flag_correlato", "flag_non_mappato", "flag_escludi_montecarlo"]:
        df[col] = normalizza_flag(df[col])

    df["fattore_correzione_prob"] = pd.to_numeric(
        df["fattore_correzione_prob"], errors="coerce"
    ).fillna(1.0).clip(lower=0.0, upper=1.0)

    return df


# =========================================================
# LETTURA DATI
# =========================================================
def leggi_ticket() -> pd.DataFrame:
    file_ticket = scegli_file_ticket()

    print(f"Lettura ticket da: {file_ticket}")

    if file_ticket == FILE_TICKET_COMPAT:
        print("✅ Uso file con compatibilità esiti generato dallo script 3b")
    else:
        print("⚠ Uso fallback senza compatibilità esiti: esegui prima lo script 3b")

    df = leggi_csv(file_ticket)

    print(f"Righe lette dal CSV originale: {len(df)}")
    print(f"Colonne trovate: {list(df.columns)}")

    required = {
        "concessionario",
        "id_ticket",
        "evento_descrizione",
        "quota_evento",
        "importo_pagato",
        "importo_vincita_potenziale",
    }

    if not required.issubset(df.columns):
        mancanti = sorted(required - set(df.columns))
        raise ValueError(f"Colonne mancanti nel file ticket: {mancanti}")

    if "nome_commerciale" not in df.columns:
        df["nome_commerciale"] = ""

    if "codice_fiscale" not in df.columns:
        if "cf" in df.columns:
            df["codice_fiscale"] = df["cf"]
        else:
            df["codice_fiscale"] = ""

    if "data_ora_vend" not in df.columns:
        df["data_ora_vend"] = ""

    df = aggiungi_colonne_compatibilita_default(df)

    df["concessionario"] = df["concessionario"].astype(str).str.strip().str.upper()
    df["id_ticket"] = df["id_ticket"].astype(str).str.strip()
    df["nome_commerciale"] = df["nome_commerciale"].astype(str).str.strip()
    df["codice_fiscale"] = df["codice_fiscale"].astype(str).str.strip().str.upper()
    df["evento_descrizione"] = df["evento_descrizione"].astype(str).str.strip()
    df["data_ora_vend"] = df["data_ora_vend"].astype(str).str.strip()

    df["quota_evento"] = converti_numero_italiano(df["quota_evento"])
    df["importo_pagato"] = converti_numero_italiano(df["importo_pagato"])
    df["importo_vincita_potenziale"] = converti_numero_italiano(
        df["importo_vincita_potenziale"]
    )

    print("Quote valide:", df["quota_evento"].notna().sum())
    print("Quote > 1:", (df["quota_evento"] > 1).sum())
    print("Importi pagati validi:", df["importo_pagato"].notna().sum())
    print("Vincite potenziali valide:", df["importo_vincita_potenziale"].notna().sum())

    filtro_nome = str(NOME_COMMERCIALE).strip() if NOME_COMMERCIALE else ""
    filtro_conc = str(CONCESSIONARIO).strip().upper() if CONCESSIONARIO else ""

    if filtro_nome:
        df = df[df["nome_commerciale"] == filtro_nome].copy()

    if filtro_conc:
        df = df[df["concessionario"] == filtro_conc].copy()

    print(f"Righe dopo filtri nome/concessionario: {len(df)}")

    df = df[
        (df["id_ticket"] != "") &
        (df["concessionario"] != "") &
        (df["evento_descrizione"] != "")
    ].copy()

    print(f"Righe dopo filtro campi obbligatori: {len(df)}")

    df = df[df["quota_evento"].notna() & (df["quota_evento"] > 1)].copy()

    print(f"Righe dopo filtro quota valida > 1: {len(df)}")

    df["evento_descrizione_norm"] = df["evento_descrizione"].apply(normalizza_descrizione)
    df["data_ora_vend_dt"] = parse_data_ora_vend(df["data_ora_vend"])

    df["ticket_key"] = df.apply(
        lambda r: make_ticket_key(r["concessionario"], r["id_ticket"]),
        axis=1
    )

    df["event_key"] = df.apply(
        lambda r: make_event_key(r["concessionario"], r["evento_descrizione_norm"]),
        axis=1
    )

    print(f"Ticket esclusi da compatibilità: {df[['concessionario', 'id_ticket', 'flag_escludi_montecarlo']].drop_duplicates()['flag_escludi_montecarlo'].sum()}")

    if not df.empty:
        print("\nDistribuzione compatibilita_ticket:")
        print(
            df[["concessionario", "id_ticket", "compatibilita_ticket"]]
            .drop_duplicates()["compatibilita_ticket"]
            .value_counts(dropna=False)
            .to_string()
        )

    return df


# =========================================================
# PROBABILISTICO
# =========================================================
def calcola_probabilita_evento(quota_evento):
    if pd.isna(quota_evento):
        return pd.NA

    try:
        q = float(quota_evento)
    except Exception:
        return pd.NA

    if q <= 1:
        return pd.NA

    p = 1.0 / q
    return min(max(p, 0.0), 1.0)


def calcola_ticket_probabilistico(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["prob_evento_implicita"] = df["quota_evento"].apply(calcola_probabilita_evento)

    records = []

    gruppi = df.groupby(["concessionario", "id_ticket"], dropna=False)

    for (concessionario, id_ticket), g in gruppi:
        n_eventi_tot = len(g)
        nome_commerciale = g["nome_commerciale"].iloc[0]
        codice_fiscale = g["codice_fiscale"].iloc[0]

        compatibilita_ticket = str(g["compatibilita_ticket"].iloc[0]).strip()
        motivo_compatibilita = str(g["motivo_compatibilita"].iloc[0]).strip()
        flag_incompatibile = int(pd.to_numeric(g["flag_incompatibile"], errors="coerce").fillna(0).max())
        flag_correlato = int(pd.to_numeric(g["flag_correlato"], errors="coerce").fillna(0).max())
        flag_non_mappato = int(pd.to_numeric(g["flag_non_mappato"], errors="coerce").fillna(0).max())
        flag_escludi_montecarlo = int(pd.to_numeric(g["flag_escludi_montecarlo"], errors="coerce").fillna(0).max())
        fattore_correzione_prob = float(pd.to_numeric(g["fattore_correzione_prob"], errors="coerce").fillna(1.0).min())

        importo_pagato = pd.to_numeric(g["importo_pagato"], errors="coerce").dropna()
        importo_pagato = float(importo_pagato.iloc[0]) if not importo_pagato.empty else 0.0

        importo_vincita = pd.to_numeric(g["importo_vincita_potenziale"], errors="coerce").dropna()
        importo_vincita = float(importo_vincita.iloc[0]) if not importo_vincita.empty else 0.0

        quote = pd.to_numeric(g["quota_evento"], errors="coerce")
        prob_eventi = pd.to_numeric(g["prob_evento_implicita"], errors="coerce")

        quota_ticket = float(quote.prod()) if quote.notna().all() else 0.0
        prob_ticket_lorda = float(prob_eventi.prod()) if prob_eventi.notna().all() else 0.0

        if flag_escludi_montecarlo == 1:
            prob_ticket = 0.0
            stato_probabilistico = "ESCLUSO_INCOMPATIBILE"
        else:
            prob_ticket = prob_ticket_lorda * fattore_correzione_prob
            stato_probabilistico = "CALCOLATO"

        vincita_calc = importo_pagato * quota_ticket if quota_ticket > 0 else 0.0
        valore_atteso = prob_ticket * importo_vincita

        records.append({
            "concessionario": concessionario,
            "id_ticket": id_ticket,
            "nome_commerciale": nome_commerciale,
            "codice_fiscale": codice_fiscale,
            "compatibilita_ticket": compatibilita_ticket,
            "flag_incompatibile": flag_incompatibile,
            "flag_correlato": flag_correlato,
            "flag_non_mappato": flag_non_mappato,
            "flag_escludi_montecarlo": flag_escludi_montecarlo,
            "stato_probabilistico": stato_probabilistico,
            "motivo_compatibilita": motivo_compatibilita,
            "fattore_correzione_prob": round(fattore_correzione_prob, 6),
            "n_eventi_tot": int(n_eventi_tot),
            "num_coppie_correlate": int(pd.to_numeric(g["num_coppie_correlate"], errors="coerce").fillna(0).max()),
            "num_coppie_incompatibili": int(pd.to_numeric(g["num_coppie_incompatibili"], errors="coerce").fillna(0).max()),
            "num_coppie_non_mappate": int(pd.to_numeric(g["num_coppie_non_mappate"], errors="coerce").fillna(0).max()),
            "quota_ticket_calcolata": round(quota_ticket, 6),
            "probabilita_ticket_lorda": round(prob_ticket_lorda, 10),
            "probabilita_ticket_implicita": round(prob_ticket, 10),
            "importo_pagato": round(importo_pagato, 4),
            "importo_vincita_potenziale": round(importo_vincita, 4),
            "vincita_calcolata": round(vincita_calc, 4),
            "valore_atteso_ticket": round(valore_atteso, 6),
        })

    return pd.DataFrame(records)


def crea_riepilogo_per_nome_commerciale(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    return (
        df.groupby(["concessionario", "nome_commerciale"], dropna=False)
        .agg(
            num_ticket=("id_ticket", "count"),
            ticket_calcolati=("stato_probabilistico", lambda s: int((s == "CALCOLATO").sum())),
            ticket_esclusi_incompatibili=("flag_escludi_montecarlo", "sum"),
            ticket_compatibili=("compatibilita_ticket", lambda s: int((s == "COMPATIBILE").sum())),
            ticket_correlati=("compatibilita_ticket", lambda s: int((s == "CORRELATO").sum())),
            ticket_misti=("compatibilita_ticket", lambda s: int((s == "MISTO").sum())),
            ticket_non_mappati=("compatibilita_ticket", lambda s: int((s == "NON_MAPPATO").sum())),
            ticket_incompatibili=("compatibilita_ticket", lambda s: int((s == "INCOMPATIBILE").sum())),
            somma_importo_pagato=("importo_pagato", "sum"),
            somma_vincita_potenziale=("importo_vincita_potenziale", "sum"),
            somma_valore_atteso=("valore_atteso_ticket", "sum"),
        )
        .reset_index()
        .sort_values(by="somma_valore_atteso", ascending=False)
    )


def crea_top_ticket(df: pd.DataFrame, n: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    return df.sort_values(
        by=["valore_atteso_ticket", "importo_vincita_potenziale"],
        ascending=False
    ).head(n).reset_index(drop=True)


# =========================================================
# MONTE CARLO
# =========================================================
def quota_to_prob(quota_evento):
    if pd.isna(quota_evento):
        return pd.NA

    try:
        q = float(quota_evento)
    except Exception:
        return pd.NA

    if q <= 1:
        return pd.NA

    p = 1.0 / q
    return max(PROB_MIN, min(PROB_MAX, p))


def clamp_prob(p):
    if pd.isna(p):
        return pd.NA

    try:
        p = float(p)
    except Exception:
        return pd.NA

    return max(PROB_MIN, min(PROB_MAX, p))


def prepara_dati_mc(df: pd.DataFrame):
    df = df.copy()

    if df["data_ora_vend_dt"].notna().any():
        df = df.sort_values(
            by=["concessionario", "evento_descrizione_norm", "data_ora_vend_dt", "id_ticket"],
            ascending=[True, True, True, True]
        ).reset_index(drop=True)
    else:
        df = df.sort_values(
            by=["concessionario", "evento_descrizione_norm", "id_ticket"],
            ascending=[True, True, True]
        ).reset_index(drop=True)

    eventi = (
        df.groupby(["concessionario", "evento_descrizione_norm"], dropna=False)
        .agg(
            quota_evento_last=("quota_evento", "last"),
            quota_evento_max=("quota_evento", "max"),
            quota_evento_min=("quota_evento", "min"),
            quota_evento_media=("quota_evento", "mean"),
            num_righe=("ticket_key", "count"),
            ticket_unici=("ticket_key", pd.Series.nunique),
        )
        .reset_index()
    )

    eventi["event_key"] = eventi.apply(
        lambda r: make_event_key(r["concessionario"], r["evento_descrizione_norm"]),
        axis=1
    )

    eventi["prob_base_last"] = eventi["quota_evento_last"].apply(quota_to_prob)

    eventi["drift_ratio"] = np.where(
        eventi["quota_evento_last"] > 0,
        eventi["quota_evento_max"] / eventi["quota_evento_last"],
        np.nan
    )

    eventi["drift_ratio"] = pd.to_numeric(eventi["drift_ratio"], errors="coerce")
    eventi["drift_ratio"] = eventi["drift_ratio"].replace([np.inf, -np.inf], np.nan)
    eventi["drift_ratio"] = eventi["drift_ratio"].fillna(1.0)
    eventi["drift_ratio"] = eventi["drift_ratio"].clip(lower=0.5, upper=5.0)

    eventi["prob_con_drift"] = (
        pd.to_numeric(eventi["prob_base_last"], errors="coerce") *
        (eventi["drift_ratio"] ** DRIFT_POWER)
    )

    eventi["prob_finale"] = eventi["prob_con_drift"] * SHOCK_FACTOR
    eventi["prob_finale"] = eventi["prob_finale"].apply(clamp_prob)

    eventi = eventi[eventi["prob_finale"].notna()].copy()

    df = df.merge(
        eventi[["concessionario", "evento_descrizione_norm", "prob_finale", "event_key"]],
        on=["concessionario", "evento_descrizione_norm"],
        how="inner",
        suffixes=("", "_evento")
    ).copy()

    if "event_key_evento" in df.columns:
        df["event_key"] = df["event_key_evento"]
        df = df.drop(columns=["event_key_evento"])

    ticket_info = (
        df.groupby(["concessionario", "id_ticket", "ticket_key"], dropna=False)
        .agg(
            nome_commerciale=("nome_commerciale", "first"),
            codice_fiscale=("codice_fiscale", "first"),
            importo_pagato=("importo_pagato", "first"),
            importo_vincita_potenziale=("importo_vincita_potenziale", "first"),
            n_eventi=("event_key", "count"),
            compatibilita_ticket=("compatibilita_ticket", "first"),
            flag_incompatibile=("flag_incompatibile", "max"),
            flag_correlato=("flag_correlato", "max"),
            flag_non_mappato=("flag_non_mappato", "max"),
            flag_escludi_montecarlo=("flag_escludi_montecarlo", "max"),
            fattore_correzione_prob=("fattore_correzione_prob", "min"),
            motivo_compatibilita=("motivo_compatibilita", "first"),
        )
        .reset_index()
    )

    for col in ["flag_incompatibile", "flag_correlato", "flag_non_mappato", "flag_escludi_montecarlo"]:
        ticket_info[col] = normalizza_flag(ticket_info[col])

    ticket_info["fattore_correzione_prob"] = pd.to_numeric(
        ticket_info["fattore_correzione_prob"], errors="coerce"
    ).fillna(1.0).clip(lower=0.0, upper=1.0)

    ticket_eventi = (
        df.groupby("ticket_key", dropna=False)["event_key"]
        .apply(list)
        .to_dict()
    )

    evento_prob = dict(zip(eventi["event_key"], eventi["prob_finale"]))

    return eventi, ticket_info, ticket_eventi, evento_prob


def esegui_montecarlo(ticket_info, ticket_eventi, evento_prob):
    rng = np.random.default_rng(SEED)

    eventi_list = list(evento_prob.keys())
    prob_array = np.array([evento_prob[e] for e in eventi_list], dtype=float)

    ticket_keys = ticket_info["ticket_key"].tolist()
    concessionari = ticket_info["concessionario"].fillna("").astype(str).tolist()
    nomi_comm = ticket_info["nome_commerciale"].fillna("").astype(str).tolist()
    codici_fiscali = ticket_info["codice_fiscale"].fillna("").astype(str).tolist()
    compatibilita = ticket_info["compatibilita_ticket"].fillna("NON_CONTROLLATO").astype(str).tolist()

    payout_ticket = ticket_info["importo_vincita_potenziale"].fillna(0).astype(float).to_numpy()
    flag_escludi = ticket_info["flag_escludi_montecarlo"].fillna(0).astype(int).to_numpy()

    if not ESCLUDI_INCOMPATIBILI_DA_MONTECARLO:
        flag_escludi = np.zeros_like(flag_escludi)

    evento_to_idx = {e: i for i, e in enumerate(eventi_list)}

    ticket_event_idx = []
    for tkey in ticket_keys:
        evs = ticket_eventi.get(tkey, [])
        idxs = [evento_to_idx[e] for e in evs if e in evento_to_idx]
        ticket_event_idx.append(idxs)

    risultati = []
    risultati_conc = []
    risultati_comm = []
    risultati_comm_cf = []

    n_ticket_esclusi = int(flag_escludi.sum())

    for it in range(1, N_SIM + 1):
        esiti_evento = rng.random(len(eventi_list)) < prob_array

        ticket_vincenti_mask = np.array([
            bool(np.all(esiti_evento[idxs])) if len(idxs) > 0 else False
            for idxs in ticket_event_idx
        ])

        # Applicazione operativa del controllo compatibilità:
        # i ticket incompatibili non possono vincere in nessuna simulazione.
        ticket_vincenti_mask = ticket_vincenti_mask & (flag_escludi == 0)

        payout_vincenti = payout_ticket * ticket_vincenti_mask
        payout_totale = float(payout_vincenti.sum())
        num_ticket_vincenti = int(ticket_vincenti_mask.sum())

        risultati.append({
            "iterazione": it,
            "ticket_vincenti": num_ticket_vincenti,
            "ticket_esclusi_compatibilita": n_ticket_esclusi,
            "payout_totale": round(payout_totale, 6),
        })

        df_it = pd.DataFrame({
            "concessionario": concessionari,
            "nome_commerciale": nomi_comm,
            "codice_fiscale": codici_fiscali,
            "compatibilita_ticket": compatibilita,
            "flag_escludi_montecarlo": flag_escludi,
            "ticket_vincente": ticket_vincenti_mask.astype(int),
            "payout_ticket": payout_vincenti,
        })

        df_it_conc = (
            df_it.groupby("concessionario", dropna=False)
            .agg(
                ticket_vincenti=("ticket_vincente", "sum"),
                ticket_esclusi_compatibilita=("flag_escludi_montecarlo", "sum"),
                payout_totale=("payout_ticket", "sum"),
            )
            .reset_index()
        )
        df_it_conc.insert(0, "iterazione", it)
        risultati_conc.append(df_it_conc)

        df_it_comm = (
            df_it.groupby(["concessionario", "nome_commerciale"], dropna=False)
            .agg(
                ticket_vincenti=("ticket_vincente", "sum"),
                ticket_esclusi_compatibilita=("flag_escludi_montecarlo", "sum"),
                payout_totale=("payout_ticket", "sum"),
            )
            .reset_index()
        )
        df_it_comm.insert(0, "iterazione", it)
        risultati_comm.append(df_it_comm)

        df_it_comm_cf = (
            df_it.groupby(
                ["concessionario", "nome_commerciale", "codice_fiscale"],
                dropna=False
            )
            .agg(
                ticket_vincenti=("ticket_vincente", "sum"),
                ticket_esclusi_compatibilita=("flag_escludi_montecarlo", "sum"),
                payout_totale=("payout_ticket", "sum"),
            )
            .reset_index()
        )
        df_it_comm_cf.insert(0, "iterazione", it)
        risultati_comm_cf.append(df_it_comm_cf)

    df_sim = pd.DataFrame(risultati)
    df_sim_conc = pd.concat(risultati_conc, ignore_index=True) if risultati_conc else pd.DataFrame()
    df_sim_comm = pd.concat(risultati_comm, ignore_index=True) if risultati_comm else pd.DataFrame()
    df_sim_comm_cf = pd.concat(risultati_comm_cf, ignore_index=True) if risultati_comm_cf else pd.DataFrame()

    return df_sim, df_sim_conc, df_sim_comm, df_sim_comm_cf


def crea_statistiche_globali(df_sim: pd.DataFrame, eventi: pd.DataFrame, ticket_info: pd.DataFrame) -> pd.DataFrame:
    payout = pd.to_numeric(df_sim["payout_totale"], errors="coerce").fillna(0)
    ticket_vincenti = pd.to_numeric(df_sim["ticket_vincenti"], errors="coerce").fillna(0)

    compat_counts = ticket_info["compatibilita_ticket"].fillna("NON_CONTROLLATO").astype(str).value_counts().to_dict()

    stats = {
        "n_simulazioni": int(len(df_sim)),
        "n_eventi_modelizzati": int(len(eventi)),
        "n_ticket_modelizzati": int(len(ticket_info)),
        "n_ticket_esclusi_compatibilita": int(pd.to_numeric(ticket_info["flag_escludi_montecarlo"], errors="coerce").fillna(0).sum()),
        "ticket_compatibili": int(compat_counts.get("COMPATIBILE", 0)),
        "ticket_correlati": int(compat_counts.get("CORRELATO", 0)),
        "ticket_misti": int(compat_counts.get("MISTO", 0)),
        "ticket_non_mappati": int(compat_counts.get("NON_MAPPATO", 0)),
        "ticket_incompatibili": int(compat_counts.get("INCOMPATIBILE", 0)),
        "ticket_non_controllati": int(compat_counts.get("NON_CONTROLLATO", 0)),
        "drift_power": float(DRIFT_POWER),
        "shock_factor": float(SHOCK_FACTOR),
        "payout_medio": round(float(payout.mean()), 6),
        "payout_mediana": round(float(payout.median()), 6),
        "payout_p90": round(float(payout.quantile(0.90)), 6),
        "payout_p95": round(float(payout.quantile(0.95)), 6),
        "payout_p99": round(float(payout.quantile(0.99)), 6),
        "payout_massimo_osservato": round(float(payout.max()), 6),
        "ticket_vincenti_medio": round(float(ticket_vincenti.mean()), 6),
        "ticket_vincenti_p95": round(float(ticket_vincenti.quantile(0.95)), 6),
        "ticket_vincenti_massimo": round(float(ticket_vincenti.max()), 6),
        "prob_media_base_last": round(float(pd.to_numeric(eventi["prob_base_last"], errors="coerce").mean()), 6),
        "prob_media_finale": round(float(pd.to_numeric(eventi["prob_finale"], errors="coerce").mean()), 6),
        "drift_ratio_medio": round(float(pd.to_numeric(eventi["drift_ratio"], errors="coerce").mean()), 6),
        "drift_ratio_massimo": round(float(pd.to_numeric(eventi["drift_ratio"], errors="coerce").max()), 6),
    }

    for soglia in SOGLIE_PAYOUT:
        stats[f"prob_payout_supera_{int(soglia)}"] = round(float((payout > soglia).mean()), 6)

    return pd.DataFrame([stats])


def crea_statistiche_per_concessionario(df_sim_conc: pd.DataFrame) -> pd.DataFrame:
    if df_sim_conc.empty:
        return pd.DataFrame()

    out = (
        df_sim_conc.groupby("concessionario", dropna=False)
        .agg(
            payout_medio=("payout_totale", "mean"),
            payout_mediana=("payout_totale", "median"),
            payout_p90=("payout_totale", lambda s: s.quantile(0.90)),
            payout_p95=("payout_totale", lambda s: s.quantile(0.95)),
            payout_p99=("payout_totale", lambda s: s.quantile(0.99)),
            payout_massimo_osservato=("payout_totale", "max"),
            ticket_vincenti_medio=("ticket_vincenti", "mean"),
            ticket_vincenti_massimo=("ticket_vincenti", "max"),
            ticket_esclusi_compatibilita=("ticket_esclusi_compatibilita", "max"),
        )
        .reset_index()
    )

    return out.sort_values(
        by=["payout_p95", "payout_medio"],
        ascending=False
    ).reset_index(drop=True)


def crea_statistiche_per_commerciale(df_sim_comm: pd.DataFrame) -> pd.DataFrame:
    if df_sim_comm.empty:
        return pd.DataFrame()

    out = (
        df_sim_comm.groupby(["concessionario", "nome_commerciale"], dropna=False)
        .agg(
            payout_medio=("payout_totale", "mean"),
            payout_mediana=("payout_totale", "median"),
            payout_p90=("payout_totale", lambda s: s.quantile(0.90)),
            payout_p95=("payout_totale", lambda s: s.quantile(0.95)),
            payout_p99=("payout_totale", lambda s: s.quantile(0.99)),
            payout_massimo_osservato=("payout_totale", "max"),
            ticket_vincenti_medio=("ticket_vincenti", "mean"),
            ticket_vincenti_massimo=("ticket_vincenti", "max"),
            ticket_esclusi_compatibilita=("ticket_esclusi_compatibilita", "max"),
        )
        .reset_index()
    )

    return out.sort_values(
        by=["payout_p95", "payout_medio"],
        ascending=False
    ).reset_index(drop=True)


def crea_statistiche_per_nomecommerciale_cf(
    df_sim_comm_cf: pd.DataFrame,
    ticket_info: pd.DataFrame
) -> pd.DataFrame:
    """
    Crea il riepilogo Monte Carlo per nome_commerciale + codice_fiscale.

    La colonna eventi_medi_giocati_cf viene calcolata sui ticket del CF
    presenti nel perimetro della simulazione Monte Carlo (ticket_info),
    indipendentemente dall'esito vincente delle singole iterazioni.
    I ticket eventualmente esclusi dalla compatibilita restano identificabili
    tramite ticket_esclusi_compatibilita gia presente nell'output.
    """
    if df_sim_comm_cf.empty:
        return pd.DataFrame()

    out = (
        df_sim_comm_cf.groupby(
            ["concessionario", "nome_commerciale", "codice_fiscale"],
            dropna=False
        )
        .agg(
            payout_medio=("payout_totale", "mean"),
            payout_mediana=("payout_totale", "median"),
            payout_p90=("payout_totale", lambda s: s.quantile(0.90)),
            payout_p95=("payout_totale", lambda s: s.quantile(0.95)),
            payout_p99=("payout_totale", lambda s: s.quantile(0.99)),
            payout_massimo_osservato=("payout_totale", "max"),
            ticket_vincenti_medio=("ticket_vincenti", "mean"),
            ticket_vincenti_massimo=("ticket_vincenti", "max"),
            ticket_esclusi_compatibilita=("ticket_esclusi_compatibilita", "max"),
        )
        .reset_index()
    )

    # Numero medio di eventi giocati dal CF sui ticket inseriti nel perimetro MC.
    ticket_cf = ticket_info.copy()
    ticket_cf["n_eventi"] = pd.to_numeric(ticket_cf["n_eventi"], errors="coerce")

    eventi_medi_cf = (
        ticket_cf.groupby(
            ["concessionario", "nome_commerciale", "codice_fiscale"],
            dropna=False
        )
        .agg(
            eventi_medi_giocati_cf=("n_eventi", "mean"),
        )
        .reset_index()
    )

    eventi_medi_cf["eventi_medi_giocati_cf"] = (
        pd.to_numeric(eventi_medi_cf["eventi_medi_giocati_cf"], errors="coerce")
        .round(2)
    )

    out = out.merge(
        eventi_medi_cf,
        on=["concessionario", "nome_commerciale", "codice_fiscale"],
        how="left"
    )

    out["eventi_medi_giocati_cf"] = (
        pd.to_numeric(out["eventi_medi_giocati_cf"], errors="coerce")
        .fillna(0)
        .round(2)
    )

    return out.sort_values(
        by=["payout_p95", "payout_medio"],
        ascending=False
    ).reset_index(drop=True)



# =========================================================
# OUTPUT PUBBLICO CLIENTE PSEUDONIMIZZATO
# =========================================================
def genera_cliente_id(codice_fiscale: str) -> str:
    """Genera un identificativo stabile senza pubblicare il codice fiscale."""
    cf = str(codice_fiscale).strip().upper()
    if not cf:
        return ""

    if not PSEUDONYM_SECRET:
        raise EnvironmentError(
            "Manca PIPELINE_PSEUDONYM_SECRET: necessario per creare cliente_id."
        )

    digest = hmac.new(
        PSEUDONYM_SECRET.encode("utf-8"),
        cf.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:20].upper()

    return f"CL_{digest}"


def crea_output_pubblico_cliente_id(df_per_comm_cf: pd.DataFrame) -> pd.DataFrame:
    """Sostituisce il CF con cliente_id; questo è l'unico file cliente pubblicabile."""
    if df_per_comm_cf.empty:
        return pd.DataFrame()

    out = df_per_comm_cf.copy()
    out["cliente_id"] = out["codice_fiscale"].apply(genera_cliente_id)

    # Nessun codice fiscale nel CSV destinato alla pubblicazione.
    out = out.drop(columns=["codice_fiscale"], errors="ignore")

    prime = ["concessionario", "nome_commerciale", "cliente_id"]
    resto = [c for c in out.columns if c not in prime]
    return out[prime + resto]

# =========================================================
# MAIN
# =========================================================
def main():
    print("=" * 80)
    print("ANALISI PROBABILISTICA + MONTE CARLO - CON COMPATIBILITA ESITI")
    print(f"Versione script: {SCRIPT_VERSION}")
    print("=" * 80)
    print(f"Cartella base: {BASE_PATH}")
    print(f"Input preferito: {FILE_TICKET_COMPAT}")
    print(f"Fallback: {FILE_TICKET_FALLBACK}")
    print(f"Simulazioni: {N_SIM}")
    print("=" * 80)

    df = leggi_ticket()

    if df.empty:
        print("⚠ Nessun ticket disponibile dopo tutti i filtri.")
        print("Controlla soprattutto quota_evento, id_ticket, concessionario ed evento_descrizione.")
        return

    print(f"\nRighe ticket-eventi finali: {len(df)}")
    print(f"Ticket unici: {df[['concessionario', 'id_ticket']].drop_duplicates().shape[0]}")

    ticket_prob = calcola_ticket_probabilistico(df)

    if ticket_prob.empty:
        print("⚠ Nessun ticket elaborato")
        return

    riepilogo = crea_riepilogo_per_nome_commerciale(ticket_prob)
    top_ticket = crea_top_ticket(ticket_prob, TOP_N)

    scrivi_csv(ticket_prob, OUT_TICKET_PROB)
    scrivi_csv(riepilogo, OUT_RIEPILOGO_COMM)
    scrivi_csv(top_ticket, OUT_TOP_TICKET)

    eventi, ticket_info, ticket_eventi, evento_prob = prepara_dati_mc(df)

    if eventi.empty or ticket_info.empty or not evento_prob:
        print("⚠ Dati insufficienti per Monte Carlo")
        return

    print(f"\nTicket modelizzati Monte Carlo: {len(ticket_info)}")
    print(f"Ticket esclusi Monte Carlo per compatibilità: {int(ticket_info['flag_escludi_montecarlo'].sum())}")

    df_sim, df_sim_conc, df_sim_comm, df_sim_comm_cf = esegui_montecarlo(
        ticket_info,
        ticket_eventi,
        evento_prob
    )

    df_stats = crea_statistiche_globali(df_sim, eventi, ticket_info)
    df_per_conc = crea_statistiche_per_concessionario(df_sim_conc)
    df_per_comm = crea_statistiche_per_commerciale(df_sim_comm)
    df_per_comm_cf = crea_statistiche_per_nomecommerciale_cf(
        df_sim_comm_cf,
        ticket_info
    )
    df_per_comm_cliente_id = crea_output_pubblico_cliente_id(df_per_comm_cf)

    eventi_out = eventi.copy()

    for col in [
        "quota_evento_last",
        "quota_evento_max",
        "quota_evento_min",
        "quota_evento_media",
        "prob_base_last",
        "drift_ratio",
        "prob_con_drift",
        "prob_finale",
    ]:
        eventi_out[col] = pd.to_numeric(eventi_out[col], errors="coerce").round(6)

    ticket_info_out = ticket_info.copy()
    for col in ["importo_pagato", "importo_vincita_potenziale", "fattore_correzione_prob"]:
        ticket_info_out[col] = pd.to_numeric(ticket_info_out[col], errors="coerce").round(6)

    scrivi_csv(df_sim, OUT_SIM)
    scrivi_csv(df_stats, OUT_STATS)
    scrivi_csv(df_per_conc, OUT_PER_CONC)
    scrivi_csv(df_per_comm, OUT_PER_COMM)
    scrivi_csv(df_per_comm_cliente_id, OUT_PER_COMM_CLIENTE_ID)
    if SALVA_OUTPUT_PRIVATO_CF:
        scrivi_csv(df_per_comm_cf, OUT_PER_COMM_CF_PRIVATO)
    scrivi_csv(eventi_out, OUT_EVENTI)
    scrivi_csv(ticket_info_out, OUT_MC_TICKET_INFO)

    print("\n✅ FILE CREATI:")
    print(OUT_TICKET_PROB)
    print(OUT_RIEPILOGO_COMM)
    print(OUT_SIM)
    print(OUT_STATS)
    print(OUT_PER_CONC)
    print(OUT_PER_COMM)
    print(OUT_PER_COMM_CLIENTE_ID)
    if SALVA_OUTPUT_PRIVATO_CF:
        print(OUT_PER_COMM_CF_PRIVATO)
    print(OUT_TOP_TICKET)
    print(OUT_EVENTI)
    print(OUT_MC_TICKET_INFO)

    print(f"\nTicket probabilistici: {len(ticket_prob)}")
    print(f"Top ticket: {len(top_ticket)}")
    print(f"Simulazioni Monte Carlo: {len(df_sim)}")
    print(f"Righe per concessionario: {len(df_per_conc)}")
    print(f"Righe per nome commerciale: {len(df_per_comm)}")
    print(f"Righe per nome commerciale + cliente_id pubblico: {len(df_per_comm_cliente_id)}")
    print("Codice fiscale usato internamente e sostituito da cliente_id nell'output pubblico.")
    print(f"Ticket esclusi per incompatibilità: {int(ticket_info['flag_escludi_montecarlo'].sum())}")

    if not top_ticket.empty:
        top_t = top_ticket.iloc[0]
        print("\nTicket più rischioso per valore atteso:")
        print(
            f"concessionario={top_t['concessionario']} | "
            f"id_ticket={top_t['id_ticket']} | "
            f"nome_commerciale={top_t['nome_commerciale']} | "
            f"compatibilita={top_t.get('compatibilita_ticket', '')} | "
            f"valore_atteso_ticket={top_t['valore_atteso_ticket']} | "
            f"importo_vincita_potenziale={top_t['importo_vincita_potenziale']}"
        )


if __name__ == "__main__":
    main()
