# Офлайн-развёртывание Keycloak (Windows 11 + Docker)

Перенос контейнеров **Keycloak + PostgreSQL** на ПК **без интернета**.
На целевой машине нет `docker pull`: только `docker load` и
`compose up --pull never`.

Пакет **содержит секреты** (`generated/.env`, TLS-ключи, client secrets).
Не публикуйте его в Git/общий чат.

Агрегатор переносится отдельно: [offline-aggregator.md](offline-aggregator.md).

## Что нужно на машине-источнике

- Docker Desktop, образы уже загружены:
  - `quay.io/keycloak/keycloak:26.7.3`
  - `postgres:17.11`
- В `_main/federation` уже есть:
  - `generated/.env` и `generated/realm/` (после `python prepare.py`)
  - `certs/server.crt`, `certs/server.key` (и желательно `ca.crt`)
  - желательно `sites.json`

```powershell
cd D:\PycharmProjects\moodle\_main\federation
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\export-identity.ps1
```

Каталог `transfer-identity/`:

```text
transfer-identity/
  IMPORT-IDENTITY.cmd
  README.txt
  images/keycloak-26.7.3.tar
  images/postgres-17.11.tar
  volumes/identity_db.tgz       # пользователи/realm из БД, если volume был
  project/
    compose.yml
    generated/                  # секреты
    certs/
    sites.json                  # если был
    docs/...
  scripts/
    import-identity.ps1
    _offline-lib.ps1
```

Скопируйте **весь** каталог на USB.

## Целевой ПК (без интернета)

1. Docker Desktop **Running**.
2. Скопируйте `transfer-identity` на диск.
3. Запустите **`IMPORT-IDENTITY.cmd`**  
   или из `cmd.exe`:

```bat
cd /d D:\path\transfer-identity
IMPORT-IDENTITY.cmd
```

Важно: в `.cmd` используется `-PackageDir "%~dp0."` (с точкой). Не убирайте точку —
хвостовой `\` без неё ломает разбор аргументов PowerShell.

4. Откройте **https://127.0.0.1:8443/admin** (принять самоподписанный сертификат).
5. Логин: `bootstrap-admin`  
   Пароль: `project\generated\.env` → `KC_BOOTSTRAP_ADMIN_PASSWORD`  
   (после импорта рабочая копия также в `transfer-identity\runtime\generated\.env`).

Скрипт:

- `docker load` обоих образов;
- копирует compose/generated/certs в `runtime\`;
- при наличии `identity_db.tgz` поднимает Postgres, восстанавливает volume,
  затем поднимает Keycloak (**чтобы не затереть БД повторным пустым init**);
- ждёт OIDC discovery realm `students`;
- использует `pull_policy: never` в compose.

## Ручные команды (эквивалент)

На источнике (есть сеть один раз):

```powershell
docker pull quay.io/keycloak/keycloak:26.7.3
docker pull postgres:17.11
docker save -o keycloak-26.7.3.tar quay.io/keycloak/keycloak:26.7.3
docker save -o postgres-17.11.tar postgres:17.11
```

На цели:

```powershell
docker load -i postgres-17.11.tar
docker load -i keycloak-26.7.3.tar
# каталог с compose.yml, generated/, certs/:
docker compose --env-file generated/.env up -d --pull never
```

Проверка:

```powershell
curl.exe -k -s https://127.0.0.1:8443/realms/students/.well-known/openid-configuration
```

## Важно

| Тема | Деталь |
|---|---|
| Интернет на цели | Не нужен после `docker load` |
| Секреты | Весь пакет конфиденциален |
| Volume БД | Без `.tgz` Keycloak поднимется «с нуля» и импортирует realm JSON из `generated/realm` (пользователей, созданных после первого запуска, не будет) |
| С volume | Восстанавливаются пользователи и клиенты из снимка БД |
| Порт / IP | Из `generated/.env`: `IDP_BIND_IP`, `IDP_HTTPS_PORT`, `IDP_URL` |
| Moodle SSO | На каждом Moodle всё ещё нужна ручная настройка OAuth 2 и HTTPS |
| Не делать | `docker pull`, `down -v` на рабочей БД без бэкапа |

## Остановка / логи

```powershell
cd transfer-identity\runtime
docker compose --env-file generated/.env ps
docker compose --env-file generated/.env logs --tail 80 keycloak
docker compose --env-file generated/.env stop
```

Подробности повседневной работы: [operator-guide.md](operator-guide.md).  
Первичная настройка realm на машине с Python: [deployment.md](deployment.md).
