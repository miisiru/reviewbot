"""한 번에 처리한 기록들의 간단한 요약을 HTML 한 장으로 만든다(판정별 묶음 + 기록 카드).
모양은 theherta.com 의 기록 목록(/archive)을 따른다: 어두운 배경, 「✦ 묶음 이름 (n entries)」 머리글, 캐릭터 · 광추 그림 + E / S 배지,
사이클 알약, LTD / STD 알약, 날짜 · 플랫폼. 사이트의 클래스 이름을 그대로 쓰고,
  - data/ui_theme/site.css (tools/extract_ui_theme.py 가 사이트 덤프에서 만든다, 깃에 올리지 않음)가 있으면 그것으로 사이트와 똑같이,
  - 없으면 이 파일의 LITE_CSS(같은 색 · 모양을 직접 쓴 작은 스타일)로 그린다.
python summary_html.py [rev_id ...] [--out work/summary.html]   (rev 를 주지 않으면 work/results.jsonl 의 마지막 묶음 말고 runs/ 전체의 auto.json)"""
import os, sys, re, json, html
from datetime import datetime
from urllib.parse import quote
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from paths import RUNS, WORK, DATA   # noqa: E402

SITE = 'https://theherta.com'
THEME = os.path.join(DATA, 'ui_theme', 'site.css')
ORDER = ['CHECK', 'REJECT', 'APPROVE']            # 사람이 먼저 봐야 할 것부터
VERDICT_LOOK = {                                   # 카드 테두리 · 배지 색(사이트의 강조 행: 붉은 테두리 · 보라 테두리 행과 같은 방식)
    'APPROVE': ('border-emerald-400/40 bg-emerald-500/[0.06] rb-c-approve', 'text-emerald-300 border-emerald-400/40 bg-emerald-500/10 rb-v-approve'),
    'CHECK': ('border-amber-400/40 bg-amber-500/[0.06] rb-c-check', 'text-amber-300 border-amber-400/40 bg-amber-500/10 rb-v-check'),
    'REJECT': ('border-red-500/50 bg-red-500/[0.07] rb-c-reject', 'text-red-300 border-red-500/50 bg-red-500/10 rb-v-reject'),
}

LITE_CSS = """
:root{--bg:#020205;--panel:rgba(15,15,25,.72);--text:#e2e8f0;--dim:#94a3b8;--blue:#60a5fa;--purple:#c084fc;--pink:#fb7185;--gold:#fbbf24}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 20% -10%,rgba(96,165,250,.10),transparent),radial-gradient(900px 500px at 100% 0,rgba(192,132,252,.08),transparent),#020205;
  color:var(--text);min-height:100vh;background-attachment:fixed;font-family:Geist,Inter,system-ui,-apple-system,sans-serif;font-size:14px;line-height:1.35}
a{color:inherit;text-decoration:none}
.rb-wrap{max-width:860px;margin:0 auto;padding:18px 12px 60px;display:flex;flex-direction:column;gap:12px}
.rb-title{font-size:26px;font-weight:800;letter-spacing:-.01em;background:linear-gradient(120deg,#60a5fa 0%,#c084fc 52%,#fb7185 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.rb-sub{font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:rgba(255,255,255,.35);font-weight:700}
.rb-stats{display:flex;flex-wrap:wrap;gap:8px}
.rb-group{display:flex;flex-direction:column;gap:4px;border-radius:12px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025);overflow:hidden}
.rb-ghead{display:flex;align-items:center;gap:8px;padding:8px 16px;border-bottom:1px solid rgba(255,255,255,.08);font-size:14px;font-weight:600;text-align:left}
.rb-gicon{color:var(--blue)}
.rb-gcount{color:rgba(255,255,255,.3);font-size:12px;font-weight:400}
.rb-gbody{display:flex;flex-direction:column;gap:4px;padding:2px}
.rb-card{position:relative;border-radius:12px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025);overflow:hidden;transition:all .4s cubic-bezier(.4,0,.2,1)}
.rb-card:hover{background:rgba(255,255,255,.05)}
.rb-row{display:flex;gap:10px;padding:8px}
.rb-team{display:flex;gap:6px;flex-shrink:0}
.rb-slot{display:flex;flex-direction:column;align-items:center;gap:4px}
.rb-char{position:relative;width:56px;height:56px;border-radius:8px;overflow:hidden;background:rgba(255,255,255,.05);box-shadow:0 0 0 1px rgba(255,255,255,.08)}
.rb-char.rb-first{box-shadow:0 0 0 1px rgba(147,197,253,.5),0 0 10px rgba(96,165,250,.15)}
.rb-lc{position:relative;width:36px;height:50px;border-radius:4px;overflow:hidden;background:rgba(255,255,255,.05);box-shadow:0 0 0 1px rgba(255,255,255,.1);margin-top:2px}
.rb-char img,.rb-lc img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.rb-char img{object-position:top}
.rb-badge{position:absolute;right:0;bottom:0;font-size:11px;font-weight:700;padding:0 6px;line-height:15px;border-radius:4px 0 0 0;background:rgba(0,0,0,.85)}
.rb-e{color:#bfdbfe}.rb-s{color:#e9d5ff}
.rb-mid{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:4px}
.rb-line{display:flex;align-items:center;gap:6px;min-width:0}
.rb-name{font-size:14px;font-weight:600;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rb-meta{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:11px;color:rgba(255,255,255,.25);white-space:nowrap;font-variant-numeric:tabular-nums}
.rb-yt{color:#f87171;font-weight:700;font-size:10px;letter-spacing:.06em}.rb-bili{color:#38bdf8;font-weight:700;font-size:10px;letter-spacing:.06em}
.rb-pills{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.rb-pill{display:inline-flex;align-items:center;gap:6px;padding:2px 8px 2px 6px;border-radius:999px;border:1px solid rgba(56,189,248,.3);background:linear-gradient(90deg,rgba(14,165,233,.15),rgba(59,130,246,.10),rgba(14,165,233,.05));box-shadow:0 0 10px -2px rgba(56,189,248,.35);white-space:nowrap}
.rb-pill i{width:4px;height:4px;border-radius:99px;background:#7dd3fc;box-shadow:0 0 6px rgba(56,189,248,.9)}
.rb-pill b{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:rgba(125,211,252,.7)}
.rb-pill span{font-size:12px;font-weight:700;color:#bae6fd;font-variant-numeric:tabular-nums}
.rb-sub-pill{font-size:10px;padding:2px 8px;border-radius:999px;background:rgba(59,130,246,.1);border:1px solid rgba(59,130,246,.2);color:rgba(96,165,250,.8);white-space:nowrap}
.rb-verdict{font-size:10px;font-weight:800;letter-spacing:.08em;padding:2px 8px;border-radius:999px;border:1px solid;white-space:nowrap}
.rb-cnt{display:inline-flex;align-items:center;gap:6px;padding:2px 4px 2px 8px;border-radius:999px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.02);white-space:nowrap}
.rb-cnt b{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:rgba(255,255,255,.3)}
.rb-cnt span{font-size:12px;font-weight:700;min-width:20px;text-align:center;padding:2px 6px;border-radius:999px;background:rgba(255,255,255,.05);color:rgba(255,255,255,.4)}
.rb-cnt.rb-ltd{background:rgba(249,115,22,.1);border-color:rgba(249,115,22,.5)}
.rb-cnt.rb-ltd b{color:#fdba74}.rb-cnt.rb-ltd span{background:rgba(255,255,255,.1);color:#fff}
.rb-end{margin-left:auto;display:flex;gap:6px}
.rb-why{margin:2px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:2px;font-size:11px;color:rgba(255,255,255,.55)}
.rb-why li:before{content:"• ";color:rgba(255,255,255,.3)}
.rb-why.rb-bad li{color:#fca5a5}.rb-why.rb-chk li{color:#fcd34d}
.rb-links{display:flex;gap:6px;flex-wrap:wrap}
.rb-link{font-size:10px;padding:2px 8px;border-radius:999px;background:rgba(59,130,246,.1);border:1px solid rgba(59,130,246,.2);color:#93c5fd}
.rb-link:hover{background:rgba(59,130,246,.2)}
.rb-c-approve{border-color:rgba(52,211,153,.4)!important;background:rgba(16,185,129,.06)!important}
.rb-c-check{border-color:rgba(251,191,36,.4)!important;background:rgba(245,158,11,.06)!important}
.rb-c-reject{border-color:rgba(239,68,68,.5)!important;background:rgba(239,68,68,.07)!important}
.rb-v-approve{color:#6ee7b7;border-color:rgba(52,211,153,.4);background:rgba(16,185,129,.1)}
.rb-v-check{color:#fcd34d;border-color:rgba(251,191,36,.4);background:rgba(245,158,11,.1)}
.rb-v-reject{color:#fca5a5;border-color:rgba(239,68,68,.5);background:rgba(239,68,68,.1)}
@media(max-width:640px){.rb-char{width:40px;height:40px}.rb-lc{width:24px;height:36px}.rb-meta{display:none}.rb-row{flex-wrap:wrap}}
"""


def esc(x):
    return html.escape(str(x if x is not None else ''), quote=True)


def img(kind, name):
    return f'{SITE}/px_{kind}/{quote(str(name))}.png' if name else ''


def when(iso):
    try:
        return datetime.fromisoformat(str(iso).replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
    except Exception:
        return ''


def platform(url):
    u = url or ''
    if 'bilibili' in u or 'b23.tv' in u:
        return '<i class="fa-brands fa-bilibili"></i> <span class="rb-bili">bili</span>'
    if 'youtu' in u:
        return '<i class="fa-brands fa-youtube"></i> <span class="rb-yt">YT</span>'
    return ''


def load(rev):
    d = os.path.join(RUNS, rev)
    try:
        item = json.load(open(os.path.join(d, 'review.json'), encoding='utf8'))
        auto = json.load(open(os.path.join(d, 'auto.json'), encoding='utf8'))
    except (OSError, ValueError):
        return None
    pl = item.get('payload') or {}
    sides = pl.get('runs') or [pl]
    return {'rev': rev, 'side': dict(pl, **sides[0]), 'runs': len(sides), 'auto': auto}


def card(e):
    s, a = e['side'], e['auto']
    verdict = a.get('verdict', 'CHECK')
    border, badge = VERDICT_LOOK.get(verdict, VERDICT_LOOK['CHECK'])
    slots = []
    for i in range(1, 5):
        c = s.get(f'p{i}_char')
        if not c:
            continue
        lc = s.get(f'p{i}_lc')
        first = ' rb-first ring-1 ring-blue-300/50' if i == 1 else ' ring-1 ring-white/8'
        light = (f'<div class="run-card-light-cone"><div class="rb-lc relative w-6 h-9 sm:w-9 sm:h-[3.1rem] rounded overflow-hidden bg-white/5 ring-1 ring-white/10 mt-0.5">'
                 f'<img alt="{esc(lc)}" loading="lazy" src="{esc(img("lc", lc))}" onerror="this.style.display=\'none\'">'
                 f'<span class="rb-badge rb-s absolute bottom-0 right-0 text-[11px] font-bold px-1.5 leading-[15px] rounded-tl bg-black/85 text-purple-200">S{esc(s.get(f"p{i}_superimp", "?"))}</span></div></div>'
                 if lc else '')
        slots.append(
            f'<div class="flex flex-col items-center gap-1 select-none rb-slot"><div class="rb-char{first} relative w-10 h-10 sm:w-14 sm:h-14 rounded-lg overflow-hidden bg-white/5 group">'
            f'<img alt="{esc(c)}" title="{esc(c)}" loading="lazy" src="{esc(img("char", c))}" class="object-cover object-top" onerror="this.style.display=\'none\'">'
            f'<span class="rb-badge rb-e absolute bottom-0 right-0 text-[11px] font-bold px-1.5 leading-[15px] rounded-tl bg-black/85 text-blue-200">E{esc(s.get(f"p{i}_eidolon", "?"))}</span></div>{light}</div>')
    mode = str(s.get('mode') or '').upper()
    metric = s.get('metric_value')
    if isinstance(metric, float) and metric.is_integer():
        metric = int(metric)
    label = 'Score' if mode == 'AS' else 'Cycle'
    pills = [f'<span class="rb-verdict {badge}">{esc(verdict)} {esc(a.get("confidence", ""))}%</span>']
    if metric not in (None, ''):
        pills.append(f'<div class="theme-metric-pill theme-metric-pill-blue rb-pill inline-flex items-center gap-1 rounded-full border stat-number"><i class="theme-metric-pill-dot"></i>'
                     f'<b class="theme-metric-pill-label">{label}</b><span class="theme-metric-pill-value">{esc(metric)}</span></div>')
    for t in (s.get('subcategory'), s.get('boss_name'), mode):
        if t:
            pills.append(f'<span class="theme-run-subcategory-pill rb-sub-pill">{esc(t)}</span>')
    ltd, std = s.get('total_limited_5star_count'), s.get('total_standard_5star_count')
    counts = ''
    if ltd is not None:
        counts = (f'<div class="rb-end"><div class="rb-cnt rb-ltd stat-number"><b>Ltd</b><span>{esc(ltd)}</span></div>'
                  f'<div class="rb-cnt stat-number"><b>Std</b><span>{esc(std if std is not None else 0)}</span></div></div>')
    why = []
    for x in (a.get('problems') or [])[:4]:
        why.append(('rb-bad', x))
    for x in (a.get('check_reasons') or [])[:4]:
        why.append(('rb-chk', x))
    reasons = ''.join(f'<ul class="rb-why {c}"><li>{esc(t)}</li></ul>' for c, t in why)
    video = s.get('video_url') or ''
    links = [f'<a class="rb-link" href="{SITE}/mod?review={esc(e["rev"])}" target="_blank" rel="noopener">Review {esc(e["rev"])}</a>']
    if video:
        links.append(f'<a class="rb-link" href="{esc(video)}" target="_blank" rel="noopener">Video</a>')
    note = f' <span class="rb-gcount">({e["runs"]} runs in one item)</span>' if e['runs'] > 1 else ''
    return (f'<div id="run-card-{esc(e["rev"])}" class="theme-run-card rb-card relative rounded-xl border overflow-hidden {border}">'
            f'<div class="rb-row p-1.5 sm:p-2 flex gap-1.5 sm:gap-2.5"><div class="rb-team flex gap-1 sm:gap-1.5 shrink-0">{"".join(slots)}</div>'
            f'<div class="rb-mid flex-1 min-w-0 flex flex-col justify-center gap-0.5 sm:gap-1">'
            f'<div class="rb-line flex items-center gap-x-1 sm:gap-x-1.5 min-w-0"><span class="rb-name text-sm font-semibold leading-tight truncate text-white">{esc(s.get("author_name") or e["rev"])}</span>{note}'
            f'<span class="rb-meta stat-number text-white/25 text-[11px]">{platform(video)} {esc(when(s.get("video_date")))}</span></div>'
            f'<div class="rb-pills flex items-center gap-2 min-w-0">{"".join(pills)}{counts}</div>'
            f'{reasons}<div class="rb-links">{"".join(links)}</div></div></div></div>')


def page(entries, title='Review summary', seconds=None):
    # 사이트 CSS(있으면)를 먼저, 그 뒤에 이 파일의 스타일을 항상 붙인다: 사이트 CSS 는 사이트가 쓰는 클래스만 들어 있어(Tailwind 가
    # 안 쓰는 클래스를 뺀다) 요약 전용 클래스(rb-*)는 따로 필요하다. 같은 것을 가리키면 뒤에 오는 이 스타일이 이긴다
    css = (open(THEME, encoding='utf8').read() + '\n' if os.path.exists(THEME) else '') + LITE_CSS
    groups = {v: [e for e in entries if e['auto'].get('verdict') == v] for v in ORDER}
    other = [e for e in entries if e['auto'].get('verdict') not in ORDER]
    if other:
        groups['CHECK'] += other
    stats = ''.join(f'<span class="rb-verdict {VERDICT_LOOK[v][1]}">{v} {len(groups[v])}</span>' for v in ORDER)
    body = []
    for v in ORDER:
        if not groups[v]:
            continue
        rows = sorted(groups[v], key=lambda e: (e['auto'].get('confidence') or 0, e['rev']))
        body.append(f'<div class="flex flex-col gap-1 rounded-xl border border-white/8 bg-white/[0.025] overflow-hidden rb-group">'
                    f'<div class="rb-ghead px-2.5 py-1 sm:px-4 sm:py-2 border-b border-white/8 flex items-center gap-1 sm:gap-2">'
                    f'<span class="theme-run-team-header-icon rb-gicon text-[10px] sm:text-sm">✦</span>'
                    f'<span class="theme-run-team-header-text text-[11px] sm:text-sm font-semibold">{v}</span>'
                    f'<span class="rb-gcount text-white/30 text-[9px] sm:text-xs">({len(rows)} entries)</span></div>'
                    f'<div class="rb-gbody flex flex-col gap-1 p-0.5">{"".join(card(e) for e in rows)}</div></div>')
    took = f' · {seconds / 60:.1f} min' if seconds else ''
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">'
            f'<style>{css}</style></head><body><main class="rb-wrap">'
            f'<div><div class="rb-title">{esc(title)}</div><div class="rb-sub">{len(entries)} records · {esc(datetime.now().strftime("%Y-%m-%d %H:%M"))}{esc(took)}</div></div>'
            f'<div class="rb-stats">{stats}</div>{"".join(body)}</main></body></html>')


def write_summary(revs, out=None, seconds=None):
    entries = [e for e in (load(r) for r in revs) if e]
    if not entries:
        return None
    os.makedirs(WORK, exist_ok=True)
    out = out or os.path.join(WORK, f'summary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html')
    text = page(entries, seconds=seconds)
    open(out, 'w', encoding='utf8').write(text)
    open(os.path.join(WORK, 'summary_latest.html'), 'w', encoding='utf8').write(text)
    return out


if __name__ == '__main__':
    a = sys.argv[1:]
    out = a[a.index('--out') + 1] if '--out' in a else None
    revs = [x for x in a if x.startswith('rev_')]
    if not revs:
        revs = sorted(x for x in os.listdir(RUNS) if os.path.exists(os.path.join(RUNS, x, 'auto.json')))
    print(write_summary(revs, out))
