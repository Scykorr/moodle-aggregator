# Moodle 5.2 (latest stable) + PHP 8.3 + Apache
FROM moodlehq/moodle-php-apache:8.3

ARG MOODLE_BRANCH=MOODLE_502_STABLE

ENV MOODLE_DOCKER_WWWROOT=/var/www/html \
    APACHE_DOCUMENT_ROOT=/var/www/html/public

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --depth 1 --branch "${MOODLE_BRANCH}" \
        https://github.com/moodle/moodle.git /var/www/html \
    && mkdir -p /var/www/moodledata \
    && chown -R www-data:www-data /var/www/html /var/www/moodledata \
    && chmod -R 755 /var/www/html \
    && chmod -R 777 /var/www/moodledata

COPY docker/entrypoint.sh /usr/local/bin/moodle-entrypoint.sh
COPY docker/apache-moodle.conf /etc/apache2/sites-available/000-default.conf
COPY docker/php/ /usr/local/lib/moodle-helpers/
RUN sed -i 's/\r$//' /usr/local/bin/moodle-entrypoint.sh \
    && chmod +x /usr/local/bin/moodle-entrypoint.sh \
    && a2enmod rewrite

WORKDIR /var/www/html
EXPOSE 80

ENTRYPOINT ["/usr/local/bin/moodle-entrypoint.sh"]
CMD ["apache2-foreground"]
