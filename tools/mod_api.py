"""theherta.com 검토 API 를 브라우저 자동 조종(Chrome DevTools) 없이 부른다.

인증은 사이트 로그인(Discord → Supabase) 세션의 access token 을 Bearer 로 쓴다. config.json 에
  "mod_token":        access token(한 시간 남짓이면 만료)
  "mod_refresh_token": refresh token
  "supabase_url":      https://<project>.supabase.co
  "supabase_anon_key": 사이트가 쓰는 공개 anon 키
를 넣어 두면 만료됐을 때 refresh token 으로 새 access token 을 받아 config.json 에 다시 적는다
(Supabase refresh token 은 한 번 쓰면 바뀐다). 값 얻는 법은 README 참고.

python mod_api.py queue [--out work/queue.json]      대기열을 받아 파일로(기본 work/queue.json)
python mod_api.py claim <rev_id>                     검토 중 표시(사이트가 1분짜리로 잡는다)
python mod_api.py release <rev_id>                   검토 중 표시 풀기
python mod_api.py decide <rev_id> approve --yes
python mod_api.py decide <rev_id> reject "사유" --yes  승인 · 거절(--yes 없으면 보내지 않고 보낼 내용만 보인다)"""
import os, sys, json, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import CONFIG, WORK, config   # noqa: E402

BASE = os.environ.get('THEHERTA_BASE', 'https://theherta.com')


def _save_cfg(cfg):
    json.dump(cfg, open(CONFIG, 'w', encoding='utf8'), ensure_ascii=False, indent=1)


def refresh(cfg):
    """refresh token 으로 새 access token(Supabase GoTrue). 성공하면 config.json 을 고쳐 쓴다."""
    need = ('mod_refresh_token', 'supabase_url', 'supabase_anon_key')
    if not all(cfg.get(k) for k in need):
        raise SystemExit('access token 이 만료됐고 refresh 에 필요한 값(' + ', '.join(need) + ')이 config.json 에 없다')
    req = urllib.request.Request(cfg['supabase_url'].rstrip('/') + '/auth/v1/token?grant_type=refresh_token',
                                 data=json.dumps({'refresh_token': cfg['mod_refresh_token']}).encode(),
                                 headers={'apikey': cfg['supabase_anon_key'], 'Content-Type': 'application/json'})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    cfg['mod_token'], cfg['mod_refresh_token'] = r['access_token'], r['refresh_token']
    cfg['mod_token_expires_at'] = int(time.time()) + int(r.get('expires_in', 3600))
    _save_cfg(cfg)
    return cfg


def call(method, path, body=None, _retry=True):
    cfg = config()
    tok = os.environ.get('THEHERTA_TOKEN') or cfg.get('mod_token')
    if not tok:
        raise SystemExit('config.json 에 mod_token 이 없다(README 「토큰 얻기」)')
    if not os.environ.get('THEHERTA_TOKEN') and cfg.get('mod_token_expires_at') and cfg['mod_token_expires_at'] < time.time() + 60:
        tok = refresh(cfg)['mod_token']
    req = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json',
                                          'User-Agent': 'reviewbot'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry and not os.environ.get('THEHERTA_TOKEN'):
            refresh(config())
            return call(method, path, body, _retry=False)
        raise SystemExit(f'{method} {path} -> HTTP {e.code}: {e.read()[:300]!r}')


def queue(out=None):
    r = call('GET', '/api/mod/reviews?filter=pending&limit=300&order=oldest')
    items = r.get('reviews', r) if isinstance(r, dict) else r
    out = out or os.path.join(WORK, 'queue.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(items, open(out, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    return items, out


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        sys.exit(1)
    cmd = a[0]
    if cmd == 'queue':
        items, out = queue(a[a.index('--out') + 1] if '--out' in a else None)
        free = [x for x in items if not x.get('claimed_by_name')]
        print(f'{len(items)} pending ({len(free)} not claimed) -> {out}')
    elif cmd == 'claim':
        print(call('POST', f'/api/mod/reviews/{a[1]}/claim'))
    elif cmd == 'release':
        print(call('DELETE', f'/api/mod/reviews/{a[1]}/claim'))
    elif cmd == 'decide':
        rev, action = a[1], a[2]
        if action not in ('approve', 'reject'):
            raise SystemExit('approve 또는 reject')
        body = {'action': action}
        if action == 'reject':
            reason = next((x for x in a[3:] if not x.startswith('--')), '')
            if not reason.strip():
                raise SystemExit('거절에는 사유가 있어야 한다(한 줄, 여러 문제는 「 / 」로 잇는다)')
            body['reason'] = reason
        if '--yes' not in a:
            print('보내지 않음(--yes 가 없다):', rev, json.dumps(body, ensure_ascii=False))
        else:
            print(call('POST', f'/api/mod/reviews/{rev}/decision', body))
    else:
        print(__doc__)
        sys.exit(1)
