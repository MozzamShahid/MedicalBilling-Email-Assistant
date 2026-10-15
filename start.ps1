# Starts the backend, which also serves the built CRM at http://localhost:8000
Set-Location "$PSScriptRoot\backend"
$env:PYTHONIOENCODING = "utf-8"
& .\.venv\Scripts\python -m uvicorn app.main:app --port 8000
