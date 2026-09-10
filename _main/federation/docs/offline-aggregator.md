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
  volumes/aggregator_data.tgz      # catalog.json + servers.json, если volume был
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
2. Запустите Docker Desktop → Status **Running** (кита в трее, зелёный).
3. Скопируйте папку `transfer-aggregator` на диск.
4. Дважды щёлкните **`IMPORT-AGGREGATOR.cmd`**  
   либо из `cmd.exe`:

```bat
cd /d D:\path\transfer-aggregator
IMPORT-AGGREGATOR.cmd
```

Не запускайте `.ps1` двойным щелчком через «Открыть с помощью» — только через `.cmd`
или:

```bat
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\scripts\import-aggregator.ps1" -PackageDir "%cd%."
```

Обратите внимание на `%cd%.` / `%~dp0.` — точка после пути обязательна:
иначе хвостовой `\` в кавычках ломает разбор аргументов PowerShell.

5. Откройте:
   - каталог (студенты): **http://127.0.0.1:8090/**
   - админку: **http://127.0.0.1:8090/admin**  
   (порт из `runtime\.env.aggregator`).

Скрипт:

- загружает образ (`docker load`, без registry);
- копирует compose/env в `transfer-aggregator\runtime`;
- поднимает контейнер с `--no-build --pull never` и `pull_policy: never`;
- при наличии `volumes\aggregator_data.tgz` восстанавливает каталог и probe-список;
- проверяет `http://127.0.0.1:<port>/healthz`.

### Если CMD пишет ошибку

| Сообщение | Что сделать |
|---|---|
| Docker Desktop is not running | Запустить Docker Desktop и дождаться Running |
| Missing image file | Скопирован неполный пакет — нужен `images\moodle-aggregator-local.tar` |
| Cannot overwrite variable Args… | Старая версия скрипта — возьмите свежий `transfer-aggregator` из репозитория |
| string is missing the terminator | Старый `.cmd` с `%~dp0` без точки — пересоберите пакет `export-aggregator.ps1` |

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
| Volume | Без `.tgz` каталог пустой — заполните в `/admin` |
| Секреты | Адреса в volume; пароль админки — `AGGREGATOR_TOKEN` в `.env.aggregator` |
| Публичный `/` | Без пароля; не путать с `/admin` |
| Не делать | `docker compose build` / `pull` на офлайн-ПК |

## Остановка / логи

```powershell
cd transfer-aggregator\runtime
docker compose --env-file .env.aggregator -f compose.aggregator.yml ps
docker compose --env-file .env.aggregator -f compose.aggregator.yml logs --tail 50
docker compose --env-file .env.aggregator -f compose.aggregator.yml stop
```

Не используйте `down -v`, если нужно сохранить каталог (`catalog.json`).
