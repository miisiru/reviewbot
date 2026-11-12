"""로그인된 전용 Chrome(--remote-debugging-port=9333)의 localStorage 에서 사이트 세션 토큰을 읽어 config.json 의 mod_token 으로 쓴다.
토큰은 어디에도 출력하지 않는다. 사용: python chrome_token.py [포트]
전용 Chrome 띄우기: chrome --user-data-dir=<빈 폴더> --remote-debugging-port=9333 https://theherta.com/mod  (한 번 로그인하면 프로필에 남는다)"""
import os, sys, json, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import websocket                      # noqa: E402
from paths import CONFIG, config      # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9333
JS = """(()=>{const o={};for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);if(/^sb-.*auth-token/.test(k)){try{const v=JSON.parse(localStorage.getItem(k));o[k]={a:v.access_token||(v.currentSession&&v.currentSession.access_token),r:v.refresh_token||(v.currentSession&&v.currentSession.refresh_token),e:v.expires_at||(v.currentSession&&v.currentSession.expires_at)}}catch(e){}}}return JSON.stringify(o)})()"""


def read():
    tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json'))
    page = next((t for t in tabs if t['type'] == 'page' and 'theherta.com' in t['url']), None)
    if not page:
        raise SystemExit('theherta.com 탭이 없다(전용 Chrome 에서 사이트를 열어 로그인해 주세요)')
    ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=20, suppress_origin=True)
    ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': JS, 'returnByValue': True}}))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == 1:
            break
    ws.close()
    return json.loads(r['result']['result']['value'] or '{}'), page['url']


if __name__ == '__main__':
    data, url = read()
    if not data:
        raise SystemExit('로그인 토큰이 없다(로그인이 끝났는지 확인: ' + url.split('?')[0] + ')')
    key, v = next(iter(data.items()))
    ref = key[3:].split('-auth-token')[0]
    cfg = config()
    cfg['mod_token'], cfg['mod_refresh_token'] = v['a'], v['r']
    if v.get('e'):
        cfg['mod_token_expires_at'] = int(v['e'])
    cfg.setdefault('supabase_url', f'https://{ref}.supabase.co')
    json.dump(cfg, open(CONFIG, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('mod_token saved; expires in', int(v.get('e') or 0) - int(time.time()), 's; project', ref)
