"""증거 그림을 imgur 에 올려 https 주소를 얻는다(봇 메모의 evidence.image_url 용).

config.json 의 "imgur_client_id"(또는 환경 변수 IMGUR_CLIENT_ID)가 있어야 한다. imgur 에서 앱(Anonymous usage)을 등록하면 얻는 Client ID.
없으면 upload() 가 None 을 돌려주고 메모는 그림 주소 없이 간다. 올린 그림은 work/imgur_cache.json 에 (내용 해시 → 주소)로 기억해 두 번 올리지 않는다.
imgur 에 올리면 공개 주소가 생긴다 — 올리는 것은 사이트 기록에 붙는 쇼케이스 · 전투 시트 그림뿐이다.

python imgur.py <그림 파일>      올려서 주소를 찍는다"""
import os, sys, json, time, base64, hashlib, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORK, config   # noqa: E402

CACHE = os.path.join(WORK, 'imgur_cache.json')
MAX_SIDE = 1600


def client_id():
    return os.environ.get('IMGUR_CLIENT_ID') or config().get('imgur_client_id') or None


def _shrink(path):
    """긴 변 1600px 이하 JPEG 바이트(imgur 한도 10MB 아래로, 시트가 클 때)."""
    import cv2
    img = cv2.imread(path)
    if img is None:
        return open(path, 'rb').read()
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes() if ok else open(path, 'rb').read()


def _cache():
    try:
        return json.load(open(CACHE, encoding='utf8'))
    except (OSError, ValueError):
        return {}


def upload(path, retries=4):
    """그림 파일을 올려 https 주소를 돌려준다. client id 가 없거나 실패하면 None(실패해도 검토는 계속된다)."""
    cid = client_id()
    if not cid or not os.path.isfile(path):
        return None
    data = _shrink(path)
    key = hashlib.sha1(data).hexdigest()
    cache = _cache()
    if cache.get(key):
        return cache[key]
    body = json.dumps({'image': base64.b64encode(data).decode(), 'type': 'base64', 'title': os.path.basename(path)[:100]}).encode()
    for k in range(retries):
        req = urllib.request.Request('https://api.imgur.com/3/image', data=body, method='POST',
                                     headers={'Authorization': 'Client-ID ' + cid, 'Content-Type': 'application/json',
                                              'User-Agent': 'reviewbot'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                link = (json.load(r).get('data') or {}).get('link')
            if link and link.startswith('https://'):
                cache[key] = link
                os.makedirs(WORK, exist_ok=True)
                json.dump(cache, open(CACHE, 'w', encoding='utf8'), indent=1)
                return link
            return None
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and k < retries - 1:
                time.sleep(min(60, int(e.headers.get('Retry-After') or 5 * (k + 1))))
                continue
            print(f'imgur upload failed: HTTP {e.code}', file=sys.stderr)
            return None
        except (urllib.error.URLError, OSError) as e:
            if k < retries - 1:
                time.sleep(3 * (k + 1))
                continue
            print(f'imgur upload failed: {e}', file=sys.stderr)
            return None
    return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    print(upload(sys.argv[1]) or 'not uploaded (no imgur_client_id, or failed)')
