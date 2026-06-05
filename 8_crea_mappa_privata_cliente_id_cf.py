from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd


# =========================================================
# CONFIGURAZIONE
# =========================================================
BASE_PATH = Path(
    os.getenv(
        "PIPELINE_BASE_PATH",
        r"G:\Il mio Drive\progetti phyton\63_montecarlo_incompatibilita"
    )
)

INPUT_FILE = BASE_PATH / "4b_concessionari_ticket_eventi_compatibilita.csv"

OUTPUT_DIR = BASE_PATH / "output_privato"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "mappa_cliente_id_codice_fiscale.csv"

# IMPORTANTE:
# In GitHub Actions imposta CLIENTE_ID_SALT nei Secrets.
# Non cambiare mai il SALT dopo aver generato gli ID,
# altrimenti cambieranno tutti i cliente_id.
SALT = os.getenv("CLIENTE_ID_SALT", "cambia_questa_stringa_segreta")


# =========================================================
# FUNZIONI
# =========================================================
def crea_cliente_id(codice_fiscale: str) -> str:
    """
    Genera un cliente_id stabile e univoco partendo SOLO dal codice fiscale.

    Logica:
    stesso codice_fiscale = stesso cliente_id
    anche se il cliente compare su concessionari o punti vendita diversi.
    """
    cf = str(codice_fiscale).strip().upper()

    if cf == "":
        return ""

    valore = f"{SALT}|{cf}"
    return "CL_" + hashlib.sha256(valore.encode("utf-8")).hexdigest()[:20].upper()


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


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    print("=" * 80)
    print("CREAZIONE MAPPA PRIVATA CLIENTE_ID - CODICE_FISCALE")
    print("=" * 80)
    print(f"Input:  {INPUT_FILE}")
    print(f"Output: {OUTPUT_FILE}")
    print("=" * 80)

    df = leggi_csv(INPUT_FILE)

    colonne_richieste = {
        "concessionario",
        "nome_commerciale",
        "codice_fiscale",
    }

    mancanti = colonne_richieste - set(df.columns)

    if mancanti:
        raise ValueError(f"Colonne mancanti nel file input: {sorted(mancanti)}")

    df["concessionario"] = df["concessionario"].astype(str).str.strip().str.upper()
    df["nome_commerciale"] = df["nome_commerciale"].astype(str).str.strip()
    df["codice_fiscale"] = df["codice_fiscale"].astype(str).str.strip().str.upper()

    df = df[df["codice_fiscale"] != ""].copy()

    if df.empty:
        print("⚠ Nessun codice fiscale valido trovato.")
        return

    # Cliente ID generato SOLO dal codice fiscale
    df["cliente_id"] = df["codice_fiscale"].apply(crea_cliente_id)

    # Mappa privata univoca: 1 cliente_id = 1 codice_fiscale
    mappa_base = (
        df[
            [
                "cliente_id",
                "codice_fiscale",
            ]
        ]
        .drop_duplicates()
        .sort_values("cliente_id")
        .reset_index(drop=True)
    )

    # Informazioni aggiuntive descrittive, non fanno parte della chiave primaria
    info_cliente = (
        df[
            [
                "cliente_id",
                "concessionario",
                "nome_commerciale",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            [
                "cliente_id",
                "concessionario",
                "nome_commerciale",
            ]
        )
        .reset_index(drop=True)
    )

    # Aggrego concessionari e nomi commerciali collegati allo stesso cliente
    info_aggregata = (
        info_cliente
        .groupby("cliente_id", dropna=False)
        .agg(
            concessionari=("concessionario", lambda x: " | ".join(sorted(set(x)))),
            nomi_commerciali=("nome_commerciale", lambda x: " | ".join(sorted(set(x)))),
        )
        .reset_index()
    )

    mappa = mappa_base.merge(
        info_aggregata,
        on="cliente_id",
        how="left"
    )

    # Controllo sicurezza: ogni cliente_id deve avere un solo CF
    controllo = (
        mappa
        .groupby("cliente_id")["codice_fiscale"]
        .nunique()
        .reset_index(name="num_cf")
    )

    problemi = controllo[controllo["num_cf"] > 1]

    if not problemi.empty:
        raise ValueError(
            "Errore: trovati cliente_id associati a più codici fiscali. "
            "Controllare la funzione di hashing."
        )

    mappa.to_csv(
        OUTPUT_FILE,
        sep=";",
        index=False,
        encoding="utf-8-sig"
    )

    print("\n✅ File privato creato correttamente")
    print(f"Percorso: {OUTPUT_FILE}")
    print(f"Clienti unici: {len(mappa)}")
    print(f"Codici fiscali unici: {mappa['codice_fiscale'].nunique()}")
    print("=" * 80)


if __name__ == "__main__":
    main()
