# Catatan Belajar & Persiapan Interview

Rangkuman pribadi Phase 1–8: konsep yang dipelajari per phase, cara menjelaskannya ke interviewer, dan jawaban Knowledge Check.

## Cerita project dalam 60 detik

> "Saya membangun cloud storage pribadi untuk keluarga, mirip Google Drive, secara bertahap. Mulai dari FastAPI yang menyimpan file di folder lokal, lalu saya pindahkan ke object storage lewat S3 API, metadata ke PostgreSQL dengan migration Alembic, menambah autentikasi JWT dengan isolasi data per user, kuota, folder bersama, lalu membungkus semuanya dengan Docker Compose di belakang Nginx dengan HTTPS. Setiap push dicek otomatis oleh GitHub Actions: lint, test di SQLite dan PostgreSQL, smoke test seluruh stack, lalu image dipublish ke GHCR. Tiap phase menyelesaikan masalah yang muncul di phase sebelumnya, jadi saya bisa menjelaskan *kenapa* setiap teknologi dipakai."

## Ringkasan per phase

### Phase 1: FastAPI + folder lokal
- Virtual environment mengisolasi dependency per project. Prinsip yang sama dipakai Docker di level OS.
- Upload memakai `multipart/form-data`, dan `UploadFile` menyimpan file besar ke disk sementara, bukan ke RAM.
- Path traversal (`../../main.py`) dicegah dengan `Path(name).name`, lalu dicek ulang dengan `resolve()` + parent (defense in depth).
- Status code: `201` dibuat, `204` dihapus tanpa body, `404`, `409` bentrok, `422` validasi otomatis.
- REST: path = resource, method = aksi. DELETE bersifat idempotent.

### Phase 2: Object storage (Silo)
- Filesystem itu hierarkis. Object storage itu datar: bucket → object (key + data + metadata), diakses lewat HTTP.
- Silo menyimpan object sebagai `xl.meta` + `part.1` dengan hash bitrot per blok 1 MiB. Selisih 64 byte = 2 blok × 32 byte hash.
- ETag (upload non-multipart) = MD5 isi file.
- Presigned URL = tanda tangan HMAC-SHA256 atas bucket, key, waktu, dan host. Membuatnya nggak menghubungi server. Diubah satu karakter → `SignatureDoesNotMatch`. Lewat waktu → `Request has expired`.
- Kenapa Silo: MinIO Community Edition diarsipkan pada 2026. Karena kode memakai S3 API, backend bisa diganti.

### Phase 3: Database
- Database = source of truth. Silo cuma menyimpan byte dengan key UUID.
- Unique constraint jadi pengaman terakhir terhadap race condition. Cek di kode saja nggak cukup.
- Urutan operasi dua sistem: upload ke storage dulu lalu commit DB (gagal → hapus object). Delete: DB dulu lalu storage. Sisa terburuk cuma object yatim.
- Alembic: perubahan skema tercatat di Git, bisa di-upgrade/downgrade, dan sama di semua environment.
- SQLite membuang timezone, PostgreSQL menyimpannya (`timestamptz`). API selalu mengirim UTC.

### Phase 4: Authentication
- Authentication = siapa kamu (`401`). Authorization = boleh apa (`403`).
- Argon2id sengaja lambat dan boros memori (64 MiB per hash), beda dengan SHA256 yang dirancang cepat.
- JWT ditandatangani, bukan dienkripsi: payload bisa dibaca siapa pun. `algorithms=["HS256"]` wajib eksplisit untuk mencegah serangan `alg: none`.
- JWT nggak bisa dicabut → umur pendek + cek `is_active` di setiap request.
- Login anti-enumeration: pesan sama + verifikasi dummy hash supaya waktunya sama.

### Phase 5: Fitur storage
- `server_default` mengisi baris lama saat menambah kolom NOT NULL. Kolom nullable aman tanpa default.
- `PATCH` = ubah sebagian. `model_fields_set` membedakan "field nggak dikirim" dan "dikirim `null`".
- Wildcard injection: `%` di `LIKE` harus di-escape (`autoescape=True`).
- Pagination dengan `limit`/`offset` + urutan kedua (`id`) supaya stabil.
- `404` kalau user nggak boleh tahu resource itu ada, `403` kalau boleh tahu tapi nggak boleh mengubah.

### Phase 6: Docker
- Image = resep, container = hasil yang berjalan, volume = data yang bertahan.
- Urutan `COPY requirements.txt` → `pip install` → `COPY . .` memanfaatkan cache layer (build ulang 3 detik, bukan 30).
- Di dalam Docker network, nama service = hostname (DNS internal).
- `--host 0.0.0.0` wajib di container. Pembatasan akses dilakukan di `ports: "127.0.0.1:..."`.
- Init container + `depends_on: condition` menjamin migration selesai sebelum API menyala.
- Dua klien S3: alamat internal untuk operasi, alamat publik untuk menandatangani URL.

### Phase 7: Nginx
- Reverse proxy = satu pintu masuk: TLS, header keamanan, batas upload, routing.
- `413` dari Nginx tanpa `100 Continue` (hemat bandwidth) vs `413` dari FastAPI setelah file terkirim.
- `Referrer-Policy: no-referrer` mencegah presigned URL bocor lewat header `Referer`.
- HSTS jangan diaktifkan di `localhost`.
- Origin sama → nggak ada masalah CORS, tapi header `Authorization` ikut terbawa saat redirect, jadi harus dibuang di route storage.

### Phase 8: CI/CD
- CI = setiap perubahan diverifikasi otomatis. CD = hasilnya dikemas dan siap di-deploy.
- Test memakai SQLite + moto (cepat, tanpa server), lalu diulang di PostgreSQL, ditambah smoke test di stack asli untuk menutup celah mocking.
- `needs` membuat pipeline fail fast. `publish` cuma dari `main`.
- Token pipeline least-privilege. Secret smoke test dibuat acak per run.
- Image bertag commit SHA supaya bisa deploy versi persis dan rollback.

## Jawaban Knowledge Check

**Tutorial 1**
1. *Install tanpa venv?* Library masuk ke Python global dan bisa bentrok antar project.
2. *`main:app`?* `main` = file `main.py`, `app` = variabel objek FastAPI di dalamnya.
3. *Kenapa `.venv/` dan `storage/` di-ignore?* `.venv` besar dan spesifik mesin, cukup `requirements.txt`. `storage/` berisi data user.
4. *Uvicorn vs FastAPI?* Uvicorn = server ASGI yang menerima koneksi jaringan. FastAPI = framework yang berisi logika endpoint.
5. *Kenapa `--reload` bukan untuk production?* Boros resource (mengawasi file) dan bisa me-restart aplikasi tanpa disengaja.

**Tutorial 2–3**
1. *Kenapa multipart?* JSON cuma teks. Multipart membawa data biner per bagian.
2. *Tanpa `Path(...).name`?* Path traversal bisa menulis file di luar folder storage.
3. *Kenapa `201`?* Resource baru dibuat.
4. *Path sama, method beda?* Server mencocokkan kombinasi method + path.
5. *Kenapa `st_mtime` nggak bisa dipercaya?* Itu waktu modifikasi, bisa berubah saat file disalin atau diedit.

**Tutorial 5–6 (S3 & presigned URL)**
1. *Kenapa secret di `.env`?* Kode masuk Git, sedangkan secret nggak boleh ikut.
2. *`head_object` vs `get_object`?* Metadata saja vs isi file.
3. *Kenapa paginator?* S3 membatasi 1000 object per request.
4. *Kenapa cek sebelum `delete_object`?* S3 delete selalu sukses (idempotent). Kita ingin `404` yang jujur.
5. *Pindah ke AWS S3?* Cukup ganti endpoint, credential, dan bucket di `.env`.
6. *Presigned URL tanpa menghubungi Silo?* Cuma perhitungan HMAC dengan secret key.
7. *`200` vs `206`?* Seluruh isi vs sebagian (range request).

**Tutorial 7–8 (database)**
1. *Kenapa UUID key?* Nama bebas, rename murah, key nggak bisa ditebak.
2. *Unique constraint kalau udah dicek di kode?* Mencegah race condition saat dua request lolos pengecekan bersamaan.
3. *Urutan upload vs delete?* Supaya kegagalan cuma menyisakan object yatim, bukan metadata yang menunjuk ke data hilang.
4. *`Depends(get_db)` dengan `yield`?* Session dibuka per request dan pasti ditutup setelahnya (`finally`).
5. *Kenapa migration?* `create_all` nggak mengubah tabel yang sudah ada. Migration mencatat, menerapkan, dan membatalkan perubahan skema.

**Tutorial 9 (auth)**
1. *Authn vs authz?* Login = authn. "File ini milik siapa" = authz.
2. *Argon2 vs SHA256?* Argon2 sengaja lambat dan boros memori sehingga tebakan mahal, dan punya salt.
3. *Kalau `JWT_SECRET` bocor?* Siapa pun bisa membuat token atas nama siapa saja, termasuk admin.
4. *Kenapa `404` bukan `403`?* Supaya keberadaan file orang lain nggak bocor.
5. *Mitigasi JWT nggak bisa dicabut?* Umur 60 menit + cek `is_active` setiap request.

**Tutorial 12–13 (Docker & Nginx)**
1. *Image vs container?* Cetakan vs instance yang sedang berjalan.
2. *Kenapa `COPY requirements.txt` dipisah?* Cache layer `pip install`.
3. *Kenapa `0.0.0.0` di container?* `127.0.0.1` di container berarti container itu sendiri.
4. *Kenapa dua klien S3?* Host ikut ditandatangani, sedangkan browser dan container melihat alamat berbeda.
5. *`down` vs `down -v`?* `down` menghapus container, data aman. `-v` ikut menghapus volume (data).
6. *Batas upload Nginx vs FastAPI?* Nginx menolak sebelum isi dikirim. FastAPI tahu kuota per user.
7. *Kenapa `--forwarded-allow-ips "*"` aman di sini?* API cuma bisa diakses lewat Nginx, jadi header nggak bisa dipalsukan dari luar.

**Tutorial 14 (CI/CD)**
1. *CI vs CD?* Verifikasi otomatis vs pengemasan/pemasangan otomatis.
2. *Kenapa SQLite + moto?* Cepat tanpa server. Risiko beda perilaku ditutup dengan test di PostgreSQL dan smoke test di stack asli.
3. *Kenapa `.env` acak di CI?* Nggak perlu menyimpan secret sungguhan di GitHub.
4. *`needs` dan publish di `main`?* Fail fast. PR belum direview jadi nggak boleh menghasilkan image.
5. *Kenapa tag SHA?* Deploy versi persis dan rollback.

## Pertanyaan interview yang mungkin muncul

- *Bagaimana kamu menjaga konsistensi antara database dan object storage?* Lihat ADR-003 dan Challenges #12.
- *Apa yang terjadi kalau dua orang upload file bernama sama bersamaan?* Unique constraint + compensating delete.
- *Bagaimana kamu memastikan migration aman?* Named constraints, `server_default`, roundtrip + `alembic check` di CI.
- *Kenapa nggak langsung pakai cloud?* ADR-013: egress, RAM, biaya untuk penggunaan keluarga.
- *Ceritakan bug tersulit.* Challenges #13 (dua metode autentikasi) atau #14 (port bentrok + crash loop).
- *Apa yang belum aman?* `docs/security.md` → Known gaps. Menyebutkan kekurangan sendiri menunjukkan kematangan.
