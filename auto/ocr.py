"""언어별 OCR. 검출은 RapidOCR 기본(ch PP-OCRv3 det), 인식은 언어별 PP-OCRv5 모델(models/<lang>).
lang: chinese(간체 · 번체 · 일본어 · 영어) / korean / latin(영 · 불 · 독 · 서 · 포 · 베트남) / eslav(러시아) / thai / english
사용: from ocr import OCR; o = OCR('korean'); o(img_bgr) -> [(x, y, w, h, text, score)]"""
import os
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize import TextRecognizer

HERE = os.path.dirname(os.path.abspath(__file__))
_cache = {}

# RapidOCR 1.2.3 은 CUDA 만 안다 → 세션을 만들 때 DirectML(그래픽카드)을 먼저 쓰게 바꾼다
import onnxruntime as _ort
import rapidocr_onnxruntime.utils as _ru
_OrigSession = _ru.InferenceSession
HAS_GPU = 'DmlExecutionProvider' in _ort.get_available_providers()
USE_GPU = os.environ.get('OCR_GPU') == '1' and HAS_GPU


def set_gpu(on):
    """이 뒤에 만드는 OCR 엔진이 그래픽카드를 쓸지. 큰 그림(빌드 화면)은 GPU 가 두 배 빠르고,
    작은 칸을 수없이 읽는 HUD · 보유 효과는 크기가 매번 달라 GPU 가 오히려 느리다."""
    global USE_GPU
    USE_GPU = bool(on) and HAS_GPU


def _Session(path, sess_options=None, providers=None):
    # 일꾼 여러 개가 각자 모든 코어를 쓰면 서로 밀어낸다 → 일꾼당 스레드 수를 제한
    n = int(os.environ.get('OCR_THREADS', '0'))
    if n:
        sess_options.intra_op_num_threads = n
        sess_options.inter_op_num_threads = 1
    if USE_GPU:
        sess_options.enable_mem_pattern = False
        providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
    return _OrigSession(path, sess_options=sess_options, providers=providers)


_ru.InferenceSession = _Session


class OCR:
    def __init__(self, lang='chinese'):
        self.lang = lang
        key = (lang, USE_GPU)
        if key in _cache:
            self.engine = _cache[key]
            return
        # 기본 limit_type=min 은 작은 자르기를 736px 이상으로 키워 느리다 → max 로
        eng = RapidOCR(det_model_path=None, det_limit_type='max', det_limit_side_len=960, use_angle_cls=False)
        d = os.path.join(HERE, 'models', lang)
        cfg = {'use_cuda': False, 'model_path': os.path.join(d, 'rec.onnx'),
               'keys_path': os.path.join(d, 'dict.txt'), 'rec_img_shape': [3, 48, 320], 'rec_batch_num': 6}
        eng.text_recognizer = TextRecognizer(cfg)
        _cache[key] = self.engine = eng

    def __call__(self, img, scale=1.0):
        """img: BGR ndarray. scale: 작은 글씨는 키워서 읽는다."""
        if scale != 1.0:
            import cv2
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        res, _ = self.engine(img)
        out = []
        for box, text, score in res or []:
            b = np.array(box) / scale
            x, y = b[:, 0].min(), b[:, 1].min()
            out.append((int(x), int(y), int(b[:, 0].max() - x), int(b[:, 1].max() - y), text, float(score)))
        return out


LANG_GROUP = {'KR': 'korean', 'EN': 'chinese', 'CHS': 'chinese', 'CHT': 'chinese', 'JP': 'chinese',
              'FR': 'latin', 'DE': 'latin', 'ES': 'latin', 'PT': 'latin', 'VI': 'latin', 'ID': 'latin',
              'RU': 'eslav', 'TH': 'thai'}
