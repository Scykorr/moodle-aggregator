# Развёртывание центрального входа

## 1. Инвентаризация

Рабочая папка: `_main/federation`. Скопируйте `sites.example.json` в `sites.json`.
Для каждого сайта внесите фактический URL, IPv4, подсеть и полный номер релиза.
Версию можно посмотреть администратором в уведомлениях/информации сайта или
в переменной `$release` файла `version.php` установленного Moodle (в новых
версиях — `public/version.php`). На локальном контейнере `moodle_app` 08.09.2026
прочитан релиз **5.2.2+ (Build: 20260903)**. Версии удалённых Moodle 3/4 неизвестны.

Поддерживаемый генератором путь — встроенный OAuth 2 для 3.3+ в ветке 3,
4.x и 5.x. Проверка номера не заменяет проверку исправлений безопасности и
совместимости фактического релиза. Moodle 3.0–3.2 сначала обновляют на копии либо
проектируют отдельную интеграцию. Номер `3` без младшего релиза не принимается.

`bind_ip` — IP интерфейса хоста, на котором запустится Keycloak, а не IP контейнера
и не произвольный удалённый адрес. Хост должен владеть этим адресом. Нестандартный
порт задаётся в `idp_url`, например `https://sso.campus.example:8443`.
Пути в URL Moodle поддерживаются; путь в `idp_url` этим шаблоном не поддержан.
Не создавайте новые экземпляры существующих Moodle: подключаются уже имеющиеся.

## 2. HTTPS и сеть

Подготовьте маршрутизацию и DNS по [схеме](architecture.md). Создайте `certs/`:

- `server.crt` — сертификат Keycloak и промежуточная цепочка в PEM;
- `server.key` — соответствующий незашифрованный PEM-ключ, доступный только
  администраторам хоста и процессу Keycloak;
- `ca.crt` — цепочка доверенного внутреннего CA для диагностики.

В сертификате должен быть SAN имени из `idp_url` (или IP SAN для IP URL).
Установите доверие к CA на клиентских ПК и в PHP/cURL контейнеров Moodle.
На Linux обеспечьте чтение ключа UID 1000 контейнера, например владельцем/ACL,
не делайте закрытый ключ общедоступным. В Windows настройте доступ к каталогу
для Docker Desktop и ограничьте NTFS-права администратором/оператором сервиса.

Keycloak сам завершает TLS на 8443; Compose публикует его как 443 на выбранном IP.
HTTP, порт БД и health/management port наружу не публикуются. Административная
консоль находится на том же HTTPS listener; ограничение `/admin` по источнику
требует отдельного proxy/сетевого решения перед промышленным развёртыванием.
[Keycloak TLS](https://www.keycloak.org/server/enabletls),
[production guidance](https://www.keycloak.org/server/configuration-production).

Каждый Moodle тоже должен иметь рабочий HTTPS и правильный `$CFG->wwwroot`.
Исходный стек в корне пока использует HTTP: перед SSO настройте TLS на его
веб-сервере или доверенном reverse proxy. При завершении TLS на proxy проверьте
`sslproxy` и передаваемые заголовки по версии Moodle; не выставляйте их вслепую.
Простая замена `http` на `https` в `.env` не включает TLS на Apache.

## 3. Подготовка и запуск

```powershell
python prepare.py --validate-only
python prepare.py
docker compose --env-file generated/.env config --quiet
docker compose --env-file generated/.env pull
docker compose --env-file generated/.env up -d
docker compose --env-file generated/.env ps
docker compose --env-file generated/.env logs --tail 100 keycloak
```

В Compose закреплены Keycloak 26.7.3 и PostgreSQL 17.11. Перед обновлением
проверьте совместимость и восстановление БД на копии.
[Keycloak downloads](https://www.keycloak.org/downloads),
[PostgreSQL 17 releases](https://www.postgresql.org/docs/17/release.html).
Используется режим `start`, отдельная БД и постоянный volume;
для ускорения повторных запусков в будущем можно собрать оптимизированный образ.
[Контейнер Keycloak](https://www.keycloak.org/server/containers),
[база данных](https://www.keycloak.org/server/db).

Генератор создаёт `generated/.env`, `generated/realm/students-realm.json`
(имя зависит от realm) и `generated/moodle-settings.md`. Они содержат секреты,
не отправляйте их в GitHub. На Unix родительский `generated` закрыт режимом 0700;
на Windows конфиденциальность зависит от NTFS ACL. Экспорт realm читается
контейнером через bind mount. Администраторы Docker имеют доступ к env и секретам.

Войдите в Keycloak как `bootstrap-admin` с паролем из локального `.env`.
Создайте постоянного администратора с MFA и удалите временного bootstrap admin
по инструкции Keycloak. В realm `students` настройте внутренний SMTP для
подтверждения email и восстановления пароля. Для пилотного пользователя
администратор может подтвердить проверенный email сам; не отключайте проверку
всем пользователям ради обхода отсутствующей почты.

Учетные записи создаёт администратор в Keycloak; саморегистрация выключена.
Пароль задаётся там один раз (временный с обязательной сменой при первом входе).
Заполните имя, фамилию, уникальный подтверждённый email. AD не нужен.

## 4. Настройки каждого Moodle

Откройте `generated/moodle-settings.md` локально. Для каждого сайта:

1. Администрирование → Сервер → Сервисы OAuth 2: создайте пользовательский
   сервис с названием «Единый аккаунт», client ID и secret именно этого Moodle.
2. Base URL — `https://<sso>/realms/<realm>`. Включите использование на странице
   входа, задайте scopes входа и offline scopes `openid profile email`.
3. Проверьте discovery и три endpoint: authorization, token, userinfo. При
   ручной настройке они находятся под `/protocol/openid-connect/` с окончаниями
   `auth`, `token`, `userinfo`. Client authentication — секрет клиента;
   Keycloak принимает стандартные способы client_secret_basic/client_secret_post.
4. В сопоставлении полей сервиса удалите конфликтующие mappings для username
   и установите `sub → username`, `given_name → firstname`, `family_name → lastname`,
   `email → email`. Системный аккаунт для обычного входа не нужен.
5. Включите OAuth 2 в «Плагины → Аутентификация». Сохраните аварийный локальный
   административный вход. Политику создания новых пользователей меняйте только
   после этапа привязки из [плана миграции](migration.md).

Keycloak-клиенты разрешают только Authorization Code, являются confidential и
имеют разные секреты. Разрешён ровно `<wwwroot>/admin/oauth2callback.php`, без `*`.
Это путь **встроенного OAuth 2**, не callback плагина `auth_oidc`.
Не включайте принудительный PKCE до проверки поддержки конкретным старым Moodle.
На более новых релизах его можно включить согласованно с клиентом.

Основание настроек: [OAuth 2 services](https://docs.moodle.org/311/en/OAuth_2_services),
[OAuth 2 authentication](https://docs.moodle.org/405/en/OAuth_2_authentication).

## 5. Проверка и добавление сайтов

```powershell
python probe.py --ca certs/ca.crt
```

Запускайте диагностику с каждой нужной подсети. Она проверяет текущую машину:
проверка с Windows-хоста не доказывает доступность из PHP-контейнера Moodle.
Из каждого Moodle дополнительно выполните тест OAuth 2 в интерфейсе и вход
пилотного студента. Диагностика не отключает проверку сертификата и не авторизует
пользователей.

`--import-realm` импортирует realm только при первом старте. Если realm уже есть,
перезапуск не применит новые клиенты. [Поведение импорта](https://www.keycloak.org/server/importExport).
Для нового Moodle добавьте запись в `sites.json`, выполните `--validate-only`,
создайте отдельный confidential OIDC client в существующем realm через консоль,
включите Standard Flow, выключите Direct Access Grants, задайте точный callback
и scopes profile/email. Секрет возьмите из Credentials этого клиента и настройте
Moodle по шагам выше. Генератор первичного развёртывания специально не имеет
`--force`: нельзя затереть работающие секреты или realm ради нового сайта.

## 6. Офлайн и резервное копирование

На машине с интернетом загрузите образы и сохраните их для переноса:

```powershell
docker pull quay.io/keycloak/keycloak:26.7.3
docker pull postgres:17.11
docker save -o identity-images.tar quay.io/keycloak/keycloak:26.7.3 postgres:17.11
# На целевом сервере:
docker load -i identity-images.tar
docker compose --env-file generated/.env up -d --pull never
```

Образы и ключи не публикуются; секреты лучше генерировать на целевом сервере.
Для эксплуатации резервируйте PostgreSQL, конфигурацию, сертификаты/ключи и
каждый Moodle отдельно. Для логического дампа используйте `pg_dump -Fc` в файл
внутри контейнера и `docker compose cp` для вывода, чтобы PowerShell не испортил
бинарный dump перенаправлением. Проверяйте восстановление на изолированной БД.
Realm JSON первого запуска не является актуальной резервной копией пользователей.
Обычная остановка: `docker compose --env-file generated/.env stop`;
не применяйте `down -v` к рабочему серверу.
