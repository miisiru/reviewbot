"""검토 순서: 후원자(도네이션 레인, HIGH PRIORITY)의 기록이 먼저, 그다음 일반 기록. 각 줄 안에서는 제출된 시각(created_at) 오래된 순.
후원자 판정은 사이트와 같다: 기록의 author_name(없으면 첫 런의 author_name)을 소문자로 바꿔 /api/archive/donors 의 name · display_name 과 맞춘다.
영상 날짜(payload.video_date)는 쓰지 않는다.
python queue_order.py [queue.json]   → 줄마다 「순서 줄 rev 제출시각 작성자」"""
import json, os, sys, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(os.path.dirname(HERE), 'work')


def donor_names():
    r = urllib.request.Request('https://theherta.com/api/archive/donors', headers={'User-Agent': 'Mozilla/5.0'})
    d = json.load(urllib.request.urlopen(r, timeout=30))
    out = set()
    for e in d.get('donors', []):
        for k in (e.get('name'), e.get('display_name')):
            if isinstance(k, str) and k.strip():
                out.add(k.strip().lower())
    return out


def author(item):
    a = (item.get('author_name') or '').strip()
    if not a:
        for it in item.get('submission_review_items') or []:
            a = ((it.get('payload') or {}).get('author_name') or '').strip()
            if a:
                break
    return a


def ordered(items, donors=None):
    donors = donors if donors is not None else donor_names()
    rows = [(author(x).lower() in donors, x) for x in items]
    rows.sort(key=lambda r: (not r[0], r[1]['created_at']))
    return rows


if __name__ == '__main__':
    q = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORK, 'queue_live.json'), encoding='utf8'))
    for i, (don, x) in enumerate(ordered(q), 1):
        print(i, 'DONOR' if don else 'normal', x['id'], x['created_at'][:19], author(x))
