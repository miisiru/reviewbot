"""사이트(theherta.com) 덤프(브라우저 콘솔 스크립트가 저장한 theherta-ui-dump.json)에서 요약 HTML 이 쓸 스타일을 뽑는다 → data/ui_theme/
  site.css   사이트 CSS 를 이어 붙인 것(상대 주소의 글꼴 · 그림은 https://theherta.com 절대 주소로 바꿈). 깃에 올리지 않는다(data/ 는 .gitignore)
  vars.json  :root 의 색 · 글꼴 변수
python extract_ui_theme.py <theherta-ui-dump.json>   (덤프는 tools/ui_dump_console.js 를 브라우저 콘솔에 붙여 만든다)"""
import os, sys, re, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import DATA   # noqa: E402

SITE = 'https://theherta.com'
SKIP = ('cdnjs.cloudflare.com', 'fonts.googleapis.com')       # 요약 HTML 이 따로 링크하는 것(Font Awesome) · 받아도 쓸모 없는 것


def absolutize(css, base):
    def fix(m):
        u = m.group(2).strip()
        if u.startswith(('data:', 'http:', 'https:', '//', '#')):
            return m.group(0)
        if u.startswith('/'):
            return f'url({m.group(1)}{SITE}{u}{m.group(1)})'
        return f'url({m.group(1)}{base.rsplit("/", 1)[0]}/{u}{m.group(1)})'
    return re.sub(r'url\((["\']?)([^)"\']+)\1\)', fix, css)


def main():
    src = sys.argv[1]
    d = json.load(open(src, encoding='utf8'))
    parts = []
    for c in d.get('css', []):
        url = c.get('url') or ''
        if not c.get('text') or any(s in url for s in SKIP):
            continue
        parts.append(f'/* {url} */\n' + absolutize(c['text'], url if url.startswith('http') else SITE + '/'))
    out = os.path.join(DATA, 'ui_theme')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'site.css'), 'w', encoding='utf8').write('\n'.join(parts))
    json.dump(d.get('rootVars', {}), open(os.path.join(out, 'vars.json'), 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('site.css', sum(len(p) for p in parts), 'bytes from', len(parts), 'files →', out)


if __name__ == '__main__':
    main()
