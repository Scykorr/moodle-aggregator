# Федерация Moodle

Единый вход в независимые Moodle через Keycloak, без Active Directory.
Исходный стек опубликован первым коммитом `91961fe` в
[Scykorr/moodle-aggregator](https://github.com/Scykorr/moodle-aggregator).

## Что готово

- `compose.yml`: отдельный Keycloak + PostgreSQL, HTTPS, отдельный volume.
- `sites.example.json`: реестр Moodle в нескольких подсетях.
- `prepare.py`: проверка реестра, генерация realm, отдельного OAuth-клиента и
  случайного секрета для каждого Moodle, локального файла настроек.
- `probe.py`: проверка DNS/IP, TLS и discovery сервера входа.
- [Варианты и архитектура](docs/architecture.md).
- [Развёртывание и подключение Moodle](docs/deployment.md).
- [Существующие аккаунты и приёмочные проверки](docs/migration.md).
- [Результаты проверки комплекта](docs/verification.md).

Это комплект для развёртывания, а не уже подключённая сеть: реальные адреса,
сертификаты и младшие версии Moodle пока неизвестны. На действующих Moodle
настройки не изменялись. Примерные версии `3.11`, `4.5`, `5.2` не являются
результатом обследования серверов пользователя.

## Начало работы

Из этой папки, Python 3.10+ и Docker Compose v2:

```powershell
Copy-Item sites.example.json sites.json
# Отредактировать sites.json: версии, IP, подсети, канонические HTTPS URL.
python prepare.py --validate-only
python prepare.py
# Подготовить certs/server.crt и certs/server.key по инструкции.
docker compose --env-file generated/.env config --quiet
docker compose --env-file generated/.env up -d
python probe.py --ca certs/ca.crt
```

Не запускайте примерные адреса как боевую конфигурацию. Файл `sites.json`,
папки `generated/` и `certs/` исключены из Git. Генератор не отправляет данные
по сети и не перезаписывает существующий `generated/`.

## Проверки разработчика

```powershell
python -m unittest discover -s tests -v
python prepare.py --config sites.example.json --validate-only
```

Проверки покрывают неверные версии, адреса и подсети, изоляцию клиентов,
случайные секреты, защиту от перезаписи и неверный OIDC issuer.
Полный вход студента на реальных Moodle проверяется отдельно по плану миграции.

Дополнительный интеграционный тест требует Docker и OpenSSL:

```powershell
python tests/smoke_identity.py --openssl 'C:\Program Files\Git\usr\bin\openssl.exe'
```

Он запускает отдельный временный проект на свободном localhost-порту, проверяет
настоящий TLS, discovery и импорт клиента через Admin API. Затем удаляет только
свои контейнеры и volume. Образы остаются в Docker cache. На Linux/macOS обычно
достаточно `python tests/smoke_identity.py`, если `openssl` есть в PATH.
