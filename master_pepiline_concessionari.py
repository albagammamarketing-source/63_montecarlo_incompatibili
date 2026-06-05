from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


# =========================================================
# CONFIGURAZIONE PATH
# =========================================================
PROJECT_DIR = Path(
    os.getenv("PIPELINE_PROJECT_PATH", str(Path(__file__).resolve().parent))
).resolve()

OUTPUT_DIR = Path(
    os.getenv("PIPELINE_BASE_PATH", str(PROJECT_DIR / ".runtime_output"))
).resolve()

MATRIX_FILE = Path(
    os.getenv(
        "PIPELINE_MATRIX_FILE",
        str(PROJECT_DIR / "Matrice_Compatibilita_Esiti_Calcio_v1_0.xlsx"),
    )
).resolve()


# =========================================================
# VERSIONE
# =========================================================
SCRIPT_VERSION = "master_63_montecarlo_pubblico_cliente_id_privato_cf_v2"


# =========================================================
# CONFIGURAZIONE STEP
# =========================================================
@dataclass
class Step:
    ordine: int
    nome: str
    filename: str
    enabled: bool = True


RUN_ESTRAZIONE = True
RUN_ALLINEAMENTO = True
RUN_COMPATIBILITA_ESITI = True
RUN_PROBABILISTICO = True
RUN_MONTECARLO_DEF = True
RUN_RISCHIO_CLUSTER = True
RUN_TOP_EVENTI = True
RUN_MAPPA_PRIVATA_CLIENTI = True

STOP_ON_ERROR = True


STEPS = [
    Step(
        1,
        "Estrazione DB multi-concessionario",
        "1_concessionari_estrazione_generica.py",
        RUN_ESTRAZIONE,
    ),
    Step(
        2,
        "Allineamento dati concessionari",
        "2_concessionari_generico_motore_allineamento.py",
        RUN_ALLINEAMENTO,
    ),
    Step(
        3,
        "Controllo compatibilita esiti",
        "3b_concessionari_controllo_compatibilita_esiti.py",
        RUN_COMPATIBILITA_ESITI,
    ),
    Step(
        4,
        "Analisi probabilistica ticket",
        "4_concessionari_probabilita_ticket.py",
        RUN_PROBABILISTICO,
    ),
    Step(
        5,
        "Monte Carlo DEF con cliente_id pubblico",
        "5_concessionari_metodo_montecarlo_DEF.py",
        RUN_MONTECARLO_DEF,
    ),
    Step(
        6,
        "Rischio cluster",
        "6_concessionari_rischio_cluster.py",
        RUN_RISCHIO_CLUSTER,
    ),
    Step(
        7,
        "Top eventi impatto nome commerciale",
        "7_concessionari_top_eventi_impatto_nome_commerciale.py",
        RUN_TOP_EVENTI,
    ),
    Step(
        8,
        "Crea mappa privata cliente_id codice fiscale",
        "8_crea_mappa_privata_cliente_id_cf.py",
        RUN_MAPPA_PRIVATA_CLIENTI,
    ),
]


# =========================================================
# FUNZIONI
# =========================================================
def verifica_ambiente() -> None:
    if not PROJECT_DIR.exists():
        raise FileNotFoundError(f"Cartella progetto non trovata: {PROJECT_DIR}")

    if not MATRIX_FILE.exists():
        raise FileNotFoundError(
            f"Manca Matrice_Compatibilita_Esiti_Calcio_v1_0.xlsx: {MATRIX_FILE}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def stampa_intestazione() -> None:
    print("=" * 80)
    print("PIPELINE MONTE CARLO - OUTPUT PUBBLICO CON cliente_id + MAPPA PRIVATA CF")
    print("=" * 80)
    print(f"Versione: {SCRIPT_VERSION}")
    print(f"Project dir: {PROJECT_DIR}")
    print(f"Output temporanei: {OUTPUT_DIR}")
    print(f"Matrice compatibilita: {MATRIX_FILE}")
    print(f"Python: {sys.executable}")
    print("-" * 80)
    print(f"Estrazione DB:          {'ON' if RUN_ESTRAZIONE else 'OFF'}")
    print(f"Allineamento:           {'ON' if RUN_ALLINEAMENTO else 'OFF'}")
    print(f"Compatibilita esiti:    {'ON' if RUN_COMPATIBILITA_ESITI else 'OFF'}")
    print(f"Probabilistico:         {'ON' if RUN_PROBABILISTICO else 'OFF'}")
    print(f"Monte Carlo DEF:        {'ON' if RUN_MONTECARLO_DEF else 'OFF'}")
    print(f"Rischio cluster:        {'ON' if RUN_RISCHIO_CLUSTER else 'OFF'}")
    print(f"Top eventi impatto:     {'ON' if RUN_TOP_EVENTI else 'OFF'}")
    print(f"Mappa privata clienti:  {'ON' if RUN_MAPPA_PRIVATA_CLIENTI else 'OFF'}")
    print(f"Stop on error:          {'ON' if STOP_ON_ERROR else 'OFF'}")
    print("=" * 80)


def esegui_script(step: Step) -> dict:
    script = PROJECT_DIR / step.filename

    if not script.exists():
        raise FileNotFoundError(f"Script mancante: {script}")

    print("\n" + "=" * 80)
    print(f"[{step.ordine}] AVVIO: {step.nome}")
    print(f"File: {script}")
    print("=" * 80)

    env = os.environ.copy()
    env["PIPELINE_PROJECT_PATH"] = str(PROJECT_DIR)
    env["PIPELINE_BASE_PATH"] = str(OUTPUT_DIR)
    env["PIPELINE_MATRIX_FILE"] = str(MATRIX_FILE)

    start = time.time()

    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(PROJECT_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    secondi = round(time.time() - start, 2)

    if proc.stdout.strip():
        print("\n--- OUTPUT ---")
        print(proc.stdout.strip())

    if proc.stderr.strip():
        print("\n--- ERRORI ---")
        print(proc.stderr.strip())

    ok = proc.returncode == 0

    print("\n" + "-" * 80)
    print(f"Esito step [{step.ordine}]: {'OK' if ok else 'ERRORE'}")
    print(f"Return code: {proc.returncode}")
    print(f"Tempo: {secondi} s")
    print("-" * 80)

    return {
        "ordine": step.ordine,
        "nome": step.nome,
        "script": step.filename,
        "ok": ok,
        "returncode": proc.returncode,
        "secondi": secondi,
    }


def stampa_riepilogo(risultati: list[dict]) -> None:
    print("\n" + "=" * 80)
    print("RIEPILOGO FINALE PIPELINE")
    print("=" * 80)

    if not risultati:
        print("Nessuno step eseguito.")
        return

    for r in risultati:
        stato = "OK" if r["ok"] else "KO"
        print(f"[{r['ordine']}] {stato:<2} | {r['script']:<60} | {r['secondi']} s")

    print("-" * 80)
    print(f"Totale step eseguiti: {len(risultati)}")
    print(f"OK: {sum(r['ok'] for r in risultati)}")
    print(f"KO: {sum(not r['ok'] for r in risultati)}")
    print(f"Output temporanei in: {OUTPUT_DIR}")
    print("=" * 80)


def stampa_file_attesi() -> None:
    print("\n" + "=" * 80)
    print("FILE ATTESI")
    print("=" * 80)

    files = [
        "1_concessionari_anagrafica_eventi.csv",
        "2_concessionari_ticket_eventi.csv",
        "3_concessionari_anagrafica_eventi_allineata.csv",
        "4_concessionari_ticket_eventi_allineato.csv",
        "4b_concessionari_ticket_eventi_compatibilita.csv",
        "9_concessionari_ticket_probabilistico.csv",
        "10_concessionari_riepilogo_probabilistico_per_nome_commerciale.csv",
        "11_concessionari_montecarlo_simulazioni.csv",
        "12_concessionari_montecarlo_statistiche.csv",
        "13_concessionari_montecarlo_per_concessionario.csv",
        "13_concessionari_montecarlo_per_nome_commerciale.csv",
        "13_concessionari_montecarlo_nomecommerciale_cliente_id.csv",
        "14_concessionari_top_ticket_rischio.csv",
        "15_concessionari_eventi_probabilita_drift.csv",
        "16_top20_eventi_impatto_per_concessionario.csv",
        "17_top20_eventi_impatto_per_nome_commerciale.csv",
        "20_concessionari_cluster_commerciali.csv",
        "21_concessionari_cluster_summary.csv",
        "output_privato/mappa_cliente_id_codice_fiscale.csv",
    ]

    for file in files:
        path = OUTPUT_DIR / file
        print(f"{file:<75} {'OK' if path.exists() else 'NON TROVATO'}")

    print("=" * 80)


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    verifica_ambiente()
    stampa_intestazione()

    risultati = []

    for step in STEPS:
        if not step.enabled:
            print(f"\n[{step.ordine}] SKIPPATO: {step.nome}")
            continue

        try:
            risultato = esegui_script(step)
            risultati.append(risultato)

            if not risultato["ok"] and STOP_ON_ERROR:
                print("\nSTOP PIPELINE: errore nello step precedente.")
                break

        except Exception as ex:
            print(f"\nERRORE GRAVE nello step [{step.ordine}] {step.nome}: {ex}")

            risultati.append(
                {
                    "ordine": step.ordine,
                    "nome": step.nome,
                    "script": step.filename,
                    "ok": False,
                    "returncode": -1,
                    "secondi": 0,
                }
            )

            if STOP_ON_ERROR:
                print("\nSTOP PIPELINE: errore grave.")
                break

    stampa_riepilogo(risultati)
    stampa_file_attesi()

    if any(not r["ok"] for r in risultati):
        raise RuntimeError("Pipeline completata con errori.")

    print("\nPIPELINE COMPLETATA CORRETTAMENTE")


if __name__ == "__main__":
    main()
