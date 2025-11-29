from flask import Flask, request, render_template, url_for, Response, redirect
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

from ocr_utils import run_ocr  # Tesseract 기반 OCR 함수


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


# ===================== Tesseract 경로 설정 =====================
# Windows: C:\Program Files\Tesseract-OCR\tesseract.exe
# Linux: /usr/bin/tesseract (기본 PATH에 있음)
import platform

if platform.system() == "Windows":
    TESSERACT_CMD = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
else:
    TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "tesseract")

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


# ===================== 파파고 번역 설정 =====================
# 환경변수로 API 키 설정 (또는 직접 입력)
# 네이버 클라우드 플랫폼에서 발급: https://www.ncloud.com/product/aiService/papagoTranslation

PAPAGO_CLIENT_ID = os.environ.get("PAPAGO_CLIENT_ID", "g9xnxdmfwy")
PAPAGO_CLIENT_SECRET = os.environ.get("PAPAGO_CLIENT_SECRET", "PGqk4FMFGSDpFY1CtC0tDX6mFZewtMaGgxnIZrWX")

# 네이버 클라우드 플랫폼 API (ncloud.com)
# PAPAGO_URL = "https://naveropenapi.apigw.ntruss.com/nmt/v1/translation"

# 네이버 개발자 센터 API (developers.naver.com)
PAPAGO_URL = "https://openapi.naver.com/v1/papago/n2mt"

# 번역 활성화 여부 (True로 설정하면 영어 텍스트를 한국어로 번역)
ENABLE_TRANSLATION = os.environ.get("ENABLE_TRANSLATION", "true").lower() == "true"


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
        "X-Naver-Client-Id": PAPAGO_CLIENT_ID,
        "X-Naver-Client-Secret": PAPAGO_CLIENT_SECRET,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    payload = {
        "source": source,
        "target": target,
        "text": text,
    }

    try:
        resp = requests.post(PAPAGO_URL, headers=headers, data=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()["message"]["result"]["translatedText"]
    except Exception as e:
        print("[Papago Error]", e)
        return ""


# ===================== 영양 분석 Regex =====================

@dataclass
class NutritionInfo:
    # 칼로리
    calories_value: Optional[float] = None
    calories_unit: Optional[str] = None
    # 탄수화물
    carbs_value: Optional[float] = None
    carbs_unit: Optional[str] = None
    # 당류
    sugar_value: Optional[float] = None
    sugar_unit: Optional[str] = None
    # 단백질
    protein_value: Optional[float] = None
    protein_unit: Optional[str] = None
    # 지방
    fat_value: Optional[float] = None
    fat_unit: Optional[str] = None
    # 포화지방
    saturated_fat_value: Optional[float] = None
    saturated_fat_unit: Optional[str] = None
    # 트랜스지방
    trans_fat_value: Optional[float] = None
    trans_fat_unit: Optional[str] = None
    # 콜레스테롤
    cholesterol_value: Optional[float] = None
    cholesterol_unit: Optional[str] = None
    # 나트륨
    sodium_value: Optional[float] = None
    sodium_unit: Optional[str] = None
    # 1회 제공량
    serving_size: Optional[str] = None
    # 알레르기
    allergens: Optional[List[str]] = None


# 알레르기 유발 성분 키워드 - 안전한 키워드 (2글자 이상, 오탐 가능성 낮음)
ALLERGEN_KEYWORDS_SAFE = [
    # 유제품
    "우유", "유제품", "치즈", "버터", "크림", "유당", "유청", "카제인",
    "우유류", "탈지분유", "전지분유", "연유", "요거트", "요구르트",
    # 밀/글루텐
    "글루텐", "소맥", "소맥분", "밀가루", "밀분",
    # 대두
    "대두", "두부", "된장", "간장", "대두유", "콩기름",
    # 견과류
    "땅콩", "호두", "아몬드", "캐슈넛", "피스타치오", "헤이즐넛", 
    "마카다미아", "피칸", "견과", "견과류", "브라질너트",
    # 난류
    "계란", "난류", "달걀", "난백", "난황", "전란", "전란분",
    # 갑각류
    "새우", "랍스터", "가재", "갑각류", "크랩", "쉬림프",
    # 연체류/조개류
    "오징어", "조개", "홍합", "전복", "문어", "연체류", "조개류",
    "바지락", "꼬막", "가리비", "낙지",
    # 생선
    "고등어", "연어", "참치", "생선", "어류", "어패류",
    # 기타
    "참깨", "들깨", "메밀", "아황산류", "아황산", "이산화황",
    "셀러리", "겨자", "토마토", "돼지고기", "쇠고기", "닭고기", "복숭아",
    "사과", "키위", "바나나",
]

# 짧은 키워드 (1글자) - 특정 문맥에서만 검출
ALLERGEN_KEYWORDS_SHORT = ["밀", "콩", "굴", "게", "깨", "잣", "알"]

# 짧은 키워드가 허용되는 접미사 패턴
ALLERGEN_CONTEXT_SUFFIXES = ["함유", "포함", "사용", "첨가", "성분", "원료"]

# 알레르기 OCR 오타 매핑
ALLERGEN_TYPO_MAP = {
    "우유우": "우유",
    "대두두": "대두",
    "계란란": "계란",
    "달걀걀": "달걀",
    "밀밀": "밀",
}


def normalize_ocr_text(text: str) -> str:
    """OCR 텍스트 정규화 - 흔한 오타 수정"""
    replacements = {
        # 열량 오타
        "엷니물론": "열량",
        "열망": "열량",
        "열닝": "열량",
        "엻량": "열량",
        "열량": "열량",
        "영량": "열량",
        # 나트륨 오타 (나트룹, 나트름 등)
        "나트룹": "나트륨",
        "나트름": "나트륨",
        "나트릅": "나트륨",
        "나트류": "나트륨",
        "나뜨륨": "나트륨",
        "나트륨": "나트륨",
        "나트룸": "나트륨",
        "나튜륨": "나트륨",
        # 당류 오타 (당료, 당루 등)
        "당료": "당류",
        "당류류": "당류",
        "당루": "당류",
        "당류": "당류",
        # 탄수화물 오타
        "단수화물": "탄수화물",
        "탄수화믈": "탄수화물",
        "탄수화뭃": "탄수화물",
        "@수회물": "탄수화물",
        "@수화물": "탄수화물",
        # 단백질 오타
        "단백지": "단백질",
        "단백잘": "단백질",
        "백칠": "단백질",
        "백질": "단백질",
        # 지방 오타
        "지밥": "지방",
        "지빵": "지방",
        "재방": "지방",
        "재밤": "지방",
        # 포화지방
        "포화지밥": "포화지방",
        "포화지빵": "포화지방",
        "피회재방": "포화지방",
        "피회재밤": "포화지방",
        "프화지방": "포화지방",
        # 트랜스지방
        "트스지방": "트랜스지방",
        "트렌스지방": "트랜스지방",
        "흐재": "트랜스지방",
        # 콜레스테롤
        "플레스로": "콜레스테롤",
        "콜레스로": "콜레스테롤",
        "콜레스테릴": "콜레스테롤",
        "콜레스테룰": "콜레스테롤",
        "킬세물": "콜레스테롤",
        # 알레르기 관련 오타
        "알레르기": "알레르기",
        "알러지": "알레르기",
        "알러르기": "알레르기",
        "알레지": "알레르기",
        # 알레르기 성분 오타
        "우유우": "우유",
        "대두두": "대두",
        "계란란": "계란",
        "달걀걀": "달걀",
        # 단백질 오타
        "단백지": "단백질",
        "단백잘": "단백질",
        # 탄수화물 오타
        "탄수화뭃": "탄수화물",
        "탄수화믈": "탄수화물",
        # 칼로리 오타
        "칼로리리": "칼로리",
        "kcaI": "kcal",
        "KcaI": "kcal",
        # 지방 오타
        "지밥": "지방",
        "지빵": "지방",
        # 포화지방
        "포화지빵": "포화지방",
        # 콜레스테롤
        "콜레스테릴": "콜레스테롤",
        "콜레스테룰": "콜레스테롤",
        # 단위
        "9": "g",  # 숫자 9가 g로 오인식되는 경우는 문맥에 따라
        "mq": "mg",
        "M9": "mg",
    }
    
    result = text
    for wrong, correct in replacements.items():
        result = result.replace(wrong, correct)
    
    # "숫자 9" 패턴을 "숫자 g"로 변환 (OCR이 g를 9로 인식하는 경우)
    # 예: "18 9" → "18 g", "2 9" → "2 g"
    result = re.sub(r"(\d+(?:\.\d+)?)\s*9\b", r"\1 g", result)
    
    # "숫자9" 패턴도 처리 (공백 없는 경우)
    result = re.sub(r"(\d+(?:\.\d+)?)9\b(?!\d)", r"\1g", result)
    
    return result


def extract_value_unit(text: str, patterns: list) -> tuple:
    """
    여러 패턴으로 값과 단위 추출
    Returns: (value, unit) or (None, None)
    """
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            try:
                value = float(match.group("value"))
                unit = match.group("unit") if "unit" in match.groupdict() else None
                return value, unit
            except (ValueError, IndexError):
                continue
    return None, None


def extract_nutrition_and_allergens(text: str) -> NutritionInfo:
    """
    OCR 텍스트에서 영양 정보 및 알레르기 유발 성분을 추출
    - 확장된 영양 성분 (칼로리, 탄수화물, 단백질, 지방 등)
    - OCR 오타 보정
    - 다양한 표기 패턴 지원
    """
    # 텍스트 정규화
    norm_text = normalize_ocr_text(text)
    norm_text = re.sub(r"\s+", " ", norm_text)
    
    # 숫자 패턴 (정수 또는 소수)
    num = r"(?P<value>\d+(?:[.,]\d+)?)"
    
    # ========== 칼로리/열량 ==========
    calories_patterns = [
        re.compile(rf"(?:열량|에너지|칼로리|Calories?|Energy)\s*[:\-]?\s*{num}\s*(?P<unit>kcal|cal|kca1|킬로칼로리)?", re.IGNORECASE),
        re.compile(rf"{num}\s*(?P<unit>kcal|kca1|Kcal|킬로칼로리)", re.IGNORECASE),
        # 공백 없는 패턴
        re.compile(rf"(?:열량|칼로리){num}(?P<unit>kcal)?", re.IGNORECASE),
    ]
    calories_value, calories_unit = extract_value_unit(norm_text, calories_patterns)
    
    # 공백 없는 텍스트에서도 열량 재검색
    if calories_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        cal_compact_match = re.search(r"열량(\d+(?:\.\d+)?)(kcal)?", text_compact, re.IGNORECASE)
        if cal_compact_match:
            calories_value = float(cal_compact_match.group(1))
            calories_unit = cal_compact_match.group(2) or "kcal"
    
    # ========== 탄수화물 ==========
    carbs_patterns = [
        re.compile(rf"(?:탄수화물|단수화물|탄수화믈|carbohydrate|carb)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
    ]
    carbs_value, carbs_unit = extract_value_unit(norm_text, carbs_patterns)
    
    # 공백 없는 텍스트에서도 탄수화물 재검색
    if carbs_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        carbs_compact_match = re.search(r"[탄단]수화물(\d+(?:\.\d+)?)(g|mg)?", text_compact, re.IGNORECASE)
        if carbs_compact_match:
            carbs_value = float(carbs_compact_match.group(1))
            carbs_unit = carbs_compact_match.group(2) or "g"
    
    # ========== 당류 ==========
    sugar_patterns = [
        # 기본 패턴: "당류 5g", "당료 2 g" (OCR 오타 포함)
        re.compile(rf"(?:당류|당료|당분|sugar|sugars)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
        # "당류 5g" 또는 "당류: 5 g" 형태
        re.compile(rf"(?:당류|당료)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg)?", re.IGNORECASE),
        # 공백 없는 패턴: "당류5g"
        re.compile(rf"(?:당류|당료){num}(?P<unit>g|mg)?", re.IGNORECASE),
    ]
    sugar_value, sugar_unit = extract_value_unit(norm_text, sugar_patterns)
    
    # 공백 없는 텍스트에서도 당류 재검색
    if sugar_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        sugar_compact_match = re.search(r"당[류료](\d+(?:\.\d+)?)(g|mg)?", text_compact, re.IGNORECASE)
        if sugar_compact_match:
            sugar_value = float(sugar_compact_match.group(1))
            sugar_unit = sugar_compact_match.group(2) or "g"
    
    # ========== 단백질 ==========
    protein_patterns = [
        re.compile(rf"(?:단백질|protein)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
    ]
    protein_value, protein_unit = extract_value_unit(norm_text, protein_patterns)
    
    # ========== 지방 ==========
    fat_patterns = [
        re.compile(rf"(?:지방|fat|total\s*fat)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
    ]
    fat_value, fat_unit = extract_value_unit(norm_text, fat_patterns)
    
    # ========== 포화지방 ==========
    sat_fat_patterns = [
        re.compile(rf"(?:포화지방|포화\s*지방|saturated\s*fat)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
    ]
    saturated_fat_value, saturated_fat_unit = extract_value_unit(norm_text, sat_fat_patterns)
    
    # ========== 트랜스지방 ==========
    trans_fat_patterns = [
        re.compile(rf"(?:트랜스지방|트랜스\s*지방|트스지방|트렌스지방|trans\s*fat)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
    ]
    trans_fat_value, trans_fat_unit = extract_value_unit(norm_text, trans_fat_patterns)
    
    # ========== 콜레스테롤 ==========
    cholesterol_patterns = [
        re.compile(rf"(?:콜레스테롤|플레스로|콜레스로|cholesterol)\s*[:\-]?\s*{num}\s*(?P<unit>mg|g|%)?", re.IGNORECASE),
    ]
    cholesterol_value, cholesterol_unit = extract_value_unit(norm_text, cholesterol_patterns)
    
    # ========== 나트륨 ==========
    sodium_patterns = [
        # 기본 패턴: "나트륨 150mg", "나트륨: 150 mg", "나트룹 150 mg"
        re.compile(rf"(?:나트륨|나트름|나트류|나트룹|나트룸|sodium)\s*[:\-]?\s*{num}\s*(?P<unit>mg|g|%)?", re.IGNORECASE),
        # 숫자 먼저 오는 패턴: "150mg 나트륨"
        re.compile(rf"{num}\s*(?P<unit>mg|g)\s*(?:나트륨|나트름|나트룹|sodium)", re.IGNORECASE),
        # 공백 없는 패턴: "나트륨150mg"
        re.compile(rf"(?:나트륨|나트름|나트룹){num}(?P<unit>mg|g)?", re.IGNORECASE),
        # Na 패턴
        re.compile(rf"Na\s*[:\-]?\s*{num}\s*(?P<unit>mg|g)?", re.IGNORECASE),
    ]
    sodium_value, sodium_unit = extract_value_unit(norm_text, sodium_patterns)
    
    # 공백 없는 텍스트에서도 나트륨 재검색
    if sodium_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        sodium_compact_match = re.search(r"나트[륨름류룹룸](\d+(?:\.\d+)?)(mg|g)?", text_compact, re.IGNORECASE)
        if sodium_compact_match:
            sodium_value = float(sodium_compact_match.group(1))
            sodium_unit = sodium_compact_match.group(2) or "mg"
    
    # ========== 1회 제공량 ==========
    serving_match = re.search(
        r"(?:1회\s*제공량|1회\s*섭취량|serving\s*size|총\s*내용량)[:\s]*([0-9]+(?:\.[0-9]+)?\s*(?:g|ml|mL|그램|밀리리터)?)",
        norm_text, re.IGNORECASE
    )
    serving_size = serving_match.group(1).strip() if serving_match else None
    
    # ========== 알레르기 유발 성분 ==========
    found_allergens = set()
    
    # 원본 텍스트에서도 검색 (공백 제거 버전)
    text_no_space = re.sub(r"\s+", "", text)
    
    # 디버깅: 알레르기 검색 대상 텍스트 출력
    print(f"[알레르기 검색] 공백제거 텍스트 일부: {text_no_space[:300]}...")
    
    # 1. 안전한 키워드(2글자 이상) - 전체 텍스트에서 검색
    for kw in ALLERGEN_KEYWORDS_SAFE:
        if kw in norm_text or kw in text_no_space:
            print(f"[알레르기 발견] '{kw}' 감지!")
            found_allergens.add(kw)
    
    # 2. 알레르기 관련 섹션 패턴들
    allergen_section_patterns = [
        r"(?:알[레러]르기|알[레러]지|allerg)[^:]*[:\s]*([^\n.。]{5,100})",
        r"(?:함유|포함|contains?)[:\s]*([^\n.。]+)",
        r"(?:이\s*제품은?|본\s*제품은?)[^에]*(?:사용|제조|생산)[^\n.。]*",
        r"(?:원재료|원료)[:\s]*([^\n]{10,200})",
        r"[(\(]([^)\)]*(?:우유|대두|밀|계란|땅콩|견과)[^)\)]*)[)\)]",
    ]
    
    for pattern in allergen_section_patterns:
        matches = re.findall(pattern, norm_text, re.IGNORECASE)
        for match in matches:
            section_text = match if isinstance(match, str) else " ".join(match)
            # 안전한 키워드 검색
            for kw in ALLERGEN_KEYWORDS_SAFE:
                if kw in section_text:
                    found_allergens.add(kw)
            # 짧은 키워드는 알레르기 섹션 내에서만 검출
            for kw in ALLERGEN_KEYWORDS_SHORT:
                if kw in section_text:
                    found_allergens.add(kw)
    
    # 3. "OO 함유/포함" 패턴 (예: "우유 함유", "밀 포함") - 짧은 키워드도 허용
    for suffix in ALLERGEN_CONTEXT_SUFFIXES:
        contains_pattern = re.findall(rf"(\w{{1,5}})\s*{suffix}", norm_text)
        for item in contains_pattern:
            if item in ALLERGEN_KEYWORDS_SAFE or item in ALLERGEN_KEYWORDS_SHORT:
                found_allergens.add(item)
    
    # 4. 괄호 안 알레르기 표시 (예: "(우유, 대두, 밀 포함)")
    paren_matches = re.findall(r"[(\(]([^)\)]+)[)\)]", norm_text)
    for paren_content in paren_matches:
        # 괄호 안에 알레르기 관련 키워드가 있으면 짧은 키워드도 검출
        has_allergen_context = any(kw in paren_content for kw in ["함유", "포함", "알레르기", "알러지"])
        for kw in ALLERGEN_KEYWORDS_SAFE:
            if kw in paren_content:
                found_allergens.add(kw)
        if has_allergen_context:
            for kw in ALLERGEN_KEYWORDS_SHORT:
                if kw in paren_content:
                    found_allergens.add(kw)
    
    found_allergens = sorted(found_allergens) if found_allergens else None
    
    # ========== 백업 추출: 줄 단위 분석 ==========
    # 패턴 매칭이 실패한 경우, 줄 단위로 키워드와 숫자를 찾음
    lines = text.split('\n')
    
    def find_number_near_keyword(lines: list, keywords: list) -> tuple:
        """키워드가 있는 줄 또는 인접 줄에서 숫자 찾기"""
        for i, line in enumerate(lines):
            line_lower = line.lower()
            for kw in keywords:
                if kw in line_lower or kw in line:
                    # 같은 줄에서 숫자 찾기
                    nums = re.findall(r'(\d+(?:[.,]\d+)?)\s*(mg|g|kcal|%)?', line)
                    if nums:
                        try:
                            val = float(nums[0][0].replace(',', '.'))
                            unit = nums[0][1] if nums[0][1] else None
                            return val, unit
                        except:
                            pass
                    # 다음 줄에서 숫자 찾기
                    if i + 1 < len(lines):
                        nums = re.findall(r'(\d+(?:[.,]\d+)?)\s*(mg|g|kcal|%)?', lines[i+1])
                        if nums:
                            try:
                                val = float(nums[0][0].replace(',', '.'))
                                unit = nums[0][1] if nums[0][1] else None
                                return val, unit
                            except:
                                pass
        return None, None
    
    # 백업: 나트륨
    if sodium_value is None:
        sodium_value, sodium_unit = find_number_near_keyword(
            lines, ['나트륨', '나트룹', '나트름', 'sodium', 'na']
        )
        if sodium_unit is None and sodium_value:
            sodium_unit = 'mg'
    
    # 백업: 당류
    if sugar_value is None:
        sugar_value, sugar_unit = find_number_near_keyword(
            lines, ['당류', '당료', 'sugar']
        )
        if sugar_unit is None and sugar_value:
            sugar_unit = 'g'
    
    # 백업: 탄수화물
    if carbs_value is None:
        carbs_value, carbs_unit = find_number_near_keyword(
            lines, ['탄수화물', '단수화물', 'carb']
        )
        if carbs_unit is None and carbs_value:
            carbs_unit = 'g'
    
    # 백업: 단백질
    if protein_value is None:
        protein_value, protein_unit = find_number_near_keyword(
            lines, ['단백질', 'protein']
        )
        if protein_unit is None and protein_value:
            protein_unit = 'g'
    
    # 백업: 지방
    if fat_value is None:
        fat_value, fat_unit = find_number_near_keyword(
            lines, ['지방', 'fat']
        )
        if fat_unit is None and fat_value:
            fat_unit = 'g'
    
    # 백업: 열량
    if calories_value is None:
        calories_value, calories_unit = find_number_near_keyword(
            lines, ['열량', '칼로리', 'calorie', 'kcal', 'energy']
        )
        if calories_unit is None and calories_value:
            calories_unit = 'kcal'
    
    # ========== 최종 백업: 숫자+단위 패턴으로 직접 찾기 ==========
    full_text = " ".join(lines)
    
    # 열량: 숫자 + kcal 패턴
    if calories_value is None:
        kcal_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kcal|kca1|Kcal|킬로칼로리)', full_text, re.IGNORECASE)
        if kcal_match:
            calories_value = float(kcal_match.group(1))
            calories_unit = 'kcal'
    
    # 나트륨: 숫자(100이상) + mg 패턴 (나트륨은 보통 100mg 이상)
    if sodium_value is None:
        # "숫자 mg" 패턴 중 나트륨일 가능성이 높은 것 찾기
        mg_matches = re.findall(r'(\d+(?:\.\d+)?)\s*mg', full_text, re.IGNORECASE)
        for match in mg_matches:
            val = float(match)
            # 50-2000mg 범위는 나트륨일 가능성 높음
            if 50 <= val <= 2000 and sodium_value is None:
                sodium_value = val
                sodium_unit = 'mg'
                break
    
    # 탄수화물: 숫자 + g 패턴 중 10-100 범위
    if carbs_value is None:
        g_matches = re.findall(r'(\d+(?:\.\d+)?)\s*g\b', full_text, re.IGNORECASE)
        for match in g_matches:
            val = float(match)
            # 10-100g 범위는 탄수화물일 가능성
            if 10 <= val <= 100 and carbs_value is None:
                carbs_value = val
                carbs_unit = 'g'
                break
    
    return NutritionInfo(
        calories_value=calories_value,
        calories_unit=calories_unit or "kcal" if calories_value else None,
        carbs_value=carbs_value,
        carbs_unit=carbs_unit or "g" if carbs_value else None,
        sugar_value=sugar_value,
        sugar_unit=sugar_unit or "g" if sugar_value else None,
        protein_value=protein_value,
        protein_unit=protein_unit or "g" if protein_value else None,
        fat_value=fat_value,
        fat_unit=fat_unit or "g" if fat_value else None,
        saturated_fat_value=saturated_fat_value,
        saturated_fat_unit=saturated_fat_unit or "g" if saturated_fat_value else None,
        trans_fat_value=trans_fat_value,
        trans_fat_unit=trans_fat_unit or "g" if trans_fat_value else None,
        cholesterol_value=cholesterol_value,
        cholesterol_unit=cholesterol_unit or "mg" if cholesterol_value else None,
        sodium_value=sodium_value,
        sodium_unit=sodium_unit or "mg" if sodium_value else None,
        serving_size=serving_size,
        allergens=found_allergens or None,
    )


def extract_nutrition_and_allergens_english(text: str) -> NutritionInfo:
    """
    영어 영양정보 라벨에서 추출
    """
    norm_text = re.sub(r"\s+", " ", text.lower())
    
    # 영어 패턴 정의
    def extract_en(patterns):
        for pattern in patterns:
            match = re.search(pattern, norm_text, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(",", "."))
                    unit = match.group(2) if len(match.groups()) > 1 else None
                    return value, unit
                except (ValueError, IndexError):
                    continue
        return None, None
    
    # Calories
    cal_value, cal_unit = extract_en([
        r"calories?\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(kcal|cal)?",
        r"energy\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(kcal|kj)?",
    ])
    
    # Carbohydrates
    carbs_value, carbs_unit = extract_en([
        r"(?:total\s+)?carbohydrate[s]?\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(g|mg)?",
        r"carbs?\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(g|mg)?",
    ])
    
    # Sugar
    sugar_value, sugar_unit = extract_en([
        r"(?:total\s+)?sugar[s]?\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(g|mg)?",
    ])
    
    # Protein
    protein_value, protein_unit = extract_en([
        r"protein[s]?\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(g|mg)?",
    ])
    
    # Fat
    fat_value, fat_unit = extract_en([
        r"(?:total\s+)?fat\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(g|mg)?",
    ])
    
    # Saturated Fat
    sat_fat_value, sat_fat_unit = extract_en([
        r"saturated\s*fat\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(g|mg)?",
    ])
    
    # Trans Fat
    trans_fat_value, trans_fat_unit = extract_en([
        r"trans\s*fat\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(g|mg)?",
    ])
    
    # Cholesterol
    chol_value, chol_unit = extract_en([
        r"cholesterol\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(mg|g)?",
    ])
    
    # Sodium
    sodium_value, sodium_unit = extract_en([
        r"sodium\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(mg|g)?",
    ])
    
    # 영어 알레르기 성분
    en_allergens = [
        "milk", "egg", "peanut", "tree nut", "soy", "wheat", "fish", "shellfish",
        "sesame", "gluten", "lactose", "almond", "walnut", "cashew", "hazelnut",
        "pecan", "pistachio", "macadamia", "shrimp", "crab", "lobster", "clam",
        "oyster", "squid", "octopus", "mussel", "scallop"
    ]
    
    found = []
    allergen_section = re.search(r"(?:contains|allergen|allergy)[:\s]+(.+?)(?:\.|$)", norm_text, re.IGNORECASE)
    search_text = allergen_section.group(1) if allergen_section else norm_text
    
    for allergen in en_allergens:
        if re.search(rf"\b{allergen}\b", search_text, re.IGNORECASE):
            found.append(allergen)
    
    return NutritionInfo(
        calories_value=cal_value,
        calories_unit=cal_unit or "kcal" if cal_value else None,
        carbs_value=carbs_value,
        carbs_unit=carbs_unit or "g" if carbs_value else None,
        sugar_value=sugar_value,
        sugar_unit=sugar_unit or "g" if sugar_value else None,
        protein_value=protein_value,
        protein_unit=protein_unit or "g" if protein_value else None,
        fat_value=fat_value,
        fat_unit=fat_unit or "g" if fat_value else None,
        saturated_fat_value=sat_fat_value,
        saturated_fat_unit=sat_fat_unit or "g" if sat_fat_value else None,
        trans_fat_value=trans_fat_value,
        trans_fat_unit=trans_fat_unit or "g" if trans_fat_value else None,
        cholesterol_value=chol_value,
        cholesterol_unit=chol_unit or "mg" if chol_value else None,
        sodium_value=sodium_value,
        sodium_unit=sodium_unit or "mg" if sodium_value else None,
        serving_size=None,
        allergens=found or None,
    )


def merge_nutrition(primary: NutritionInfo, secondary: NutritionInfo) -> NutritionInfo:
    """
    두 영양정보를 병합 (primary 우선, None인 경우 secondary로 보완)
    """
    return NutritionInfo(
        calories_value=primary.calories_value or secondary.calories_value,
        calories_unit=primary.calories_unit or secondary.calories_unit,
        carbs_value=primary.carbs_value or secondary.carbs_value,
        carbs_unit=primary.carbs_unit or secondary.carbs_unit,
        sugar_value=primary.sugar_value or secondary.sugar_value,
        sugar_unit=primary.sugar_unit or secondary.sugar_unit,
        protein_value=primary.protein_value or secondary.protein_value,
        protein_unit=primary.protein_unit or secondary.protein_unit,
        fat_value=primary.fat_value or secondary.fat_value,
        fat_unit=primary.fat_unit or secondary.fat_unit,
        saturated_fat_value=primary.saturated_fat_value or secondary.saturated_fat_value,
        saturated_fat_unit=primary.saturated_fat_unit or secondary.saturated_fat_unit,
        trans_fat_value=primary.trans_fat_value or secondary.trans_fat_value,
        trans_fat_unit=primary.trans_fat_unit or secondary.trans_fat_unit,
        cholesterol_value=primary.cholesterol_value or secondary.cholesterol_value,
        cholesterol_unit=primary.cholesterol_unit or secondary.cholesterol_unit,
        sodium_value=primary.sodium_value or secondary.sodium_value,
        sodium_unit=primary.sodium_unit or secondary.sodium_unit,
        serving_size=primary.serving_size or secondary.serving_size,
        allergens=primary.allergens or secondary.allergens,
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


@app.route("/upload", methods=["POST"])
@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        # API 요청인지 확인 (Accept 헤더 또는 경로로 판단)
        if request.path == "/api/upload" or request.headers.get("Accept") == "application/json":
            return Response(json.dumps({"error": "No file provided"}, ensure_ascii=False),
                            content_type="application/json; charset=utf-8")
        return redirect(url_for("index"))

    file = request.files["file"]
    label = request.form.get("label", "").strip() or None  # 제품명 (선택)
    
    item_id = str(uuid.uuid4())
    filename = f"{item_id}.jpg"
    save_path = UPLOAD_DIR / filename
    file.save(save_path)

    # OCR
    text = run_ocr(str(save_path), lang="kor+eng")
    
    # 디버그: OCR 결과 출력
    print(f"[OCR 원본 - 전체]\n{text}\n{'='*50}")

    # 영어 텍스트인 경우 한국어로 번역
    translated = ""
    analysis_text = text  # 분석에 사용할 텍스트
    
    if ENABLE_TRANSLATION and PAPAGO_CLIENT_ID and PAPAGO_CLIENT_SECRET:
        # 영어가 주로 포함된 경우 번역
        korean_chars = len(re.findall(r'[가-힣]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        
        if english_chars > korean_chars:
            print("[번역] 영어 텍스트 감지 → 한국어로 번역 중...")
            translated = translate_text_papago(text)
            if translated:
                print(f"[번역 결과]\n{translated[:500]}...")
                analysis_text = translated  # 번역된 텍스트로 분석
    
    # 분석 (번역된 텍스트 또는 원본 사용)
    nutrition = extract_nutrition_and_allergens(analysis_text)
    
    # 영어 원본에서도 추가 분석 (번역이 부정확할 경우 대비)
    if translated:
        nutrition_original = extract_nutrition_and_allergens_english(text)
        # 번역 분석에서 못 찾은 값은 영어 분석으로 보완
        nutrition = merge_nutrition(nutrition, nutrition_original)
    
    # 디버그: 영양 정보 출력 (상세)
    print(f"[영양 분석]")
    print(f"  열량: {nutrition.calories_value} {nutrition.calories_unit or ''}")
    print(f"  탄수화물: {nutrition.carbs_value} {nutrition.carbs_unit or ''}")
    print(f"  당류: {nutrition.sugar_value} {nutrition.sugar_unit or ''}")
    print(f"  단백질: {nutrition.protein_value} {nutrition.protein_unit or ''}")
    print(f"  지방: {nutrition.fat_value} {nutrition.fat_unit or ''}")
    print(f"  나트륨: {nutrition.sodium_value} {nutrition.sodium_unit or ''}")
    print(f"  알레르기: {nutrition.allergens}")

    result = {
        "id": item_id,
        "label": label,
        "filename": filename,
        "text": text,
        "analysis": nutrition_to_dict(nutrition),
        "translated_text": translated,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "detail_url": url_for("detail", item_id=item_id, _external=True)
    }

    ocr_results.append(result)

    # 웹 폼에서 업로드한 경우 리다이렉트, API 요청이면 JSON 반환
    if request.path == "/api/upload" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return Response(
            json.dumps(result, ensure_ascii=False),
            content_type="application/json; charset=utf-8"
        )
    
    # 라즈베리파이 등 외부에서 API로 요청한 경우 JSON 반환
    if request.headers.get("Accept") == "application/json" or "python-requests" in request.headers.get("User-Agent", "").lower():
        return Response(
            json.dumps(result, ensure_ascii=False),
            content_type="application/json; charset=utf-8"
        )
    
    # 웹 폼에서 업로드한 경우 메인 페이지로 리다이렉트
    return redirect(url_for("index"))


# ===================== 실행 =====================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
