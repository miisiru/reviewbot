"""증거 그림을 imgbb(api.imgbb.com)에 올려 https 주소를 얻는다(봇 메모의 evidence.image_url 용). imgur 는 운영을 멈췄다.

config.json 의 "imgbb_key"(또는 환경 변수 IMGBB_KEY)가 있어야 한다(https://api.imgbb.com/ 에서 받는 API 키). 키는 어디에도 출력하지 않는다.
없으면 upload() 가 None 을 돌려주고 메모는 그림 주소 없이 간다. 올린 그림은 work/imgbb_cache.json 에 (내용 해시 → 주소)로 기억해 두 번 올리지 않는다.
"imgbb_expiration"(초, 60~15552000)을 config.json 에 두면 그 시간 뒤 지워진다(기본: 지우지 않음).
올리면 공개 주소가 생긴다 — 올리는 것은 사이트 기록에 붙는 쇼케이스 · 전투 시트 그림뿐이다.

python imgbb.py <그림 파일>      올려서 주소를 찍는다"""
import os, sys, json, time, base64, hashlib, urllib.request, urllib.parse, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORK, config   # noqa: E402

CACHE = os.path.join(WORK, 'imgbb_cache.json')
MAX_SIDE = 1600      # imgbb 한도 32MB 아래로 충분


def api_key():
    return os.environ.get('IMGBB_KEY') or config().get('imgbb_key') or None


def _shrink(path):
    """긴 변 1600px 이하 JPEG 바이트(imgbb 한도 32MB 아래로, 시트가 클 때)."""
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
    """그림 파일을 올려 https 주소를 돌려준다. 키가 없거나 실패하면 None(실패해도 검토는 계속된다)."""
    key = api_key()
    if not key or not os.path.isfile(path):
        return None
    data = _shrink(path)
    h = hashlib.sha1(data).hexdigest()
    cache = _cache()
    if cache.get(h):
        return cache[h]
    form = {'image': base64.b64encode(data).decode(), 'name': os.path.splitext(os.path.basename(path))[0][:100]}
    exp = config().get('imgbb_expiration')
    url = 'https://api.imgbb.com/1/upload?key=' + urllib.parse.quote(key) + (f'&expiration={int(exp)}' if exp else '')
    body = urllib.parse.urlencode(form).encode()
    for k in range(retries):
        req = urllib.request.Request(url, data=body, method='POST',
                                     headers={'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'reviewbot'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r).get('data') or {}
                link = d.get('url') or d.get('display_url')
            if link and link.startswith('https://'):
                cache[h] = link
                os.makedirs(WORK, exist_ok=True)
                json.dump(cache, open(CACHE, 'w', encoding='utf8'), indent=1)
                return link
            return None
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and k < retries - 1:
                time.sleep(min(60, int(e.headers.get('Retry-After') or 5 * (k + 1))))
                continue
            print(f'imgbb upload failed: HTTP {e.code}', file=sys.stderr)
            return None
        except (urllib.error.URLError, OSError) as e:
            if k < retries - 1:
                time.sleep(3 * (k + 1))
                continue
            print(f'imgbb upload failed: {e}', file=sys.stderr)
            return None
    return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    print(upload(sys.argv[1]) or 'not uploaded (no imgbb_key, or failed)')
