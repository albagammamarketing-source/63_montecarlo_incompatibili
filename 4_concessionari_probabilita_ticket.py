from __future__ import annotations

try:
    import pandas as pd
except ImportError:
    print("Installa pandas")
    raise

import os
from pathlib import Path


# =========================================================
# PATH
# =========================================================
BASE_PATH = Path(
    os.getenv(
        "PIPELINE_BASE_PATH",
        r"G:\Il mio Drive\progetti phyton\63_montecarlo_incompatibilita"
    )
)

# Input preferito: file arricchito dallo script 3b.
# Se non esiste, lo script usa il file allineato standard.
FILE_TICKET_COMPAT = BASE_PATH / "4b_concessionari_ticket_eventi_compatibilita.csv"
FILE_TICKET_FALLBACK = BASE_PATH / "4_concessionari_ticket_eventi_allineato.csv"

OUT_TICKET_PROB = BASE_PATH / "9_concessionari_ticket_probabilistico.csv"
OUT_RIEPILOGO_COMM = BASE_PATH / "10_concessionari_riepilogo_probabilistico_per_nome_commerciale.csv"
OUT_TOP_TICKET = BASE_PATH / "14_concessionari_top_ticket_rischio.csv"

SCRIPT_VERSION = "4_probabilistico_con_compatibilita_v1"


# =========================================================
# PARAMETRI
# =========================================================
NOME_COMMERCIALE = None
CONCESSIONARIO = None
TOP_N = 100

# Se True, i ticket con flag_escludi_montecarlo=1 vengono esclusi anche
# dall'analisi probabilistica: probabilita_ticket_implicita=0 e valore_atteso=0.
ESCLUDI_TICKET_INCOMPATIBILI = True


# =========================================================
# UTILS
# =========================================================
def scegli_file_input() -> Path:
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


def converti_intero(series: pd.Series, default: int = 0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default).astype(int)


def scrivi_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(
        path,
        sep=";",
        index=False,
        encoding="utf-8-sig",
        decimal=",",
        header=True
    )


def prima_stringa(g: pd.DataFrame, col: str, default: str = "") -> str:
    if col not in g.columns:
        return default
    vals = g[col].fillna("").astype(str).str.strip()
    if vals.empty:
        return default
    return vals.iloc[0]


def prima_numerica(g: pd.DataFrame, col: str, default: float = 0.0) -> float:
    if col not in g.columns:
        return default
    vals = pd.to_numeric(g[col], errors="coerce").dropna()
    if vals.empty:
        return default
    return float(vals.iloc[0])


# =========================================================
# LETTURA DATI
# =========================================================
def leggi_ticket() -> pd.DataFrame:
    file_ticket = scegli_file_input()
    df = leggi_csv(file_ticket)

    print(f"Lettura ticket da: {file_ticket}")
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

    # Colonne base opzionali.
    for col in [
        "nome_commerciale",
        "codice_fiscale",
        "des_sport",
        "des_manif",
        "des_avv",
        "des_scom",
        "des_eve",
        "des_vin",
        "match_key",
        "esito_key_matrice",
        "compatibilita_ticket",
        "motivo_compatibilita",
    ]:
        if col not in df.columns:
            df[col] = ""

    # Colonne operative compatibilità. Se il file 4b non è stato ancora creato,
    # vengono valorizzate a default per mantenere retrocompatibilità.
    compat_defaults = {
        "flag_incompatibile": 0,
        "flag_correlato": 0,
        "flag_non_mappato": 0,
        "flag_escludi_montecarlo": 0,
        "num_match_controllati": 0,
        "num_esiti_non_mappati": 0,
        "num_coppie_totali": 0,
        "num_coppie_compatibili": 0,
        "num_coppie_correlate": 0,
        "num_coppie_incompatibili": 0,
        "num_coppie_non_mappate": 0,
    }

    for col, default in compat_defaults.items():
        if col not in df.columns:
            df[col] = default
        df[col] = converti_intero(df[col], default=default)

    if "fattore_correzione_prob" not in df.columns:
        df["fattore_correzione_prob"] = 1.0
    df["fattore_correzione_prob"] = pd.to_numeric(
        df["fattore_correzione_prob"], errors="coerce"
    ).fillna(1.0)

    # Normalizzazione stringhe.
    for col in [
        "concessionario",
        "id_ticket",
        "nome_commerciale",
        "codice_fiscale",
        "evento_descrizione",
        "des_sport",
        "des_manif",
        "des_avv",
        "des_scom",
        "des_eve",
        "des_vin",
        "match_key",
        "esito_key_matrice",
        "compatibilita_ticket",
        "motivo_compatibilita",
    ]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["concessionario"] = df["concessionario"].str.upper()
    df["codice_fiscale"] = df["codice_fiscale"].str.upper()
    df["compatibilita_ticket"] = df["compatibilita_ticket"].str.upper()

    df["quota_evento"] = converti_numero_italiano(df["quota_evento"])
    df["importo_pagato"] = converti_numero_italiano(df["importo_pagato"])
    df["importo_vincita_potenziale"] = converti_numero_italiano(
        df["importo_vincita_potenziale"]
    )

    filtro_nome = str(NOME_COMMERCIALE).strip() if NOME_COMMERCIALE else ""
    filtro_conc = str(CONCESSIONARIO).strip().upper() if CONCESSIONARIO else ""

    if filtro_nome:
        df = df[df["nome_commerciale"] == filtro_nome].copy()

    if filtro_conc:
        df = df[df["concessionario"] == filtro_conc].copy()

    df = df[
        (df["id_ticket"] != "") &
        (df["concessionario"] != "") &
        (df["evento_descrizione"] != "")
    ].copy()

    print(f"Righe dopo filtro campi obbligatori: {len(df)}")

    df = df[
        df["quota_evento"].notna() &
        (df["quota_evento"] > 1)
    ].copy()

    print(f"Righe dopo filtro quota valida > 1: {len(df)}")

    if "flag_escludi_montecarlo" in df.columns:
        ticket_esclusi = (
            df[["concessionario", "id_ticket", "flag_escludi_montecarlo"]]
            .drop_duplicates(subset=["concessionario", "id_ticket"])
        )
        print(
            "Ticket esclusi da compatibilità: "
            f"{int((ticket_esclusi['flag_escludi_montecarlo'] == 1).sum())}"
        )

    return df


# =========================================================
# CALCOLI
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

    df["prob_evento_implicita"] = df["quota_evento"].apply(
        calcola_probabilita_evento
    )

    records = []

    gruppi = df.groupby(
        [
            "concessionario",
            "id_ticket",
        ],
        dropna=False
    )

    for (concessionario, id_ticket), g in gruppi:
        n_eventi_tot = len(g)

        nome_commerciale = prima_stringa(g, "nome_commerciale")
        codice_fiscale = prima_stringa(g, "codice_fiscale")
        compatibilita_ticket = prima_stringa(g, "compatibilita_ticket", "NON_CONTROLLATO")
        motivo_compatibilita = prima_stringa(g, "motivo_compatibilita")

        flag_incompatibile = int(prima_numerica(g, "flag_incompatibile", 0))
        flag_correlato = int(prima_numerica(g, "flag_correlato", 0))
        flag_non_mappato = int(prima_numerica(g, "flag_non_mappato", 0))
        flag_escludi_montecarlo = int(prima_numerica(g, "flag_escludi_montecarlo", 0))
        fattore_correzione_prob = float(prima_numerica(g, "fattore_correzione_prob", 1.0))

        num_match_controllati = int(prima_numerica(g, "num_match_controllati", 0))
        num_esiti_non_mappati = int(prima_numerica(g, "num_esiti_non_mappati", 0))
        num_coppie_totali = int(prima_numerica(g, "num_coppie_totali", 0))
        num_coppie_correlate = int(prima_numerica(g, "num_coppie_correlate", 0))
        num_coppie_incompatibili = int(prima_numerica(g, "num_coppie_incompatibili", 0))
        num_coppie_non_mappate = int(prima_numerica(g, "num_coppie_non_mappate", 0))

        importo_pagato = prima_numerica(g, "importo_pagato", 0.0)
        importo_vincita_potenziale = prima_numerica(g, "importo_vincita_potenziale", 0.0)

        quote = pd.to_numeric(g["quota_evento"], errors="coerce")
        n_quote_valide = int(quote.notna().sum())

        prob_eventi = pd.to_numeric(g["prob_evento_implicita"], errors="coerce")
        n_prob_valide = int(prob_eventi.notna().sum())

        if n_quote_valide == n_eventi_tot:
            quota_ticket_calcolata = float(quote.prod())
        else:
            quota_ticket_calcolata = 0.0

        if n_prob_valide == n_eventi_tot:
            probabilita_ticket_lorda = float(prob_eventi.prod())
        else:
            probabilita_ticket_lorda = 0.0

        ticket_escluso_probabilistico = (
            ESCLUDI_TICKET_INCOMPATIBILI and flag_escludi_montecarlo == 1
        )

        if ticket_escluso_probabilistico:
            probabilita_ticket_implicita = 0.0
            valore_atteso_ticket = 0.0
            vincita_calcolata = 0.0
            stato_probabilistico = "ESCLUSO_INCOMPATIBILE"
        else:
            probabilita_ticket_implicita = probabilita_ticket_lorda * fattore_correzione_prob
            probabilita_ticket_implicita = max(0.0, min(1.0, probabilita_ticket_implicita))
            vincita_calcolata = (
                float(importo_pagato * quota_ticket_calcolata)
                if quota_ticket_calcolata > 0
                else 0.0
            )
            valore_atteso_ticket = float(
                probabilita_ticket_implicita * importo_vincita_potenziale
            )
            stato_probabilistico = "CALCOLATO"

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
            "n_eventi_tot": int(n_eventi_tot),
            "n_quote_valide": int(n_quote_valide),
            "n_prob_valide": int(n_prob_valide),
            "num_match_controllati": num_match_controllati,
            "num_esiti_non_mappati": num_esiti_non_mappati,
            "num_coppie_totali": num_coppie_totali,
            "num_coppie_correlate": num_coppie_correlate,
            "num_coppie_incompatibili": num_coppie_incompatibili,
            "num_coppie_non_mappate": num_coppie_non_mappate,
            "fattore_correzione_prob": round(fattore_correzione_prob, 6),
            "quota_ticket_calcolata": round(quota_ticket_calcolata, 6),
            "probabilita_ticket_lorda": round(probabilita_ticket_lorda, 10),
            "probabilita_ticket_implicita": round(probabilita_ticket_implicita, 10),
            "importo_pagato": round(importo_pagato, 4),
            "importo_vincita_potenziale": round(importo_vincita_potenziale, 4),
            "vincita_calcolata": round(vincita_calcolata, 4),
            "valore_atteso_ticket": round(valore_atteso_ticket, 6),
        })

    out = pd.DataFrame(records)

    if out.empty:
        return pd.DataFrame(columns=[
            "concessionario",
            "id_ticket",
            "nome_commerciale",
            "codice_fiscale",
            "compatibilita_ticket",
            "flag_incompatibile",
            "flag_correlato",
            "flag_non_mappato",
            "flag_escludi_montecarlo",
            "stato_probabilistico",
            "motivo_compatibilita",
            "n_eventi_tot",
            "n_quote_valide",
            "n_prob_valide",
            "num_match_controllati",
            "num_esiti_non_mappati",
            "num_coppie_totali",
            "num_coppie_correlate",
            "num_coppie_incompatibili",
            "num_coppie_non_mappate",
            "fattore_correzione_prob",
            "quota_ticket_calcolata",
            "probabilita_ticket_lorda",
            "probabilita_ticket_implicita",
            "importo_pagato",
            "importo_vincita_potenziale",
            "vincita_calcolata",
            "valore_atteso_ticket",
        ])

    return out


def crea_riepilogo_per_nome_commerciale(ticket_prob: pd.DataFrame) -> pd.DataFrame:
    if ticket_prob.empty:
        return pd.DataFrame(columns=[
            "concessionario",
            "nome_commerciale",
            "num_ticket",
            "ticket_calcolati",
            "ticket_esclusi_incompatibili",
            "ticket_compatibili",
            "ticket_correlati",
            "ticket_misti",
            "ticket_non_mappati",
            "ticket_incompatibili",
            "somma_importo_pagato",
            "somma_importo_vincita_potenziale",
            "somma_vincita_calcolata",
            "somma_valore_atteso",
            "probabilita_ticket_media",
            "payout_potenziale_massimo",
            "valore_atteso_ticket_massimo",
        ])

    out = (
        ticket_prob.groupby(
            [
                "concessionario",
                "nome_commerciale",
            ],
            dropna=False
        )
        .agg(
            num_ticket=("id_ticket", "count"),
            ticket_calcolati=("stato_probabilistico", lambda s: int((s == "CALCOLATO").sum())),
            ticket_esclusi_incompatibili=("stato_probabilistico", lambda s: int((s == "ESCLUSO_INCOMPATIBILE").sum())),
            ticket_compatibili=("compatibilita_ticket", lambda s: int((s == "COMPATIBILE").sum())),
            ticket_correlati=("compatibilita_ticket", lambda s: int((s == "CORRELATO").sum())),
            ticket_misti=("compatibilita_ticket", lambda s: int((s == "MISTO").sum())),
            ticket_non_mappati=("compatibilita_ticket", lambda s: int((s == "NON_MAPPATO").sum())),
            ticket_incompatibili=("compatibilita_ticket", lambda s: int((s == "INCOMPATIBILE").sum())),
            somma_importo_pagato=("importo_pagato", "sum"),
            somma_importo_vincita_potenziale=("importo_vincita_potenziale", "sum"),
            somma_vincita_calcolata=("vincita_calcolata", "sum"),
            somma_valore_atteso=("valore_atteso_ticket", "sum"),
            probabilita_ticket_media=("probabilita_ticket_implicita", "mean"),
            payout_potenziale_massimo=("importo_vincita_potenziale", "max"),
            valore_atteso_ticket_massimo=("valore_atteso_ticket", "max"),
        )
        .reset_index()
    )

    colonne_numeriche = [
        "somma_importo_pagato",
        "somma_importo_vincita_potenziale",
        "somma_vincita_calcolata",
        "somma_valore_atteso",
        "probabilita_ticket_media",
        "payout_potenziale_massimo",
        "valore_atteso_ticket_massimo",
    ]

    for col in colonne_numeriche:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out["somma_importo_pagato"] = out["somma_importo_pagato"].round(4)
    out["somma_importo_vincita_potenziale"] = (
        out["somma_importo_vincita_potenziale"].round(4)
    )
    out["somma_vincita_calcolata"] = out["somma_vincita_calcolata"].round(4)
    out["somma_valore_atteso"] = out["somma_valore_atteso"].round(6)
    out["probabilita_ticket_media"] = out["probabilita_ticket_media"].round(10)
    out["payout_potenziale_massimo"] = out["payout_potenziale_massimo"].round(4)
    out["valore_atteso_ticket_massimo"] = (
        out["valore_atteso_ticket_massimo"].round(6)
    )

    out = out.sort_values(
        by=[
            "somma_valore_atteso",
            "somma_importo_vincita_potenziale",
            "num_ticket",
        ],
        ascending=False
    ).reset_index(drop=True)

    return out


def crea_top_ticket(
    ticket_prob: pd.DataFrame,
    top_n: int = 100
) -> pd.DataFrame:
    if ticket_prob.empty:
        return pd.DataFrame(columns=ticket_prob.columns)

    out = ticket_prob.sort_values(
        by=[
            "valore_atteso_ticket",
            "importo_vincita_potenziale",
            "probabilita_ticket_implicita",
        ],
        ascending=False
    ).head(top_n).reset_index(drop=True)

    return out


# =========================================================
# MAIN
# =========================================================
def main():
    filtro_nome = (
        "TUTTI"
        if NOME_COMMERCIALE is None or str(NOME_COMMERCIALE).strip() == ""
        else NOME_COMMERCIALE
    )

    filtro_conc = (
        "TUTTI"
        if CONCESSIONARIO is None or str(CONCESSIONARIO).strip() == ""
        else str(CONCESSIONARIO).strip().upper()
    )

    print("=" * 80)
    print("ANALISI PROBABILISTICA TICKET - CON COMPATIBILITA ESITI")
    print(f"Versione script: {SCRIPT_VERSION}")
    print("=" * 80)
    print(f"Filtro nome_commerciale: {filtro_nome}")
    print(f"Filtro concessionario: {filtro_conc}")
    print(f"Cartella base: {BASE_PATH}")
    print(f"Input preferito: {FILE_TICKET_COMPAT}")
    print(f"Fallback: {FILE_TICKET_FALLBACK}")
    print("=" * 80)

    df = leggi_ticket()

    if df.empty:
        print("⚠ Nessun ticket disponibile dopo il filtro")
        return

    print(f"Righe ticket-eventi lette: {len(df)}")
    print(
        "Ticket unici per concessionario: "
        f"{df[['concessionario', 'id_ticket']].drop_duplicates().shape[0]}"
    )

    ticket_prob = calcola_ticket_probabilistico(df)

    if ticket_prob.empty:
        print("⚠ Nessun ticket elaborato")
        return

    ticket_prob = ticket_prob.sort_values(
        by=[
            "valore_atteso_ticket",
            "importo_vincita_potenziale",
            "probabilita_ticket_implicita",
        ],
        ascending=False
    ).reset_index(drop=True)

    riepilogo_comm = crea_riepilogo_per_nome_commerciale(ticket_prob)
    top_ticket = crea_top_ticket(ticket_prob, TOP_N)

    scrivi_csv(ticket_prob, OUT_TICKET_PROB)
    scrivi_csv(riepilogo_comm, OUT_RIEPILOGO_COMM)
    scrivi_csv(top_ticket, OUT_TOP_TICKET)

    print("\n✅ FILE CREATI:")
    print(OUT_TICKET_PROB)
    print(OUT_RIEPILOGO_COMM)
    print(OUT_TOP_TICKET)

    print(f"\nTicket probabilistici: {len(ticket_prob)}")
    print(f"Commerciali in riepilogo: {len(riepilogo_comm)}")
    print(f"Top ticket salvati: {len(top_ticket)}")
    print(
        "Ticket esclusi per incompatibilità: "
        f"{int((ticket_prob['stato_probabilistico'] == 'ESCLUSO_INCOMPATIBILE').sum())}"
    )

    print("\nDistribuzione compatibilita_ticket:")
    print(ticket_prob["compatibilita_ticket"].value_counts(dropna=False).to_string())

    if not riepilogo_comm.empty:
        top = riepilogo_comm.iloc[0]

        print("\nTop nome_commerciale per somma_valore_atteso:")
        print(
            f"{top['concessionario']} | "
            f"{top['nome_commerciale']} | "
            f"somma_valore_atteso={top['somma_valore_atteso']} | "
            f"num_ticket={top['num_ticket']}"
        )

    if not top_ticket.empty:
        top_t = top_ticket.iloc[0]

        print("\nTicket più rischioso per valore atteso:")
        print(
            f"concessionario={top_t['concessionario']} | "
            f"id_ticket={top_t['id_ticket']} | "
            f"nome_commerciale={top_t['nome_commerciale']} | "
            f"compatibilita={top_t['compatibilita_ticket']} | "
            f"valore_atteso_ticket={top_t['valore_atteso_ticket']} | "
            f"importo_vincita_potenziale={top_t['importo_vincita_potenziale']}"
        )


if __name__ == "__main__":
    main()
