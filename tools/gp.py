"""보유 효과(계정 공통 효과) 배너 감지(AI 없음).
  - 카스토리스 「Sanctuary of Mooncocoon / 달의 고치의 비호 / 月茧之庇 …」(flag revive)
  - 은랑 LV.999 「McAwolfee 999 / 999 디펜더 / 999安全卫士 …」 + 위쪽 안내 「…hacked into the game…」(flag firewall)
배너는 0.5초만 뜨기도 해서 4fps 로 전투 전체를 본다. 오른쪽 가운데 띠(배너 자리)를 잘라, 흰 글자가 있는 프레임만 OCR 하고
배너 이름(12개 언어)과 비슷한지 본다. 은랑 안내 문구는 화면 위쪽 가운데 칸.
python gp.py <rev> [vid]"""
import os, sys, re, json, difflib
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tabs                              # noqa: E402
from judge import ocr, norm, ROOT        # noqa: E402

BANNERS = {
    'revive': ['Sanctuary of Mooncocoon', '달의 고치의 비호', '月茧之庇', '月繭之庇', '月の繭の庇護', 'Sự Che Chở Từ Kén Nguyệt',
               'Защита лунного кокона', 'Santuario de la crisálida lunar', 'Santuário do Casulo Lunar', 'Sanctuaire du Cocon lunaire',
               'Zufluchtsort des Mondkokons'],
    'firewall': ['McAwolfee 999', '999 디펜더', '999安全卫士', '999安全衛士', '999セキュリティバリア', 'Волчерский 999',
                 'Protección 999 grados', 'LobaGuard 999', 'Louvast antivirus', 'Firewall-Wolf 999'],
}
HACK = ['hacked into the game', '게임을 해킹', '骇入游戏', '駭入遊戲', 'ゲームにハッキング', 'đã hack trò chơi', 'แฮ็กเข้าเกม',
        'взламывает игру', 'hackeó el juego', 'hackeou o jogo', 'a piraté le jeu', 'ins Spiel gehackt', 'meretas game']
_NB = {k: [norm(x) for x in v] for k, v in BANNERS.items()}
_NH = [norm(x) for x in HACK]


def match(text, words):
    n = norm(text)
    if len(n) < 3:
        return 0.0
    best = 0.0
    for w in words:
        if w in n or (len(n) >= 4 and n in w):
            return 1.0
        best = max(best, difflib.SequenceMatcher(None, n, w).ratio())
    return best


def big_text_row(c, H):
    """큰 흰 글자(화면 높이 2.5~9%)가 가로 한 줄로 몇 개인지. 배너 이름은 셋 넘게 나오고,
    피해 숫자 · 작은 안내 글은 대개 그보다 작거나 흩어져 있다. 이것으로 OCR 할 프레임을 1/10 로 줄인다."""
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 2] > 190) & (hsv[..., 1] < 70)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m, 8)
    cs = [st[i][:4] for i in range(1, n)
          if 0.025 * H <= st[i][3] <= 0.09 * H and st[i][2] <= 1.6 * st[i][3] and st[i][4] >= 0.15 * st[i][2] * st[i][3]]
    best = 0
    for x, y, w, h in cs:
        best = max(best, sum(1 for q in cs if abs((q[1] + q[3] / 2) - (y + h / 2)) < 0.35 * h and 0.6 * h <= q[3] <= 1.5 * h))
    return best


def texty(c):
    """흰 글자처럼 보이는 픽셀 비율(밝고 채도 낮은 픽셀이 가로 띠로)."""
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
    m = (hsv[..., 2] > 200) & (hsv[..., 1] < 60)
    return float(m.mean())


def scan(rev, vid=0, model='chinese', fps=4):
    d = os.path.join(ROOT, rev)
    vids = json.load(open(os.path.join(d, 'videos.json'), encoding='utf8')) if os.path.exists(os.path.join(d, 'videos.json')) else [{'file': 'video0.mp4'}]
    video = os.path.join(d, vids[vid].get('file', f'video{vid}.mp4'))
    dur, W, H = tabs.probe(video)
    end = dur
    tl = os.path.join(d, f'tabs{vid}', 'timeline.txt')
    if os.path.exists(tl):
        ws = [float(m.group(1)) for m in re.finditer(r'window ([\d.]+)-', open(tl, encoding='utf8').read())]
        late = [w for w in ws if w > 0.3 * dur]
        if late:
            end = min(late)
    hits, nocr, nfr = [], 0, 0
    prev = {}
    for t, f in tabs.frames(video, 0, end, fps, W, H):
        nfr += 1
        band = f[int(0.55 * H):int(0.71 * H), int(0.62 * W):int(0.98 * W)]
        top = f[int(0.02 * H):int(0.12 * H), int(0.20 * W):int(0.80 * W)]
        for where, c in (('band', band), ('top', top)):
            if where == 'band':
                if big_text_row(c, H) < 3:
                    continue
            else:
                if nfr % max(1, int(fps)) != 0:
                    continue      # 위쪽 해킹 안내는 몇 초씩 떠 있어서 1초에 한 번만 본다(보스 이름 · 체력 막대가 늘 있어 매번 읽으면 느리다)
                tx = texty(c)
                if tx < 0.004 or tx > 0.35:
                    continue
            small = cv2.resize(c, (64, 16), interpolation=cv2.INTER_AREA).astype(np.int16)
            if where in prev and np.abs(prev[where] - small).mean() < 3:
                continue          # 같은 자리에서 바로 앞에 읽은 것과 거의 같은 그림
            prev[where] = small
            nocr += 1
            for b in ocr(c, model):
                txt = b[4]
                if where == 'band':
                    for flag, words in _NB.items():
                        s = match(txt, words)
                        if s >= 0.75:
                            hits.append({'t': round(t, 2), 'flag': flag, 'text': txt, 'score': round(s, 2)})
                else:
                    s = match(txt, _NH)
                    if s >= 0.75:
                        hits.append({'t': round(t, 2), 'flag': 'firewall', 'text': txt, 'score': round(s, 2), 'where': 'top'})
    seen = sorted({h['flag'] for h in hits})
    return {'video': video, 'end': round(end, 1), 'frames': nfr, 'ocr_calls': nocr, 'seen': seen, 'hits': hits[:20]}


if __name__ == '__main__':
    rev = sys.argv[1]
    jp = os.path.join(ROOT, rev, 'judge.json')
    model = json.load(open(jp, encoding='utf8')).get('ocr_model', 'chinese') if os.path.exists(jp) else 'chinese'
    r = scan(rev, int(sys.argv[2]) if len(sys.argv) > 2 else 0, model=model)
    p = json.load(open(os.path.join(ROOT, rev, 'review.json'), encoding='utf8'))['payload']
    print(rev, 'flags=', repr(p.get('flags')), 'seen=', r['seen'], 'frames', r['frames'], 'ocr', r['ocr_calls'])
    for h in r['hits'][:6]:
        print('  ', h)
