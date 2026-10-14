# RTRMS - 3 services + gateway

| Container | SERVICE_ROLE | Serves |
|---|---|---|
| rtrms-web | web | landing, legal pages, public APIs, customer QR menu & ordering, /static |
| rtrms-owner | owner | /owner/... (dashboard, menu manager, staff, QR, reports, printing API) |
| rtrms-superadmin | superadmin | /superadmin/... |
| rtrms-gateway | - | nginx, the only exposed port (5000) - routes by URL path |

Same code and same image for all three; `SERVICE_ROLE` decides which routes a container answers
(others return 404). All share one SQLite file (WAL mode) and the uploads volumes.

## Run
    copy .env.example .env      (or reuse your existing .env)
    docker compose up -d --build
    open http://localhost:5000

Logs of one service: `docker compose logs -f owner`
Stop: `docker compose down`   |  Wipe data too: `docker compose down -v`
Single-container mode still works: run without SERVICE_ROLE (defaults to `all`).
