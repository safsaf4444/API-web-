:: Seren — local dev startup
:: Excludes app.db from watchfiles so AI requests don't cause mid-flight restarts

cd /d C:\Users\safad\API-web-
call .venv\Scripts\activate
uvicorn backend.app:app --reload --port 8000 --reload-exclude "*.db" --reload-exclude "*.db-shm" --reload-exclude "*.db-wal"