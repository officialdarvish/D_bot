"""Setup layout layered on the same exported stylesheets as the web panel."""
import html
from html.parser import HTMLParser
from pathlib import Path
import re


def panel_stylesheets(root: Path | None = None) -> str:
    roots = [root] if root is not None else [Path(__file__).resolve().parents[2] / 'frontend_out', Path(__file__).resolve().parents[2] / 'frontend/out']
    class Styles(HTMLParser):
        def __init__(self):
            super().__init__()
            self.hrefs = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            href = attrs.get('href', '')
            if tag == 'link' and attrs.get('rel') == 'stylesheet' and re.fullmatch(r'/_next/static/[A-Za-z0-9_./-]+\.css', href) and '..' not in href:
                self.hrefs.append(href)
    for directory in roots:
        for page in (directory / 'admin.html', directory / 'admin/index.html'):
            if not page.is_file():
                continue
            parser = Styles()
            parser.feed(page.read_text(encoding='utf-8'))
            links = list(dict.fromkeys(h for h in parser.hrefs if (directory / h.lstrip('/')).is_file()))
            if links:
                return ''.join(f'<link rel="stylesheet" href="{html.escape(h, quote=True)}">' for h in links)
    return ''


SETUP_WIZARD_CSS = r'''
/* Fallback tokens match the web panel; exported panel CSS provides the shared theme. */
:root{color-scheme:dark;--bg:#07111f;--panel:rgba(15,31,51,.78);--line:rgba(145,190,253,.20);--text:#eef5ff;--muted:#91a3bd;--primary:#4b83db}
*{box-sizing:border-box}
body.setup-page{margin:0;min-height:100dvh;color:var(--text);background:radial-gradient(circle at 50% -8%,rgba(79,110,153,.18),transparent 32%),radial-gradient(circle at 105% 28%,rgba(48,102,181,.14),transparent 28%),linear-gradient(180deg,#091524,#06101d 48%,#071321);font-family:Vazirmatn,IRANSansX,Inter,system-ui,"Segoe UI",Tahoma,sans-serif;overflow-x:hidden}
.setup-page button,.setup-page input,.setup-page select,.setup-page textarea{font:inherit}
.setup-page h1,.setup-page h2{color:var(--text);font-weight:720;line-height:1.4;letter-spacing:-.02em}
.setup-page h1{font-size:clamp(24px,2.3vw,32px);margin:0}
.setup-page h2{font-size:clamp(17px,1.6vw,21px);margin:0 0 20px}
.setup-page p{line-height:1.85;overflow-wrap:anywhere}
.setup-page .muted{color:var(--muted)}
.setup-topbar,.setup-shell{position:relative;z-index:1;width:min(1180px,calc(100% - 48px));margin-inline:auto}
.setup-topbar{direction:ltr;display:flex;align-items:center;gap:20px;min-height:88px;padding-block:20px;border-bottom:1px solid rgba(145,190,253,.10)}
.setup-brand{display:flex;align-items:center;gap:12px;font-size:15px;font-weight:700;direction:ltr;margin-inline-end:auto}
.setup-brand-mark{display:grid;place-items:center;flex:none;width:40px;height:40px;border:1px solid rgba(145,190,253,.28);border-radius:12px;background:linear-gradient(145deg,#315d91,#1f416d);color:#dcecff;font-size:24px;box-shadow:0 10px 24px rgba(0,0,0,.18)}
.setup-status{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12px}
.setup-status-dot{width:7px;height:7px;border-radius:50%;background:#36c98f;box-shadow:0 0 12px rgba(54,201,143,.25)}
.setup-shell{padding-block:32px 48px}
.setup-card{position:relative;min-width:0;padding:clamp(20px,3vw,36px);border:1px solid rgba(145,190,253,.18);border-radius:15px;background:linear-gradient(145deg,rgba(35,55,82,.30),rgba(14,28,46,.68) 55%,rgba(12,24,41,.76));box-shadow:0 20px 60px rgba(0,0,0,.20),inset 0 1px 0 rgba(255,255,255,.035)}
.setup-intro{max-width:900px;font-size:13px;margin:10px 0 24px}
.setup-page .setup-progress-head{display:flex;align-items:center;justify-content:space-between;gap:16px;color:#c4d2e4;font-size:12px;margin-block:24px 10px}
#setupStepTitle{font-weight:650;min-width:0}
#setupPosition{flex:none;direction:ltr;color:var(--muted);font-variant-numeric:tabular-nums}
#setupProgress{display:block;appearance:none;width:100%;height:6px;border:0;border-radius:99px;overflow:hidden;background:rgba(7,18,32,.78);accent-color:#69a7ff}
#setupProgress::-webkit-progress-bar{background:rgba(7,18,32,.78);border-radius:99px}
#setupProgress::-webkit-progress-value{background:linear-gradient(90deg,#5e9ce8,#8bc0ff);border-radius:99px}
#setupProgress::-moz-progress-bar{background:linear-gradient(90deg,#5e9ce8,#8bc0ff);border-radius:99px}
.setup-page .steps{margin-top:26px}
.setup-page .step{min-width:0;padding:0;border:0;display:none}
.setup-page .step.current{display:block}
.setup-page .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;align-items:start}
.setup-page .full{grid-column:1/-1}
.setup-page label{display:grid;gap:8px;min-width:0;font-size:13px;color:#c4d2e4;text-align:start}
.setup-page input:not([type=radio]):not([type=checkbox]),.setup-page select,.setup-page textarea{width:100%;min-width:0;min-height:44px;border:1px solid rgba(136,169,214,.20);border-radius:9px;padding:11px 13px;background:rgba(10,24,41,.72);color:#eef5ff;outline:none;box-shadow:inset 0 1px 0 rgba(255,255,255,.015);transition:border-color .16s,box-shadow .16s}
.setup-page input:focus,.setup-page select:focus,.setup-page textarea:focus{border-color:rgba(111,169,248,.55);box-shadow:0 0 0 3px rgba(85,147,234,.08)}
.setup-page input::placeholder,.setup-page textarea::placeholder{color:#8192ac;opacity:1}
.setup-page textarea{min-height:112px;resize:vertical;line-height:1.8}
.setup-page select option{background:#091524;color:#eef5ff}
.setup-page input[type=checkbox],.setup-page input[type=radio]{width:18px;height:18px;min-width:18px;min-height:18px;margin:0;padding:0;accent-color:#69a7ff;box-shadow:none;cursor:pointer}
.setup-page .yesno{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;max-width:680px}
.setup-page .yesno label,.setup-page .setup-module{display:flex;align-items:center;gap:10px;min-height:50px;padding:13px 15px;border:1px solid rgba(136,169,214,.16);border-radius:10px;background:rgba(10,24,41,.48);cursor:pointer;line-height:1.7}
.setup-page .yesno label:has(input:checked),.setup-page .setup-module:has(input:checked){background:rgba(50,94,151,.22);border-color:rgba(111,169,248,.38)}
.setup-page .yesno label:hover,.setup-page .setup-module:hover{border-color:rgba(111,169,248,.44)}
.setup-page .conditional.hidden{display:none}
.setup-page .conditional{margin-top:18px}
.setup-page .note{padding:12px 14px;border:1px solid rgba(96,165,250,.20);border-radius:10px;background:rgba(24,52,86,.28);color:#bfd8f8;margin-top:14px;font-size:12px;line-height:1.85;overflow-wrap:anywhere}
.setup-page small.muted{font-size:12px;line-height:1.75}
.setup-page .actions{display:flex;justify-content:flex-end;gap:12px;flex-wrap:wrap;margin-top:26px;padding-top:22px;border-top:1px solid rgba(145,190,253,.12)}
.setup-page .btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:42px;padding:10px 18px;border:1px solid rgba(136,169,214,.20);border-radius:10px;background:rgba(19,35,56,.56);color:#eaf3ff;cursor:pointer;text-decoration:none;transition:border-color .16s,box-shadow .16s}
.setup-page .btn:hover{border-color:rgba(111,169,248,.44);box-shadow:0 10px 26px rgba(25,73,139,.10)}
.setup-page .btn.primary{border-color:rgba(119,178,255,.58);background:linear-gradient(180deg,rgba(66,111,174,.80),rgba(29,58,99,.88));box-shadow:inset 0 1px 0 rgba(255,255,255,.10),0 12px 28px rgba(25,73,139,.16)}
.setup-page button:focus-visible,.setup-page summary:focus-visible{outline:2px solid #8bbfff;outline-offset:3px}
.setup-page .btn:disabled{opacity:.6;cursor:wait}
#setupLanguage{min-width:100px;padding:8px 12px;font-size:12px;direction:ltr}
#setupBack{margin-inline-end:auto}
#setupServers{display:flex;flex-wrap:wrap;gap:10px;list-style:none;margin:0 0 22px;padding:0}
#setupServers:empty{display:none}
#setupServers li{padding:10px 14px;border:1px solid rgba(54,201,143,.24);border-radius:10px;background:rgba(32,113,84,.18);color:#9ce8ca;font-size:12px;overflow-wrap:anywhere}
#setupServerForm input{direction:ltr;text-align:left}
#setupAddServer{justify-self:start}
#setupError:not(:empty){padding:12px 14px;margin-top:18px;border:1px solid rgba(255,114,133,.28);border-radius:10px;background:rgba(116,35,49,.18);color:#ffb6c0;white-space:pre-wrap;font-size:13px;line-height:1.8}
.setup-page iframe{display:block;width:100%;height:72dvh;min-height:520px;border:1px solid rgba(145,190,253,.12);border-radius:12px;background:#07111f;color-scheme:dark}
.setup-restore{margin-top:24px;padding-top:18px;border-top:1px solid rgba(145,190,253,.12)}
.setup-restore>summary{display:inline-flex;align-items:center;min-height:38px;padding:8px 12px;color:#bfd3ed;border:1px solid rgba(145,190,253,.18);border-radius:9px;cursor:pointer;list-style:none;font-size:12px}
.setup-restore>summary::-webkit-details-marker{display:none}
.setup-restore-body{padding-top:16px}
.setup-restore-keys{margin-top:16px}
.setup-restore-keys>summary{cursor:pointer;font-size:13px;margin-bottom:16px;color:#bfd3ed}
#setupRestoreStatus{overflow-wrap:anywhere;color:var(--muted);font-size:13px}
.setup-page input[type=file]{padding:8px;line-height:1.8}
.setup-page input[type=file]::file-selector-button{border:1px solid rgba(136,169,214,.24);border-radius:6px;background:rgba(50,94,151,.22);color:#dcecff;padding:5px 10px;margin-inline-end:10px;font:inherit;cursor:pointer}
html[dir=rtl] .setup-page .setup-card,html[dir=rtl] .setup-page .step{direction:rtl;text-align:right}
.setup-page [dir=ltr]{direction:ltr;text-align:left}
@media(max-width:760px){.setup-topbar,.setup-shell{width:calc(100% - 28px)}.setup-topbar{gap:12px;min-height:76px;padding-block:16px}.setup-status{display:none}.setup-shell{padding-block:20px 32px}.setup-card{padding:22px 18px}.setup-page .grid{grid-template-columns:1fr;gap:16px}.setup-page .full{grid-column:auto}.setup-page .actions .btn{flex:1;min-width:100px}.setup-page .setup-progress-head{align-items:flex-start}.setup-page iframe{min-height:480px;height:72dvh}}
@media(max-width:380px){.setup-brand{font-size:12px}.setup-brand-mark{width:34px;height:34px;font-size:21px}.setup-page .yesno{grid-template-columns:1fr}.setup-card{padding:20px 14px}.setup-page h1{font-size:23px}}
@media(prefers-reduced-motion:reduce){.setup-page *,.setup-page *:before,.setup-page *:after{animation:none!important;scroll-behavior:auto!important;transition:none!important}}
.setup-page [hidden]{display:none!important}
'''
