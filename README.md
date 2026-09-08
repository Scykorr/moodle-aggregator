# Moodle Offline (Docker)

Локальный стек **Moodle 5.2** (ветка `MOODLE_502_STABLE`) + MariaDB 11.4 для работы в **локальной сети без интернета**, с возможностью переноса на другой ПК и GUI-утилитой настройки.

## Состав

| Компонент | Назначение |
|-----------|------------|
| `docker-compose.yml` | Moodle + MariaDB |
| `Dockerfile` | Образ Moodle 5.2 на PHP 8.3 |
| `scripts/export-for-transfer.ps1` | Сборка пакета для USB (образы + проект) |
| `scripts/import-and-start.ps1` | Загрузка образов и запуск на целевом ПК |
| `configurator/` | Python GUI → `MoodleConfigurator.exe` |
| `docs/` | Руководства на русском |

## Быстрый старт (ПК с интернетом)

1. Установите [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. В каталоге проекта:

```powershell
copy .env.example .env
docker compose build
docker compose up -d
```

3. Соберите конфигуратор:

```powershell
cd configurator
.\build.ps1
```

4. Запустите `configurator\dist\MoodleConfigurator.exe`, укажите LAN IP и нажмите **Применить и перезапустить**.

5. Для переноса:

```powershell
.\scripts\export-for-transfer.ps1
```

Скопируйте папку `transfer-package` на целевой компьютер.

## На целевом ПК (без интернета)

1. Установите Docker Desktop (установочный файл лучше заранее скачать и положить в пакет).
2. Скопируйте содержимое `transfer-package`.
3. Из `project\scripts` выполните `.\import-and-start.ps1`.
4. Запустите `MoodleConfigurator.exe`, задайте IP этого ПК в сети, примените.
5. Откройте в браузерах сети: `http://<IP>/`.

Учётка по умолчанию (см. `.env`): `admin` / `Admin123!`.

## Документация

- [_main/README.md](_main/README.md) — развитие проекта и федерация Moodle
- [_main/federation/docs/web-aggregator.md](_main/federation/docs/web-aggregator.md) —
  **Docker-агрегатор с веб-интерфейсом** на порту 8088: список HTTP(S)-серверов и проверки.
- Перед публикацией: `git add <файлы>`, затем `python scripts/check_repository.py`.
  Проверка ограничивает размер каждого файла 5 МиБ и исключает бинарные файлы;
  дополнительно просмотрите `git diff --cached` на предмет секретов и персональных данных.

- [docs/01-развёртывание.md](docs/01-развёртывание.md) — развёртывание и перенос
- [docs/02-работа-с-конфигуратором.md](docs/02-работа-с-конфигуратором.md) — работа с EXE
