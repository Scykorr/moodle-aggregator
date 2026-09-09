# Офлайн-развёртывание агрегатора (Windows 11 + Docker)

Перенос **готового** Docker-образа агрегатора на ПК **без интернета**.
Сборка на целевой машине не нужна: только `docker load` и `compose up --no-build --pull never`.

Агрегатор **не** содержит Keycloak и пользователей. Отдельный пакет IdP:
[offline-keycloak.md](offline-keycloak.md).

## Что нужно на машине-источнике (есть сеть или уже скачанные слои)

- Docker Desktop
- Рабочая папка `_main/federation`
- Образ `moodle-aggregator:local` (если нет — скрипт соберёт его)

```powershell
cd D:\PycharmProjects\moodle\_main\federation
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\export-aggregator.ps1
```

Появится каталог `transfer-aggregator/` (в Git не коммитится):

```text
transfer-aggregator/
  IMPORT-AGGREGATOR.cmd
  README.txt
  images/moodle-aggregator-local.tar
  volumes/aggregator_data.tgz      # список серверов, если volume уже был
  project/
    compose.aggregator.yml
    .env.aggregator
    docs/...
  scripts/
    import-aggregator.ps1
    _offline-lib.ps1
```

Скопируйте **весь** `transfer-aggregator` на USB / внешний диск.

## Целевой ПК (без интернета)

1. Установите Docker Desktop заранее (установочный файл тоже можно привезти на USB).
2. Запустите Docker Desktop → Status **Running**.
3. Скопируйте папку `transfer-aggregator` на диск.
4. Дважды щёлкните **`IMPORT-AGGREGATOR.cmd`**  
   либо:

```powershell
cd <путь>\transfer-aggregator
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\import-aggregator.ps1 -PackageDir .
```

5. Откройте **http://127.0.0.1:8090** (порт из `runtime\.env.aggregator`).

Скрипт:

- загружает образ (`docker load`, без registry);
- копирует compose/env в `transfer-aggregator\runtime`;
- поднимает контейнер с `--no-build --pull never` и `pull_policy: never`;
- при наличии `volumes\aggregator_data.tgz` восстанавливает список серверов;
- проверяет `http://127.0.0.1:<port>/healthz`.

## Ручные команды (эквивалент)

На источнике:

```powershell
docker compose -f compose.aggregator.yml build
docker save -o moodle-aggregator-local.tar moodle-aggregator:local
```

На цели:

```powershell
docker load -i moodle-aggregator-local.tar
# в каталоге с compose.aggregator.yml и .env.aggregator:
docker compose --env-file .env.aggregator -f compose.aggregator.yml up -d --no-build --pull never
curl.exe -s http://127.0.0.1:8090/healthz
```

## Важно

| Тема | Деталь |
|---|---|
| Интернет на цели | Не нужен, если образ уже в `.tar` |
| `localhost` в списке Moodle | Проверка идёт из контейнера — используйте LAN IP / `host.docker.internal` |
| Порт | По умолчанию **8090** (не 8088 — занят другими проектами) |
| Volume | Без `.tgz` список серверов пустой — его можно заполнить в UI |
| Секреты | В пакете только адреса; пароль панели — `AGGREGATOR_TOKEN` в `.env.aggregator` |
| Не делать | `docker compose build` / `pull` на офлайн-ПК |

## Остановка / логи

```powershell
cd transfer-aggregator\runtime
docker compose --env-file .env.aggregator -f compose.aggregator.yml ps
docker compose --env-file .env.aggregator -f compose.aggregator.yml logs --tail 50
docker compose --env-file .env.aggregator -f compose.aggregator.yml stop
```

Не используйте `down -v`, если нужно сохранить список серверов.
