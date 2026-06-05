from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd


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

SALT = os.getenv("CLIENTE_ID_SALT", "cambia_questa_stringa_segreta")


def crea_cliente_id(concessionario: str, codice_fiscale: str) -> str:
    valore = f"{SALT}|{concessionario}|{codice_fiscale}".upper().strip()
    return hashlib.sha256(valore.encode("utf-8")).hexdigest()[:16]


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"File non trovato: {INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE, sep=";", dtype=str).fillna("")

    colonne_richieste = {
        "concessionario",
        "nome_commerciale",
        "codice_fiscale",
    }

    mancanti = colonne_richieste - set(df.columns)
    if mancanti:
        raise ValueError(f"Colonne mancanti nel file input: {mancanti}")

    df["concessionario"] = df["concessionario"].astype(str).str.strip().str.upper()
    df["nome_commerciale"] = df["nome_commerciale"].astype(str).str.strip()
    df["codice_fiscale"] = df["codice_fiscale"].astype(str).str.strip().str.upper()

    df = df[df["codice_fiscale"] != ""].copy()

    df["cliente_id"] = df.apply(
        lambda r: crea_cliente_id(
            r["concessionario"],
            r["codice_fiscale"]
        ),
        axis=1
    )

    mappa = (
        df[
            [
                "concessionario",
                "nome_commerciale",
                "cliente_id",
                "codice_fiscale",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            [
                "concessionario",
                "nome_commerciale",
                "cliente_id",
            ]
        )
        .reset_index(drop=True)
    )

    mappa.to_csv(
        OUTPUT_FILE,
        sep=";",
        index=False,
        encoding="utf-8-sig"
    )

    print(f"Creato file privato: {OUTPUT_FILE}")
    print(f"Righe mappa: {len(mappa)}")


if __name__ == "__main__":
    main()