#!/bin/bash
set -euo pipefail

MOODLE_DIR="${MOODLE_DOCKER_WWWROOT:-/var/www/html}"
DATA_DIR="${MOODLE_DATAROOT:-/var/www/moodledata}"
CONFIG_FILE="${MOODLE_DIR}/config.php"
HELPERS="/usr/local/lib/moodle-helpers"

DB_HOST="${MOODLE_DATABASE_HOST:-db}"
DB_PORT="${MOODLE_DATABASE_PORT:-3306}"
DB_NAME="${MOODLE_DATABASE_NAME:-moodle}"
DB_USER="${MOODLE_DATABASE_USER:-moodle}"
DB_PASS="${MOODLE_DATABASE_PASSWORD:-moodlepass}"
DB_PREFIX="${MOODLE_DATABASE_PREFIX:-mdl_}"

WWWROOT="${MOODLE_WWWROOT:-http://localhost}"
SITE_FULLNAME="${MOODLE_SITE_FULLNAME:-Moodle LMS}"
SITE_SHORTNAME="${MOODLE_SITE_SHORTNAME:-Moodle}"
ADMIN_USER="${MOODLE_ADMIN_USER:-admin}"
ADMIN_PASS="${MOODLE_ADMIN_PASSWORD:-Admin123!}"
ADMIN_EMAIL="${MOODLE_ADMIN_EMAIL:-admin@example.com}"
LANG="${MOODLE_LANG:-ru}"

export MOODLE_DATABASE_HOST MOODLE_DATABASE_PORT MOODLE_DATABASE_NAME
export MOODLE_DATABASE_USER MOODLE_DATABASE_PASSWORD MOODLE_DATABASE_PREFIX
export MOODLE_DOCKER_WWWROOT

mkdir -p "${DATA_DIR}"
chown -R www-data:www-data "${DATA_DIR}" 2>/dev/null || true

write_config() {
  cat > "${CONFIG_FILE}" <<EOF
<?php
unset(\$CFG);
global \$CFG;
\$CFG = new stdClass();

\$CFG->dbtype    = 'mariadb';
\$CFG->dblibrary = 'native';
\$CFG->dbhost    = '${DB_HOST}';
\$CFG->dbname    = '${DB_NAME}';
\$CFG->dbuser    = '${DB_USER}';
\$CFG->dbpass    = '${DB_PASS}';
\$CFG->prefix    = '${DB_PREFIX}';
\$CFG->dboptions = [
    'dbpersist' => 0,
    'dbport' => ${DB_PORT},
    'dbsocket' => '',
    'dbcollation' => 'utf8mb4_unicode_ci',
];

\$CFG->wwwroot   = '${WWWROOT}';
\$CFG->dataroot  = '${DATA_DIR}';
\$CFG->admin     = 'admin';
\$CFG->directorypermissions = 02777;
\$CFG->pathtophp = '/usr/local/bin/php';

require_once(__DIR__ . '/lib/setup.php');
EOF
  chown www-data:www-data "${CONFIG_FILE}" 2>/dev/null || true
  chmod 640 "${CONFIG_FILE}" 2>/dev/null || true
}

echo "[moodle] Waiting for database ${DB_HOST}:${DB_PORT}..."
ready=0
for i in $(seq 1 90); do
  if php "${HELPERS}/db_ping.php" >/dev/null 2>&1; then
    echo "[moodle] Database is ready."
    ready=1
    break
  fi
  sleep 2
done
if [ "${ready}" -ne 1 ]; then
  echo "[moodle] ERROR: database not reachable" >&2
  exit 1
fi

if ! php "${HELPERS}/tables_exist.php"; then
  echo "[moodle] First-time CLI install (wwwroot=${WWWROOT})..."
  rm -f "${CONFIG_FILE}"
  php "${MOODLE_DIR}/admin/cli/install.php" \
    --lang="${LANG}" \
    --wwwroot="${WWWROOT}" \
    --dataroot="${DATA_DIR}" \
    --dbtype=mariadb \
    --dbhost="${DB_HOST}" \
    --dbname="${DB_NAME}" \
    --dbuser="${DB_USER}" \
    --dbpass="${DB_PASS}" \
    --prefix="${DB_PREFIX}" \
    --fullname="${SITE_FULLNAME}" \
    --shortname="${SITE_SHORTNAME}" \
    --adminuser="${ADMIN_USER}" \
    --adminpass="${ADMIN_PASS}" \
    --adminemail="${ADMIN_EMAIL}" \
    --agree-license \
    --non-interactive
  chown www-data:www-data "${CONFIG_FILE}" 2>/dev/null || true
  php "${HELPERS}/update_wwwroot.php" "${WWWROOT}" || true
  echo "[moodle] Installation finished."
else
  echo "[moodle] Existing installation detected."
  if [ ! -f "${CONFIG_FILE}" ]; then
    echo "[moodle] Recreating missing config.php from environment..."
    write_config
  else
    php "${HELPERS}/update_wwwroot.php" "${WWWROOT}" || write_config
  fi
  php "${MOODLE_DIR}/admin/cli/purge_caches.php" 2>/dev/null || true
fi

if php "${HELPERS}/tables_exist.php"; then
  php "${MOODLE_DIR}/admin/cli/cfg.php" --name=fullname --set="${SITE_FULLNAME}" 2>/dev/null || true
  php "${MOODLE_DIR}/admin/cli/cfg.php" --name=shortname --set="${SITE_SHORTNAME}" 2>/dev/null || true
fi

echo "[moodle] Starting Apache on wwwroot=${WWWROOT}"
exec "$@"
