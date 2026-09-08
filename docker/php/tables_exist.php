<?php
// Exit 0 if Moodle config table already exists.
$host = getenv('MOODLE_DATABASE_HOST') ?: 'db';
$port = (int) (getenv('MOODLE_DATABASE_PORT') ?: 3306);
$name = getenv('MOODLE_DATABASE_NAME') ?: 'moodle';
$user = getenv('MOODLE_DATABASE_USER') ?: 'moodle';
$pass = getenv('MOODLE_DATABASE_PASSWORD') ?: 'moodlepass';
$prefix = getenv('MOODLE_DATABASE_PREFIX') ?: 'mdl_';

mysqli_report(MYSQLI_REPORT_OFF);
$m = @new mysqli($host, $user, $pass, $name, $port);
if (!$m || $m->connect_errno) {
    exit(1);
}

$table = $m->real_escape_string($prefix . 'config');
$db = $m->real_escape_string($name);
$res = $m->query(
    "SELECT COUNT(*) AS c FROM information_schema.tables " .
    "WHERE table_schema='{$db}' AND table_name='{$table}'"
);
if (!$res) {
    exit(1);
}
$row = $res->fetch_assoc();
exit(((int) $row['c']) > 0 ? 0 : 1);
