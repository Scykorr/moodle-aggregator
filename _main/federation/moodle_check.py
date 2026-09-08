"""Read-only HTTP(S) discovery for an administrator-supplied Moodle address."""
from dataclasses import dataclass
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_BODY = 1024 * 1024


@dataclass(frozen=True)
class CheckResult:
    kind: str
    message: str
    url: str
    status: int | None = None
    elapsed_ms: int = 0


def normalize_address(value):
    value = value.strip()
    if not value or re.search(r'\s|[\x00-\x1f\x7f]', value):
        raise ValueError('Введите IP или HTTP(S)-адрес без пробелов.')
    if '://' not in value:
        value = 'http://' + value
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Разрешены только HTTP и HTTPS.')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('Не указывайте логин и пароль в адресе.')
    try:
        port = parsed.port
        if port == 0:
            raise ValueError()
    except ValueError:
        raise ValueError('Порт должен быть числом от 1 до 65535.') from None
    host = parsed.hostname
    if ':' in host:
        host = '[' + str(ipaddress.IPv6Address(host)) + ']'
    elif re.fullmatch(r'[0-9.]+', host):
        host = str(ipaddress.IPv4Address(host))
    else:
        host = host.encode('idna').decode('ascii')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+', host):
            raise ValueError('Некорректное имя сервера.')
    authority = host + (f':{port}' if port is not None else '')
    path = urllib.parse.quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parsed.query, safe="%=&?/:;+,$@-._~")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), authority, path, query, ''))


class MoodleHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.generator = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name', '').lower() == 'generator':
            self.generator |= bool(re.search(r'\bmoodle\b', attrs.get('content', ''), re.I))
        for attribute in ('src', 'href', 'action'):
            if attrs.get(attribute):
                self.links.append(attrs[attribute])


def moodle_evidence(html):
    parser = MoodleHTML()
    parser.feed(html)
    if parser.generator:
        return 'метатег generator=Moodle'
    if re.search(r'\bM\.cfg\s*=', html) and any('/theme/' in link for link in parser.links):
        return 'конфигурация M.cfg и ресурсы темы Moodle'
    if (any('/lib/javascript.php' in link for link in parser.links)
            and any('/login/index.php' in link for link in parser.links)):
        return 'характерные пути JavaScript и входа Moodle'
    return None


class CheckedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = normalize_address(newurl)
        return super().redirect_request(req, fp, code, msg, headers, target)


def check_moodle(address, timeout=6):
    start = time.monotonic()
    url = address

    def result(kind, message, status=None):
        return CheckResult(kind, message, url, status, round((time.monotonic() - start) * 1000))

    try:
        url = normalize_address(address)
        # Check LAN directly; do not forward local addresses to environment proxies.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), CheckedRedirects(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        request = urllib.request.Request(url, headers={
            'User-Agent': 'MoodleAggregator-Availability/1.0',
            'Accept': 'text/html,application/xhtml+xml', 'Accept-Encoding': 'identity',
        })
        with opener.open(request, timeout=timeout) as response:
            url = response.geturl()
            status = response.status
            content_type = response.headers.get_content_type()
            if content_type not in ('text/html', 'application/xhtml+xml'):
                return result('unknown', f'HTTP {status}: сервер доступен, ответ не HTML.', status)
            body = response.read(MAX_BODY + 1)
            charset = response.headers.get_content_charset() or 'utf-8'
            try:
                html = body[:MAX_BODY].decode(charset, errors='replace')
            except LookupError:
                html = body[:MAX_BODY].decode('utf-8', errors='replace')
            evidence = moodle_evidence(html)
            if evidence:
                return result('moodle', f'HTTP {status}: найдены признаки Moodle ({evidence}).', status)
            suffix = ' Проверен первый 1 МиБ страницы.' if len(body) > MAX_BODY else ''
            return result('unknown', f'HTTP {status}: доступен, Moodle не подтверждён.' + suffix, status)
    except urllib.error.HTTPError as exc:
        url = exc.geturl()
        exc.close()
        if exc.code in (401, 403):
            return result('restricted', f'HTTP {exc.code}: сервер отвечает, доступ ограничен.', exc.code)
        return result('http_error', f'HTTP {exc.code}: ошибка HTTP или перенаправления.', exc.code)
    except (ssl.SSLError, urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        if isinstance(reason, ssl.SSLError):
            return result('unreachable', 'Ошибка HTTPS: проверьте сертификат и доверие к CA.')
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return result('unreachable', 'Время ожидания истекло. Проверьте адрес, сеть и брандмауэр.')
        if isinstance(reason, socket.gaierror):
            return result('unreachable', 'Имя сервера не найдено в DNS.')
        return result('unreachable', f'Нет соединения: {reason}')
    except (ValueError, UnicodeError) as exc:
        return result('invalid', str(exc))


def load_addresses(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('format') != 1 or not isinstance(data.get('addresses'), list):
        raise ValueError('Неподдерживаемый формат списка серверов.')
    if not all(isinstance(address, str) for address in data['addresses']):
        raise ValueError('Адреса должны быть строками.')
    return data['addresses']


def save_addresses(path, addresses):
    normalized = [normalize_address(value) for value in addresses if value.strip()]
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'format': 1, 'addresses': normalized},
                                   ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return len(normalized)
