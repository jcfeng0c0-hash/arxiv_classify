import os
import pytest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base, Paper


def test_summary_inequalities_do_not_swallow_card_view():
    with patch.dict(os.environ, {'ARXIV_WEBUI_SESSION_SECRET': 'mobile-tests'}), patch('migrate_db.migrate'):
        import webui
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(Paper(arxiv_id='2401.12345', title='Test', abstract='Original abstract',
                     summary_cn='0.10<z<0.44\n<script>unsafe</script>', my_label='interested', version=2))
        db.commit()
    try:
        with patch.object(webui, 'get_db_session', sessions):
            client = webui.app.test_client()
            response = client.get('/?label=interested')
            assert response.status_code == 200
            soup = BeautifulSoup(response.data, 'html.parser')
            card = soup.select_one('#cardView')
            assert card is not None
            assert card.find_parent(id='paperList') is None
            assert '0.10<z<0.44' in soup.select_one('.summary-cn').get_text()
            assert soup.select_one('.summary-cn script') is None
            assert soup.select_one('#cardPrev') and soup.select_one('#cardNext')
            data = client.get('/api/papers').json['papers'][0]
            assert data['abstract'] == 'Original abstract'
            assert data['version'] == 2
    finally:
        engine.dispose()


def test_card_initialization_waits_for_page_script():
    source = (Path(__file__).resolve().parents[1] / 'templates/base.html').read_text()
    assert "document.addEventListener('DOMContentLoaded', () => applyViewMode(getViewMode()))" in source
    assert 'height: var(--card-viewport-height, 100vh)' in source
    assert 'grid-template-rows: minmax(0, 1fr) auto' in source
    assert 'grid-template-rows: 24px 66px 30px 20px 44px minmax(0, 1fr)' in source
    assert 'window.visualViewport' in source
    assert 'body.view-cards #cardActions' in source


@pytest.mark.parametrize('action,important', [('dismiss', False), ('important', True)])
@pytest.mark.parametrize('arxiv_id', ['2401.12345', 'astro-ph/0601001'])
def test_review_marks_read_and_important_without_reclassifying(action, important, arxiv_id):
    with patch.dict(os.environ, {'ARXIV_WEBUI_SESSION_SECRET': 'mobile-tests'}), patch('migrate_db.migrate'):
        import webui
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(Paper(arxiv_id=arxiv_id, title='Test', my_label='interested', is_read=False,
                     is_important_author=not important))
        db.commit()
    try:
        with patch.object(webui, 'get_db_session', sessions):
            response = webui.app.test_client().post(f'/api/paper/{arxiv_id}/review', json={'action': action})
            assert response.status_code == 200
            assert response.json == {'success': True, 'is_read': True, 'is_important': important}
        with sessions() as db:
            paper = db.query(Paper).one()
            assert paper.is_read and paper.reviewed_at is not None
            assert paper.is_important_author == important
            assert paper.my_label == 'interested'
    finally:
        engine.dispose()
