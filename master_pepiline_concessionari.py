from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

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

SCRIPT_VERSION = "master_63_montecarlo_pubblico_cliente_id_v1"

@dataclass
class Step:
    ordine: int
    nome: str
    filename: str

STEPS = [
    Step(1, "Estrazione DB multi-concessionario", "1_concessionari_estrazione_generica.py"),
    Step(2, "Allineamento dati concessionari", "2_concessionari_generico_motore_allineamento.py"),
    Step(3, "Controllo compatibilita esiti", "3b_concessionari_controllo_compatibilita_esiti.py"),
    Step(4, "Analisi probabilistica ticket", "4_concessionari_probabilita_ticket.py"),
    Step(5, "Monte Carlo DEF con cliente_id pubblico", "5_concessionari_metodo_montecarlo_DEF.py"),
    Step(6, "Rischio cluster", "6_concessionari_rischio_cluster.py"),
    Step(7, "Top eventi impatto nome commerciale", "7_concessionari_top_eventi_impatto_nome_commerciale.py"),
]

def verifica_ambiente() -> None:
    if not MATRIX_FILE.exists():
        raise FileNotFoundError(
            "Manca Matrice_Compatibilita_Esiti_Calcio_v1_0.xlsx nella root del progetto."
        )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def esegui_script(step: Step) -> dict:
    script = PROJECT_DIR / step.filename
    if not script.exists():
        raise FileNotFoundError(f"Script mancante: {script}")

    print("\n" + "=" * 80)
    print(f"[{step.ordine}] {step.nome}")
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
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print("\nERRORI:")
        print(proc.stderr.strip())

    return {"script": step.filename, "ok": proc.returncode == 0, "secondi": secondi}

def main() -> None:
    verifica_ambiente()
    print("PIPELINE MONTE CARLO - OUTPUT PUBBLICO CON cliente_id")
    print(f"Versione: {SCRIPT_VERSION}")
    print(f"Output temporanei: {OUTPUT_DIR}")

    risultati = []
    for step in STEPS:
        risultato = esegui_script(step)
        risultati.append(risultato)
        if not risultato["ok"]:
            raise RuntimeError(f"Pipeline interrotta: errore in {step.filename}")

    print("\nPIPELINE COMPLETATA")
    for r in risultati:
        print(f"{r['script']}: OK ({r['secondi']} s)")

if __name__ == "__main__":
    main()
