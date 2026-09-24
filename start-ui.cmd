@echo off
rem Starts both processes needed by the review UI (data/ folders act as the DB).
start "DocExtract API" cmd /k "cd /d %~dp0 && python -m uvicorn src.doc_extraction.server:app --port 8000"
start "DocExtract UI" cmd /k "cd /d %~dp0ui && npm run dev"
echo Both windows launched. UI: http://localhost:5173
