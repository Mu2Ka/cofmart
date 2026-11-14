import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.web import create_web_app
from tests.helpers import TOKEN, init_data


async def test_local_web_serves_mini_app_and_protects_api(db, tmp_path):
    (tmp_path / 'index.html').write_text('<html>Mini App</html>', encoding='utf-8')
    app = create_web_app(Settings('sqlite+aiosqlite://', bot_token=TOKEN), db, tmp_path)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/')).status_code == 200
            assert (await client.get('/api/health')).json() == {'status': 'ok'}
            assert (await client.get('/api/cafes')).status_code == 401
            response = await client.get('/api/cafes', headers={'Authorization': 'tma ' + init_data()})
            assert response.status_code == 200
            assert len(response.json()) == 2
            assert (await client.get('/.env')).status_code == 404
            assert (await client.get('/demo')).status_code == 404
