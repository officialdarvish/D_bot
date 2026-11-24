from pathlib import Path
from types import SimpleNamespace
from html.parser import HTMLParser
from app.services.setup_theme import panel_stylesheets
from app.services.setup_steps import staged
from app.api import admin_web as web


def test_setup_reuses_only_existing_same_origin_panel_stylesheets(tmp_path):
    css=tmp_path/'_next/static/chunks/theme.css';css.parent.mkdir(parents=True);css.write_text('body{}')
    (tmp_path/'admin.html').write_text('<link rel="stylesheet" href="/_next/static/chunks/theme.css"><link rel="stylesheet" href="https://untrusted.example/theme.css"><link rel="stylesheet" href="/_next/static/missing.css">')
    assert panel_stylesheets(tmp_path)=='<link rel="stylesheet" href="/_next/static/chunks/theme.css">'
    assert panel_stylesheets(tmp_path/'absent')==''


def rendered(monkeypatch):
    monkeypatch.setattr(web,'_session_csrf_token',lambda request:'csrf-only-for-test')
    monkeypatch.setattr(web,'_with_web_prefix',lambda request,path:'/private'+path)
    values={'force_join_enabled':'1','rules_enabled':'1','support_username':'@support','bot_name':'A < B','web_path':'private','setup_step':'0','feature_trials':'1'}
    page=web._setup_wizard_html(None,values)
    return staged(page,values,'/private','csrf-only-for-test',[SimpleNamespace(id=1,name='Sanaei test',server_type='xui')])


def test_setup_title_navigation_and_sensitive_fields(monkeypatch):
    page=rendered(monkeypatch)
    assert '<title>WIzard Setup D Bot</title>' in page
    assert 'id="setup-title">WIzard Setup D Bot</h1>' in page
    assert 'Initial D BOT Setup' not in page
    for name in ('setupBack','setupNext','setupFinish','setupProgress','setupLanguage','setupStepTitle'):
        assert page.count(f'id="{name}"')==1
    assert 'A &lt; B' not in page and 'name="bot_name"' not in page
    assert '/private/setup/save?csrf=' in page
    assert 'data-server="password"' in page and 'name="password"' not in page
    assert 'data-setup-restore="aes_password"' in page
    assert '/private/setup/options/discounts' in page


def test_server_selects_are_labelled_and_language_options_are_separate(monkeypatch):
    class Controls(HTMLParser):
        def __init__(self):
            super().__init__();self.labels=0;self.labelled=[]
        def handle_starttag(self,tag,attrs):
            if tag=='label':self.labels+=1
            if tag=='select':self.labelled.append(self.labels>0)
        def handle_endtag(self,tag):
            if tag=='label':self.labels-=1
    parser=Controls();parser.feed(rendered(monkeypatch))
    assert parser.labelled and all(parser.labelled)
    page=rendered(monkeypatch)
    assert 'Public / عمومی' not in page and 'class="setup-module"' in page
