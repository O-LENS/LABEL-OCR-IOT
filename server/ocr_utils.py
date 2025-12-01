from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

# 한글만 인식 (영어 오인식 방지)
TESSERACT_LANG = "kor"
# PSM 모드: 3=자동, 4=단일열, 6=단일블록, 11=희소텍스트
# preserve_interword_spaces=0 으로 변경 (글자 분리 방지)
TESSERACT_CONFIG = "--oem 3 --psm 6"
TESSERACT_CONFIG_SPARSE = "--oem 3 --psm 11"
TESSERACT_CONFIG_AUTO = "--oem 3 --psm 3"
TESSERACT_CONFIG_SINGLE_COL = "--oem 3 --psm 4"  # 단일 열 (표 형식에 좋음)


def resize_image(img: np.ndarray, target_width: int = 1800) -> np.ndarray:
    """이미지 리사이즈 - OCR 성능 향상"""
    h, w = img.shape[:2]
    if w < target_width:
        scale = target_width / w
        new_w = target_width
        new_h = int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    return img


def adjust_brightness_contrast(img: np.ndarray, brightness: int = 30, contrast: int = 30) -> np.ndarray:
    """밝기와 대비 조정"""
    # 밝기: -127 ~ 127, 대비: -127 ~ 127
    brightness = int((brightness - 0) * (255 - (-255)) / (127 - (-127)) + (-255))
    contrast = int((contrast - 0) * (127 - (-127)) / (127 - (-127)) + (-127))
    
    if brightness != 0:
        if brightness > 0:
            shadow = brightness
            highlight = 255
        else:
            shadow = 0
            highlight = 255 + brightness
        alpha = (highlight - shadow) / 255
        gamma = shadow
        img = cv2.addWeighted(img, alpha, img, 0, gamma)
    
    if contrast != 0:
        alpha = float(131 * (contrast + 127)) / (127 * (131 - contrast))
        gamma = 127 * (1 - alpha)
        img = cv2.addWeighted(img, alpha, img, 0, gamma)
    
    return img


def gamma_correction(img: np.ndarray, gamma: float = 1.2) -> np.ndarray:
    """감마 보정 - 어두운 이미지 밝게"""
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
    return cv2.LUT(img, table)


def preprocess_image(image_path: str) -> np.ndarray:
    """
    식품 라벨 OCR을 위한 이미지 전처리 (강화됨)
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")
    
    # 리사이즈
    img = resize_image(img)
    
    # 밝기/대비 자동 조정
    img = adjust_brightness_contrast(img, brightness=20, contrast=25)
    
    # 그레이스케일 변환
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 감마 보정 (어두운 이미지 밝게)
    gray = gamma_correction(gray, gamma=1.3)
    
    # 노이즈 제거 (bilateral filter - 엣지 보존)
    denoised = cv2.bilateralFilter(gray, 9, 75, 75)
    
    # CLAHE - 대비 향상 (더 강하게)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    
    # 샤프닝 (더 강하게)
    kernel = np.array([[-1, -1, -1],
                       [-1, 10, -1],
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
    
    # 추가: 매우 크게 확대 (3000px) - 작은 한글 텍스트용
    try:
        xlarge = resize_image(original.copy(), target_width=3000)
        gray_xl = cv2.cvtColor(xlarge, cv2.COLOR_BGR2GRAY)
        # 언샤프 마스킹으로 글씨 선명하게
        gaussian = cv2.GaussianBlur(gray_xl, (0, 0), 3)
        unsharp = cv2.addWeighted(gray_xl, 1.5, gaussian, -0.5, 0)
        # CLAHE
        clahe_xl = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced_xl = clahe_xl.apply(unsharp)
        variants.append(("초대형 확대", enhanced_xl))
    except Exception as e:
        print(f"[OCR 초대형 확대 오류] {e}")
    
    # 추가: 이진화 + 모폴로지 (깨진 글씨 복원)
    try:
        resized_morph = resize_image(original.copy(), target_width=2000)
        gray_morph = cv2.cvtColor(resized_morph, cv2.COLOR_BGR2GRAY)
        # Otsu 이진화
        _, binary_morph = cv2.threshold(gray_morph, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # 닫힘 연산으로 끊어진 글씨 연결
        kernel_close = np.ones((2, 2), np.uint8)
        closed = cv2.morphologyEx(binary_morph, cv2.MORPH_CLOSE, kernel_close)
        variants.append(("모폴로지", closed))
    except Exception as e:
        print(f"[OCR 모폴로지 오류] {e}")
    
    # 추가: 히스토그램 평활화 (밝기 균일화)
    try:
        resized_eq = resize_image(original.copy(), target_width=2000)
        gray_eq = cv2.cvtColor(resized_eq, cv2.COLOR_BGR2GRAY)
        equalized = cv2.equalizeHist(gray_eq)
        variants.append(("히스토그램 평활화", equalized))
    except Exception as e:
        print(f"[OCR 히스토그램 평활화 오류] {e}")
    
    # 추가: 밝기/대비 강화 버전
    try:
        bright = resize_image(original.copy(), target_width=2000)
        bright = adjust_brightness_contrast(bright, brightness=40, contrast=40)
        gray_bright = cv2.cvtColor(bright, cv2.COLOR_BGR2GRAY)
        gray_bright = gamma_correction(gray_bright, gamma=1.5)
        clahe_bright = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced_bright = clahe_bright.apply(gray_bright)
        variants.append(("밝기강화", enhanced_bright))
    except Exception as e:
        print(f"[OCR 밝기강화 오류] {e}")
    
    # 추가: 어두운 배경용 (영양성분표가 어두운 경우)
    try:
        dark_bg = resize_image(original.copy(), target_width=2000)
        dark_bg = adjust_brightness_contrast(dark_bg, brightness=50, contrast=50)
        gray_dark = cv2.cvtColor(dark_bg, cv2.COLOR_BGR2GRAY)
        # 감마 더 높게
        gray_dark = gamma_correction(gray_dark, gamma=2.0)
        _, binary_dark = cv2.threshold(gray_dark, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(("어두운배경용", binary_dark))
    except Exception as e:
        print(f"[OCR 어두운배경용 오류] {e}")

    # 여러 PSM 모드로 OCR 시도 (글자 분리 최소화)
    configs = [
        ("기본", TESSERACT_CONFIG),
        ("단일열", TESSERACT_CONFIG_SINGLE_COL),
        ("자동", TESSERACT_CONFIG_AUTO),
        ("희소", TESSERACT_CONFIG_SPARSE),
        ("표전용", "--oem 3 --psm 6 -c tessedit_char_blacklist=|[]{}~"),  # 특수문자 제외
        ("세그먼트7", "--oem 3 --psm 7"),  # 단일 텍스트 라인
        ("세그먼트13", "--oem 3 --psm 13"),  # Raw line
    ]
    
    # 한글 전용 설정 (추가 시도)
    kor_configs = [
        ("한글기본", "--oem 3 --psm 6"),
        ("한글열", "--oem 3 --psm 4"),
    ]
    
    for variant_name, img in variants:
        if img is None:
            continue
        # 표준 설정으로 OCR
        for config_name, config in configs:
            try:
                text = _tesseract_text(img, lang, config)
                if text:
                    all_texts.extend(text.splitlines())
            except pytesseract.TesseractError as e:
                print(f"[Tesseract 오류 - {variant_name}/{config_name}] {e}")
        
        # 한글 전용 OCR (더 정확한 한글 인식)
        for config_name, config in kor_configs:
            try:
                text = _tesseract_text(img, "kor", config)  # 한글만
                if text:
                    all_texts.extend(text.splitlines())
            except pytesseract.TesseractError as e:
                print(f"[Tesseract 오류 - {variant_name}/{config_name}/kor] {e}")

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
