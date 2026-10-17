"""화면 그림으로 알아보는 도구(imgrec.py)가 쓰는 게임 그림을 받는다 → data/
원본: HF 데이터셋 fffffffff1/assets (최신판, 없으면 fffffffff1/imageassets 정식판)의 PNG. imgrec 가 읽는 꼴로 바꿔 저장한다.
  data/img/lightconemaxfigures/<광추 아이디>.webp      광추 카드 그림
  data/img/skillicons/<캐릭터>/SkillIcon_*_Rank*.webp  켜진 성혼 노드 아이콘(AvatarRankConfig 의 IconPath)
  data/ui/path/<길>_small.png                          머리글 운명의 길 아이콘
  data/ui/element/<속성>_color.png · _dtype.png        상세 화면 속성 아이콘
성혼 아이콘은 data/ExcelOutput/AvatarRankConfig.json 이 있어야 받는다(없으면 건너뛴다).
python get_assets.py [--force]   (이미 있는 파일은 건너뜀)"""
import os, sys, re, json, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import DATA, EXCEL      # noqa: E402

REPOS = ['fffffffff1/assets', 'fffffffff1/imageassets']
FORCE = '--force' in sys.argv
PATHS = ['Joy', 'Knight', 'Mage', 'Memory', 'Pirest', 'Rogue', 'Shaman', 'Warlock', 'Warrior']
ELEMENTS = ['Fire', 'Ice', 'Imaginary', 'Physical', 'Quantum', 'Thunder', 'Wind']


def fetch(path):
    """HF 에서 파일 하나(바이트). 최신판에 없으면 정식판. 둘 다 없으면 None."""
    for repo in REPOS:
        url = f'https://huggingface.co/datasets/{repo}/resolve/main/{path}'
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'reviewbot'}), timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    return None


def listing(path):
    """HF 폴더 바로 아래 파일 이름들(최신판 우선, 둘을 합친다)."""
    names = set()
    for repo in REPOS:
        url = f'https://huggingface.co/api/datasets/{repo}/tree/main/{path}'
        while url:
            try:
                r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'reviewbot'}), timeout=60)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                raise
            names.update(os.path.basename(x['path']) for x in json.load(r) if x['type'] == 'file')
            m = re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link') or '')
            url = m.group(1) if m else None
    return sorted(names)


def save(raw, dest, webp=False, height=None):
    if os.path.exists(dest) and not FORCE:
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if webp:
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
        if height and im.shape[0] != height:       # 광추 카드는 세로 720 으로 맞춰 둔다(imgrec 의 점수 기준)
            im = cv2.resize(im, (round(im.shape[1] * height / im.shape[0]), height), interpolation=cv2.INTER_AREA)
        cv2.imwrite(dest, im, [cv2.IMWRITE_WEBP_QUALITY, 101])     # 101 = 무손실
    else:
        open(dest, 'wb').write(raw)
    return True


TASKS = []      # (HF 경로, 저장 위치, webp 여부, 세로 크기) — 모아 두었다가 병렬로 받는다


def get(path, dest, webp=False, height=None):
    if FORCE or not os.path.exists(dest):
        TASKS.append((path, dest, webp, height))


def run_tasks():
    def one(t):
        path, dest, webp, height = t
        raw = fetch(path)
        if raw is None:
            return path, False
        save(raw, dest, webp, height)
        return path, True
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, TASKS))
    missing = [p for p, ok in res if not ok]
    print(f'받음 {len(res) - len(missing)} 개' + (f', HF 에 없음 {len(missing)} 개(예: {missing[:3]})' if missing else ''))
    TASKS.clear()


def bulk(src_dir, dest_dir, pattern, webp, label, height=None):
    files = [f for f in listing(src_dir) if re.fullmatch(pattern, f)]
    for f in files:
        stem = f.rsplit('.', 1)[0]
        get(f'{src_dir}/{f}', os.path.join(dest_dir, stem + ('.webp' if webp else '.png')), webp, height)
    print(f'{label}: HF {len(files)} 개')


def main():
    bulk('spriteoutput/lightconemaxfigures', os.path.join(DATA, 'img', 'lightconemaxfigures'), r'2\d+\.png', True, '광추 카드', 720)
    for p in PATHS:
        get(f'spriteoutput/professioniconsmall/IconProfession{p}Small.png', os.path.join(DATA, 'ui', 'path', f'{p}_small.png'))
    for e in ELEMENTS:
        get(f'spriteoutput/ui/nature/iconnaturecolor/IconNatureColor{e}.png', os.path.join(DATA, 'ui', 'element', f'{e}_color.png'))
        get(f'spriteoutput/icondamagetype/IconDamageType{e}.png', os.path.join(DATA, 'ui', 'element', f'{e}_dtype.png'))
    fp = os.path.join(EXCEL, 'AvatarRankConfig.json')
    if os.path.exists(fp):
        for r in json.load(open(fp, encoding='utf8')):
            cid = r['RankID'] // 100
            ip = (r.get('IconPath') or '').replace('\\', '/')
            fn = os.path.basename(ip).rsplit('.', 1)[0]
            if fn:
                src = os.path.dirname(ip).lower() + '/' + fn + '.png'      # 폴더는 소문자, 파일 이름은 그대로
                get(src, os.path.join(DATA, 'img', 'skillicons', str(cid), fn + '.webp'), True)
    else:
        print('성혼 아이콘: ExcelOutput/AvatarRankConfig.json 이 없어 건너뜀(README 의 게임 자료 받기 먼저)')
    run_tasks()


if __name__ == '__main__':
    main()
