<?php
// Wait until MariaDB accepts connections (mysqli).
$host = getenv('MOODLE_DATABASE_HOST') ?: 'db';
$port = (int) (getenv('MOODLE_DATABASE_PORT') ?: 3306);
$user = getenv('MOODLE_DATABASE_USER') ?: 'moodle';
$pass = getenv('MOODLE_DATABASE_PASSWORD') ?: 'moodlepass';

mysqli_report(MYSQLI_REPORT_OFF);
$m = @new mysqli($host, $user, $pass, '', $port);
if ($m && !$m->connect_errno) {
    fwrite(STDOUT, "ok\n");
    exit(0);
}
exit(1);
