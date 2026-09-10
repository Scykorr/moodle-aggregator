# Агрегатор в Docker с веб-интерфейсом

## Запуск

Все команды выполняются в `_main/federation`. На компьютере нужен Docker;
устанавливать Python, Tkinter или Node.js для веб-интерфейса не требуется.

```powershell
docker compose -f compose.aggregator.yml up -d --build
docker compose -f compose.aggregator.yml ps
```

Адрес по умолчанию: **http://localhost:8090** — **публичный каталог** факультетов и
кафедр (без пароля). Админка структуры и проверок: **http://localhost:8090/admin**.
Это самостоятельный сервис, он не требует предварительного запуска Keycloak.
Корневые контейнеры Moodle и `compose.yml` сервера идентификации не меняются.

В админке доступны факультеты (без обязательного Moodle), кафедры/площадки
(в том числе вне факультетов), drag-and-drop, адреса HTTP(S), проверка Moodle и
сохранение каталога. Публичная страница читает `GET /api/catalog`.

«Проверить» сначала сохраняет список. Результаты обновляются автоматически.
Несохранённые изменения отмечены под таблицей. При конкурентном редактировании
в разных браузерах сервер возвращает конфликт вместо перезаписи чужого списка.
Пароль (если настроен) остаётся в памяти вкладки, после перезагрузки вводится снова.

## Доступ из локальной сети

```powershell
Copy-Item .env.aggregator.example .env.aggregator
```

Укажите в `.env.aggregator`:

```dotenv
AGGREGATOR_BIND_IP=10.10.0.10
AGGREGATOR_PORT=8088
AGGREGATOR_TOKEN=replace-with-a-long-random-ascii-password
```

Замените IP на адрес интерфейса **этого Docker-хоста**, а пароль на собственный
длинный случайный ASCII-пароль. Файл не публикуется в Git. Запустите:

```powershell
docker compose --env-file .env.aggregator -f compose.aggregator.yml up -d --build
```

Открывайте публичный каталог `http://10.10.0.10:8088/` и админку
`http://10.10.0.10:8088/admin` с разрешённых компьютеров. Для доступа нужны
маршруты между подсетями и правило входящего TCP-порта в брандмауэре хоста.
По умолчанию публикация ограничена 127.0.0.1. **Каталог `/` публичный**;
админку `/admin` и API сохранения/проверок не публикуйте без `AGGREGATOR_TOKEN`:
они позволяют менять структуру и проверять доступные контейнеру адреса.
На недоверенных сегментах используйте HTTPS reverse proxy, поскольку HTTP
не шифрует пароль.

## Откуда проверяются Moodle

Запросы выполняет **контейнер**, не браузер и не Windows-хост. `localhost`
и `127.0.0.1` в строке сервера обозначают сам контейнер агрегатора. Для Moodle
на том же Docker-хосте используйте его LAN IP либо `host.docker.internal`
(добавлен через host-gateway). Для удалённых Moodle используйте их IP/имя,
доступное из Docker-сети. У Moodle может быть перенаправление на `wwwroot`:
этот конечный адрес тоже должен разрешаться и открываться из контейнера.

Если сервер перенаправляет на `localhost` или недоступное внутреннее имя,
проверьте его канонический URL и сетевую настройку. Обнаружение не меняет `wwwroot`.
HTTP поддерживается без принудительного перевода в HTTPS. Для SSO требования
к HTTPS остаются отдельными.

Зелёный статус означает признаки Moodle в HTML, а не проверенный логин.
Жёлтый — HTTP-сервер доступен, но Moodle не подтверждён/доступ ограничен.
Красный — ошибка HTTP, адреса, TLS, DNS или соединения. Анализируется первый
1 МиБ HTML, не более пяти редиректов. Таймаут каждой сетевой операции — 6 секунд;
время DNS и цепочка редиректов могут увеличить общее время.

Для внутренних CA добавьте доверенные сертификаты в производный образ
(`update-ca-certificates` при сборке) либо смонтируйте полный PEM trust bundle
и задайте `SSL_CERT_FILE`. Проверка TLS не отключается.

## Хранение, перезапуск и офлайн-перенос

Каталог факультетов/кафедр: `/data/catalog.json` на volume
`moodle-aggregator_aggregator_data`. Список адресов для проверок синхронизируется
в `/data/servers.json`. При первом запуске, если есть только `servers.json`,
создаётся каталог с площадками без факультета. В исходниках адресов сети и
результатов нет. Изменения сохраняются атомарно; результаты проверок временные
и после рестарта сбрасываются в «Не проверен».

```powershell
docker compose -f compose.aggregator.yml restart
docker compose -f compose.aggregator.yml logs --tail 100
docker compose -f compose.aggregator.yml stop
```

Для конфигурации LAN добавляйте тот же `--env-file .env.aggregator` ко всем
командам. Не используйте `down -v`, если нужно сохранить список.
Резервную копию каталога: `docker compose cp` из `/data/catalog.json`
(и при необходимости `/data/servers.json`) после сохранения. Храните вне Git.

Для машины без интернета заранее соберите образ и сохраните пакет:

См. пошаговую инструкцию и скрипты: **[offline-aggregator.md](offline-aggregator.md)**.

Кратко:

```powershell
# Источник:
.\scripts\export-aggregator.ps1
# Цель (офлайн):
# IMPORT-AGGREGATOR.cmd  внутри transfer-aggregator/
```

Ручной минимум:

```powershell
docker save -o moodle-aggregator.tar moodle-aggregator:local
# На целевой машине:
docker load -i moodle-aggregator.tar
docker compose --env-file .env.aggregator -f compose.aggregator.yml up -d --no-build --pull never
```

Образ переносит приложение; `volumes\aggregator_data.tgz` в пакете — каталог
и список для проверок. `.tar` и каталоги `transfer-*` исключены из Git.
Приложение работает от UID 10001, использует Waitress, не монтирует Docker socket
и не получает доступ к базам данных Moodle. `PUT /api/catalog` и проверки
требуют Origin и специальный заголовок; при заданном пароле — Bearer-токен.
`GET /api/catalog` (без `?admin=1`) публичен.

## Проверки разработки

Backend: Flask 3.1.3, Waitress 3.0.2; интерфейс — статические HTML/CSS/JS,
без CDN и внешних ресурсов. [Flask](https://pypi.org/project/Flask/),
[Waitress](https://pypi.org/project/waitress/).

```powershell
python -m pip install -r web/requirements.txt
python -m unittest discover -s web/tests -v
```

Тесты проверяют каталог (публичный GET, PUT с токеном, revision), миграцию
из `servers.json`, сохранение реестра проверок, конфликт изменений,
контроль доступа, защиту от запросов чужого сайта, очередь и запоздалые результаты.
