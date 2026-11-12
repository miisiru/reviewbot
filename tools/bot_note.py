"""판정 결과를 봇 메모(POST /api/bot/reviews/<id>/notes)로 남긴다. 판정이 끝날 때 한 번만(카드에는 가장 새 것 하나만 보인다).

verdict: APPROVE → approve, REJECT → reject, CHECK → check. 사유 · 증거는 보고(report.py)와 같은 내용을 짧게.
증거 그림(쇼케이스 시트 · 전투 시트)은 imgur 에 올려 image_url 로 붙인다(imgur_client_id 가 없으면 그림 없이).
봇 키가 없으면 아무것도 하지 않는다(예전 세션 토큰 방식은 메모가 없다).

python bot_note.py <rev_id> [--dry]     runs/<rev>/auto.json 과 work/queue.json 으로 메모를 만들어 보낸다(--dry 는 보내지 않고 보인다)"""
import os, sys, re, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import RUNS, WORK   # noqa: E402
import mod_api, imgur          # noqa: E402
from report import playback_sources, timestamp_link, attach_sheets   # noqa: E402

VERDICT = {'APPROVE': 'approve', 'REJECT': 'reject', 'CHECK': 'check'}


def _raw_url(markdown):
    m = re.search(r'\]\((https?://[^)]+)\)', markdown or '')
    return m.group(1) if m else None


def _plain(s):
    return re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', str(s))


def build_note(rev, res, item, upload_images=True):
    """(verdict, confidence, summary, reasons, evidence). 보내지는 않는다."""
    verdict = VERDICT.get(res.get('verdict'), 'check')
    problems = [_plain(x) for x in (res.get('problems') or [])]
    checks = [_plain(x) for x in (res.get('check_reasons') or [])]
    if verdict == 'reject':
        summary = ' / '.join(problems) or 'Problems found'
    elif verdict == 'check':
        summary = '; '.join(checks + problems) or 'Needs a human check'
    else:
        summary = 'All checked items match the submission'
    reasons = problems + [f'[check] {c}' for c in checks]
    reasons += [f'−{n} {_plain(w)}' for n, w in (res.get('deductions') or [])]

    pl = item.get('payload') or {}
    side = (pl.get('runs') or [pl])[0]
    src = playback_sources(rev, res, side)
    start = side.get('battle_timestamp')
    if start is None:
        m = re.search(r'[?&#](?:t|start)=(\d+)', side.get('video_url') or '')
        start = int(m.group(1)) if m else 0
    evidence = []
    u = _raw_url(timestamp_link(src['battle_online'], start, 'x')) if src['battle_online'] else None
    if u:
        evidence.append({'label': 'Battle video', 't': int(start), 'url': u})
    sh_t = res.get('showcase')
    u = _raw_url(timestamp_link(src['build_online'], sh_t, 'x')) if src['build_online'] and sh_t is not None else None
    if u:
        evidence.append({'label': 'Showcase', 't': int(sh_t), 'url': u})
    if upload_images and imgur.client_id():
        try:
            payload, files = attach_sheets(os.path.join(RUNS, rev), {})
            for att, f in zip(payload.get('attachments') or [], files):
                link = imgur.upload(f)
                if link:
                    evidence.append({'label': att.get('description') or os.path.basename(f), 'image_url': link})
        except Exception as e:      # 그림이 안 올라가도 메모는 간다
            print(f'{rev}: evidence images skipped: {e}', file=sys.stderr)
    return verdict, int(res.get('confidence') or 0), summary[:500], [r[:500] for r in reasons][:50], evidence[:50]


def post(rev, res, item, dry=False):
    """메모를 보낸다. 봇 키가 없으면 None. 실패해도 예외를 던지지 않고 이유 글을 돌려준다(검토 흐름이 멈추지 않게)."""
    if not mod_api.bot_key():
        return None
    v, c, s, reasons, ev = build_note(rev, res, item)
    if dry:
        return json.dumps({'verdict': v, 'confidence': c, 'summary': s, 'reasons': reasons, 'evidence': ev}, ensure_ascii=False, indent=1)
    try:
        mod_api.note(rev, v, c, s, reasons, ev)
        return 'note ok'
    except SystemExit as e:           # mod_api.call 은 HTTP 오류를 SystemExit 로 낸다(404 = 그 사이 다른 사람이 결정함)
        return f'note failed: {e}'


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    rev = sys.argv[1]
    q = {x['id']: x for x in json.load(open(os.path.join(WORK, 'queue.json'), encoding='utf8'))}
    res = json.load(open(os.path.join(RUNS, rev, 'auto.json'), encoding='utf8'))
    print(post(rev, res, q[rev], dry='--dry' in sys.argv))
