# 63_montecarlo_incompatibili

Pipeline Monte Carlo concessionari con controllo compatibilità degli esiti e output pubblici per dashboard.

## Struttura, come Dashboard-auto

- `.github/workflows/`: esecuzione automatica.
- `output/`: CSV consultabili tramite link pubblico.
- script Python nella root.
- `requirements.txt`: dipendenze.

## Codice fiscale e output pubblico

Il codice fiscale viene estratto e utilizzato **solo internamente** per raggruppare correttamente lo stesso cliente.

Il file pubblico per cliente è:

`output/13_concessionari_montecarlo_nomecommerciale_cliente_id.csv`

e contiene `cliente_id`, non il codice fiscale. `cliente_id` è creato con HMAC-SHA256 e una chiave privata contenuta nel secret `PIPELINE_PSEUDONYM_SECRET`.

Il file interno con codice fiscale non viene creato nel workflow pubblico (`PIPELINE_SAVE_PRIVATE_CF_OUTPUT=false`).

## File da aggiungere nella root

Caricare manualmente:

`Matrice_Compatibilita_Esiti_Calcio_v1_0.xlsx`

prima di eseguire il workflow. Verificare che la matrice non contenga credenziali o dati personali.

## Secrets GitHub Actions richiesti

In `Settings > Secrets and variables > Actions` creare:

1. `PIPELINE_DB_CONFIG_JSON` — connessioni DB in JSON.
2. `PIPELINE_PSEUDONYM_SECRET` — chiave lunga e casuale, da non cambiare se si vuole mantenere stabile `cliente_id`.
3. `PIPELINE_DB_PORT` — facoltativo; se omesso viene utilizzata la porta 3306.

Esempio di forma JSON, senza dati reali:

```json
{
  "CONCESSIONARIO": {
    "host": "HOST_PRIVATO",
    "user": "UTENTE_PRIVATO",
    "password": "PASSWORD_PRIVATA",
    "database": "DATABASE_PRIVATO"
  }
}
```

## Output pubblicati

- `12_concessionari_montecarlo_statistiche.csv`
- `13_concessionari_montecarlo_per_concessionario.csv`
- `13_concessionari_montecarlo_per_nome_commerciale.csv`
- `13_concessionari_montecarlo_nomecommerciale_cliente_id.csv`
- `20_concessionari_cluster_commerciali.csv`
- `21_concessionari_cluster_summary.csv`
- `16_top20_eventi_impatto_per_concessionario.csv`
- `17_top20_eventi_impatto_per_nome_commerciale.csv`

## Output esclusi dalla pubblicazione

Restano soltanto nell'area temporanea dell'esecuzione e non vengono committati: dati ticket, file con incompatibilità dettagliata, file probabilistici a livello ticket e qualsiasi file con codice fiscale.

## Avvio

Dopo aver caricato la matrice e configurato i secrets:

`Actions > Aggiorna output Monte Carlo pubblici > Run workflow`
