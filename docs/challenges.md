# Challenges and lessons

Real problems hit while building the project, how each was diagnosed, and what it taught. Each one started with reading the error before changing anything.

## Environment and tooling

**1. `requirements.txt` committed as a binary file.**
*Symptom:* the first commit counted 0 lines for `requirements.txt`; `git show --numstat` printed `- -`.
*Cause:* `pip freeze > requirements.txt` in Windows PowerShell 5.1 writes UTF-16, which Git treats as binary.
*Fix:* re-save as UTF-8; verify with `git grep -n fastapi HEAD -- requirements.txt` (a diff against the old binary version still shows `- -`, so checking only the latest version is the reliable test). Since then: `pip freeze | Set-Content -Encoding ascii`.
*Lesson:* shell redirection is not encoding-neutral; verify artifacts, not just commands.

**2. Wrong shell, wrong syntax.**
*Symptom:* `cd: too many arguments`, `-bash: Select-String: command not found`, `The term 'docker' is not recognized`.
*Cause:* switching between PowerShell and WSL Bash. Windows paths and PowerShell cmdlets don't exist in Bash, and the Docker Engine installed in WSL doesn't exist in PowerShell.
*Fix:* read the prompt (`PS …>` vs `user@host:…$`), quote paths with spaces, and run `docker` in WSL and `curl.exe` helpers in PowerShell.

**3. Line endings.**
Git warned `LF will be replaced by CRLF`, and a CRLF `.env` read by Compose on Linux can append an invisible `\r` to every secret. Fixed with `.gitattributes` (`* text=auto eol=lf`) and by checking `grep -c $'\r' .env` → `0`.

**4. Downloads landing inside the repository.**
Installers and binaries saved by the browser into the project folder showed up as untracked files. They were moved to a separate `tools/` directory, and the Silo binary was verified against its published SHA-256 before use.

## Application

**5. `NameError` behind a `500`.**
The client only saw `Internal Server Error`; the traceback in the server log ended in `NameError: name 'get_file_path' is not defined` at `main.py:63`. Reading traceback frames from the bottom and skipping library frames found the one line in project code. The helper had never been pasted in. Python resolves names at call time, so the server started fine and failed only on that request.

**6. Two apps in one file.**
After a refactor into routers, a commit showed `465 insertions(+)` and no deletions, which is impossible for a refactor that shrinks `main.py`. The file had 267 lines and two `app = FastAPI(...)`: the new code was pasted below the old. It worked only because the last definition wins. Cleaned up and amended (before any push).

**7. Placeholders in secrets.**
`alembic` failed with `password authentication failed`, while `psql` with the same user worked. A check that printed only the password's length (20) and whether it contained `<`/`>` (true) showed `.env` still held the literal `<password-cloud-app>`. Later `KeyError: 'JWT_SECRET'` turned out to be `JWT.SECRET`. Debugging secrets without printing them is a habit worth keeping.

**8. Time zones across databases.**
SQLite returned naive datetimes (fixed by labelling them UTC); PostgreSQL returned `+07:00` because the server time zone followed Windows. The same instant was serialized differently per environment. The validator now converts everything to UTC, so the API contract no longer depends on server settings.

**9. Helper scripts that fail silently.**
A login helper returned an empty token on a wrong password, and the next five requests failed with a misleading "invalid token". The helper now throws immediately with the server's message. Fail fast, close to the cause.

## Database and migrations

**10. Adding a NOT NULL column to a populated table.**
`owner_id` could be added only because `files` happened to be empty. For `quota_bytes` on a populated `users` table, `server_default` lets PostgreSQL fill existing rows. A nullable `folder_id` needed neither.

**11. Unnamed constraints break downgrades.**
Autogenerate emitted `drop_constraint(None, ...)` and warned about it. The folders migration was fixed when it was written; a later full `downgrade base` test exposed the same problem in the earlier ownership migration. Both foreign keys now have explicit names, the earlier one matching PostgreSQL's default name so existing databases are unaffected, and CI runs a full downgrade/upgrade roundtrip plus `alembic check` on every push.

## Storage and networking

**12. Presigned URLs behind Docker and a proxy.**
Inside Compose the API reaches storage at `silo:9000`, which a browser can't resolve, and the `Host` header is part of the signature, so the URL cannot be rewritten after signing. Solution: a second boto3 client that signs for the public address (no network call is needed to sign).

**13. "Request has multiple authentication types".**
After Nginx put API and storage on one origin, `curl -L` (and browsers) kept the `Authorization: Bearer` header when following the redirect, so Silo received a JWT *and* a query signature and rejected the request. Nginx now clears `Authorization` on the storage route.

**14. Port 80 already taken, then a crash loop.**
`docker compose up` failed with `address already in use`; `ss -ltnp` showed an Nginx installed directly in WSL (21 processes: one master plus a worker per CPU thread) serving an old static site. After disabling it, the Docker Nginx container kept restarting with `host not found in upstream "api:8000"`: the container created during the failed start was never attached to the network. `docker compose up -d --force-recreate nginx` fixed it.

**15. Where an upload is rejected matters.**
The API's `413` arrived only after `HTTP/1.1 100 Continue` and the full 2 MB body; Nginx's `413` arrived with no `100 Continue` and `Connection: close`. Limits belong at the edge, with the application check kept for quotas the proxy cannot know about.

## Process

**16. Secrets shared too early.**
Development passwords were typed into visible prompts and screenshots. All of them are treated as compromised and will be rotated before real use. The Docker environment was given new random secrets before its database volume was first initialized, because `POSTGRES_PASSWORD` is only applied then.
