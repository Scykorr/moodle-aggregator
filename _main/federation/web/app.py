"""Docker-hosted Moodle aggregator: public catalog portal and admin checks."""
import hmac
import os

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from catalog import Catalog
from registry import ConflictError, Registry


def create_app(directory=None, token=None, registry=None, catalog=None):
    app = Flask(__name__, static_folder='static')
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
    data_dir = directory or os.environ.get('DATA_DIR', '/data')
    inventory = registry or Registry(data_dir)
    store = catalog or Catalog(data_dir, registry=inventory)
    app.extensions['registry'] = inventory
    app.extensions['catalog'] = store
    token = os.environ.get('AGGREGATOR_TOKEN', '') if token is None else token

    @app.before_request
    def protect_api():
        if not request.path.startswith('/api/'):
            return None
        public_get = request.method in ('GET', 'HEAD', 'OPTIONS') and request.path == '/api/catalog'
        if public_get:
            return None
        if token and not hmac.compare_digest(
                request.headers.get('Authorization', '').encode(),
                ('Bearer ' + token).encode()):
            return jsonify(error='Введите пароль администратора.'), 401
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('X-Aggregator-Request') != '1':
                return jsonify(error='Запрос отклонён.'), 403
            origin = request.headers.get('Origin')
            if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
                return jsonify(error='Запрос с другого сайта отклонён.'), 403
        return None

    @app.after_request
    def response_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.get('/')
    def portal():
        return send_from_directory(app.static_folder, 'portal.html')

    @app.get('/admin')
    def admin():
        return send_from_directory(app.static_folder, 'admin.html')

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    @app.get('/api/catalog')
    def get_catalog():
        # Public read: no check statuses. Admin UI uses ?admin=1 with auth via before_request.
        if request.args.get('admin') == '1':
            if token:
                expected = ('Bearer ' + token).encode()
                if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), expected):
                    return jsonify(error='Введите пароль администратора.'), 401
            return jsonify(store.snapshot(include_states=True))
        return jsonify(store.public_snapshot())

    def payload():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Ожидается JSON-объект.')
        return data

    @app.put('/api/catalog')
    def save_catalog():
        data = payload()
        return jsonify(store.replace(data, data.get('revision')))

    @app.get('/api/servers')
    def servers():
        return jsonify(inventory.snapshot())

    @app.put('/api/servers')
    def save():
        data = payload()
        return jsonify(inventory.replace(data.get('servers'), data.get('revision')))

    @app.post('/api/check')
    def check():
        return jsonify(inventory.check(payload().get('ids'))), 202

    @app.errorhandler(ValueError)
    def bad_request(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(ConflictError)
    def conflict(exc):
        return jsonify(error=str(exc)), 409

    @app.errorhandler(OSError)
    def storage_error(exc):
        app.logger.error('Inventory storage error: %s', type(exc).__name__)
        return jsonify(error='Не удалось сохранить список. Проверьте доступность тома данных.'), 503

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=f'Ошибка запроса: HTTP {exc.code}'), exc.code

    return app


if __name__ == '__main__':
    from waitress import serve
    serve(create_app(), host='0.0.0.0', port=8080, threads=8, max_request_body_size=2 * 1024 * 1024)
