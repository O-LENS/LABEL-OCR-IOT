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

PAPAGO_CLIENT_ID = os.environ.get("PAPAGO_CLIENT_ID", "5v23u9jclu")
PAPAGO_CLIENT_SECRET = os.environ.get("PAPAGO_CLIENT_SECRET", "c5tsieOQ3vF8rfHt9qFUo0BknJEZZbxYZW8s3IvJ")

# 네이버 클라우드 플랫폼 API (ncloud.com)
PAPAGO_URL = "https://naveropenapi.apigw.ntruss.com/nmt/v1/translation"

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
        "X-NCP-APIGW-API-KEY-ID": PAPAGO_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": PAPAGO_CLIENT_SECRET,
        "Content-Type": "application/json",
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
    # 유제품 (체다 제외 - OCR 오탐 발생)
    "우유", "유제품", "치즈", "버터", "크림", "유당", "유청", "카제인",
    "우유류", "탈지분유", "전지분유", "연유", "요거트", "요구르트",
    "분유", "유크림", "크림치즈", "모짜렐라", "체다치즈",
    # 밀/글루텐
    "글루텐", "소맥", "소맥분", "밀가루", "밀분", "밀전분", "소맥전분",
    "통밀", "강력분", "박력분", "중력분", "듀럼밀",
    # 대두
    "대두", "두부", "된장", "간장", "대두유", "콩기름", "대두분", 
    "두유", "청국장", "콩나물", "검정콩", "서리태", "흑태",
    # 견과류
    "땅콩", "호두", "아몬드", "캐슈넛", "피스타치오", "헤이즐넛", 
    "마카다미아", "피칸", "견과", "견과류", "브라질너트", "잣",
    "해바라기씨", "호박씨", "해바라기", "캐슈", "피넛",
    # 난류
    "계란", "난류", "달걀", "난백", "난황", "전란", "전란분",
    "계란노른자", "계란흰자", "메추리알", "오리알",
    # 갑각류
    "새우", "랍스터", "가재", "갑각류", "크랩", "쉬림프", "대게", "킹크랩",
    "꽃게", "홍게", "게살", "새우젓", "젓갈",
    # 연체류/조개류
    "오징어", "조개", "홍합", "전복", "문어", "연체류", "조개류",
    "바지락", "꼬막", "가리비", "낙지", "쭈꾸미", "해삼", "성게",
    "굴소스", "굴젓", "굴비", "멍게", "개조개", "모시조개",
    # 생선/어류
    "고등어", "연어", "참치", "생선", "어류", "어패류", "멸치", "정어리",
    "꽁치", "삼치", "갈치", "조기", "광어", "우럭", "도미", "붕어",
    "잉어", "뱅어포", "명태", "황태", "북어", "대구", "가자미",
    "피시", "생선살",
    # 기타 알레르겐
    "참깨", "들깨", "메밀", "아황산류", "아황산", "이산화황",
    "셀러리", "겨자", "토마토", "돼지고기", "쇠고기", "닭고기", "복숭아",
    "사과", "키위", "바나나", "망고", "파인애플", "딸기", "살구", "자두",
    "아보카도", "루핀", "연근", "율무",
    # 한국 식품에 자주 등장
    "김치", "액젓", "까나리액젓", "멸치액젓", "새우액젓",
    "피쉬소스", "굴비", "미역", "다시마", "김",
]

# 짧은 키워드 (1글자) - 매우 엄격한 문맥에서만 검출 (오탐 방지)
# "게"는 오탐이 너무 많아 제외 (게살, 꽃게, 대게는 SAFE에 있음)
ALLERGEN_KEYWORDS_SHORT = ["밀", "콩", "굴", "깨", "잣", "란"]

# 짧은 키워드가 허용되는 접미사/접두사 패턴
ALLERGEN_CONTEXT_SUFFIXES = ["함유", "포함", "사용", "첨가", "성분", "원료", "들어"]
ALLERGEN_CONTEXT_PREFIXES = ["함", "유", "포", "알레르기", "알러지", "주의"]

# 알레르기 OCR 오타 매핑 (더 확장)
ALLERGEN_TYPO_MAP = {
    # 중복 글자 오타
    "우유우": "우유",
    "대두두": "대두",
    "계란란": "계란",
    "달걀걀": "달걀",
    "밀밀": "밀",
    "새우우": "새우",
    "오징어어": "오징어",
    # OCR 인식 오류 - 오징어 (다양한 변형)
    "오정어": "오징어",
    "오징아": "오징어",
    "오칭어": "오징어",
    "오진어": "오징어",
    "오짱어": "오징어",
    "오쯩어": "오징어",
    "오징이": "오징어",
    "오징여": "오징어",
    "오징오": "오징어",
    "오짖어": "오징어",
    "요징어": "오징어",
    "왜징어": "오징어",
    "오짇어": "오징어",
    "오징": "오징어",  # 끝글자 누락
    "우윳": "우유",
    "게란": "계란",
    "겨란": "계란",
    "계런": "계란",
    "대뚜": "대두",
    "태두": "대두",
    "데두": "대두",
    "새우새": "새우",
    "세우": "새우",
    "쌔우": "새우",
    "랍스타": "랍스터",
    "호뚜": "호두",
    "아몬뜨": "아몬드",
    "피스타치요": "피스타치오",
    "멜치": "멸치",
    "고등아": "고등어",
    "참캐": "참깨",
    "들캐": "들깨",
    "메밀밀": "메밀",
    "밀까루": "밀가루",
    "밀까르": "밀가루",
    "굴소쓰": "굴소스",
    "간쟝": "간장",
    "된쟝": "된장",
    "돼지고끼": "돼지고기",
    "쇠고끼": "쇠고기",
    "닭고끼": "닭고기",
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
        # 당류 오타 (당료, 당루, 담류 등)
        "당료": "당류",
        "당류류": "당류",
        "당루": "당류",
        "당류": "당류",
        "담류": "당류",
        "담 류": "당류",
        "담류류": "당류",
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
        # "당 192kcal" 패턴 (1봉지당, 1회 제공량당 등)
        re.compile(rf"당\s*{num}\s*(?P<unit>kcal|kca1|Kcal)", re.IGNORECASE),
        # "192 kcal" 단독 (kcal 앞 숫자)
        re.compile(rf"(?<![0-9]){num}\s*(?P<unit>kcal|kca1|Kcal|킬로칼로리)", re.IGNORECASE),
    ]
    calories_value, calories_unit = extract_value_unit(norm_text, calories_patterns)
    
    # 공백 없는 텍스트에서도 열량 재검색
    if calories_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        cal_compact_match = re.search(r"열량(\d+(?:\.\d+)?)(kcal)?", text_compact, re.IGNORECASE)
        if cal_compact_match:
            calories_value = float(cal_compact_match.group(1))
            calories_unit = cal_compact_match.group(2) or "kcal"
    
    # 추가: "XXXkcal" 패턴 직접 검색 (열량 키워드 없이)
    if calories_value is None:
        kcal_direct = re.search(r"(\d{2,4})\s*(?:kcal|kca1|Kcal)", norm_text, re.IGNORECASE)
        if kcal_direct:
            val = float(kcal_direct.group(1))
            if 50 <= val <= 1500:  # 합리적인 열량 범위
                calories_value = val
                calories_unit = "kcal"
    
    # 추가: 공백 포함 "1 9 2 kcal" 패턴
    if calories_value is None:
        spaced_kcal = re.search(r"(\d)\s*(\d)\s*(\d)\s*(?:kcal|kca1)", norm_text, re.IGNORECASE)
        if spaced_kcal:
            val = float(spaced_kcal.group(1) + spaced_kcal.group(2) + spaced_kcal.group(3))
            if 50 <= val <= 999:
                calories_value = val
                calories_unit = "kcal"
    
    # 추가: "1g2 kcal" 패턴 (g가 9로 오인식된 경우)
    if calories_value is None or calories_value < 30:
        kcal_g_pattern = re.search(r"(\d)[gㅇOo](\d)\s*(?:kcal|kca1|Kcal)", norm_text, re.IGNORECASE)
        if kcal_g_pattern:
            val = float(kcal_g_pattern.group(1) + "9" + kcal_g_pattern.group(2))
            if 50 <= val <= 999:
                calories_value = val
                calories_unit = "kcal"
                print(f"[열량 추출] g→9 변환: {val}kcal")
    
    # 추가: 라인별로 "192kcal" 또는 "192 kcal" 찾기
    if calories_value is None or calories_value < 30:
        for line in text.split('\n'):
            kcal_line = re.search(r"(\d{2,3})\s*(?:kcal|kca1|Kcal|키)", line, re.IGNORECASE)
            if kcal_line:
                val = float(kcal_line.group(1))
                if 50 <= val <= 999:
                    calories_value = val
                    calories_unit = "kcal"
                    print(f"[열량 추출] 라인별: {val}kcal")
                    break
    
    # 추가: "당 192" 패턴 (kcal 없이) - 1봉지당 뒤의 숫자
    if calories_value is None or calories_value < 30:
        dang_pattern = re.search(r"[봉회]\s*지?\s*당\s*(\d{2,3})", norm_text, re.IGNORECASE)
        if dang_pattern:
            val = float(dang_pattern.group(1))
            if 50 <= val <= 999:
                calories_value = val
                calories_unit = "kcal"
                print(f"[열량 추출] 당 패턴: {val}kcal")
    
    # 열량 값 보정: 너무 작은 값(30 미만)이면 텍스트에서 다시 검색
    if calories_value is not None and calories_value < 30:
        # 전체 텍스트에서 합리적인 kcal 값 찾기
        all_kcal = re.findall(r"(\d{2,3})\s*(?:kcal|kca1|Kcal|키)", text, re.IGNORECASE)
        for match in all_kcal:
            val = float(match)
            if 50 <= val <= 999:
                print(f"[열량 보정] {calories_value} → {val}kcal")
                calories_value = val
                calories_unit = "kcal"
                break
    
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
    
    # 탄수화물 값 보정: 100 초과시 마지막 숫자(6,8,9)를 g로 간주하고 제거
    if carbs_value is not None and carbs_value > 100:
        carbs_str = str(int(carbs_value))
        if len(carbs_str) >= 2 and carbs_str[-1] in '6896':
            corrected = float(carbs_str[:-1])
            if 0 <= corrected <= 100:
                print(f"[탄수화물 보정] {carbs_value} → {corrected}g")
                carbs_value = corrected
                carbs_unit = "g"
    
    # 추가: 탄수화물 라인별 검색 (28g 9% 패턴)
    if carbs_value is None or carbs_value > 60:
        for line in text.split('\n'):
            # "탄수화물 28g" 또는 "탄 수 화 물 28 g" 패턴
            carbs_line = re.search(r"[탄단]\s*수\s*화\s*물\s*(\d{1,2})\s*(?:g|8|9)", line, re.IGNORECASE)
            if carbs_line:
                val = float(carbs_line.group(1))
                if 5 <= val <= 60:
                    print(f"[탄수화물 추출] 라인별: {val}g")
                    carbs_value = val
                    carbs_unit = "g"
                    break
        
        # 압축 텍스트에서 "탄수화물28g" 패턴
        if carbs_value is None or carbs_value > 60:
            text_compact = re.sub(r"\s+", "", text)
            carbs_compact = re.search(r"[탄단]수화물(\d{1,2})[g89]", text_compact, re.IGNORECASE)
            if carbs_compact:
                val = float(carbs_compact.group(1))
                if 5 <= val <= 60:
                    print(f"[탄수화물 추출] 압축: {val}g")
                    carbs_value = val
                    carbs_unit = "g"
    
    # 탄수화물 값 보정: "20 8" → "28" (28g가 20 8로 분리된 경우)
    if carbs_value is not None and 15 <= carbs_value <= 25:
        # "탄수화물 20 8" 패턴 확인 (20 뒤에 8이 있으면 28로 합침)
        carbs_208_match = re.search(r"[탄단]\s*수\s*화\s*물\s*(\d{1,2})\s*8", text, re.IGNORECASE)
        if carbs_208_match:
            first_num = int(carbs_208_match.group(1))
            if first_num == int(carbs_value) and first_num < 30:
                corrected = first_num * 10 + 8  # 20 → 208 → 실제로는 28
                # 실제로는 "2" + "8" = 28이어야 함
                if str(first_num).endswith('0'):
                    corrected = int(str(first_num)[:-1] + '8')  # 20 → 28
                    if 20 <= corrected <= 50:
                        print(f"[탄수화물 보정] {carbs_value} → {corrected}g (20 8 → 28)")
                        carbs_value = float(corrected)
                        carbs_unit = "g"
    
    # ========== 당류 ==========
    sugar_patterns = [
        # 기본 패턴: "당류 5g", "당료 2 g" (OCR 오타 포함)
        re.compile(rf"(?:당류|당료|담류|당분|sugar|sugars)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
        # "당류 5g" 또는 "당류: 5 g" 형태
        re.compile(rf"(?:당류|당료|담류)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg)?", re.IGNORECASE),
        # 공백 없는 패턴: "당류5g"
        re.compile(rf"(?:당류|당료|담류){num}(?P<unit>g|mg)?", re.IGNORECASE),
    ]
    sugar_value, sugar_unit = extract_value_unit(norm_text, sugar_patterns)
    
    # 공백 없는 텍스트에서도 당류 재검색
    if sugar_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        sugar_compact_match = re.search(r"[당담][류료](\d+(?:\.\d+)?)(g|mg)?", text_compact, re.IGNORECASE)
        if sugar_compact_match:
            sugar_value = float(sugar_compact_match.group(1))
            sugar_unit = sugar_compact_match.group(2) or "g"
    
    # 추가: "당류 13g 13%" 패턴 (g 앞의 숫자만 추출, % 무시)
    if sugar_value is None:
        sugar_with_percent = re.search(r"[당담][류료]\s*(\d+(?:\.\d+)?)\s*g\s*\d+\s*%", norm_text, re.IGNORECASE)
        if sugar_with_percent:
            sugar_value = float(sugar_with_percent.group(1))
            sugar_unit = "g"
    
    # 추가: 공백 있는 "당 류 13 g" 패턴
    if sugar_value is None:
        sugar_spaced = re.search(r"[당담]\s*류\s*(\d+(?:\.\d+)?)\s*(?:g|그램)", norm_text, re.IGNORECASE)
        if sugar_spaced:
            sugar_value = float(sugar_spaced.group(1))
            sugar_unit = "g"
    
    # 추가: "당류 13 13%" 패턴 (g 없이 숫자만 있는 경우, 첫번째 숫자가 당류값)
    if sugar_value is None:
        sugar_num_only = re.search(r"[당담]\s*류[^0-9]*(\d{1,2})(?:\s+|\s*[^0-9])(\d{1,3})\s*%?", norm_text, re.IGNORECASE)
        if sugar_num_only:
            val = float(sugar_num_only.group(1))
            if 0 <= val <= 50:  # 당류 합리적 범위
                sugar_value = val
                sugar_unit = "g"
                print(f"[당류 추출] 숫자만 패턴: {val}g")
    
    # 추가: "138" 패턴 (13g가 138로 인식된 경우, g→8)
    if sugar_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        # 당류 뒤에 오는 2-3자리 숫자에서 마지막 8을 g로 해석
        sugar_g8_match = re.search(r"[당담][류료][^0-9]*(\d{1,2})8", text_compact, re.IGNORECASE)
        if sugar_g8_match:
            val = float(sugar_g8_match.group(1))
            if 0 <= val <= 50:
                sugar_value = val
                sugar_unit = "g"
                print(f"[당류 추출] 8→g 변환: {val}g")
    
    # 당류 값 보정: 100 초과시 마지막 숫자(8,6,9)를 g로 간주하고 제거
    if sugar_value is not None and sugar_value > 50:
        sugar_str = str(int(sugar_value))
        if len(sugar_str) >= 2 and sugar_str[-1] in '8689':
            corrected = float(sugar_str[:-1])
            if 0 <= corrected <= 50:
                print(f"[당류 보정] {sugar_value} → {corrected}g (마지막 숫자 제거)")
                sugar_value = corrected
                sugar_unit = "g"
    
    # ========== 단백질 ==========
    protein_patterns = [
        re.compile(rf"(?:단백질|protein)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
    ]
    protein_value, protein_unit = extract_value_unit(norm_text, protein_patterns)
    
    # 공백 제거 후 단백질 재검색
    if protein_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        # "단백질2g4%" 패턴 - 퍼센트 앞의 숫자가 아닌 g 앞의 숫자
        protein_match = re.search(r"단백질(\d+(?:\.\d+)?)\s*g", text_compact, re.IGNORECASE)
        if protein_match:
            protein_value = float(protein_match.group(1))
            protein_unit = "g"
    
    # ========== 지방 ==========
    fat_patterns = [
        re.compile(rf"(?:지방|시방|fat|total\s*fat)\s*[:\-]?\s*{num}\s*(?P<unit>g|mg|그램|%)?", re.IGNORECASE),
    ]
    fat_value, fat_unit = extract_value_unit(norm_text, fat_patterns)
    
    # 공백 제거 후 지방 재검색 (포화지방, 트랜스지방 제외)
    if fat_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        # "지방9g17%", "시방88" - 포화지방/트랜스지방 제외
        fat_match = re.search(r"(?<!포화)(?<!트랜스)(?<!스)[지시]방(\d+(?:\.\d+)?)\s*g?", text_compact, re.IGNORECASE)
        if fat_match:
            fat_value = float(fat_match.group(1))
            fat_unit = "g"
    
    # 지방 값 보정: 지방 8g가 88로 인식된 경우
    if fat_value is not None and fat_value > 50:
        fat_str = str(int(fat_value))
        if len(fat_str) >= 2 and fat_str[-1] in '8689':
            corrected = float(fat_str[:-1])
            if 0 <= corrected <= 50:
                print(f"[지방 보정] {fat_value} → {corrected}g")
                fat_value = corrected
                fat_unit = "g"
    
    # 추가: 라인별로 "지방 8g" 패턴 찾기
    if fat_value is None or fat_value < 5:
        for line in text.split('\n'):
            # "지방 8g 15%" 패턴 - 포화지방/트랜스지방 제외
            if '포화' not in line and '트랜스' not in line:
                fat_line = re.search(r"[지시]방\s*(\d+(?:\.\d+)?)\s*(?:g|8)\s*\d*\s*%?", line, re.IGNORECASE)
                if fat_line:
                    val = float(fat_line.group(1))
                    if 3 <= val <= 50:
                        print(f"[지방 추출] 라인별: {val}g")
                        fat_value = val
                        fat_unit = "g"
                        break
    
    # 추가: "시방 88" 패턴 (지방 8g가 시방 88로 인식)
    if fat_value is None or fat_value < 5:
        fat_88 = re.search(r"[지시]방\s*(\d)8\s*1[59]", norm_text, re.IGNORECASE)  # "시방 88 15%" 패턴
        if fat_88:
            val = float(fat_88.group(1))
            if 3 <= val <= 20:
                print(f"[지방 추출] 88패턴: {val}g")
                fat_value = val
                fat_unit = "g"
    
    # 추가: 압축 텍스트에서 지방 찾기
    if fat_value is None or fat_value < 5:
        text_compact = re.sub(r"\s+", "", text)
        # "지방8g15%" 또는 "시방8815%"
        fat_compact = re.search(r"(?<!포화)(?<!트랜스)[지시]방(\d)[g8]?1[59]", text_compact, re.IGNORECASE)
        if fat_compact:
            val = float(fat_compact.group(1))
            if 3 <= val <= 20:
                print(f"[지방 추출] 압축: {val}g")
                fat_value = val
                fat_unit = "g"
    
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
    
    # 추가: "나트륨 160mg 8%" 패턴 (mg 앞의 숫자만 추출, % 무시)
    if sodium_value is None:
        sodium_with_percent = re.search(r"나트[륨름류룹룸]\s*(\d+(?:\.\d+)?)\s*mg\s*\d+\s*%", norm_text, re.IGNORECASE)
        if sodium_with_percent:
            sodium_value = float(sodium_with_percent.group(1))
            sodium_unit = "mg"
    
    # 추가: 공백 있는 "나 트 륨 160 mg" 패턴
    if sodium_value is None:
        sodium_spaced = re.search(r"나\s*트\s*[륨름류]\s*(\d+(?:\.\d+)?)\s*(?:mg|밀리그램)", norm_text, re.IGNORECASE)
        if sodium_spaced:
            sodium_value = float(sodium_spaced.group(1))
            sodium_unit = "mg"
    
    # 추가: "트륨 160mg" 패턴 (나 가 잘려서 인식된 경우)
    if sodium_value is None:
        sodium_partial = re.search(r"트[륨름류]\s*(\d+(?:\.\d+)?)\s*(?:mg|밀리그램)", norm_text, re.IGNORECASE)
        if sodium_partial:
            val = float(sodium_partial.group(1))
            if 10 <= val <= 5000:  # 나트륨 합리적 범위
                sodium_value = val
                sodium_unit = "mg"
    
    # 추가: "XXXmg" 패턴 (나트륨 키워드 없이, mg 앞의 3자리 숫자)
    if sodium_value is None:
        # 100~999mg 범위의 숫자 + mg 패턴
        sodium_mg_only = re.search(r"(\d{2,3})\s*mg\s*\d*\s*%?", norm_text, re.IGNORECASE)
        if sodium_mg_only:
            val = float(sodium_mg_only.group(1))
            if 50 <= val <= 999:  # 나트륨 합리적 범위
                sodium_value = val
                sodium_unit = "mg"
                print(f"[나트륨 추출] mg만 패턴: {val}mg")
    
    # 추가: "16008" 패턴 (160mg 8%가 16008로 합쳐진 경우)
    if sodium_value is None:
        text_compact = re.sub(r"\s+", "", norm_text)
        # 나트륨 근처의 큰 숫자에서 앞 3자리 추출
        sodium_big_match = re.search(r"[나트][트륨름류룹]?[^0-9]*(\d{3})(\d{1,2})\d*", text_compact, re.IGNORECASE)
        if sodium_big_match:
            val = float(sodium_big_match.group(1))
            if 100 <= val <= 500:  # 일반 식품 나트륨 범위
                sodium_value = val
                sodium_unit = "mg"
                print(f"[나트륨 추출] 큰숫자 분리: {val}mg")
    
    # 추가: 라인별로 "160mg" 찾기
    if sodium_value is None:
        for line in text.split('\n'):
            mg_match = re.search(r"(\d{2,3})\s*mg", line, re.IGNORECASE)
            if mg_match:
                val = float(mg_match.group(1))
                if 50 <= val <= 999:
                    sodium_value = val
                    sodium_unit = "mg"
                    print(f"[나트륨 추출] 라인별 mg: {val}mg")
                    break
    
    # 나트륨 값 보정: 5000 초과시 앞 3자리만 추출 (140mg7% → 14007 → 140)
    if sodium_value is not None and sodium_value > 1000:
        sodium_str = str(int(sodium_value))
        if len(sodium_str) >= 4:
            # 앞 3자리 추출 (14007 → 140)
            corrected = float(sodium_str[:3])
            if 50 <= corrected <= 999:
                print(f"[나트륨 보정] {sodium_value} → {corrected}mg (앞 3자리)")
                sodium_value = corrected
                sodium_unit = "mg"
    
    # 추가: "140mg7%" 패턴 직접 검색 (mg 뒤에 %가 붙어있는 경우)
    if sodium_value is None:
        sodium_mg_percent = re.search(r"(\d{2,3})mg\d{1,2}%", text.replace(" ", ""), re.IGNORECASE)
        if sodium_mg_percent:
            val = float(sodium_mg_percent.group(1))
            if 50 <= val <= 999:
                print(f"[나트륨 추출] mg%패턴: {val}mg")
                sodium_value = val
                sodium_unit = "mg"
    
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
    norm_text_no_space = re.sub(r"\s+", "", norm_text)
    
    # 디버깅: 알레르기 검색 대상 텍스트 출력
    print(f"[알레르기 검색] 공백제거 텍스트 일부: {text_no_space[:500]}...")
    
    # 0. OCR 오타 보정 적용
    allergen_search_text = norm_text
    for typo, correct in ALLERGEN_TYPO_MAP.items():
        allergen_search_text = allergen_search_text.replace(typo, correct)
    allergen_search_no_space = re.sub(r"\s+", "", allergen_search_text)
    
    print(f"[알레르기 검색] 오타보정 텍스트: {allergen_search_text[:300]}...")
    
    # 1. 안전한 키워드(2글자 이상) - 전체 텍스트에서 검색
    for kw in ALLERGEN_KEYWORDS_SAFE:
        if kw in allergen_search_text or kw in allergen_search_no_space or kw in text_no_space:
            print(f"[알레르기 발견] '{kw}' 감지!")
            found_allergens.add(kw)
    
    # 2. 알레르기 관련 섹션 패턴들 (더 확장)
    allergen_section_patterns = [
        r"(?:알[레러]르기|알[레러]지|allerg)[^:]*[:\s]*([^\n.。]{5,200})",
        r"(?:함유|포함|contains?)[:\s]*([^\n.。]+)",
        r"(?:이\s*제품은?|본\s*제품은?)[^\n.。]*(?:사용|제조|생산)[^\n.。]*",
        r"(?:원재료|원료|원재료명)[:\s및]*([^\n]{10,500})",
        r"[(\(]([^)\)]*(?:우유|대두|밀|계란|땅콩|견과|새우|게|오징어|조개)[^)\)]*)[)\)]",
        r"(?:주의|경고|알림)[:\s]*([^\n.。]{5,200})",
        r"(?:동일|같은)\s*(?:제조|생산|시설)[^\n.。]*",
    ]
    
    for pattern in allergen_section_patterns:
        matches = re.findall(pattern, allergen_search_text, re.IGNORECASE)
        for match in matches:
            section_text = match if isinstance(match, str) else " ".join(match)
            section_no_space = re.sub(r"\s+", "", section_text)
            # 안전한 키워드 검색
            for kw in ALLERGEN_KEYWORDS_SAFE:
                if kw in section_text or kw in section_no_space:
                    print(f"[알레르기 섹션발견] '{kw}' in section")
                    found_allergens.add(kw)
            # 짧은 키워드는 명시적 알레르기 표시가 있는 섹션에서만 검출
            has_explicit_allergen_marker = any(marker in section_text for marker in ["함유", "포함", "알레르기", "알러지"])
            if has_explicit_allergen_marker:
                for kw in ALLERGEN_KEYWORDS_SHORT:
                    # 짧은 키워드가 단독으로 있거나 콤마/괄호로 구분된 경우만
                    if re.search(rf"(?:^|[,，、\s(（])({kw})(?:[,，、\s)）]|$)", section_text):
                        print(f"[알레르기 섹션발견-짧은] '{kw}' in section (명시적)")
                        found_allergens.add(kw)
    
    # 3. "OO 함유/포함" 패턴 (예: "우유 함유", "밀 포함") - 짧은 키워드도 허용
    for suffix in ALLERGEN_CONTEXT_SUFFIXES:
        contains_pattern = re.findall(rf"(\w{{1,10}})\s*{suffix}", allergen_search_text)
        for item in contains_pattern:
            if item in ALLERGEN_KEYWORDS_SAFE or item in ALLERGEN_KEYWORDS_SHORT:
                print(f"[알레르기 문맥발견] '{item} {suffix}'")
                found_allergens.add(item)
    
    # 4. 괄호 안 알레르기 표시 (예: "(우유, 대두, 밀 포함)")
    paren_matches = re.findall(r"[(\(]([^)\)]+)[)\)]", allergen_search_text)
    for paren_content in paren_matches:
        paren_no_space = re.sub(r"\s+", "", paren_content)
        # 괄호 안에 알레르기 관련 키워드가 있으면 짧은 키워드도 검출
        has_allergen_context = any(kw in paren_content for kw in ["함유", "포함", "알레르기", "알러지", "주의"])
        for kw in ALLERGEN_KEYWORDS_SAFE:
            if kw in paren_content or kw in paren_no_space:
                print(f"[알레르기 괄호발견] '{kw}' in ({paren_content[:30]}...)")
                found_allergens.add(kw)
        if has_allergen_context:
            for kw in ALLERGEN_KEYWORDS_SHORT:
                if kw in paren_content:
                    found_allergens.add(kw)
    
    # 5. 콤마/슬래시로 분리된 원재료 목록에서 검색 (안전한 키워드만)
    ingredient_list_patterns = [
        r"원재료[명]?[:\s및]*(.+?)(?:영양|내용|유통|보관|주의|$)",
        r"재료[:\s]*(.+?)(?:영양|내용|유통|보관|$)",
    ]
    for pattern in ingredient_list_patterns:
        match = re.search(pattern, allergen_search_text, re.DOTALL | re.IGNORECASE)
        if match:
            ingredients = match.group(1)
            # 콤마, 슬래시, 괄호 등으로 분리
            items = re.split(r"[,，、/·\s]+", ingredients)
            for item in items:
                item = item.strip()
                # 안전한 키워드만 원재료에서 검출
                for kw in ALLERGEN_KEYWORDS_SAFE:
                    if kw in item:
                        print(f"[알레르기 원재료발견] '{kw}' in '{item}'")
                        found_allergens.add(kw)
    
    # 6. 직접 텍스트에서 주요 알레르겐 재검색 (OCR 오류 대비)
    # 2글자 이상만 포함 (1글자는 오탐 발생)
    major_allergens_check = ["오징어", "새우", "꽃게", "대게", "조개", "우유", "계란", "대두", "땅콩", "호두", "아몬드", "밀가루", "글루텐"]
    for allergen in major_allergens_check:
        # 띄어쓰기 무시 검색
        if allergen in text_no_space or allergen in norm_text_no_space:
            if allergen not in found_allergens:
                print(f"[알레르기 최종검색] '{allergen}' 추가 발견!")
                found_allergens.add(allergen)
    
    found_allergens = sorted(found_allergens) if found_allergens else None
    print(f"[알레르기 최종] {found_allergens}")
    
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
    
    # ========== 최종 백업: 공백 완전 제거 후 패턴 찾기 ==========
    full_text = " ".join(lines)
    # 공백, 특수문자 제거한 텍스트
    compact_text = re.sub(r'[\s\|\[\]\{\}\(\)\-_~]', '', text)
    print(f"[영양분석-압축] {compact_text[:500]}...")
    
    # 압축 텍스트에서 영양성분 추출 (최우선)
    # 패턴: 키워드 + 숫자 + 단위 + 퍼센트
    def extract_from_compact(keyword_pattern, text_to_search):
        """압축 텍스트에서 '키워드숫자g퍼센트' 패턴 추출"""
        # 예: 당류25g25% → 25 추출
        pattern = rf'{keyword_pattern}(\d+(?:\.\d+)?)\s*[gG]?\s*\d*%?'
        match = re.search(pattern, text_to_search, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1)), 'g'
            except:
                pass
        return None, None
    
    def extract_mg_from_compact(keyword_pattern, text_to_search):
        """압축 텍스트에서 mg 단위 추출"""
        pattern = rf'{keyword_pattern}(\d+(?:\.\d+)?)\s*(?:mg|m[gG9])?'
        match = re.search(pattern, text_to_search, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1)), 'mg'
            except:
                pass
        return None, None
    
    # 나트륨 (압축 텍스트)
    if sodium_value is None:
        sodium_value, sodium_unit = extract_mg_from_compact(r'나트[륨름룹류]', compact_text)
        if sodium_value:
            print(f"[압축추출] 나트륨: {sodium_value}mg")
    
    # 당류 (압축 텍스트)
    if sugar_value is None:
        sugar_value, sugar_unit = extract_from_compact(r'당[류료]', compact_text)
        if sugar_value:
            print(f"[압축추출] 당류: {sugar_value}g")
    
    # 탄수화물 (압축 텍스트)
    if carbs_value is None:
        carbs_value, carbs_unit = extract_from_compact(r'탄수화물', compact_text)
        if carbs_value:
            print(f"[압축추출] 탄수화물: {carbs_value}g")
    
    # 단백질 (압축 텍스트)
    if protein_value is None:
        protein_value, protein_unit = extract_from_compact(r'단백질', compact_text)
        if protein_value:
            print(f"[압축추출] 단백질: {protein_value}g")
    
    # 지방 (압축 텍스트) - 포화지방, 트랜스지방 제외
    if fat_value is None:
        # "지방" 앞에 "포화", "트랜스"가 없는 경우만
        fat_match = re.search(r'(?<!포화)(?<!트랜스)(?<!스)지방(\d+(?:\.\d+)?)\s*[gG]?', compact_text)
        if fat_match:
            try:
                fat_value = float(fat_match.group(1))
                fat_unit = 'g'
                print(f"[압축추출] 지방: {fat_value}g")
            except:
                pass
    
    # 열량 (압축 텍스트)
    if calories_value is None:
        cal_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kcal|kca1|킬로칼로리|Kcal)', compact_text, re.IGNORECASE)
        if cal_match:
            try:
                calories_value = float(cal_match.group(1))
                calories_unit = 'kcal'
                print(f"[압축추출] 열량: {calories_value}kcal")
            except:
                pass
    
    # ========== 기존 백업: 숫자+단위 패턴으로 직접 찾기 ==========
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
    
    # ========== 비정상 값 필터링 ==========
    # 식품 영양정보의 합리적 범위를 벗어난 값은 OCR 오류로 간주
    def validate_range(value, max_val, name):
        if value is not None and value > max_val:
            print(f"[값 필터링] {name}: {value} > {max_val} (비정상, 무시)")
            return None
        return value
    
    # 1회 제공량 기준 합리적 최대값 (엄격하게)
    # 일반 식품 기준: 열량 1000kcal, 각 영양소 100g 이하가 합리적
    calories_value = validate_range(calories_value, 1500, "열량")  # 최대 1500kcal
    carbs_value = validate_range(carbs_value, 150, "탄수화물")  # 최대 150g
    sugar_value = validate_range(sugar_value, 100, "당류")  # 최대 100g
    protein_value = validate_range(protein_value, 100, "단백질")  # 최대 100g
    fat_value = validate_range(fat_value, 100, "지방")  # 최대 100g
    saturated_fat_value = validate_range(saturated_fat_value, 50, "포화지방")  # 최대 50g
    trans_fat_value = validate_range(trans_fat_value, 20, "트랜스지방")  # 최대 20g
    cholesterol_value = validate_range(cholesterol_value, 1000, "콜레스테롤")  # 최대 1000mg
    sodium_value = validate_range(sodium_value, 5000, "나트륨")  # 최대 5000mg

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
                analysis_text = translated
    
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