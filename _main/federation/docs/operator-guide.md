# Работа с агрегатором и Keycloak

Практическое руководство для текущего стенда: **два независимых Docker-стека**.
Они не обмениваются данными напрямую. Вместе дают обнаружение Moodle и единый
вход студентов.

## Два контейнерных стека

| Стек | Compose | Контейнеры | Зачем |
|---|---|---|---|
| Агрегатор | `compose.aggregator.yml` | `moodle-aggregator-aggregator-1` | Список Moodle, проверка HTTP(S), зелёный/жёлтый/красный статус |
| Идентификация | `compose.yml` | `moodle-identity-keycloak-1`, `moodle-identity-db-1` | Учётные записи студентов, OIDC/OAuth 2 для всех Moodle |

**Агрегатор не хранит пользователей.**  
**Keycloak не проверяет доступность Moodle и не ведёт список серверов для UI.**

Текущие адреса на этом ПК (localhost):

| Сервис | URL |
|---|---|
| Агрегатор | http://127.0.0.1:8090 |
| Keycloak (вход / admin) | https://127.0.0.1:8443 |
| Консоль администратора Keycloak | https://127.0.0.1:8443/admin |

Пароль bootstrap-админа Keycloak: файл `generated/.env`, переменная
`KC_BOOTSTRAP_ADMIN_PASSWORD`. Логин: `bootstrap-admin`.  
Секреты OAuth-клиентов Moodle: `generated/moodle-settings.md` (не в Git).

Сертификат Keycloak самоподписанный — браузер покажет предупреждение; для
стенда это нормально.

## Офлайн-перенос на другой ПК

- Агрегатор: [offline-aggregator.md](offline-aggregator.md) (`scripts/export-aggregator.ps1`)
- Keycloak: [offline-keycloak.md](offline-keycloak.md) (`scripts/export-identity.ps1`)

На целевом Windows 11 без интернета: Docker Desktop Running → `IMPORT-*.cmd`.

## Как запускать и останавливать

Все команды из папки `_main/federation`.

### Агрегатор

```powershell
docker compose --env-file .env.aggregator -f compose.aggregator.yml up -d --build
docker compose --env-file .env.aggregator -f compose.aggregator.yml ps
docker compose --env-file .env.aggregator -f compose.aggregator.yml stop
```

Порт задаётся в `.env.aggregator` (`AGGREGATOR_PORT`, сейчас **8090**, чтобы не
пересекаться с другими проектами на 8088). Подробности: [web-aggregator.md](web-aggregator.md).

### Keycloak

```powershell
docker compose --env-file generated/.env up -d
docker compose --env-file generated/.env ps
docker compose --env-file generated/.env stop
```

Не используйте `down -v` на рабочем Keycloak: удалится volume с пользователями.
Первый запуск уже сделал `prepare.py` и импорт realm `students`. Повторный
`prepare.py` без очистки `generated/` не перезапишет секреты (это защита).

## Роли: что делать в каком интерфейсе

### В агрегаторе (обнаружение)

1. Откройте http://127.0.0.1:8090.
2. Добавьте строку на каждый Moodle: LAN IP или полный HTTP(S) URL.
3. Не указывайте `localhost` / `127.0.0.1` для Moodle на том же Docker-хосте —
   проверка идёт **из контейнера**. Используйте LAN IP хоста или
   `host.docker.internal` (и следите, чтобы `$CFG->wwwroot` Moodle совпадал
   с адресом, на который идёт редирект).
4. «Проверить» / «Проверить все»: зелёный = в HTML есть признаки Moodle;
   жёлтый = сервер отвечает, Moodle не подтверждён; красный = сеть/HTTP/TLS.
5. «Сохранить список» пишет адреса в Docker volume (общий для браузеров).

Агрегатор **не** создаёт клиентов Keycloak и **не** настраивает OAuth в Moodle.

### В Keycloak (учётные записи)

1. Откройте https://127.0.0.1:8443/admin, войдите как `bootstrap-admin`.
2. Переключитесь в realm **`students`** (не `master` для студентов).
3. **Users → Add user**: имя, фамилия, уникальный email; задайте пароль
   (temporary → смена при первом входе). Саморегистрация в realm выключена.
4. Для постоянной работы создайте своего администратора с MFA и уберите
   зависимость от bootstrap-пароля (см. [deployment.md](deployment.md)).
5. Клиенты OIDC на Moodle уже заведены генератором (`moodle4`, `moodle5` и т.д.
   в Clients). Секреты — только в `moodle-settings.md`.

Новые студенты заводятся **только в Keycloak**. На Moodle локальная запись
появится сама при первом входе через «Единый аккаунт».

## Схема работы нескольких Moodle

```text
Студент
   │
   ├─► Keycloak (один логин/пароль)     ← контейнер identity
   │
   └─► Moodle A / B / C …               ← ваши серверы (не агрегатор)
         кнопка «Единый аккаунт»
         OAuth 2 → Keycloak

Администратор сети
   └─► Агрегатор                         ← контейнер aggregator
         список URL, проверка доступности
```

| Вопрос | Ответ |
|---|---|
| Где создавать студента? | Keycloak, realm `students` |
| Где курсы и оценки? | В каждом Moodle отдельно |
| Нужно ли регистрироваться на каждом новом Moodle? | Нет: тот же Keycloak → локальный профиль создаётся при первом SSO |
| Связывает ли агрегатор учётки? | Нет |
| Общий каталог курсов? | Нет, это отдельная задача после SSO |

Сопоставление полей: `sub` → username OAuth-сервиса Moodle (стабильный ключ).
Не привязывайте людей «по похожему email» вручную в БД.

Существующие локальные аккаунты Moodle: привязка через Linked logins на пилоте —
[migration.md](migration.md).

## Подключение ещё одного Moodle (кратко)

1. **Агрегатор:** добавить URL, убедиться в зелёном/приемлемом статусе из нужной сети.
2. **Инвентарь SSO:** вписать сайт в `sites.json` (HTTPS URL, IP, подсеть, версия 3.3+/4.x/5.x).
3. **Keycloak:** если realm уже импортирован, **нового клиента через повторный
   `prepare.py` не будет** — создайте confidential OIDC client вручную в realm
   `students` (Standard Flow, точный callback
   `<wwwroot>/admin/oauth2callback.php`, scopes profile/email, свой secret).
4. **Moodle:** Администрирование → OAuth 2 — сервис «Единый аккаунт» по
   [deployment.md](deployment.md) и секрету из консоли / `moodle-settings.md`.
5. У Moodle должен быть рабочий **HTTPS** и корректный `$CFG->wwwroot`.
6. Пилотный вход студента с Keycloak; для старых учёток — Linked logins.

Локальный контейнер `moodle_app` сейчас на HTTP (`wwwroot=http://localhost`) —
полный SSO к нему на стенде ещё не готов, пока не настроен TLS.

## Типовые команды диагностики

```powershell
# Агрегатор жив?
curl.exe -s http://127.0.0.1:8090/healthz

# Keycloak discovery (нужен trust к certs/ca.crt)
python probe.py --ca certs/ca.crt

# Логи
docker compose --env-file .env.aggregator -f compose.aggregator.yml logs --tail 50
docker compose --env-file generated/.env logs --tail 50 keycloak
```

`probe.py` проверяет и IdP, и URL из `sites.json`. Заглушки вроде
`*.invalid` дадут FAIL по DNS — на Keycloak это не влияет, если строка
`OK keycloak: discovery and issuer` есть.

## Безопасность на стенде

- `generated/`, `certs/`, `sites.json`, `.env.aggregator` не коммитить (уже в `.gitignore`).
- Перед выносом в LAN: задать `AGGREGATOR_TOKEN`, сменить bind IP, для Keycloak —
  LAN IP/`idp_url` и нормальный сертификат с SAN.
- Пароль bootstrap после создания постоянного админа ротировать/ограничить.

## Связанные документы

- [architecture.md](architecture.md) — зачем Keycloak, границы SSO  
- [deployment.md](deployment.md) — развёртывание IdP и OAuth в Moodle  
- [migration.md](migration.md) — старые студенты и приёмка  
- [web-aggregator.md](web-aggregator.md) — детали панели агрегатора  
