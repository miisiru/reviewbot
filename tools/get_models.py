"""OCR 인식 모델(PaddleOCR PP-OCRv5 의 ONNX 변환, Apache-2.0)을 받는다 → auto/models/<언어>/
출처: https://huggingface.co/monkt/paddleocr-onnx (languages/<언어>/rec.onnx · dict.txt · config.json)
python get_models.py [언어 ...]   (기본: chinese korean latin eslav thai english)"""
import os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, '..', 'auto', 'models')
BASE = 'https://huggingface.co/monkt/paddleocr-onnx/resolve/main/languages'
langs = sys.argv[1:] or ['chinese', 'korean', 'latin', 'eslav', 'thai', 'english']
for lang in langs:
    os.makedirs(os.path.join(DEST, lang), exist_ok=True)
    for fn in ('config.json', 'dict.txt', 'rec.onnx'):
        out = os.path.join(DEST, lang, fn)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            continue
        print('get', lang, fn)
        urllib.request.urlretrieve(f'{BASE}/{lang}/{fn}', out)
print('ok ->', os.path.abspath(DEST))
