<?php
// Update $CFG->wwwroot in config.php. Usage: php update_wwwroot.php http://host
$root = $argv[1] ?? '';
$moodledir = getenv('MOODLE_DOCKER_WWWROOT') ?: '/var/www/html';
$file = rtrim($moodledir, '/') . '/config.php';

if ($root === '' || !is_file($file)) {
    fwrite(STDERR, "missing config or wwwroot\n");
    exit(1);
}

$c = file_get_contents($file);
$replacement = '$CFG->wwwroot   = ' . var_export($root, true) . ';';
$new = preg_replace(
    '/\$CFG->wwwroot\s*=\s*[\'"][^\'"]*[\'"];/',
    $replacement,
    $c,
    1,
    $count
);

if (!$count) {
    fwrite(STDERR, "wwwroot line not found\n");
    exit(1);
}

file_put_contents($file, $new);
fwrite(STDOUT, "wwwroot set to {$root}\n");
