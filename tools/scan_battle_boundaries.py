"""Battle segmentation with HUD tracking; --full-ocr retains the legacy scan."""
import argparse
import difflib
import json
import re
import sys
import subprocess
import time
import unicodedata
from pathlib import Path

PROMPTS = {'TextMapCHS': {'battle_start': '战斗开始', 'your_turn': '我方行动中', 'enemy_turn': '敌方行动中', 'battle_over': '结束战斗'}, 'TextMapCHT': {'battle_start': '戰鬥開始', 'your_turn': '我方行動中', 'enemy_turn': '敵方行動中', 'battle_over': '結束戰鬥'}, 'TextMapDE': {'battle_start': 'Kampf beginnt', 'your_turn': 'Du bist am Zug', 'enemy_turn': 'Gegner ist am Zug', 'battle_over': 'Kampf endet'}, 'TextMapEN': {'battle_start': 'Battle Start', 'your_turn': 'Your Turn', 'enemy_turn': "Enemy's Turn", 'battle_over': 'Battle Over'}, 'TextMapES': {'battle_start': '¡Comienza la batalla!', 'your_turn': 'Tu turno', 'enemy_turn': 'Turno enemigo', 'battle_over': 'Fin de la batalla'}, 'TextMapFR': {'battle_start': 'Début du combat', 'your_turn': 'Votre tour', 'enemy_turn': "Tour de l'ennemi", 'battle_over': 'Combat terminé'}, 'TextMapID': {'battle_start': 'Pertempuran Dimulai', 'your_turn': 'Giliran Timmu', 'enemy_turn': 'Giliran Musuh', 'battle_over': 'Pertempuran Berakhir'}, 'TextMapJP': {'battle_start': '戦闘開始', 'your_turn': '味方のターン', 'enemy_turn': '敵のターン', 'battle_over': '戦闘終了'}, 'TextMapKR_0': {'battle_start': '전투\xa0시작', 'your_turn': '아군\xa0행동\xa0중', 'enemy_turn': '적\xa0행동\xa0중', 'battle_over': '전투\xa0종료'}, 'TextMapPT': {'battle_start': 'Início da Batalha', 'your_turn': 'Sua Vez', 'enemy_turn': 'Vez do Inimigo', 'battle_over': 'Fim da Batalha'}, 'TextMapRU_0': {'battle_start': 'В бой!', 'your_turn': 'Ваш ход', 'enemy_turn': 'Ход противника', 'battle_over': 'Бой окончен'}, 'TextMapTH_0': {'battle_start': 'เริ่มการต่อสู้', 'your_turn': 'แอ็กชันของฝ่ายคุณ', 'enemy_turn': 'แอ็กชันของฝ่ายศัตรู', 'battle_over': 'สิ้นสุดการต่อสู้'}, 'TextMapVI': {'battle_start': 'Bắt Đầu', 'your_turn': 'Phe Ta', 'enemy_turn': 'Phe Địch', 'battle_over': 'Kết Thúc'}}
EXPECTED = [
    ('start', 1, 14), ('wave', 2, 59), ('end', None, 172),
    ('start', 1, 217), ('wave', 2, 277), ('end', None, 494),
    ('start', 1, 535), ('wave', 2, 599), ('end', None, 703),
]


def normalize(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return ''.join(c for c in text if c.isalnum() or unicodedata.category(c).startswith('M'))

def vietnamese_key(text):
    text = text.casefold().replace('đ', 'd')
    text = unicodedata.normalize('NFD', text)
    return ''.join(c for c in text if c.isalnum())

def recognize(text):
    original = unicodedata.normalize('NFKC', text)
    fraction = re.search(r'(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)', original)
    wave = total = None

    if fraction is None and any(c.isdigit() for c in original):
        return None

    if fraction:
        wave, total = map(int, fraction.groups())
        original = original[:fraction.start()] + original[fraction.end():]
        if not 1 <= wave <= total <= 20:
            return None
    target = normalize(original)
    if not target:
        return None
    scores = {}
    for translations in PROMPTS.values():
        for kind in ('battle_start', 'battle_over'):
            label = normalize(translations[kind])
            score = difflib.SequenceMatcher(None, target, label).ratio()
            if translations == PROMPTS['TextMapVI']:
                if vietnamese_key(original) == vietnamese_key(translations[kind]):
                    score = 1.0
            scores[kind] = max(scores.get(kind, 0), score)
    ranked = sorted(scores, key=scores.get, reverse=True)
    kind = ranked[0]
    if scores[kind] < 0.86 or scores[kind] - scores[ranked[1]] < 0.08:
        return None
    if kind == 'battle_over' and fraction:
        return None
    event = 'end' if kind == 'battle_over' else 'wave' if wave and wave > 1 else 'start'
    return {'kind': event, 'wave': wave, 'total_waves': total,
            'text': text, 'score': round(scores[kind], 4),
            'start_number_missing': event == 'start' and wave is None}


def consolidate_events(events, observations=None, gap=3.0):
    merged = []
    for original in sorted(events, key=lambda e: e['t']):
        event = dict(original)
        previous = merged[-1] if merged else None
        nearby = previous and 0 <= event['t'] - previous.get('last_t', previous['t']) <= gap
        same = nearby and (event['kind'], event.get('wave')) == (
            previous['kind'], previous.get('wave'))
        unnumbered = nearby and (
            (event['kind'] == 'start' and event.get('wave') is None
             and previous['kind'] in ('start', 'wave'))
            or (previous['kind'] == 'start' and previous.get('wave') is None
                and event['kind'] in ('start', 'wave'))
        )
        if same or unnumbered:
            if previous.get('wave') is None and event.get('wave') is not None:
                first_t = previous['t']
                previous.update(event)
                previous['t'] = first_t
            previous['last_t'] = max(previous.get('last_t', previous['t']),
                                     event.get('last_t', event['t']))
        else:
            merged.append(event)

    for event in merged:
        if event.get('wave') is None:
            continue
        readings = [o for o in (observations or events)
                    if o['kind'] == event['kind'] and o.get('wave') == event['wave']
                    and event['t'] <= o['t'] <= event.get('last_t', event['t'])]
        votes = {}
        for reading in readings:
            total = reading.get('total_waves')
            votes.setdefault(total, set()).add(reading['t'])
        ranked = sorted(votes, key=lambda total: len(votes[total]), reverse=True)
        event.pop('boundary_warning', None)
        if len(ranked) > 1:
            winner = ranked[0]
            support = len(votes[winner])
            if support >= 2 and support >= 2 * len(votes[ranked[1]]):
                event['total_waves'] = winner
                event['total_votes'] = {str(k): len(v) for k, v in votes.items()}
            else:
                event['boundary_warning'] = 'Conflicting wave totals in one banner; verify boundary'
    return merged


def recovery_ranges(events, end):
    segments, _ = assemble(events)
    ranges = []
    for segment in segments:
        if segment['end'] is not None or segment['start'] is None:
            continue
        left = segment['waves'][-1]['t'] if segment['waves'] else segment['start']
        following = [e['t'] for e in events
                     if e['kind'] == 'start' and e['t'] > left]
        right = min(following) if following else end
        if right > left:
            ranges.append((left, right))
    return ranges


def prompt_matches(engine, crop, diagnostics=None, context=None):
    boxes = sorted(engine(crop, scale=2.0 if crop.shape[1] < 800 else 1.0),
                   key=lambda box: (box[1], box[0]))
    texts = [box[4] for box in boxes]
    for left, right in zip(boxes, boxes[1:]):
        if abs((left[1]+left[3]/2)-(right[1]+right[3]/2)) < .5*max(left[3],right[3]):
            texts.append(left[4] + ' ' + right[4])
    matches = [match for text in texts if (match := recognize(text)) is not None]
    if diagnostics is not None:
        diagnostics.write(json.dumps({'context': context, 'texts': texts, 'matches': matches}, ensure_ascii=False) + '\n')
    return matches


def assemble(events):
    segments, warnings = [], []
    current = None
    first_start = next(
        (event['t'] for event in events if event['kind'] == 'start'),
        None,
    )
    for event in events:
        kind = event['kind']
        if kind == 'start':
            if current is not None and event.get('wave') is None:
                last_prompt = (
                    current['waves'][-1]['t']
                    if current['waves']
                    else current['start']
                )
                if (
                    last_prompt is not None
                    and 0 <= event['t'] - last_prompt <= 3.0
                ):
                    continue

            if current is not None:
                current['warnings'].append('New start before an end was detected')
                current['status'] = 'CHECK'
                segments.append(current)
            current = {'start': event['t'], 'end': None, 'waves': [],
                       'status': 'candidate', 'warnings': []}
            if event.get('start_inferred'):
                current['start_inferred'] = True
                current['start_source'] = event.get('source')
            
            if event.get('boundary_warning'):
                current['warnings'].append(event['boundary_warning'])
                
        elif kind == 'wave':
            if current is None:
                current = {'start': None, 'end': None, 'waves': [],
                           'status': 'CHECK', 'warnings': ['First-wave start not detected']}
            current['waves'].append({'t': event['t'], 'wave': event['wave'], 'total': event['total_waves']})
        elif current is not None:
            current['end'] = event['t']
            if current['warnings']:
                current['status'] = 'CHECK'
            segments.append(current)
            current = None
        else:
            if first_start is not None and event['t'] < first_start:
                event['ignored_reason'] = 'Possible opening preview before first battle start'
            else:
                warnings.append(f"End at {event['t']} without a detected start")
    if current is not None:
        current['status'] = 'CHECK'
        current['warnings'].append('Battle end not detected')
        segments.append(current)
    return segments, warnings


def aligned_text_row(components, image_height, crop_width):
    """Conservative geometry check; text meaning is still checked by OCR."""
    for x, y, width, height in components:
        row = [box for box in components
               if abs((box[1] + box[3]/2) - (y + height/2))
               <= max(.006*image_height, .45*max(height, box[3]))
               and .5*height <= box[3] <= 2*height]
        if len(row) >= 3:
            span = max(box[0]+box[2] for box in row) - min(box[0] for box in row)
            if span >= .065*crop_width:
                return True
    return False


def prompt_text_gate(crop, image_height):
    import cv2
    import numpy as np
    if crop.size == 0:
        return False
    scale = min(1.0, 640/crop.shape[1])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    height = image_height*scale
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 2] >= 130) & (hsv[..., 1] <= 100)).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    components = [tuple(map(int, row[:4])) for row in stats[1:]
                  if .008*height <= row[3] <= .055*height
                  and 1 <= row[2] <= 3*row[3] and row[4] >= 3]
    return aligned_text_row(components, height, crop.shape[1])


def compare_boundaries(baseline, result, tolerance=.75):
    comparisons = []
    used = set()
    for expected in baseline['events']:
        choices = [(i, actual) for i, actual in enumerate(result['events'])
                   if i not in used and all(actual.get(k)==expected.get(k)
                                            for k in ('kind', 'wave', 'total_waves'))]
        nearest = min(choices, key=lambda item: abs(item[1]['t']-expected['t'])) if choices else None
        retained = nearest is not None and abs(nearest[1]['t']-expected['t']) <= tolerance
        if retained:
            used.add(nearest[0])
        comparisons.append({'kind':expected['kind'], 'wave':expected.get('wave'),
                            'baseline_t':expected['t'],
                            'gated_t':nearest[1]['t'] if nearest else None,
                            'retained':retained})
    return {'tolerance_seconds':tolerance,
            'all_baseline_events_retained':all(c['retained'] for c in comparisons),
            'events':comparisons,
            'extra_events':[e for i,e in enumerate(result['events']) if i not in used],
            'baseline_segment_count':len(baseline['segments']),
            'gated_segment_count':len(result['segments'])}


def letterbox_rows(frame):
    """위아래 검은 띠의 높이 (top, bottom). 띠가 없거나 위아래가 어긋나면 (0, 0).
    띠 안에 워터마크 글자가 있어도(빌리빌리: 위 띠에 「…  bilibili」, rev_1lqaklu) 띠로 보도록, 행의 80% 이상이 어두우면 어두운 행으로 센다.
    (예전: 98% — 글자가 걸친 행이 한 줄도 어두운 행이 아니어서 띠를 못 알아보고 HUD 검색 영역이 띠 안에 들어갔다)"""
    h = frame.shape[0]
    dark_rows = (frame.max(axis=2) <= 28).mean(axis=1) >= .80
    limit = int(.20 * h)
    top = bottom = 0
    while top < limit and dark_rows[top]:
        top += 1
    while bottom < limit and dark_rows[h - 1 - bottom]:
        bottom += 1
    if (min(top, bottom) < 4 or max(top, bottom) >= limit
            or abs(top - bottom) > max(4, int(.02 * h))):
        return 0, 0
    return top, bottom


def boundary_crop(frame):
    h, w = frame.shape[:2]
    top, bottom = letterbox_rows(frame)
    active_h = h - top - bottom
    return frame[top + int(.08 * active_h):top + int(.26 * active_h),
                 int(.25 * w):int(.75 * w)]


def adaptive_ranges(events, start, end):
    """Search unresolved start/end intervals; intermediate waves are clues only."""
    if not events:
        return [(start, end)]
    ranges = []
    active = None
    previous_end = start
    orphan_wave = None
    for event in sorted(events, key=lambda e: e['t']):
        t = event['t']
        if event['kind'] == 'start':
            if active is not None:
                ranges.append((active, t))
            elif orphan_wave is not None:
                ranges.append((previous_end, t))
            active = t
            orphan_wave = None
        elif event['kind'] == 'wave':
            if active is None and orphan_wave is None:
                orphan_wave = t
        else:
            if active is None:
                # Inspect an opening end too; assemble still ignores preview ends.
                ranges.append((previous_end, t))
            active = None
            orphan_wave = None
            previous_end = t
    if active is not None or orphan_wave is not None:
        ranges.append((active if active is not None else previous_end, end))
    merged = []
    for left, right in sorted(ranges):
        left, right = max(start, left - .5), min(end, right + .5)
        if right <= left:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return merged



HUD_TEMPLATES = {'pause': 'iVBORw0KGgoAAAANSUhEUgAAAA0AAAATCAYAAABLN4eXAAABxElEQVR4nHWTT2sTURTFf+fOy0yppcWgoN0pJCspiH4HKa3gtujXNaItXdZNSHEjxLqzf5KZvHddvMm0ifHCMHDPO/eec+aNdnpDdxfguDtm4J4AB4FkHYYbkhEkkHl7KCEBLmJMAHkICQECUoyElCJv3r5mOHzBr6spn0cj7m5q3IUooHAODl4xGLxkOr3i29k5AeD4+B0nn95zenrO94sLft7+prBASlBVJUdHh5x8/MDXL+dMLn9gJmN3d5tn+0/o9/dQYZgF3AvMDBA7j3Z4vv+U/uM9ClV5EzgP30LQBpDb3qHuECRxX8oEBK6ut16BJcm7gZncbvqXwlLeWvky4K6xApv7/RkzgARKJI84MYtVBBJSfjZsaj806YHstU0b5a2McHJYWa4Q1kn3/7G8A93b+9kZ3xRTV6ugCbFYwPyuoa4XmAXAkbIvF9RNyniTfYZFjIxGZxRmTC7H3NzMQQKPOE7dOKPRKb2yZDye8Of6Gm2HgVdbFVVZEeOMu9mcYCXukeQLUkxUWyW9XsGsaWjmkWAyFvNEPbvF5JjK1oPlnCSaxqnnNTElCisIyytTSO0fK1KE5I6ZYdZGbUXrE/4C/qTVro86lC0AAAAASUVORK5CYII=', 'speed': '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', 'auto': 'iVBORw0KGgoAAAANSUhEUgAAAB4AAAATCAYAAACHrr18AAAEfElEQVR4nIWWXXfaRhCGn1khjE1SBzeNgRgcbA5Jc5rL8gPa/3/SY7dxXTs2IIr8haH+QFhod3ohITtpz8neSOxq5515550ZpFr5VR0WdQmiFnWKCACIAVXFiIAaVDXdF8FggPRcFURARVBVRARI3zX7xvMkv6+qFJxzKIpACuBJ+jsDB0VREJddzAy6JcByCU5tfi5iMm8cnieIPNlHKagqiILARmWD79afc3V1RRRFJEkMPDWeeisIxmRHCkqKIYCqAzGICGI8Xv2wSam0QhiGxPECEYM6S0FEUMAYj2azyYcPPzEKRwTBgNHob+7vI5w6UEmto5ilYRGcc2lg6rL0GIp+EeP5OGvZbe+w/t1zxuMx83mMZMwVEM1iUkprJV5tvqK0WqJer3F5ecXh4SFn52fM7qMU3IEzaTqMeDgBSMGLhSKVjQ1arTdY5zj884Dnz1fZ+L6CMYJzNqVaHYWnNArCfD5nb2+PcrlMo9GgWq0yGo349OmAs/CceLFAJOMXh2cMftFndbVEe7fNzs4Oa+U1jo+PQBTPM7kWliIEeQQWBOMZrLUEQcB0OmU4HPL+x/fU63UqlQpBMOT05JSLiwustYBSfrZKq/WGWq1Go9Hg7u6Og4MDjo4OiaJZbvvLAPkq4ixvAFEUcXx8zOXlJbVajd3dXd69e8vrep1ev0c4ClkpFdnZadFsbhPHMb/v/8FgMGAyvSaKIny/kJfQ1ysH1kyezjmstTiXimA8HnN7e0sYhnQ6Hd6+7dDtdrm5uWVlpYDve5yc9Dg4OCQcnZHYBGddGgQeZPX+WB1peaaqVhAMIh5GPFQlr0tBSBJLFEXc3PxDHD9QLBZ49myNYtEnSRZEUcTd3Q2LxQOLZAEIfsFPo1VBxCCiiLjM7hNxiQjGZEJQzeu1VFqhWq3SbrfZ2qojIuzv7xOGIeVymVarRbvdZv3FOkd/HTEY9JlOp1gnFKX4FcGaP7+gOq9FEXy/QL1ep16vsr3dpFRa5fw8pNfrEQQB83mM53kEQUCr1aJWr9Htdmk2t+j3+5ydXRBF82/nGE3Vp1m01WqNbvdnXryoMJ1O+PjxNwaDQUbpAlWw1hKGIZPJhJeDl3Q6Hdq7OzQaW/T7AScnffyi/w1glq1P8H2ftbU1rFX29vbp9/pcT8YkSZKKDgO4rGsJs9mM4XDI1dWYXu+UTqfDdrPF1us3lEolZrPZf4FTGRmMeCziVCjOOYZBwPX4mtu7O5JFwiKJEQFjsimVNwXFmNTKbBbx+fMpo9EZW1sNOp13bG5uMptFmapTIYNQECQ3MhwOmc/vuZ/d8xDHPMxjrCqKy6eAy3JmxGR6IHcA0vMomtPr9ZhMJlSrdZxN90RM5qhBapVfMh/AeApq857qstng1CFoZjybyf8ztZbgxpg8DX6hiHOQJAtEJOt48lTVYK0DddncdIgUUE3n9HLvcQmP5bEk0qHqUKf5URwnOb3LKeicSxvI8iKYfLamTWSp9McIZdmIdPmS0SzgnM0tPf2T4HneF4yIGP4FUn2Z3IQY6b4AAAAASUVORK5CYII='}

def active_picture(frame):
    top, bottom = letterbox_rows(frame)
    if not (top or bottom):
        return frame
    return frame[top:frame.shape[0] - bottom]


class BattleHUD:
    """Experimental white-icon matching; HUD absence is never a boundary."""
    @staticmethod
    def white_mask(image):
        import cv2
        import numpy as np
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        return ((hsv[..., 1] < 95) & (hsv[..., 2] > 155)).astype(np.uint8)*255

    def __init__(self):
        import base64
        import cv2
        import numpy as np
        self.templates = {}
        for name, data in HUD_TEMPLATES.items():
            color = cv2.imdecode(np.frombuffer(base64.b64decode(data), np.uint8), 1)
            variants = []
            for scale in (.85, .90, .95, 1., 1.05, 1.10, 1.15):
                template = self.white_mask(cv2.resize(color, None, fx=scale, fy=scale))
                if template.std() > 0:
                    variants.append(template)
            self.templates[name] = variants
        # 일시정지 아이콘은 영상마다 크기가 크게 다르다(1280 폭으로 맞춰도 템플릿의 0.5배~1.0배 — 1080p 녹화 · 모바일 · 가로로 넓은 화면).
        # 위의 0.85~1.15배만으로는 놓치는 영상이 많아(rev_1lqaklu 는 0%) 0.4~1.25배를 따로 훑는다
        base = cv2.imdecode(np.frombuffer(base64.b64decode(HUD_TEMPLATES['pause']), np.uint8), 1)
        self.wide_pause = []
        for step in range(17):
            template = self.white_mask(cv2.resize(base, None, fx=.40 + .05*step, fy=.40 + .05*step))
            if template.std() > 0:
                self.wide_pause.append(template)

    def read(self, frame):
        import cv2
        picture = active_picture(frame)
        h, w = picture.shape[:2]
        # UI 는 화면이 16:9 보다 넓으면 폭에, 좁으면(1106x720, 4:3 …) 높이에 맞춰 크기가 정해진다. 그래서 720p 기준 크기가 되도록
        # 넓으면 폭을 1280 에, 좁으면 높이를 720 에 맞춘다(예전: 늘 폭을 1280 에 맞춰 좁은 화면에서 아이콘이 1.16배 커졌다).
        # HUD 는 화면 오른쪽 위 모서리에 붙어 있으니 영역도 720p 기준 단위(위 100, 오른쪽 243)로 자른다.
        scale = min(1280 / w, 720 / h)
        picture = cv2.resize(picture, (round(w*scale), round(h*scale)))
        height, width = picture.shape[:2]
        region = self.white_mask(picture[:min(height, 100), max(0, width - 243):])
        scores = {}
        for name, variants in self.templates.items():
            scores[name] = max((float(cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1])
                               for template in variants
                               if template.shape[0] <= region.shape[0] and template.shape[1] <= region.shape[1]), default=0.)
        scores['pause_wide'] = max((float(cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1])
                                    for template in self.wide_pause
                                    if template.shape[0] <= region.shape[0] and template.shape[1] <= region.shape[1]), default=0.)
        present = (scores['pause'] >= .80 or (scores['speed'] >= .80 and scores['auto'] >= .65)
                   or scores['pause_wide'] >= .85)
        return {'present': bool(present), 'top': bool(present),
                'scores': {key: round(value, 4) for key, value in scores.items()}}


def hud_gaps(samples, minimum=15., step=.5):
    """Only accept absence following observed HUD, with continuous sampling."""
    gaps = []
    last_present = absent = previous = None
    positive_streak = 0
    for sample in samples:
        t = sample['t']
        if previous is not None and t-previous > step*1.6:
            last_present = absent = None
            positive_streak = 0
        previous = t
        if sample['present']:
            positive_streak += 1
            if positive_streak < 2:
                continue
            if absent is not None and t-absent >= minimum:
                gaps.append({'last_present': last_present, 'start': absent, 'end': t})
            last_present, absent = t, None
        else:
            positive_streak = 0
            if last_present is not None and absent is None:
                absent = t
    if absent is not None and samples[-1]['t']-absent >= minimum:
        gaps.append({'last_present': last_present, 'start': absent, 'end': samples[-1]['t']})
    return gaps


def hud_search_ranges(gaps, events, start, end):
    unresolved = adaptive_ranges(events, start, end)
    ranges = []
    for gap in gaps:
        # Banner can appear before or after HUD disappears.
        left, right = max(start, gap['last_present']-2), min(end, gap['start']+3)
        if any(left < b and right > a for a, b in unresolved):
            if ranges and left <= ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], max(right, ranges[-1][1]))
            else:
                ranges.append((left, right))
    return ranges


def state_frames(ff, video, start, end, fps, width, height):
    import numpy as np
    if end <= start:
        return
    process = subprocess.Popen(
        [ff, '-v', 'error', '-ss', str(start), '-t', str(end-start), '-i', str(video),
         '-vf', f'fps={fps},scale={width}:{height}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = width*height*3
    try:
        index = 0
        while True:
            chunks = bytearray()
            while len(chunks) < size:
                data = process.stdout.read(size-len(chunks))
                if not data:
                    break
                chunks.extend(data)
            if len(chunks) != size:
                break
            t = start+index/fps
            if t >= end:
                break
            yield t, np.frombuffer(chunks, np.uint8).reshape(height, width, 3)
            index += 1
        if process.poll() is None:
            process.wait()
        if process.returncode:
            raise RuntimeError(f'FFmpeg decoding failed with exit code {process.returncode}')
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def run_hud_state(args):
    started = time.perf_counter()
    scanner = sys.modules[__name__]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'auto'))
    import cv2
    import tabs
    from paths import FF
    from ocr import OCR
    duration, width, height = tabs.probe(str(args.video))
    finish = min(duration, args.end if args.end is not None else duration)
    if finish <= args.start:
        raise ValueError('end must be after start and within video')
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    engine = OCR(args.model)
    hud = scanner.BattleHUD()
    observations, retries, hud_samples = [], [], []
    counts = {'ocr_calls': 0, 'search_ocr_calls': 0, 'transition_ocr_calls': 0,
              'fallback_ocr_calls': 0, 'hud_frames': 0, 'decoded_frames': 0}
    diagnostics = (output/'raw_ocr.jsonl').open('w', encoding='utf8', buffering=1)

    def read(t, frame, source):
        counts['ocr_calls'] += 1
        counts[source+'_ocr_calls'] += 1
        found = scanner.prompt_matches(engine, scanner.boundary_crop(frame), diagnostics,
                                       {'t': round(t, 3), 'crop': source})
        found = [hit for hit in found if hit['kind'] in ('start', 'end')]
        if not found:
            return None
        hit = dict(max(found, key=lambda hit: (hit['score'], hit.get('wave') is not None)))
        hit.update(t=round(t, 3), last_t=round(t, 3), source=source)
        filename = f"{source}_{t:.3f}_{hit['kind']}.jpg"
        hit['evidence'] = filename if cv2.imwrite(str(output/filename), frame) else None
        return hit

    def transition(left, right, battle_start, source):
        info = {'range': [round(left, 3), round(right, 3)], 'fps': 4, 'source': source, 'hits': 0}
        retries.append(info)
        fps = 8 if source == 'transition' else 4
        info['fps'] = fps
        print(f'{source}: {left:.2f}-{right:.2f}s at {fps} fps', flush=True)
        stream = state_frames(FF, args.video, left, right, fps, width, height)
        try:
            for t, frame in stream:
                counts['decoded_frames'] += 1
                hit = read(t, frame, source)
                if hit and hit['t'] > battle_start+3:
                    info['hits'] += 1
                    # One recognized banner is evidence, matching baseline policy.
                    return hit
        finally:
            stream.close()
        return None

    cursor = args.start
    battle_start = None
    resets = []
    try:
        while cursor < finish:
            last_present = absent = None
            streak = 0
            checked_gap = False
            restart = False
            next_progress = cursor
            stream = state_frames(FF, args.video, cursor, finish, 2, width, height)
            try:
                for t, frame in stream:
                    counts['decoded_frames'] += 1
                    if t >= next_progress:
                        print(f"{'Searching start' if battle_start is None else 'Tracking HUD'} {t:.1f}/{finish:.1f}s", flush=True)
                        next_progress = t+30
                    if battle_start is None:
                        hit = read(t, frame, 'search')
                        if hit:
                            observations.append(hit)
                            if hit['kind'] == 'start':
                                battle_start = hit['t']
                                print(f"Battle start {battle_start:.2f}s", flush=True)
                        elif t <= args.start+.5+1e-6:
                            sample = dict(t=round(t, 3), **hud.read(frame))
                            hud_samples.append(sample)
                            counts['hud_frames'] += 1
                            if (len(hud_samples) == 2
                                    and abs(hud_samples[0]['t']-args.start) < .001
                                    and abs(t-args.start-.5) < .001
                                    and all(item['present'] for item in hud_samples)):
                                battle_start = args.start
                                inferred = {
                                    'kind': 'start', 'wave': None,
                                    'total_waves': None, 'text': '',
                                    'score': None, 't': args.start,
                                    'last_t': args.start,
                                    'source': 'opening_hud',
                                    'start_inferred': True,
                                    'evidence': 'opening_hud.jpg',
                                }
                                if not cv2.imwrite(str(output/'opening_hud.jpg'), frame):
                                    inferred['evidence'] = None
                                observations.append(inferred)
                                last_present, streak = t, 2
                                print('Battle already active at recording start; '
                                      'tracking HUD (start inferred)', flush=True)
                        continue
                    sample = dict(t=round(t, 3), **hud.read(frame))
                    hud_samples.append(sample)
                    counts['hud_frames'] += 1
                    if sample['present']:
                        streak += 1
                        if streak >= 2:
                            if absent is not None and t-absent >= 6:
                                hit = transition(
                                    max(battle_start+.5, t-2.5),
                                    min(finish, t+3),
                                    battle_start, 'transition')
                                if hit:
                                    observations.append(hit)
                                    if hit['kind'] == 'end':
                                        print(f"Battle end {hit['t']:.2f}s (HUD return search)", flush=True)
                                        battle_start = None
                                    else:
                                        print(f"Restart detected at {hit['t']:.2f}s; previous attempt starting at {battle_start:.2f}s marked incomplete", flush=True)
                                        resets.append({'previous_start': battle_start, 'new_start': hit['t']})
                                        battle_start = hit['t']
                                    cursor = hit['t']+.5
                                    restart = True
                                    break
                            last_present = t
                            absent = None
                            checked_gap = False
                        continue
                    streak = 0
                    if last_present is None:
                        continue
                    if absent is None:
                        absent = t
                    if checked_gap or t-absent < 15:
                        continue
                    checked_gap = True
                    hit = transition(max(battle_start+.5, last_present-2),
                                     min(finish, absent+5), battle_start, 'transition')
                    if hit:
                        observations.append(hit)
                        if hit['kind'] == 'end':
                            print(f"Battle end {hit['t']:.2f}s", flush=True)
                            battle_start = None
                        else:
                            print(f"Restart detected at {hit['t']:.2f}s; previous attempt starting at {battle_start:.2f}s marked incomplete", flush=True)
                            resets.append({'previous_start': battle_start, 'new_start': hit['t']})
                            battle_start = hit['t']
                        # Revisit footage after the banner, including time spent confirming absence.
                        cursor = hit['t']+.5
                        restart = True
                        break
            finally:
                stream.close()
            if restart:
                continue
            if battle_start is not None and not args.no_repair:
                # Full unresolved interval only if visual transition recovery failed.
                hit = transition(battle_start+.5, finish, battle_start, 'fallback')
                if hit:
                    observations.append(hit)
                    if hit['kind'] == 'end':
                        battle_start = None
                    else:
                        resets.append({'previous_start': battle_start, 'new_start': hit['t']})
                        battle_start = hit['t']
                    cursor = hit['t']+.5
                    continue
            break
        if not any(hit['kind'] == 'start' for hit in observations) and not args.no_repair:
            print('No battle starts found at 2 fps; full-range recovery at 4 fps', flush=True)
            info = {'range': [args.start, finish], 'fps': 4, 'source': 'missing_start_fallback', 'hits': 0}
            retries.append(info)
            recovery = state_frames(FF, args.video, args.start, finish, 4, width, height)
            try:
                for t, frame in recovery:
                    counts['decoded_frames'] += 1
                    hit = read(t, frame, 'fallback')
                    if hit:
                        observations.append(hit)
                        info['hits'] += 1
            finally:
                recovery.close()
    finally:
        diagnostics.close()
    events = scanner.consolidate_events(observations, observations)
    segments, warnings = scanner.assemble(events)
    result = {'video': str(args.video), 'model': args.model, 'fps': 2,
              'range': [args.start, finish], 'events': events, 'segments': segments,
              'warnings': warnings, 'observations': observations,
              'adaptive_retries': retries, 'reset_candidates': resets,
              'performance': dict(counts, total_ocr_calls=counts['ocr_calls'],
                                  elapsed_seconds=round(time.perf_counter()-started, 3)),
              'scanner_version': 'state-hud-production-1',
              'frame_size': {'width': width, 'height': height},
              'sampling_strategy': '2 fps start OCR / HUD tracking / 8 fps transitions / 4 fps fallback',
              'hud_recovery': {'enabled': True, 'restart_absence_seconds': 6, 'end_absence_seconds': 15},
              'note': 'Experimental; HUD disappearance never confirms an end without OCR.'}
    pending = output/'boundaries.pending'
    pending.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    pending.replace(output/'boundaries.json')
    print(f"Performance: {result['performance']}", flush=True)
    print(f"Saved {output/'boundaries.json'}", flush=True)
    (output/'hud_samples.json').write_text(json.dumps(hud_samples), encoding='utf8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', help='Existing local video path; no downloading')
    parser.add_argument('--model', default='latin', choices=['chinese', 'korean', 'latin', 'eslav', 'thai', 'english'])
    parser.add_argument('--fps', type=float, default=2)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--end', type=float)
    parser.add_argument('--output', default=None)
    parser.add_argument('--check-example', action='store_true', help='Compare against the provided 12:09 test video')
    parser.add_argument('--text-gate', action='store_true', help='Experimental bright-text geometry gate before OCR')
    parser.add_argument('--baseline', help='Ungated boundaries.json from the same video/model/range')
    parser.add_argument('--repair-limit', type=float, default=0, help='Legacy compatibility option; adaptive recovery searches unresolved intervals')
    parser.add_argument('--no-repair', action='store_true', help='Disable adaptive intermediate-frame recovery')
    parser.add_argument('--hud-recovery', action='store_true', help='Experimental HUD disappearance hints before broad recovery')
    parser.add_argument('--full-ocr', action='store_true', help='Use legacy full-video OCR instead of HUD state scanning')
    parser.add_argument('--hud-only', action='store_true', help='Visual HUD diagnostics only; no OCR or boundary scan')
    args = parser.parse_args()
    if args.fps <= 0:
        parser.error('fps must be positive')
    if args.repair_limit < 0:
        parser.error('repair-limit must be nonnegative')
    if args.fps <= 0 or args.start < 0:
        parser.error('fps must be positive and start nonnegative')
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / 'auto'))
    import cv2
    import tabs
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        parser.error(f'Video not found: {video}')
    duration, width, height = tabs.probe(str(video))
    end = min(duration, args.end if args.end is not None else duration)
    if end <= args.start:
        parser.error('end must be after start and within the video')
    output = Path(args.output) if args.output else video.parent / (video.stem + '_boundaries')
    output.mkdir(parents=True, exist_ok=True)
    if not args.full_ocr and not args.hud_only and args.fps == 2 and not args.baseline and not args.check_example and not args.text_gate:
        args.video = video
        args.output = output
        print('Boundary mode: start OCR -> HUD tracking -> transition OCR (8 fps)', flush=True)
        run_hud_state(args)
        return
    baseline = json.loads(Path(args.baseline).read_text(encoding='utf-8-sig')) if args.baseline else None
    if baseline and (baseline.get('model') != args.model or baseline.get('fps') != args.fps
                     or abs(baseline['range'][0]-args.start) > .01
                     or abs(baseline['range'][1]-end) > .1):
        parser.error('Baseline model/fps/range differ from this scan')
    started = time.perf_counter()
    if args.hud_only:
        hud = BattleHUD()
        samples = []
        for t, frame in tabs.frames(str(video), args.start, end-args.start, args.fps, width, height):
            samples.append(dict(t=round(t, 3), **hud.read(frame)))
        summary = {'video': str(video), 'range': [args.start, end], 'fps': args.fps,
                   'samples': len(samples), 'present_samples': sum(x['present'] for x in samples),
                   'gaps': hud_gaps(samples, step=1/args.fps),
                   'elapsed_seconds': round(time.perf_counter()-started, 2),
                   'detector_version': 'white-icons-2', 'ocr_calls': 0}
        (output / 'hud_samples.json').write_text(json.dumps(samples), encoding='utf8')
        (output / 'hud_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
        print(json.dumps(summary, indent=2), flush=True)
        return
    from ocr import OCR
    engine = OCR(args.model)
    diagnostics = (output / 'raw_ocr.jsonl').open('w', encoding='utf8', buffering=1)
    broad_crop = {'relative_to': 'active picture when symmetric black bars detected',
                  'y': [.08, .26], 'x': [.25, .75]}
    original_crop = dict(broad_crop)
    frame_count = ocr_calls = skipped = 0
    gate_samples = []
    hud_samples = []
    hud = BattleHUD() if args.hud_recovery else None
    events, observations = [], []
    active, last_hit = None, -100
    next_progress = args.start
    # Upper centre band covering the prompts in the supplied examples.
    for t, frame in tabs.frames(str(video), args.start, end - args.start, args.fps, width, height):
        frame_count += 1
        if hud is not None:
            hud_samples.append(dict(t=round(t, 3), **hud.read(frame)))
        if t >= next_progress:
            print(f'Scanning {t:.1f}/{end:.1f}s — {len(events)} events', flush=True)
            next_progress = t + 30
        crop = boundary_crop(frame)
        gate_passed = not args.text_gate or prompt_text_gate(crop, height)
        gate_samples.append({'t':round(t,3), 'passed':gate_passed})
        if not gate_passed:
            skipped += 1
            continue
        ocr_calls += 1
        matches = prompt_matches(
            engine, crop, diagnostics,
            {'t': round(t, 3), 'crop': 'standard'}
        )
        if not matches:
            continue
        hit = max(matches, key=lambda match: (match['score'], match.get('wave') is not None))
        hit['t'] = round(t, 3)
        observations.append(dict(hit))
        key = (hit['kind'], hit['wave'], hit['total_waves'])
        if active != key or t - last_hit > 2:
            filename = f"{len(events)+1:03d}_{t:.3f}_{hit['kind']}.jpg"
            hit['evidence'] = filename if cv2.imwrite(str(output / filename), frame) else None
            hit['last_t'] = hit['t']
            events.append(hit)
            print(f"  {t:.2f}s {hit['kind']} {hit['text']}", flush=True)
            active = key
        else:
            events[-1]['last_t'] = hit['t']
        last_hit = t
    events = consolidate_events(events, observations)
    retry_frames = retry_calls = 0
    retries = []
    retry_seen = set()
    hud_intervals = hud_gaps(hud_samples, step=1/args.fps) if hud_samples else []
    if args.hud_recovery:
        (output / 'hud_samples.json').write_text(json.dumps(hud_samples), encoding='utf8')
        print(f'HUD hints: {len(hud_intervals)} sustained disappearance(s)', flush=True)
    if not args.no_repair and abs(args.fps - 2.0) < 1e-9:
        import math
        for left, right in hud_search_ranges(hud_intervals, events, args.start, end):
            print(f'HUD transition recovery {left:.2f}-{right:.2f}s', flush=True)
            first = args.start + .25 + max(0, math.ceil((left-args.start-.25)*2-1e-8))*.5
            info = {'range': [left, right], 'sample_start': first,
                    'fps': 2, 'phase': .25, 'hits': 0, 'source': 'hud_transition'}
            retries.append(info)
            for t, frame in tabs.frames(str(video), first, right-first, 2, width, height):
                if t >= right:
                    break
                stamp = round(t, 3)
                if stamp in retry_seen:
                    continue
                retry_seen.add(stamp)
                retry_frames += 1
                retry_calls += 1
                matches = prompt_matches(engine, boundary_crop(frame), diagnostics,
                                         {'t': round(t, 3), 'crop': 'hud_transition'})
                matches = [match for match in matches if match['kind'] == 'end']
                if not matches:
                    continue
                hit = max(matches, key=lambda match: match['score'])
                hit.update(t=round(t, 3), last_t=round(t, 3), source='hud_transition')
                filename = f"hud_recovery_{t:.3f}_end.jpg"
                hit['evidence'] = filename if cv2.imwrite(str(output / filename), frame) else None
                observations.append(dict(hit))
                events.append(hit)
                info['hits'] += 1
                print(f"  HUD recovery {t:.2f}s end {hit['text']}", flush=True)
        events = consolidate_events(events, observations)
        for left, right in adaptive_ranges(events, args.start, end):
            # Global first-pass grid: start + n*.5. Add only start+.25+n*.5.
            n = max(0, math.ceil((left - args.start - .25) * 2 - 1e-8))
            first = args.start + .25 + n * .5
            if first >= right:
                continue
            print(f'Intermediate-frame recovery {first:.2f}-{right:.2f}s', flush=True)
            retry_info = {'range': [left, right], 'sample_start': first,
                          'fps': 2, 'phase': .25, 'hits': 0}
            retries.append(retry_info)
            for t, frame in tabs.frames(str(video), first, right-first, 2, width, height):
                if t >= right:
                    break
                stamp = round(t, 3)
                if stamp in retry_seen:
                    continue
                retry_seen.add(stamp)
                retry_frames += 1
                retry_calls += 1
                matches = prompt_matches(engine, boundary_crop(frame), diagnostics,
                                         {'t': round(t, 3), 'crop': 'intermediate_recovery'})
                if not matches:
                    continue
                hit = max(matches, key=lambda m: (m['score'], m.get('wave') is not None))
                hit.update(t=round(t, 3), last_t=round(t, 3), source='intermediate_recovery')
                filename = f"recovery_{t:.3f}_{hit['kind']}.jpg"
                hit['evidence'] = filename if cv2.imwrite(str(output / filename), frame) else None
                observations.append(dict(hit))
                events.append(hit)
                retry_info['hits'] += 1
                print(f"  recovery {t:.2f}s {hit['kind']} {hit['text']}", flush=True)
    events = consolidate_events(events, observations)
    segments, warnings = assemble(events)
    result = {'video': str(video), 'model': args.model, 'fps': args.fps,
              'range': [args.start, end], 'events': events, 'segments': segments,
              'warnings': warnings, 'observations': observations,
              'note': 'Provisional prompt boundaries; does not detect showcases or assign submissions.'}
    result['performance'] = {
        'text_gate':args.text_gate, 'frames':frame_count, 'ocr_calls':ocr_calls,
        'skipped_frames':skipped, 'retry_frames':retry_frames,
        'retry_ocr_calls':retry_calls, 'total_ocr_calls':ocr_calls+retry_calls,
        'elapsed_seconds':round(time.perf_counter()-started,2),
        'ocr_reduction_percent':round(100*skipped/max(1,frame_count),2),
        'net_ocr_reduction_percent':round(100*(1-(ocr_calls+retry_calls)/max(1,frame_count)),2),
    }
    result['frame_size'] = {'width': width, 'height': height}
    result['crop'] = {'primary': broad_crop, 'fallback': original_crop}
    result['raw_ocr_file'] = 'raw_ocr.jsonl'
    diagnostics.close()
    result['hud_recovery'] = {'enabled': args.hud_recovery, 'minimum_absence_seconds': 15,
                              'gaps': hud_intervals, 'samples_file': 'hud_samples.json' if hud else None}
    result['end_retries'] = []
    result['adaptive_retries'] = retries
    result['sampling_strategy'] = '2 fps plus unresolved-interval intermediate frames' if args.fps == 2 else 'fixed fps'
    result['scanner_version'] = 'adaptive-3-white-hud-legacy'
    if baseline:
        result['baseline_comparison'] = compare_boundaries(baseline, result)
    (output / 'gate_samples.json').write_text(json.dumps(gate_samples), encoding='utf8')
    print(f"Performance: {result['performance']}", flush=True)
    if baseline:
        print(f"All baseline events retained: {result['baseline_comparison']['all_baseline_events_retained']}", flush=True)
    if args.check_example:
        comparison = []
        for kind, wave, expected in EXPECTED:
            eligible = [e for e in events if e['kind']==kind and (wave is None or e['wave']==wave)]
            nearest = min(eligible, key=lambda e:abs(e['t']-expected)) if eligible else None
            delta = round(nearest['t']-expected,3) if nearest else None
            comparison.append({'kind':kind,'wave':wave,'expected':expected,
                               'detected':nearest['t'] if nearest else None,'delta':delta,
                               'within_5_seconds':delta is not None and abs(delta)<=5})
        result['example_comparison'] = comparison
    path = output / 'boundaries.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(f'Saved {path}', flush=True)


if __name__ == '__main__':
    main()
