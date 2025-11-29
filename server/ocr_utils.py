from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

TESSERACT_LANG = "kor+eng"
# PSM 모드: 3=자동, 6=단일블록, 11=희소텍스트, 12=희소+OSD
TESSERACT_CONFIG = "--oem 3 --psm 6 -c preserve_interword_spaces=1"
TESSERACT_CONFIG_SPARSE = "--oem 3 --psm 11 -c preserve_interword_spaces=1"
TESSERACT_CONFIG_AUTO = "--oem 3 --psm 3 -c preserve_interword_spaces=1"


def resize_image(img: np.ndarray, target_width: int = 1800) -> np.ndarray:
    """이미지 리사이즈 - OCR 성능 향상"""
    h, w = img.shape[:2]
    if w < target_width:
        scale = target_width / w
        new_w = target_width
        new_h = int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    return img


def preprocess_image(image_path: str) -> np.ndarray:
    """
    식품 라벨 OCR을 위한 이미지 전처리
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")
    
    # 리사이즈
    img = resize_image(img)
    
    # 그레이스케일 변환
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 노이즈 제거
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    
    # CLAHE - 대비 향상
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    
    # 샤프닝
    kernel = np.array([[-1, -1, -1],
                       [-1,  9, -1],
                       [-1, -1, -1]])
    sharpened = cv2.filter2D(enhanced, -1, kernel)
    
    return sharpened


def preprocess_for_table(image_path: str) -> np.ndarray:
    """
    표 형식 영양성분표를 위한 특수 전처리
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")
    
    # 리사이즈
    img = resize_image(img, target_width=1500)
    
    # 그레이스케일
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 강한 대비 향상
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Otsu 이진화 (표 텍스트에 효과적)
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 모폴로지 연산으로 텍스트 강화
    kernel = np.ones((1, 1), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    
    return binary


def preprocess_invert(image_path: str) -> np.ndarray:
    """
    반전 이미지 전처리 (어두운 배경의 텍스트용)
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")
    
    img = resize_image(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 반전
    inverted = cv2.bitwise_not(gray)
    
    # 대비 향상
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(inverted)
    
    return enhanced


def _tesseract_text(img: np.ndarray, lang: str, config: str = TESSERACT_CONFIG) -> str:
    """
    Tesseract 이미지 문자열 추출 헬퍼
    """
    return pytesseract.image_to_string(img, lang=lang, config=config)


def run_ocr(image_path: str, lang: str = TESSERACT_LANG) -> str:
    """
    강화된 OCR 실행
    - 여러 전처리 방식으로 OCR 수행
    - 결과 병합
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")

    original = cv2.imread(str(image_path))
    if original is None:
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")

    all_texts = []
    variants = []

    variants.append(("원본", original))

    try:
        variants.append(("전처리", preprocess_image(str(image_path))))
    except Exception as e:
        print(f"[OCR 전처리 오류] {e}")

    try:
        variants.append(("표 전처리", preprocess_for_table(str(image_path))))
    except Exception as e:
        print(f"[OCR 표 전처리 오류] {e}")

    try:
        variants.append(("반전", preprocess_invert(str(image_path))))
    except Exception as e:
        print(f"[OCR 반전 오류] {e}")

    try:
        resized = resize_image(original.copy())
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        variants.append(("적응형 이진화", binary))
    except Exception as e:
        print(f"[OCR 이진화 오류] {e}")

    # 추가: 더 크게 확대한 버전 (작은 글씨용)
    try:
        large_resized = resize_image(original.copy(), target_width=2500)
        gray_large = cv2.cvtColor(large_resized, cv2.COLOR_BGR2GRAY)
        # 강한 대비
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced_large = clahe.apply(gray_large)
        variants.append(("대형 확대", enhanced_large))
    except Exception as e:
        print(f"[OCR 대형 확대 오류] {e}")

    # 여러 PSM 모드로 OCR 시도
    configs = [
        ("기본", TESSERACT_CONFIG),
        ("자동", TESSERACT_CONFIG_AUTO),
        ("희소", TESSERACT_CONFIG_SPARSE),
    ]
    
    for variant_name, img in variants:
        if img is None:
            continue
        for config_name, config in configs:
            try:
                text = _tesseract_text(img, lang, config)
                if text:
                    all_texts.extend(text.splitlines())
            except pytesseract.TesseractError as e:
                print(f"[Tesseract 오류 - {variant_name}/{config_name}] {e}")

    # 중복 제거 및 정리
    seen = set()
    unique_texts = []
    for text in all_texts:
        cleaned = text.strip()
        # 너무 짧거나 특수문자만 있는 건 제외
        if cleaned and len(cleaned) >= 1 and cleaned not in seen:
            seen.add(cleaned)
            unique_texts.append(cleaned)
    
    return "\n".join(unique_texts)


def run_ocr_with_confidence(image_path: str, lang: str = TESSERACT_LANG) -> list:
    """
    신뢰도 정보와 함께 OCR 결과 반환
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")

    preprocessed = preprocess_image(str(image_path))

    try:
        data = pytesseract.image_to_data(
            preprocessed,
            lang=lang,
            config=TESSERACT_CONFIG,
            output_type=Output.DICT,
        )
    except pytesseract.TesseractError as e:
        raise RuntimeError(f"Tesseract 실행 실패: {e}") from e

    results = []
    n_items = len(data["text"])
    for i in range(n_items):
        text = data["text"][i].strip()
        conf = data["conf"][i]
        if not text or conf == "-1":
            continue

        x, y, w, h = (
            data["left"][i],
            data["top"][i],
            data["width"][i],
            data["height"][i],
        )
        bbox = [
            [x, y],
            [x + w, y],
            [x + w, y + h],
            [x, y + h],
        ]
        results.append(
            {
                "text": text,
                "confidence": round(float(conf), 1),
                "bbox": bbox,
            }
        )

    return results
