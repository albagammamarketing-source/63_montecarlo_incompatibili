
from __future__ import annotations

try:
    import pandas as pd
except ImportError:
    print("Libreria mancante: pandas")
    raise

try:
    import pymysql
except ImportError:
    print("Libreria mancante: pymysql")
    raise

import json
import os
from pathlib import Path


# =========================================================
# CONFIGURAZIONE
# =========================================================
PROJECT_DIR = Path(
    os.getenv("PIPELINE_PROJECT_PATH", str(Path(__file__).resolve().parent))
).resolve()

BASE_PATH = Path(
    os.getenv("PIPELINE_BASE_PATH", str(PROJECT_DIR / ".runtime_output"))
).resolve()
BASE_PATH.mkdir(parents=True, exist_ok=True)
OUTPUT_ANAG_CSV = BASE_PATH / "1_concessionari_anagrafica_eventi.csv"
OUTPUT_TICKET_EVENTI_CSV = BASE_PATH / "2_concessionari_ticket_eventi.csv"

DB_PORT = int(os.getenv("PIPELINE_DB_PORT", "3306"))
DES_STATO = os.getenv("PIPELINE_DES_STATO", "VENDUTO").strip()
NOME_COMMERCIALE = os.getenv("PIPELINE_NOME_COMMERCIALE", "").strip() or None
GIORNI_BACK = int(os.getenv("PIPELINE_GIORNI_BACK", "120"))
DATA_DA = os.getenv("PIPELINE_DATA_DA", "").strip()
DATA_A = os.getenv("PIPELINE_DATA_A", "").strip()

# Il codice fiscale è necessario per l'analisi interna e la costruzione
# del cliente_id pubblico pseudonimizzato. Non viene pubblicato in chiaro.
INCLUDI_CODICE_FISCALE = (
    os.getenv("PIPELINE_INCLUDE_CF", "true").strip().lower()
    in {"1", "true", "yes", "si"}
)


def carica_config_db() -> dict:
    """Carica le connessioni DB esclusivamente da GitHub Secret/variabile ambiente.

    PIPELINE_DB_CONFIG_JSON deve essere un JSON del tipo:
    {"360BET": {"host": "...", "user": "...", "password": "...", "database": "..."}}
    """
    raw = os.getenv("PIPELINE_DB_CONFIG_JSON", "").strip()
    if not raw:
        raise EnvironmentError(
            "Manca PIPELINE_DB_CONFIG_JSON. Configurala come GitHub Actions Secret."
        )

    try:
        configs = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("PIPELINE_DB_CONFIG_JSON non è un JSON valido.") from exc

    if not isinstance(configs, dict) or not configs:
        raise ValueError("PIPELINE_DB_CONFIG_JSON deve contenere almeno un database.")

    campi_obbligatori = {"host", "user", "password", "database"}
    output = {}

    for concessionario, cfg in configs.items():
        nome = str(concessionario).strip().upper()
        if not nome or not isinstance(cfg, dict):
            raise ValueError("Configurazione concessionario non valida.")

        mancanti = sorted(campi_obbligatori - set(cfg))
        if mancanti:
            raise ValueError(f"Configurazione {nome}: campi mancanti {mancanti}.")

        output[nome] = {k: str(cfg[k]).strip() for k in campi_obbligatori}

    return output


DB_CONFIGS = carica_config_db()

ANAG_COLUMNS = [
    "concessionario",
    "id_evento",
    "des_sport",
    "des_manif",
    "des_avv",
    "des_scom",
    "des_eve",
    "des_vin",
    "evento_descrizione",
    "stato_evento_input",
]

TICKET_COLUMNS = [
    "concessionario",
    "id_ticket",
    "nome_commerciale",
    "codice_fiscale",
    "num_evento",
    "des_stato",
    "data_ora_vend",
    "id_evento",
    "evento_descrizione",
    # Campi necessari al controllo compatibilità esiti tramite matrice Excel
    "des_sport",
    "des_manif",
    "des_avv",
    "des_scom",
    "des_eve",
    "des_vin",
    "match_key",
    "esito_key_matrice",
    "quota_evento",
    "cod_stato_esito",
    "importo_pagato",
    "importo_vincita_potenziale",
]

STRING_COLUMNS = [
    "concessionario",
    "id_ticket",
    "nome_commerciale",
    "codice_fiscale",
    "des_stato",
    "num_evento",
    "data_ora_vend",
    "des_sport",
    "des_manif",
    "des_avv",
    "des_scom",
    "des_eve",
    "des_vin",
    "cod_stato_esito",
]


# =========================================================
# DB
# =========================================================
def esegui_query(concessionario: str, cfg: dict) -> pd.DataFrame:
    conn = pymysql.connect(
        host=cfg["host"],
        port=DB_PORT,
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )

    try:
        col_data = "STR_TO_DATE(tg.data_ora_vend, '%%Y%%m%%d %%H:%%i:%%s')"

        where_clauses = [
            "tg.des_stato = %s",
            "tg.data_ora_vend IS NOT NULL",
            "tg.data_ora_vend <> ''",
            f"{col_data} IS NOT NULL",
        ]
        params = [DES_STATO]

        data_da = str(DATA_DA).strip() if DATA_DA is not None else ""
        data_a = str(DATA_A).strip() if DATA_A is not None else ""

        if data_da and data_a and data_da > data_a:
            raise ValueError("DATA_DA non può essere maggiore di DATA_A")

        if data_da or data_a:
            if data_da:
                where_clauses.append(f"{col_data} >= %s")
                params.append(data_da + " 00:00:00")

            if data_a:
                where_clauses.append(f"{col_data} <= %s")
                params.append(data_a + " 23:59:59")
        else:
            where_clauses.append(f"{col_data} >= DATE_SUB(NOW(), INTERVAL %s DAY)")
            params.append(GIORNI_BACK)

        filtro_nome = str(NOME_COMMERCIALE).strip() if NOME_COMMERCIALE is not None else ""

        if filtro_nome:
            where_clauses.append("tg.nome_commerciale = %s")
            params.append(filtro_nome)

        where_sql = "\n              AND ".join(where_clauses)

        campo_codice_fiscale = (
            "tg.cf AS codice_fiscale,"
            if INCLUDI_CODICE_FISCALE
            else "'' AS codice_fiscale,"
        )
        ordine_codice_fiscale = ", tg.cf" if INCLUDI_CODICE_FISCALE else ""

        query = f"""
            SELECT
                %s AS concessionario,
                tg.id_ticket,
                tg.nome_commerciale,
                {campo_codice_fiscale}
                tg.des_stato,
                tg.data_ora_vend,
                tg.importo_pagato_eur,
                tg.importo_vincita_eur,
                td.num_evento,
                td.des_sport,
                td.des_manif,
                td.des_avv,
                td.des_scom,
                td.des_eve,
                td.des_vin,
                td.quota,
                td.cod_stato_esito
            FROM Ticket_General tg
            INNER JOIN Ticket_Detail td
                ON tg.id_ticket = td.id_ticket
            WHERE {where_sql}
            ORDER BY {col_data}, tg.nome_commerciale{ordine_codice_fiscale}, tg.id_ticket, td.num_evento
        """

        with conn.cursor() as cur:
            cur.execute(query, [concessionario] + params)
            rows = cur.fetchall()

        return pd.DataFrame(rows)

    finally:
        conn.close()


# =========================================================
# UTILS
# =========================================================
def normalizza_colonne_stringa(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col not in df.columns:
            df[col] = ""

        df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def normalizza_testo_chiave(series: pd.Series) -> pd.Series:
    """Normalizza testi usati nelle chiavi tecniche per matching/matrice."""
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
    )


def costruisci_evento_descrizione(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "des_sport",
        "des_manif",
        "des_avv",
        "des_scom",
        "des_eve",
        "des_vin",
    ]

    for col in cols:
        if col not in df.columns:
            df[col] = ""

        df[col] = df[col].fillna("").astype(str).str.strip()

    df["evento_descrizione"] = (
        df["des_sport"] + " | " +
        df["des_manif"] + " | " +
        df["des_avv"] + " | " +
        df["des_scom"] + " | " +
        df["des_eve"]
    )

    df["evento_descrizione"] = (
        df["evento_descrizione"]
        .str.replace(r"\s+", " ", regex=True)
        .str.replace(r"\s*\|\s*", " | ", regex=True)
        .str.strip(" |")
        .str.strip()
    )

    # Chiave partita/evento sportivo: serve al futuro script 3b per confrontare
    # solo esiti appartenenti alla stessa partita/evento reale.
    df["match_key"] = (
        normalizza_testo_chiave(df["concessionario"]) + "||" +
        normalizza_testo_chiave(df["des_sport"]) + "||" +
        normalizza_testo_chiave(df["des_manif"]) + "||" +
        normalizza_testo_chiave(df["des_avv"]) + "||" +
        normalizza_testo_chiave(df["des_eve"])
    )

    # Chiave esito per la matrice Excel: famiglia mercato + evento + valore esito.
    # Esempi: Risultato Esatto|1-0, U/O Gol|Under 2.5, Goal/NoGoal|NoGoal.
    df["esito_key_matrice"] = (
        normalizza_testo_chiave(df["des_scom"]) + "||" +
        normalizza_testo_chiave(df["des_eve"]) + "||" +
        normalizza_testo_chiave(df["des_vin"])
    )

    return df


def converti_valori_numerici(df: pd.DataFrame) -> pd.DataFrame:
    df["importo_pagato_eur"] = pd.to_numeric(df["importo_pagato_eur"], errors="coerce")
    df["importo_vincita_eur"] = pd.to_numeric(df["importo_vincita_eur"], errors="coerce")
    df["quota"] = pd.to_numeric(df["quota"], errors="coerce")

    df["importo_pagato"] = (df["importo_pagato_eur"] / 100.0).round(2)
    df["importo_vincita_potenziale"] = (df["importo_vincita_eur"] / 100.0).round(2)
    df["quota_evento"] = (df["quota"] / 100.0).round(3)

    return df


def scrivi_csv(df: pd.DataFrame, path_file: Path) -> None:
    df.to_csv(
        path_file,
        sep=";",
        index=False,
        encoding="utf-8-sig",
        header=True,
        decimal=",",
    )


def crea_output_vuoti() -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        pd.DataFrame(columns=ANAG_COLUMNS),
        pd.DataFrame(columns=TICKET_COLUMNS),
    )


# =========================================================
# COSTRUZIONE OUTPUT
# =========================================================
def costruisci_output(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return crea_output_vuoti()

    anag = (
        df[
            [
                "concessionario",
                "evento_descrizione",
                "des_sport",
                "des_manif",
                "des_avv",
                "des_scom",
                "des_eve",
                "des_vin",
            ]
        ]
        .drop_duplicates(subset=["concessionario", "evento_descrizione"])
        .sort_values(by=["concessionario", "evento_descrizione"])
        .reset_index(drop=True)
    )

    anag["id_evento"] = [f"E{i + 1}" for i in range(len(anag))]
    anag["stato_evento_input"] = ""

    anag_out = anag[
        [
            "concessionario",
            "id_evento",
            "des_sport",
            "des_manif",
            "des_avv",
            "des_scom",
            "des_eve",
            "des_vin",
            "evento_descrizione",
            "stato_evento_input",
        ]
    ].copy()

    anag_out = anag_out.reindex(columns=ANAG_COLUMNS)

    mappa_eventi = anag_out[
        [
            "concessionario",
            "evento_descrizione",
            "id_evento",
        ]
    ].copy()

    ticket = df.merge(
        mappa_eventi,
        on=["concessionario", "evento_descrizione"],
        how="left",
    )

    ticket_out = ticket[
        [
            "concessionario",
            "id_ticket",
            "nome_commerciale",
            "codice_fiscale",
            "num_evento",
            "des_stato",
            "data_ora_vend",
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
            "quota_evento",
            "cod_stato_esito",
            "importo_pagato",
            "importo_vincita_potenziale",
        ]
    ].copy()

    ticket_out = ticket_out.reindex(columns=TICKET_COLUMNS)

    ticket_out = ticket_out.sort_values(
        by=[
            "concessionario",
            "nome_commerciale",
            "codice_fiscale",
            "id_ticket",
            "num_evento",
        ]
    ).reset_index(drop=True)

    return anag_out, ticket_out


# =========================================================
# MAIN
# =========================================================
def main():
    filtro_nome = (
        "TUTTI"
        if NOME_COMMERCIALE is None or str(NOME_COMMERCIALE).strip() == ""
        else str(NOME_COMMERCIALE).strip()
    )

    print("Lettura dati multi-concessionario da DB...")
    print(f"Cartella base: {BASE_PATH}")

    data_da = str(DATA_DA).strip() if DATA_DA is not None else ""
    data_a = str(DATA_A).strip() if DATA_A is not None else ""

    if data_da or data_a:
        print(
            f"Filtro: nome_commerciale={filtro_nome} | "
            f"stato={DES_STATO} | "
            f"data_vend da {data_da or 'inizio'} a {data_a or 'fine'}"
        )
    else:
        print(
            f"Filtro: nome_commerciale={filtro_nome} | "
            f"stato={DES_STATO} | "
            f"ultimi {GIORNI_BACK} giorni"
        )

    frames = []

    for concessionario, cfg in DB_CONFIGS.items():
        print(f"Lettura dati da DB concessionario: {concessionario} ({cfg['database']})")

        try:
            df_part = esegui_query(concessionario, cfg)

            if df_part.empty:
                print(f"  -> {concessionario}: nessun dato trovato")
                continue

            print(f"  -> {concessionario}: righe lette {len(df_part)}")
            frames.append(df_part)

        except Exception as ex:
            print(f"  -> {concessionario}: ERRORE {ex}")

    if not frames:
        print("⚠ Nessun dato trovato su tutti i concessionari")

        anag_vuota, ticket_vuoto = crea_output_vuoti()
        scrivi_csv(anag_vuota, OUTPUT_ANAG_CSV)
        scrivi_csv(ticket_vuoto, OUTPUT_TICKET_EVENTI_CSV)

        return

    df = pd.concat(frames, ignore_index=True)

    df.columns = [str(c).strip() for c in df.columns]

    df = normalizza_colonne_stringa(df, STRING_COLUMNS)
    df = costruisci_evento_descrizione(df)
    df = converti_valori_numerici(df)

    df = df[
        (df["concessionario"] != "") &
        (df["id_ticket"] != "") &
        (df["evento_descrizione"] != "") &
        (df["data_ora_vend"] != "")
    ].copy()

    if df.empty:
        print("⚠ Nessuna riga valida dopo pulizia")

        anag_vuota, ticket_vuoto = crea_output_vuoti()
        scrivi_csv(anag_vuota, OUTPUT_ANAG_CSV)
        scrivi_csv(ticket_vuoto, OUTPUT_TICKET_EVENTI_CSV)

        return

    anag_out, ticket_out = costruisci_output(df)

    scrivi_csv(anag_out, OUTPUT_ANAG_CSV)
    scrivi_csv(ticket_out, OUTPUT_TICKET_EVENTI_CSV)

    print("\n✅ FILE CREATI:")
    print(OUTPUT_ANAG_CSV)
    print(OUTPUT_TICKET_EVENTI_CSV)

    print(f"\nConcessionari presenti: {df['concessionario'].nunique()}")
    print(f"Eventi unici: {len(anag_out)}")
    print(f"Righe ticket-eventi: {len(ticket_out)}")
    print(
        "Ticket unici: "
        f"{ticket_out[['concessionario', 'id_ticket']].drop_duplicates().shape[0]}"
    )

    print("\nColonne ticket-eventi:")
    print(list(ticket_out.columns))

    if "codice_fiscale" in ticket_out.columns:
        print("\n✅ Colonna codice_fiscale inclusa correttamente in 2_concessionari_ticket_eventi.csv")
    else:
        print("\n⚠ ATTENZIONE: codice_fiscale NON presente nel CSV finale")

    if "cod_stato_esito" in ticket_out.columns:
        print("✅ Colonna cod_stato_esito inclusa correttamente in 2_concessionari_ticket_eventi.csv")
    else:
        print("⚠ ATTENZIONE: cod_stato_esito NON presente nel CSV finale")

    colonne_matrice = [
        "des_scom",
        "des_eve",
        "des_vin",
        "match_key",
        "esito_key_matrice",
    ]
    mancanti_matrice = [c for c in colonne_matrice if c not in ticket_out.columns]

    if not mancanti_matrice:
        print("✅ Campi matrice compatibilità inclusi nel CSV ticket-eventi")
    else:
        print(f"⚠ ATTENZIONE: campi matrice mancanti nel CSV ticket-eventi: {mancanti_matrice}")


if __name__ == "__main__":
    main()
