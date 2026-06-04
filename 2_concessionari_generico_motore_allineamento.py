from __future__ import annotations

try:
    import pandas as pd
except ImportError:
    print("Libreria mancante: pandas")
    raise

import os
from pathlib import Path


# =========================================================
# CARTELLA DI LAVORO
# =========================================================
PROJECT_DIR = Path(
    os.getenv("PIPELINE_PROJECT_PATH", str(Path(__file__).resolve().parent))
).resolve()

BASE_PATH = Path(
    os.getenv("PIPELINE_BASE_PATH", str(PROJECT_DIR / ".runtime_output"))
).resolve()
BASE_PATH.mkdir(parents=True, exist_ok=True)
# 🔥 NOMI COERENTI CON SCRIPT 1
INPUT_ANAGRAFICA = BASE_PATH / "1_concessionari_anagrafica_eventi.csv"
INPUT_TICKET_EVENTI = BASE_PATH / "2_concessionari_ticket_eventi.csv"

OUTPUT_ANAGRAFICA = BASE_PATH / "3_concessionari_anagrafica_eventi_allineata.csv"
OUTPUT_TICKET_EVENTI = BASE_PATH / "4_concessionari_ticket_eventi_allineato.csv"

# Campi introdotti dallo script 1 per il controllo compatibilità esiti.
# Devono attraversare l’allineamento senza essere persi, perché saranno
# usati dallo script 3b e poi dal Monte Carlo DEF.
CAMPI_COMPATIBILITA_TICKET = [
    "des_sport",
    "des_manif",
    "des_avv",
    "des_scom",
    "des_eve",
    "des_vin",
    "match_key",
    "esito_key_matrice",
]

CAMPI_COMPATIBILITA_ANAGRAFICA = [
    "des_sport",
    "des_manif",
    "des_avv",
    "des_scom",
    "des_eve",
    "des_vin",
]


# =========================================================
# UTILS
# =========================================================
def trova_colonna(df, candidati):
    cols_norm = {str(c).strip().lower(): c for c in df.columns}

    for cand in candidati:
        if cand.lower() in cols_norm:
            return cols_norm[cand.lower()]

    return None


def leggi_csv(path_file: Path):
    if not path_file.exists():
        raise FileNotFoundError(f"CSV non trovato: {path_file}")

    try:
        df = pd.read_csv(path_file, sep=";", dtype=str)
    except Exception:
        df = pd.read_csv(path_file, sep=None, engine="python", dtype=str)

    df.columns = (
        df.columns
        .str.replace("\ufeff", "", regex=False)
        .str.replace("ï»¿", "", regex=False)
        .str.strip()
        .str.lower()
    )

    return df.fillna("")


def normalizza_colonne_stringa(df: pd.DataFrame, colonne: list[str]) -> pd.DataFrame:
    """Normalizza colonne opzionali se presenti.

    Non crea forzatamente colonne opzionali: l’obiettivo è non perdere
    quelle prodotte dallo script 1 e renderle coerenti per gli step successivi.
    """
    df = df.copy()

    for col in colonne:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def verifica_campi_compatibilita(ticket_eventi_out: pd.DataFrame) -> None:
    mancanti = [c for c in CAMPI_COMPATIBILITA_TICKET if c not in ticket_eventi_out.columns]

    if mancanti:
        print("⚠ ATTENZIONE: campi compatibilità mancanti nel ticket allineato:")
        print(mancanti)
        print("   Controlla di aver eseguito lo script 1 aggiornato prima dello script 2.")
    else:
        print("✅ Campi compatibilità conservati nel CSV ticket allineato")


# =========================================================
# LETTURA FILE BASE
# =========================================================
def leggi_file_base():
    anag_out = leggi_csv(INPUT_ANAGRAFICA)
    ticket_eventi_out = leggi_csv(INPUT_TICKET_EVENTI)

    # --- ANAGRAFICA ---
    col_concessionario_anag = trova_colonna(anag_out, ["concessionario"])
    col_id_evento_anag = trova_colonna(anag_out, ["id_evento"])
    col_evento_descr_anag = trova_colonna(anag_out, ["evento_descrizione"])
    col_stato_input_anag = trova_colonna(anag_out, ["stato_evento_input"])

    if col_concessionario_anag is None:
        raise ValueError(f"{INPUT_ANAGRAFICA.name}: manca 'concessionario'")
    if col_id_evento_anag is None:
        raise ValueError(f"{INPUT_ANAGRAFICA.name}: manca 'id_evento'")
    if col_evento_descr_anag is None:
        raise ValueError(f"{INPUT_ANAGRAFICA.name}: manca 'evento_descrizione'")
    if col_stato_input_anag is None:
        raise ValueError(f"{INPUT_ANAGRAFICA.name}: manca 'stato_evento_input'")

    # --- TICKET ---
    col_concessionario_ticket = trova_colonna(ticket_eventi_out, ["concessionario"])
    col_id_ticket = trova_colonna(ticket_eventi_out, ["id_ticket"])
    col_nome_commerciale = trova_colonna(ticket_eventi_out, ["nome_commerciale"])
    col_num_evento = trova_colonna(ticket_eventi_out, ["num_evento"])
    col_id_evento_ticket = trova_colonna(ticket_eventi_out, ["id_evento"])
    col_evento_descr_ticket = trova_colonna(ticket_eventi_out, ["evento_descrizione"])
    col_data_ora_vend = trova_colonna(ticket_eventi_out, ["data_ora_vend"])

    # Colonne opzionali ma fondamentali per la nuova fase 3b.
    colonne_compat_presenti = {
        nome: trova_colonna(ticket_eventi_out, [nome])
        for nome in CAMPI_COMPATIBILITA_TICKET
    }

    if col_concessionario_ticket is None:
        raise ValueError(f"{INPUT_TICKET_EVENTI.name}: manca 'concessionario'")
    if col_id_ticket is None:
        raise ValueError(f"{INPUT_TICKET_EVENTI.name}: manca 'id_ticket'")
    if col_id_evento_ticket is None:
        raise ValueError(f"{INPUT_TICKET_EVENTI.name}: manca 'id_evento'")
    if col_evento_descr_ticket is None:
        raise ValueError(f"{INPUT_TICKET_EVENTI.name}: manca 'evento_descrizione'")
    if col_data_ora_vend is None:
        raise ValueError(f"{INPUT_TICKET_EVENTI.name}: manca 'data_ora_vend'")

    # =====================================================
    # NORMALIZZAZIONE
    # =====================================================
    anag_out[col_concessionario_anag] = (
        anag_out[col_concessionario_anag].astype(str).str.strip().str.upper()
    )

    anag_out[col_id_evento_anag] = (
        anag_out[col_id_evento_anag].astype(str).str.strip()
    )

    anag_out[col_evento_descr_anag] = (
        anag_out[col_evento_descr_anag].astype(str).str.strip()
    )

    anag_out[col_stato_input_anag] = (
        anag_out[col_stato_input_anag].astype(str).str.strip().str.upper()
    )

    anag_out = normalizza_colonne_stringa(anag_out, CAMPI_COMPATIBILITA_ANAGRAFICA)

    ticket_eventi_out[col_concessionario_ticket] = (
        ticket_eventi_out[col_concessionario_ticket].astype(str).str.strip().str.upper()
    )

    ticket_eventi_out[col_id_ticket] = (
        ticket_eventi_out[col_id_ticket].astype(str).str.strip()
    )

    ticket_eventi_out[col_id_evento_ticket] = (
        ticket_eventi_out[col_id_evento_ticket].astype(str).str.strip()
    )

    ticket_eventi_out[col_evento_descr_ticket] = (
        ticket_eventi_out[col_evento_descr_ticket].astype(str).str.strip()
    )

    ticket_eventi_out[col_data_ora_vend] = (
        ticket_eventi_out[col_data_ora_vend].astype(str).str.strip()
    )

    if col_nome_commerciale:
        ticket_eventi_out[col_nome_commerciale] = (
            ticket_eventi_out[col_nome_commerciale].astype(str).str.strip()
        )

    if col_num_evento:
        ticket_eventi_out[col_num_evento] = (
            ticket_eventi_out[col_num_evento].astype(str).str.strip()
        )

    # Normalizza i campi del controllo compatibilità se presenti nel file 2.
    for nome, col in colonne_compat_presenti.items():
        if col is not None:
            ticket_eventi_out[col] = ticket_eventi_out[col].fillna("").astype(str).str.strip()

    # Se match_key o esito_key_matrice mancassero ma i campi base fossero presenti,
    # li ricostruiamo per robustezza.
    if "match_key" not in ticket_eventi_out.columns and all(
        c in ticket_eventi_out.columns for c in ["concessionario", "des_sport", "des_manif", "des_avv", "des_eve"]
    ):
        ticket_eventi_out["match_key"] = (
            ticket_eventi_out["concessionario"].astype(str).str.strip().str.upper() + "||" +
            ticket_eventi_out["des_sport"].astype(str).str.strip() + "||" +
            ticket_eventi_out["des_manif"].astype(str).str.strip() + "||" +
            ticket_eventi_out["des_avv"].astype(str).str.strip() + "||" +
            ticket_eventi_out["des_eve"].astype(str).str.strip()
        )

    if "esito_key_matrice" not in ticket_eventi_out.columns and all(
        c in ticket_eventi_out.columns for c in ["des_scom", "des_eve", "des_vin"]
    ):
        ticket_eventi_out["esito_key_matrice"] = (
            ticket_eventi_out["des_scom"].astype(str).str.strip() + "||" +
            ticket_eventi_out["des_eve"].astype(str).str.strip() + "||" +
            ticket_eventi_out["des_vin"].astype(str).str.strip()
        )

    # warning utile
    if ticket_eventi_out[col_id_evento_ticket].eq("").any():
        print("⚠ Attenzione: presenti id_evento vuoti nei ticket")

    verifica_campi_compatibilita(ticket_eventi_out)

    return anag_out, ticket_eventi_out


# =========================================================
# SCRITTURA OUTPUT BASE
# =========================================================
def scrivi_output_base(anag_out, ticket_eventi_out):
    anag_out.to_csv(OUTPUT_ANAGRAFICA, index=False, sep=";", encoding="utf-8-sig")
    ticket_eventi_out.to_csv(OUTPUT_TICKET_EVENTI, index=False, sep=";", encoding="utf-8-sig")


# =========================================================
# MAIN
# =========================================================
def main():
    print(f"Lettura file anagrafica: {INPUT_ANAGRAFICA}")
    print(f"Lettura file ticket eventi: {INPUT_TICKET_EVENTI}")
    print(f"Cartella base: {BASE_PATH}")

    anag_out, ticket_eventi_out = leggi_file_base()

    print("Creo i CSV di lavoro allineati...")
    scrivi_output_base(anag_out, ticket_eventi_out)

    print(f"Creato: {OUTPUT_ANAGRAFICA}")
    print(f"Creato: {OUTPUT_TICKET_EVENTI}")

    print("\nColonne ticket-eventi allineato:")
    print(list(ticket_eventi_out.columns))

    print("Operazione completata.")


if __name__ == "__main__":
    main()
