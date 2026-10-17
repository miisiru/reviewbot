"""디스코드 웹후크로 보내기. post(키, payload, 첨부) — 키는 config.json 의 discord_webhook · question_webhook."""
import json, os, urllib.request, uuid, mimetypes
import time
import socket
import urllib.error
from paths import config


def text(msg):
    """글만 보내는 payload(링크 미리보기는 끈다)."""
    return {'content': msg[:1990], 'flags': 4}


def _post_once(key, payload, files=()):
    # 환경 변수는 검토 보고용 웹후크만 바꾼다(질문 · 시험 웹후크로 가야 할 글이 보고 채널로 새지 않게)
    url = (os.environ.get('DISCORD_WEBHOOK_URL') if key == 'discord_webhook' else None) or config().get(key)
    if not url:
        raise ValueError('Set DISCORD_WEBHOOK_URL or discord_webhook in config.json')
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
    return urllib.request.urlopen(req, timeout=30).status

def post(key, payload, files=()):
    attempts = 4

    for attempt in range(attempts):
        delay = min(30, 2 ** (attempt + 1))

        try:
            return _post_once(key, payload, files)

        except urllib.error.HTTPError as error:
            body = error.read().decode('utf8', errors='replace')

            retryable = error.code == 429 or 500 <= error.code < 600

            if not retryable or attempt == attempts - 1:
                raise RuntimeError(
                    f'Discord HTTP {error.code}: {body[:1000]}'
                ) from error

            if error.code == 429:
                try:
                    delay = max(
                        1.0,
                        float(json.loads(body)['retry_after']),
                    )
                except (ValueError, TypeError, KeyError):
                    pass

            reason = f'HTTP {error.code}'

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
        ) as error:
            if attempt == attempts - 1:
                raise

            reason = type(error).__name__

        print(
            f'Discord delivery failed ({reason}); '
            f'retrying in {delay:g}s '
            f'({attempt + 2}/{attempts})',
            flush=True,
        )
        time.sleep(delay)
