"""디스코드 웹후크로 보내기. post(키, payload, 첨부) — 키는 config.json 의 discord_webhook · question_webhook."""
import json, os, urllib.request, uuid, mimetypes
from paths import CONFIG


def text(msg):
    """글만 보내는 payload(링크 미리보기는 끈다)."""
    return {'content': msg[:1990], 'flags': 4}


def post(key, payload, files=()):
    url = json.load(open(CONFIG, encoding='utf8'))[key]
    if files:
        b = uuid.uuid4().hex
        body = (f'--{b}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'.encode()
                + json.dumps(payload).encode() + b'\r\n')
        for i, f in enumerate(files):
            ct = mimetypes.guess_type(f)[0] or 'application/octet-stream'
            body += (f'--{b}\r\nContent-Disposition: form-data; name="files[{i}]"; filename="{os.path.basename(f)}"\r\n'
                     f'Content-Type: {ct}\r\n\r\n'.encode() + open(f, 'rb').read() + b'\r\n')
        body += f'--{b}--\r\n'.encode()
        ctype = f'multipart/form-data; boundary={b}'
    else:
        body, ctype = json.dumps(payload).encode(), 'application/json'
    req = urllib.request.Request(url, data=body, headers={'Content-Type': ctype, 'User-Agent': 'herta-review'})
    return urllib.request.urlopen(req).status
