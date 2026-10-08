"""디스코드 웹후크로 알림. python notify.py "메시지" [첨부 이미지 ...]"""
import sys, json, os, urllib.request, uuid, mimetypes
cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json"), encoding="utf8"))
url = cfg["discord_webhook"]
msg = sys.argv[1]; files = sys.argv[2:]
if not files:
    req = urllib.request.Request(url, data=json.dumps({"content": msg[:1990], "flags": 4}).encode(), headers={"Content-Type": "application/json", "User-Agent": "herta-review"})
else:
    b = uuid.uuid4().hex; body = b""
    body += f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n".encode() + json.dumps({"content": msg[:1990], "flags": 4}).encode() + b"\r\n"
    for i, f in enumerate(files):
        ct = mimetypes.guess_type(f)[0] or "application/octet-stream"
        body += f"--{b}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; filename=\"{os.path.basename(f)}\"\r\nContent-Type: {ct}\r\n\r\n".encode() + open(f, "rb").read() + b"\r\n"
    body += f"--{b}--\r\n".encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}", "User-Agent": "herta-review"})
print(urllib.request.urlopen(req).status)
