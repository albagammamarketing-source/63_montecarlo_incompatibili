from __future__ import annotations

import os
import re
import unicodedata
from itertools import combinations
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError:
    print("Installa pandas: pip install pandas")
    raise

try:
    import openpyxl  # noqa: F401 - richiesto da pandas.read_excel
except ImportError:
    print("Installa openpyxl: pip install openpyxl")
    raise


# =========================================================
# PATH PROGETTO
# =========================================================
PROJECT_DIR = Path(
    os.getenv("PIPELINE_PROJECT_PATH", str(Path(__file__).resolve().parent))
).resolve()

BASE_PATH = Path(
    os.getenv("PIPELINE_BASE_PATH", str(PROJECT_DIR / ".runtime_output"))
).resolve()
BASE_PATH.mkdir(parents=True, exist_ok=True)
INPUT_TICKET = BASE_PATH / "4_concessionari_ticket_eventi_allineato.csv"
MATRIX_FILE = Path(
    os.getenv(
        "PIPELINE_MATRIX_FILE",
        str(PROJECT_DIR / "Matrice_Compatibilita_Esiti_Calcio_v1_0.xlsx"),
    )
).resolve()

OUT_TICKET_COMPAT = BASE_PATH / "4b_concessionari_ticket_eventi_compatibilita.csv"
OUT_INCOMPATIBILI = BASE_PATH / "16_concessionari_ticket_incompatibili.csv"
OUT_NON_MAPPATE = BASE_PATH / "17_concessionari_coppie_esiti_non_mappate.csv"
OUT_RIEPILOGO = BASE_PATH / "18_concessionari_riepilogo_compatibilita.csv"
OUT_DIAGNOSTICA = BASE_PATH / "19_concessionari_diagnostica_mapping_esiti.csv"

SCRIPT_VERSION = "3b_fix_matrice_header_v2"

# Se True, un ticket con almeno una coppia impossibile viene escluso dal Monte Carlo.
ESCLUDI_INCOMPATIBILI_DA_MONTECARLO = True


# =========================================================
# LETTURA / SCRITTURA
# =========================================================
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


def scrivi_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(
        path,
        sep=";",
        index=False,
        encoding="utf-8-sig",
        decimal=",",
    )


# =========================================================
# NORMALIZZAZIONI TESTUALI
# =========================================================
def pulisci_testo(value: Any) -> str:
    if value is None:
        return ""

    s = str(value).strip()
    if s.lower() in {"nan", "none", "nat"}:
        return ""

    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def norm_key(value: Any) -> str:
    s = pulisci_testo(value).lower()
    s = s.replace("/", " / ")
    s = re.sub(r"[^a-z0-9x<>+\-. /]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalizza_etichetta(value: Any) -> str:
    s = pulisci_testo(value)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# =========================================================
# MATRICE EXCEL
# =========================================================
def leggi_catalogo_esiti(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Matrice Excel non trovata: {path}")

    catalogo = pd.read_excel(path, sheet_name="Esiti_Catalogo", dtype=str).fillna("")
    catalogo.columns = catalogo.columns.str.strip()

    required = {"ID", "Famiglia", "Etichetta"}
    missing = sorted(required - set(catalogo.columns))
    if missing:
        raise ValueError(f"Foglio Esiti_Catalogo: colonne mancanti {missing}")

    catalogo["ID"] = catalogo["ID"].astype(str).str.strip()
    catalogo["Famiglia"] = catalogo["Famiglia"].astype(str).str.strip()
    catalogo["Etichetta"] = catalogo["Etichetta"].astype(str).str.strip()
    catalogo["family_key"] = catalogo["Famiglia"].apply(norm_key)
    catalogo["label_key"] = catalogo["Etichetta"].apply(norm_key)

    return catalogo


def leggi_matrice_relazioni(path: Path) -> tuple[dict[tuple[str, str], str], pd.DataFrame]:
    raw = pd.read_excel(path, sheet_name="Matrice_Relazioni", header=None, dtype=str).fillna("")

    # Struttura attesa del foglio Matrice_Relazioni:
    # riga 0: ID esiti in colonna, da colonna D in poi
    # riga 1: Famiglia esiti in colonna
    # riga 2: Etichetta esiti in colonna, con A:C = ID/Famiglia/Esito
    # righe successive: matrice relazioni.
    #
    # La versione precedente leggeva per errore la riga famiglie come ID colonna,
    # caricando solo ~348 relazioni invece di 57*57 = 3249.

    header_row = None

    for i in range(min(10, len(raw))):
        a = norm_key(raw.iloc[i, 0])
        b = norm_key(raw.iloc[i, 1]) if raw.shape[1] > 1 else ""
        c = norm_key(raw.iloc[i, 2]) if raw.shape[1] > 2 else ""

        if a == "id" and "famiglia" in b and c in {"esito", "etichetta"}:
            header_row = i
            break

    if header_row is None:
        raise ValueError(
            "Foglio Matrice_Relazioni: non trovo la riga header ID/Famiglia/Esito"
        )

    # Cerca sopra la riga header la riga che contiene gli ID colonna.
    candidate_rows = list(range(max(0, header_row - 3), header_row))

    best_row = None
    best_score = -1

    for r in candidate_rows:
        vals = [str(v).strip() for v in raw.iloc[r, 3:].tolist()]
        score = sum(bool(re.fullmatch(r"\d+", v)) for v in vals)

        if score > best_score:
            best_score = score
            best_row = r

    if best_row is None or best_score == 0:
        # fallback: se non ci sono ID numerici sopra, usa la riga header
        best_row = header_row

    col_ids = [str(v).strip() for v in raw.iloc[best_row, 3:].tolist()]

    relazioni: dict[tuple[str, str], str] = {}
    righe = []

    for i in range(header_row + 1, len(raw)):
        id_a = str(raw.iloc[i, 0]).strip()
        famiglia_a = str(raw.iloc[i, 1]).strip()
        esito_a = str(raw.iloc[i, 2]).strip()

        if not id_a or id_a.lower() == "nan":
            continue

        righe.append(
            {
                "ID": id_a,
                "Famiglia": famiglia_a,
                "Etichetta": esito_a,
            }
        )

        valori = raw.iloc[i, 3:].tolist()

        for id_b, relazione in zip(col_ids, valori):
            id_b = str(id_b).strip()
            relazione = str(relazione).strip()

            if not id_b or not relazione:
                continue

            relazioni[(id_a, id_b)] = relazione

    matrice_righe = pd.DataFrame(righe)

    return relazioni, matrice_righe


def costruisci_indici_catalogo(
    catalogo: pd.DataFrame,
) -> dict[tuple[str, str], dict[str, str]]:
    indice: dict[tuple[str, str], dict[str, str]] = {}

    for _, r in catalogo.iterrows():
        key = (r["family_key"], r["label_key"])

        indice[key] = {
            "id_matrice": str(r["ID"]),
            "famiglia_matrice": str(r["Famiglia"]),
            "esito_matrice": str(r["Etichetta"]),
        }

    return indice


# =========================================================
# MAPPING DB -> MATRICE
# =========================================================
def riconosci_famiglia(des_scom: str, des_eve: str, des_vin: str) -> str:
    testo = norm_key(f"{des_scom} {des_eve} {des_vin}")

    if any(
        x in testo
        for x in [
            "risultato esatto",
            "correct score",
            "score esatto",
        ]
    ):
        return "Risultato Esatto"

    if any(
        x in testo
        for x in [
            "parziale finale",
            "ht ft",
            "half time full time",
            "1 tempo finale",
            "primo tempo finale",
        ]
    ):
        return "HT/FT"

    if any(
        x in testo
        for x in [
            "doppia chance",
            "double chance",
        ]
    ):
        return "Doppia Chance"

    if any(
        x in testo
        for x in [
            "goal nogoal",
            "goal no goal",
            "goal / nogoal",
            "goal / no goal",
            "gg ng",
            "entrambe le squadre",
        ]
    ):
        return "Goal/NoGoal"

    if any(
        x in testo
        for x in [
            "under over",
            "over under",
            "u o gol",
            "totale gol",
            "tot gol",
        ]
    ):
        return "U/O Gol"

    # Se il testo contiene under/over con soglia, lo trattiamo come U/O Gol.
    if re.search(r"\b(under|over)\s*\d+(?:[\.,]\d+)?\b", testo):
        return "U/O Gol"

    # 1X2 / Esito finale
    if any(
        x in testo
        for x in [
            "1x2",
            "esito finale",
            "risultato finale",
            "vincente incontro",
            "vincente partita",
        ]
    ):
        return "1X2"

    return ""


def riconosci_etichetta(
    famiglia: str,
    des_scom: str,
    des_eve: str,
    des_vin: str,
) -> str:
    vin_raw = pulisci_testo(des_vin)
    s = norm_key(f"{des_vin} {des_eve} {des_scom}")
    famiglia_key = norm_key(famiglia)

    if famiglia_key == "1x2":
        # Preferisci des_vin quando contiene un esito secco.
        v = norm_key(vin_raw).upper().replace(" ", "")

        if v in {"1", "X", "2"}:
            return v

        if re.search(r"\b1\b", s) and not re.search(r"\b(1x|12)\b", s):
            return "1"

        if re.search(r"\bx\b", s):
            return "X"

        if re.search(r"\b2\b", s) and not re.search(r"\b(x2|12)\b", s):
            return "2"

    if famiglia_key == "doppia chance":
        compact = norm_key(vin_raw).upper().replace(" ", "")
        compact_all = norm_key(f"{des_vin} {des_eve}").upper().replace(" ", "")

        for label in ["1X", "X2", "12"]:
            if compact == label or label in compact_all:
                return label

    if famiglia_key in {"u / o gol", "u o gol"}:
        m = re.search(r"\b(under|over)\s*(\d+(?:[\.,]\d+)?)\b", s)

        if m:
            tipo = m.group(1).capitalize()
            soglia = m.group(2).replace(",", ".")

            if "." not in soglia:
                soglia = f"{soglia}.5"

            return f"{tipo} {soglia}"

    if famiglia_key in {"goal / nogoal", "goal nogoal"}:
        compact = norm_key(vin_raw).replace(" ", "")
        all_compact = s.replace(" ", "")

        if (
            any(x in compact for x in ["nogoal", "no-goal", "ng"])
            or "nogoal" in all_compact
            or "no/go" in all_compact
        ):
            return "NoGoal"

        if compact in {"goal", "gg", "si", "sì"} or re.search(r"\bgoal\b", s):
            return "Goal"

    if famiglia_key == "risultato esatto":
        m = re.search(r"\b([0-4])\s*[-:]\s*([0-4])\b", s)

        if m:
            return f"{m.group(1)}-{m.group(2)}"

        # Gestione esiti aggregati presenti nel catalogo.
        if "altro 1" in s or "altro casa" in s or "altro home" in s:
            return "Altro 1"

        if "altro x" in s or "altro pareggio" in s:
            return "Altro X"

        if "altro 2" in s or "altro trasferta" in s or "altro away" in s:
            return "Altro 2"

    if famiglia_key in {"ht / ft", "ht ft"}:
        compact = s.upper().replace(" ", "")
        m = re.search(r"([1X2])[/\-]([1X2])", compact)

        if m:
            return f"{m.group(1)}/{m.group(2)}"

    return ""


def mappa_esito(
    row: pd.Series,
    indice_catalogo: dict[tuple[str, str], dict[str, str]],
) -> dict[str, str]:
    des_scom = row.get("des_scom", "")
    des_eve = row.get("des_eve", "")
    des_vin = row.get("des_vin", "")

    famiglia = riconosci_famiglia(des_scom, des_eve, des_vin)
    etichetta = riconosci_etichetta(famiglia, des_scom, des_eve, des_vin) if famiglia else ""

    key = (norm_key(famiglia), norm_key(etichetta))
    found = indice_catalogo.get(key)

    if found:
        return {
            "famiglia_matrice": found["famiglia_matrice"],
            "esito_matrice": found["esito_matrice"],
            "id_esito_matrice": found["id_matrice"],
            "mapping_esito": "MAPPATO",
            "motivo_mapping": "",
        }

    if not famiglia:
        motivo = "famiglia non riconosciuta"
    elif not etichetta:
        motivo = f"etichetta non riconosciuta per famiglia {famiglia}"
    else:
        motivo = (
            f"coppia famiglia/esito non presente nel catalogo: "
            f"{famiglia} / {etichetta}"
        )

    return {
        "famiglia_matrice": famiglia,
        "esito_matrice": etichetta,
        "id_esito_matrice": "",
        "mapping_esito": "NON_MAPPATO",
        "motivo_mapping": motivo,
    }


# =========================================================
# COMPATIBILITA'
# =========================================================
def descrivi_esito(row: pd.Series) -> str:
    famiglia = row.get("famiglia_matrice", "") or row.get("des_scom", "")
    esito = row.get("esito_matrice", "") or row.get("des_vin", "") or row.get("des_eve", "")

    return f"{famiglia} = {esito}".strip(" =")


def tipo_da_relazione(rel: str) -> str:
    rel = str(rel).strip()

    if rel == "X":
        return "INCOMPATIBILE"

    if rel in {"<", ">", "="}:
        return "CORRELATO"

    if rel == "~":
        return "COMPATIBILE"

    return "NON_MAPPATO"


def valuta_ticket_match(
    g: pd.DataFrame,
    relazioni: dict[tuple[str, str], str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Valuta tutte le coppie di esiti nello stesso ticket e nello stesso match_key."""
    dettagli: list[dict[str, Any]] = []

    conteggi = {
        "num_coppie_totali": 0,
        "num_coppie_compatibili": 0,
        "num_coppie_correlate": 0,
        "num_coppie_incompatibili": 0,
        "num_coppie_non_mappate": 0,
    }

    # Evita doppioni perfetti della stessa riga evento/esito nello stesso ticket.
    subset_dedup = [
        c
        for c in [
            "id_evento",
            "des_scom",
            "des_eve",
            "des_vin",
            "id_esito_matrice",
        ]
        if c in g.columns
    ]

    gg = (
        g.drop_duplicates(subset=subset_dedup).reset_index(drop=True)
        if subset_dedup
        else g.reset_index(drop=True)
    )

    if len(gg) < 2:
        return dettagli, conteggi

    for i, j in combinations(range(len(gg)), 2):
        a = gg.iloc[i]
        b = gg.iloc[j]

        conteggi["num_coppie_totali"] += 1

        id_a = str(a.get("id_esito_matrice", "")).strip()
        id_b = str(b.get("id_esito_matrice", "")).strip()

        if not id_a or not id_b:
            rel = ""
            tipo = "NON_MAPPATO"
            motivo = "almeno uno dei due esiti non e' mappato nel catalogo matrice"
        else:
            rel = relazioni.get((id_a, id_b), "")
            tipo = tipo_da_relazione(rel)

            motivo = {
                "INCOMPATIBILE": "coppia impossibile secondo Matrice_Relazioni",
                "CORRELATO": "coppia correlata/inclusiva secondo Matrice_Relazioni",
                "COMPATIBILE": "coppia compatibile secondo Matrice_Relazioni",
                "NON_MAPPATO": "relazione non trovata in Matrice_Relazioni",
            }.get(tipo, "")

        if tipo == "INCOMPATIBILE":
            conteggi["num_coppie_incompatibili"] += 1
        elif tipo == "CORRELATO":
            conteggi["num_coppie_correlate"] += 1
        elif tipo == "COMPATIBILE":
            conteggi["num_coppie_compatibili"] += 1
        else:
            conteggi["num_coppie_non_mappate"] += 1

        dettagli.append(
            {
                "concessionario": a.get("concessionario", ""),
                "id_ticket": a.get("id_ticket", ""),
                "nome_commerciale": a.get("nome_commerciale", ""),
                "codice_fiscale": a.get("codice_fiscale", ""),
                "match_key": a.get("match_key", ""),
                "evento_descrizione_1": a.get("evento_descrizione", ""),
                "evento_descrizione_2": b.get("evento_descrizione", ""),
                "des_scom_1": a.get("des_scom", ""),
                "des_eve_1": a.get("des_eve", ""),
                "des_vin_1": a.get("des_vin", ""),
                "des_scom_2": b.get("des_scom", ""),
                "des_eve_2": b.get("des_eve", ""),
                "des_vin_2": b.get("des_vin", ""),
                "famiglia_matrice_1": a.get("famiglia_matrice", ""),
                "esito_matrice_1": a.get("esito_matrice", ""),
                "id_esito_matrice_1": id_a,
                "famiglia_matrice_2": b.get("famiglia_matrice", ""),
                "esito_matrice_2": b.get("esito_matrice", ""),
                "id_esito_matrice_2": id_b,
                "relazione_matrice": rel,
                "tipo_relazione": tipo,
                "motivo": motivo,
                "importo_pagato": a.get("importo_pagato", ""),
                "importo_vincita_potenziale": a.get("importo_vincita_potenziale", ""),
            }
        )

    return dettagli, conteggi


def classifica_ticket(row: pd.Series) -> str:
    if int(row.get("num_coppie_incompatibili", 0)) > 0:
        return "INCOMPATIBILE"

    non_mappate = int(row.get("num_coppie_non_mappate", 0))
    correlate = int(row.get("num_coppie_correlate", 0))
    esiti_non_mappati = int(row.get("num_esiti_non_mappati", 0))

    if (non_mappate > 0 or esiti_non_mappati > 0) and correlate > 0:
        return "MISTO"

    if non_mappate > 0 or esiti_non_mappati > 0:
        return "NON_MAPPATO"

    if correlate > 0:
        return "CORRELATO"

    return "COMPATIBILE"


def costruisci_motivo_ticket(row: pd.Series) -> str:
    stato = row.get("compatibilita_ticket", "")

    if stato == "INCOMPATIBILE":
        return f"presenti {int(row.get('num_coppie_incompatibili', 0))} coppie incompatibili"

    if stato == "MISTO":
        return "presenti coppie correlate e coppie/esiti non mappati"

    if stato == "NON_MAPPATO":
        return "presenti esiti o coppie non mappati nella matrice"

    if stato == "CORRELATO":
        return f"presenti {int(row.get('num_coppie_correlate', 0))} coppie correlate/inclusive"

    return "nessuna incompatibilita' rilevata"


def calcola_fattore_correzione(row: pd.Series) -> float:
    """
    Fattore operativo per il Monte Carlo.
    - Incompatibili: 0, il ticket va escluso.
    - Correlati/Misti: 1 per ora; il Monte Carlo potra' usare il flag per gestire gruppi dominanti.
    - Non mappati/compatibili: 1.
    """
    if row.get("compatibilita_ticket") == "INCOMPATIBILE":
        return 0.0

    return 1.0


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    print("=" * 80)
    print("CONTROLLO COMPATIBILITA' ESITI - MATRICE CALCIO")
    print(f"Versione script: {SCRIPT_VERSION}")
    print("=" * 80)
    print(f"Base path: {BASE_PATH}")
    print(f"Input ticket: {INPUT_TICKET}")
    print(f"Matrice Excel: {MATRIX_FILE}")
    print("=" * 80)

    BASE_PATH.mkdir(parents=True, exist_ok=True)

    ticket = leggi_csv(INPUT_TICKET)

    print(f"Righe ticket-eventi lette: {len(ticket)}")
    print(f"Colonne input: {list(ticket.columns)}")

    required = {
        "concessionario",
        "id_ticket",
        "nome_commerciale",
        "id_evento",
        "evento_descrizione",
        "des_scom",
        "des_eve",
        "des_vin",
        "match_key",
        "quota_evento",
        "importo_pagato",
        "importo_vincita_potenziale",
    }

    missing = sorted(required - set(ticket.columns))

    if missing:
        raise ValueError(f"Colonne mancanti nel file input: {missing}")

    for col in [
        "concessionario",
        "id_ticket",
        "nome_commerciale",
        "codice_fiscale",
        "id_evento",
        "evento_descrizione",
        "des_sport",
        "des_manif",
        "des_avv",
        "des_scom",
        "des_eve",
        "des_vin",
        "match_key",
        "esito_key_matrice",
    ]:
        if col not in ticket.columns:
            ticket[col] = ""

        ticket[col] = ticket[col].fillna("").astype(str).str.strip()

    if "ticket_key" not in ticket.columns:
        ticket["ticket_key"] = ticket["concessionario"] + "||" + ticket["id_ticket"]

    catalogo = leggi_catalogo_esiti(MATRIX_FILE)
    relazioni, _ = leggi_matrice_relazioni(MATRIX_FILE)
    indice_catalogo = costruisci_indici_catalogo(catalogo)

    print(f"Esiti catalogo matrice: {len(catalogo)}")
    print(f"Relazioni matrice caricate: {len(relazioni)}")

    # Mapping riga-esito verso ID matrice.
    mapped = ticket.apply(
        lambda r: mappa_esito(r, indice_catalogo),
        axis=1,
        result_type="expand",
    )

    ticket = pd.concat([ticket, mapped], axis=1)

    print("\nDistribuzione mapping esiti:")
    print(ticket["mapping_esito"].value_counts(dropna=False).to_string())

    # Valutazione ticket/match.
    dettagli_coppie: list[dict[str, Any]] = []
    records_ticket_match: list[dict[str, Any]] = []

    group_cols = ["concessionario", "id_ticket", "match_key"]

    for (concessionario, id_ticket, match_key), g in ticket.groupby(group_cols, dropna=False):
        dettagli, conteggi = valuta_ticket_match(g, relazioni)
        dettagli_coppie.extend(dettagli)

        num_esiti = int(len(g))
        num_esiti_non_mappati = int((g["mapping_esito"] == "NON_MAPPATO").sum())

        records_ticket_match.append(
            {
                "concessionario": concessionario,
                "id_ticket": id_ticket,
                "match_key": match_key,
                "num_esiti_match": num_esiti,
                "num_esiti_non_mappati": num_esiti_non_mappati,
                **conteggi,
            }
        )

    df_ticket_match = pd.DataFrame(records_ticket_match)

    # Aggregazione a livello ticket.
    agg_ticket = (
        df_ticket_match
        .groupby(["concessionario", "id_ticket"], dropna=False)
        .agg(
            num_match_controllati=("match_key", "nunique"),
            num_esiti_ticket=("num_esiti_match", "sum"),
            num_esiti_non_mappati=("num_esiti_non_mappati", "sum"),
            num_coppie_totali=("num_coppie_totali", "sum"),
            num_coppie_compatibili=("num_coppie_compatibili", "sum"),
            num_coppie_correlate=("num_coppie_correlate", "sum"),
            num_coppie_incompatibili=("num_coppie_incompatibili", "sum"),
            num_coppie_non_mappate=("num_coppie_non_mappate", "sum"),
        )
        .reset_index()
    )

    agg_ticket["compatibilita_ticket"] = agg_ticket.apply(classifica_ticket, axis=1)

    agg_ticket["flag_incompatibile"] = (
        agg_ticket["compatibilita_ticket"] == "INCOMPATIBILE"
    ).astype(int)

    agg_ticket["flag_correlato"] = (
        agg_ticket["compatibilita_ticket"].isin(["CORRELATO", "MISTO"])
    ).astype(int)

    agg_ticket["flag_non_mappato"] = (
        agg_ticket["compatibilita_ticket"].isin(["NON_MAPPATO", "MISTO"])
    ).astype(int)

    agg_ticket["flag_escludi_montecarlo"] = (
        (agg_ticket["flag_incompatibile"] == 1)
        & ESCLUDI_INCOMPATIBILI_DA_MONTECARLO
    ).astype(int)

    agg_ticket["motivo_compatibilita"] = agg_ticket.apply(
        costruisci_motivo_ticket,
        axis=1,
    )

    agg_ticket["fattore_correzione_prob"] = agg_ticket.apply(
        calcola_fattore_correzione,
        axis=1,
    )

    # Arricchimento del file principale righe ticket-evento.
    ticket_out = ticket.merge(
        agg_ticket,
        on=["concessionario", "id_ticket"],
        how="left",
    )

    # Dettagli coppie.
    df_coppie = pd.DataFrame(dettagli_coppie)

    if df_coppie.empty:
        df_coppie = pd.DataFrame(
            columns=[
                "concessionario",
                "id_ticket",
                "nome_commerciale",
                "codice_fiscale",
                "match_key",
                "evento_descrizione_1",
                "evento_descrizione_2",
                "des_scom_1",
                "des_eve_1",
                "des_vin_1",
                "des_scom_2",
                "des_eve_2",
                "des_vin_2",
                "famiglia_matrice_1",
                "esito_matrice_1",
                "id_esito_matrice_1",
                "famiglia_matrice_2",
                "esito_matrice_2",
                "id_esito_matrice_2",
                "relazione_matrice",
                "tipo_relazione",
                "motivo",
                "importo_pagato",
                "importo_vincita_potenziale",
            ]
        )

    df_incompatibili = df_coppie[df_coppie["tipo_relazione"] == "INCOMPATIBILE"].copy()
    df_non_mappate = df_coppie[df_coppie["tipo_relazione"] == "NON_MAPPATO"].copy()

    # Aggiungi anche gli esiti singoli non mappati,
    # utili quando un ticket non ha coppie nello stesso match.
    singoli_non_mappati = ticket[ticket["mapping_esito"] == "NON_MAPPATO"].copy()

    if not singoli_non_mappati.empty:
        singoli_out = singoli_non_mappati[
            [
                "concessionario",
                "id_ticket",
                "nome_commerciale",
                "codice_fiscale",
                "match_key",
                "evento_descrizione",
                "des_scom",
                "des_eve",
                "des_vin",
                "famiglia_matrice",
                "esito_matrice",
                "id_esito_matrice",
                "motivo_mapping",
                "importo_pagato",
                "importo_vincita_potenziale",
            ]
        ].copy()

        singoli_out = singoli_out.rename(
            columns={
                "evento_descrizione": "evento_descrizione_1",
                "des_scom": "des_scom_1",
                "des_eve": "des_eve_1",
                "des_vin": "des_vin_1",
                "famiglia_matrice": "famiglia_matrice_1",
                "esito_matrice": "esito_matrice_1",
                "id_esito_matrice": "id_esito_matrice_1",
                "motivo_mapping": "motivo",
            }
        )

        for col in [
            "evento_descrizione_2",
            "des_scom_2",
            "des_eve_2",
            "des_vin_2",
            "famiglia_matrice_2",
            "esito_matrice_2",
            "id_esito_matrice_2",
            "relazione_matrice",
        ]:
            singoli_out[col] = ""

        singoli_out["tipo_relazione"] = "NON_MAPPATO"

        df_non_mappate = pd.concat(
            [df_non_mappate, singoli_out],
            ignore_index=True,
            sort=False,
        )

    # Riepilogo per concessionario/nome commerciale a livello ticket.
    ticket_level_info = (
        ticket_out
        .sort_values(by=["concessionario", "id_ticket"])
        .drop_duplicates(subset=["concessionario", "id_ticket"])
        .copy()
    )

    # Numeri robusti per somme payout.
    for col in ["importo_pagato", "importo_vincita_potenziale"]:
        ticket_level_info[col] = pd.to_numeric(
            ticket_level_info[col]
            .astype(str)
            .str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False),
            errors="coerce",
        ).fillna(0)

    riepilogo = (
        ticket_level_info
        .groupby(["concessionario", "nome_commerciale"], dropna=False)
        .agg(
            num_ticket=("id_ticket", "count"),
            ticket_compatibili=(
                "compatibilita_ticket",
                lambda s: int((s == "COMPATIBILE").sum()),
            ),
            ticket_correlati=(
                "compatibilita_ticket",
                lambda s: int((s == "CORRELATO").sum()),
            ),
            ticket_misti=(
                "compatibilita_ticket",
                lambda s: int((s == "MISTO").sum()),
            ),
            ticket_non_mappati=(
                "compatibilita_ticket",
                lambda s: int((s == "NON_MAPPATO").sum()),
            ),
            ticket_incompatibili=(
                "compatibilita_ticket",
                lambda s: int((s == "INCOMPATIBILE").sum()),
            ),
            ticket_esclusi_montecarlo=("flag_escludi_montecarlo", "sum"),
            importo_pagato_totale=("importo_pagato", "sum"),
            payout_potenziale_totale=("importo_vincita_potenziale", "sum"),
        )
        .reset_index()
    )

    riepilogo["pct_incompatibili"] = (
        riepilogo["ticket_incompatibili"]
        / riepilogo["num_ticket"].replace(0, pd.NA)
        * 100
    ).fillna(0).round(4)

    riepilogo["pct_non_mappati"] = (
        riepilogo["ticket_non_mappati"]
        / riepilogo["num_ticket"].replace(0, pd.NA)
        * 100
    ).fillna(0).round(4)

    riepilogo["pct_correlati_misti"] = (
        (riepilogo["ticket_correlati"] + riepilogo["ticket_misti"])
        / riepilogo["num_ticket"].replace(0, pd.NA)
        * 100
    ).fillna(0).round(4)

    riepilogo = riepilogo.sort_values(
        by=[
            "ticket_incompatibili",
            "ticket_non_mappati",
            "payout_potenziale_totale",
        ],
        ascending=False,
    ).reset_index(drop=True)

    # Diagnostica mapping: utile per ridurre i NON_MAPPATO aggiornando la matrice/mapping.
    diagnostica = (
        ticket
        .groupby(
            [
                "des_scom",
                "des_eve",
                "des_vin",
                "famiglia_matrice",
                "esito_matrice",
                "mapping_esito",
                "motivo_mapping",
            ],
            dropna=False,
        )
        .agg(
            righe=("id_ticket", "count"),
            ticket_unici=("ticket_key", pd.Series.nunique),
            concessionari=(
                "concessionario",
                lambda s: ", ".join(sorted(set(map(str, s)))[:10]),
            ),
            esempio_evento_descrizione=("evento_descrizione", "first"),
        )
        .reset_index()
        .sort_values(
            by=["mapping_esito", "righe"],
            ascending=[False, False],
        )
    )

    # Salvataggi.
    scrivi_csv(ticket_out, OUT_TICKET_COMPAT)
    scrivi_csv(df_incompatibili, OUT_INCOMPATIBILI)
    scrivi_csv(df_non_mappate, OUT_NON_MAPPATE)
    scrivi_csv(riepilogo, OUT_RIEPILOGO)
    scrivi_csv(diagnostica, OUT_DIAGNOSTICA)

    print("\n✅ FILE CREATI:")
    print(OUT_TICKET_COMPAT)
    print(OUT_INCOMPATIBILI)
    print(OUT_NON_MAPPATE)
    print(OUT_RIEPILOGO)
    print(OUT_DIAGNOSTICA)

    print("\nDistribuzione compatibilita ticket:")
    print(agg_ticket["compatibilita_ticket"].value_counts(dropna=False).to_string())

    print("\nRiepilogo:")
    print(f"Ticket controllati: {len(agg_ticket)}")
    print(
        "Ticket incompatibili: "
        f"{int((agg_ticket['compatibilita_ticket'] == 'INCOMPATIBILE').sum())}"
    )
    print(f"Ticket esclusi Monte Carlo: {int(agg_ticket['flag_escludi_montecarlo'].sum())}")
    print(f"Coppie incompatibili: {len(df_incompatibili)}")
    print(f"Coppie/esiti non mappati: {len(df_non_mappate)}")

    print("=" * 80)
    print("Controllo compatibilita' completato.")
    print("=" * 80)


if __name__ == "__main__":
    main()
