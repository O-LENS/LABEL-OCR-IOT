from flask import Flask, request, render_template, url_for, Response
from pathlib import Path
from datetime import datetime
import uuid
import os
import re
import json
import requests
import pytesseract
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any, Tuple

from ocr_utils import run_ocr  # EasyOCR 사용 함수


# ===================== Flask / 경로 설정 =====================

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

# 🔹 JSON에서 Unicode escape 없이 한글 그대로 출력
app.config['JSON_AS_ASCII'] = False


# ===================== (선택) Tesseract 경로 설정 =====================
# - EasyOCR이 주 OCR이지만 필요할 수 있어 남김
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ===================== 번역 (지금은 동작 안 되어도 유지) =====================

PAPAGO_CLIENT_ID = ""  # 필요하면 넣기
PAPAGO_CLIENT_SECRET = ""
PAPAGO_URL = "https://naveropenapi.apigw.ntruss.com/nmt/v1/translation"


def guess_lang_pair(text: str) -> Tuple[str, str]:
    if re.search(r"[가-힣]", text):
        return "ko", "en"
    return "en", "ko"


def translate_text_papago(text: str) -> str:
    text = text.strip()
    if not text:
        return ""

    if not PAPAGO_CLIENT_ID or not PAPAGO_CLIENT_SECRET:
        return ""  # 번역 OFF

    source, target = guess_lang_pair(text)

    headers = {
        "X-NCP-APIGW-API-KEY-ID": PAPAGO_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": PAPAGO_CLIENT_SECRET,
        "Content-Type": "application/json; charset=utf-8",
    }

    payload = {
        "source": source,
        "target": target,
        "text": text,
    }

    try:
        resp = requests.post(PAPAGO_URL, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()["message"]["result"]["translatedText"]
    except Exception as e:
        print("[Papago Error]", e)
        return ""


# ===================== 영양 분석 Regex =====================

@dataclass
class NutritionInfo:
    sugar_value: Optional[float] = None
    sugar_unit: Optional[str] = None
    sodium_value: Optional[float] = None
    sodium_unit: Optional[str] = None
    allergens: Optional[List[str]] = None


ALLERGEN_KEYWORDS = [
    "우유", "치즈", "버터",
    "밀", "글루텐",
    "대두", "콩",
    "땅콩", "호두", "아몬드",
    "계란", "난류",
    "새우", "게",
    "오징어", "조개",
    "깨"
]


def extract_nutrition_and_allergens(text: str) -> NutritionInfo:
    """
    OCR 텍스트에서 '당류', '나트륨', 알레르기 유발 성분을 추출
    - '30 g당 160 kcal' 같은 문장의 '당'은 무시
    - '나트륨' OCR 오타인 '나트름'도 함께 인식
    """
    # 공백 정리
    norm_text = re.sub(r"\s+", " ", text)

    # 🔹 당류: '당류' 만 잡고, 'g당'의 '당'은 안 잡게 함
    sugar_pattern = re.compile(
        r"(당류)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg|그램|%)?",
        re.IGNORECASE,
    )
    sugar_match = sugar_pattern.search(norm_text)

    sugar_value = float(sugar_match.group(2)) if sugar_match else None
    sugar_unit = sugar_match.group(3) if (sugar_match and sugar_match.group(3)) else None

    # 🔹 나트륨: 나트륨/나트름/Na/소금/염분 등
    sodium_pattern = re.compile(
        r"(나트[륨름]|소금|염분|Na)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(mg|g|그램|%)?",
        re.IGNORECASE,
    )
    sodium_match = sodium_pattern.search(norm_text)

    sodium_value = float(sodium_match.group(2)) if sodium_match else None
    sodium_unit = sodium_match.group(3) if (sodium_match and sodium_match.group(3)) else None

    # 🔹 알레르기 키워드 검색
    found_allergens = sorted({kw for kw in ALLERGEN_KEYWORDS if kw in norm_text})

    return NutritionInfo(
        sugar_value=sugar_value,
        sugar_unit=sugar_unit,
        sodium_value=sodium_value,
        sodium_unit=sodium_unit,
        allergens=found_allergens or None,
    )



def nutrition_to_dict(info: NutritionInfo) -> Dict[str, Any]:
    return asdict(info)


# ===================== 저장소 =====================

ocr_results: List[Dict[str, Any]] = []


# ===================== Routes =====================

@app.route("/")
def index():
    return render_template("index.html", results=ocr_results)


@app.route("/detail/<item_id>")
def detail(item_id):
    item = next((x for x in ocr_results if x["id"] == item_id), None)
    if not item:
        return "Not Found", 404
    return render_template("detail.html", item=item)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return Response(json.dumps({"error": "No file provided"}, ensure_ascii=False),
                        content_type="application/json; charset=utf-8")

    file = request.files["file"]
    item_id = str(uuid.uuid4())
    filename = f"{item_id}.jpg"
    save_path = UPLOAD_DIR / filename
    file.save(save_path)

    # OCR
    text = run_ocr(str(save_path), lang="kor+eng")

    # 분석
    nutrition = extract_nutrition_and_allergens(text)

    # 번역 (OFF이어도 안전)
    translated = translate_text_papago(text)

    result = {
        "id": item_id,
        "filename": filename,
        "text": text,
        "analysis": nutrition_to_dict(nutrition),
        "translated_text": translated,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "detail_url": url_for("detail", item_id=item_id, _external=True)
    }

    ocr_results.append(result)

    # 🔹 JSON을 한글 그대로 반환
    return Response(
        json.dumps(result, ensure_ascii=False),
        content_type="application/json; charset=utf-8"
    )


# ===================== 실행 =====================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
