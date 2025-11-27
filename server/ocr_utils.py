from pathlib import Path
import easyocr

# 한 번만 로드
reader = easyocr.Reader(['ko', 'en'], gpu=False)

def run_ocr(image_path: str, lang: str = "kor+eng") -> str:
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"이미지를 찾을 수 없음: {image_path}")

    result = reader.readtext(str(image_path), detail=0)  # 텍스트만

    lines = [line.strip() for line in result if line.strip()]
    return "\n".join(lines)
