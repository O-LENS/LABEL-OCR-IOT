from pathlib import Path
import easyocr
import cv2
import numpy as np

# EasyOCR Reader - 한 번만 로드
reader = easyocr.Reader(['ko', 'en'], gpu=False)


def resize_image(img: np.ndarray, target_width: int = 1200) -> np.ndarray:
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


def run_ocr(image_path: str, lang: str = "kor+eng") -> str:
    """
    강화된 OCR 실행
    - 여러 전처리 방식으로 OCR 수행
    - 결과 병합
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")

    all_texts = []
    
    # 1. 원본 이미지 OCR
    try:
        result = reader.readtext(
            str(image_path),
            detail=0,
            paragraph=False,
            min_size=5,
            text_threshold=0.5,
            low_text=0.3,
            contrast_ths=0.1,
            adjust_contrast=0.5,
            width_ths=0.7,
        )
        all_texts.extend(result)
    except Exception as e:
        print(f"[OCR 원본 오류] {e}")

    # 2. 기본 전처리 OCR
    try:
        preprocessed = preprocess_image(str(image_path))
        result = reader.readtext(
            preprocessed,
            detail=0,
            paragraph=False,
            min_size=5,
            text_threshold=0.4,
            low_text=0.3,
        )
        all_texts.extend(result)
    except Exception as e:
        print(f"[OCR 전처리 오류] {e}")

    # 3. 표 형식 전처리 OCR
    try:
        table_preprocessed = preprocess_for_table(str(image_path))
        result = reader.readtext(
            table_preprocessed,
            detail=0,
            paragraph=False,
            min_size=5,
            text_threshold=0.4,
        )
        all_texts.extend(result)
    except Exception as e:
        print(f"[OCR 표 전처리 오류] {e}")

    # 4. 반전 이미지 OCR
    try:
        inverted = preprocess_invert(str(image_path))
        result = reader.readtext(
            inverted,
            detail=0,
            paragraph=False,
            min_size=5,
            text_threshold=0.5,
        )
        all_texts.extend(result)
    except Exception as e:
        print(f"[OCR 반전 오류] {e}")

    # 5. 적응형 이진화 OCR
    try:
        img = cv2.imread(str(image_path))
        img = resize_image(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        result = reader.readtext(
            binary,
            detail=0,
            paragraph=False,
            min_size=5,
        )
        all_texts.extend(result)
    except Exception as e:
        print(f"[OCR 이진화 오류] {e}")

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


def run_ocr_with_confidence(image_path: str) -> list:
    """
    신뢰도 정보와 함께 OCR 결과 반환
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")

    preprocessed = preprocess_image(str(image_path))
    
    results = reader.readtext(
        preprocessed,
        detail=1,
        paragraph=False,
        min_size=5,
        text_threshold=0.4,
    )
    
    return [
        {
            "text": text,
            "confidence": round(conf * 100, 1),
            "bbox": bbox
        }
        for bbox, text, conf in results
    ]
