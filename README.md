> **Runs on Render now, not GitHub Actions.** `render.yaml` defines an hourly cron
> job (`scripts/worker.py`, Dockerfile) that walks the listing, reads pending reports,
> and publishes to Supabase: tables, plus `lots.json`, `terminal.json` and
> `schedule/*.txt` in the public Storage bucket `public-data`. The pipeline's state
> (index + batches) is kept in the private bucket `pipeline`. The copies under `data/`
> here are the state as of 22 Nov 2026 and seed the first run only.

# spices-auction-data
Spices Board cardamom auction report extraction
