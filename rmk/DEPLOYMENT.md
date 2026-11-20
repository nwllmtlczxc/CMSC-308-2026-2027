# Running the timetable system

## Local setup (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m flask --app app init-db
python app.py
```

New registrations are Instructor accounts and cannot change schedules or master data. Promote the account that will administer the system with `python -m flask --app app make-admin YOUR_USERNAME`. The command only promotes an existing account.

For local debugging, set `$env:FLASK_DEBUG = '1'` before running `python app.py`. Debug mode is off by default.

## Production (Windows)

Set a long random secret and production environment in the service environment; do not commit these values. For example, generate a key with `python -c "import secrets; print(secrets.token_hex(32))"`, then configure `FLASK_SECRET_KEY` and `APP_ENV=production`. The app refuses to start in production without the secret and marks session cookies Secure, HttpOnly, and SameSite=Lax.

Initialize the database and promote an administrator once:

```powershell
python -m flask --app app init-db
python -m flask --app app make-admin YOUR_USERNAME
```

Run the app behind a reverse proxy using Waitress:

```powershell
python -m waitress --listen=127.0.0.1:8000 app:app
```

HTTPS should terminate at the reverse proxy. Keep the service bound to localhost when that proxy is on the same machine.
