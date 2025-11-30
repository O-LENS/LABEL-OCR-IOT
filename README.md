# 📦 LABEL-OCR-IOT  
라즈베리파이 카메라 기반 실시간 라벨 OCR + 영양분 분석 + 알레르기 검출 시스템

## **어엄청 오래걸림**
---

## 📌 프로젝트 개요

**LABEL-OCR-IOT**는 라즈베리파이 5 카메라를 이용해 식품 라벨을 촬영하고,  
Flask 서버가 Tesseract OCR로 분석하여 다음 정보를 자동 추출하는 프로젝트입니다.

- 🔤 **OCR 텍스트 인식 (Tesseract 기반)**
- 🧂 **영양성분 자동 추출 (당류/나트륨 탐지)**
- ⚠️ **알레르기 유발 식품 자동 검출 (우유, 견과류, 계란, 땅콩 등)**
- 🌐 **Papago API 기반 번역 기능**
- 🖥 **웹 UI에서 결과 확인 (한국어 UI 적용 완료)**

라벨을 촬영 → OCR 수행 → 영양·알레르기 분석 → 번역 → 웹 대시보드 출력  
이 흐름을 IoT 방식으로 완성한 프로젝트입니다.

---

## 🏗 시스템 구성도

```text
[Raspberry Pi]
      │ (이미지 업로드)
      ▼
[Flask Server - OCR/분석]
      │
      ├─ Tesseract → 텍스트 추출
      ├─ Regex → 당류·나트륨·알레르기 검출
      ├─ Papago → 번역 (선택)
      ▼
[Web UI - 결과 시각화]
```

---
## Windows 활성화:
```
.venv\Scripts\activate
```

## 패키지 설치
```
cd server
pip install -r requirements.txt
```

## Tesseract 설치

다운로드 링크:
```
https://github.com/UB-Mannheim/tesseract/wiki
```

설치 후 아래 중 하나로 실행 경로를 지정하세요:
- 시스템 PATH에 `tesseract`를 추가
- 또는 환경 변수 `TESSERACT_CMD`에 바이너리 경로 지정

## Flask 서버 실행
```
cd server
python app.py
```

## 브라우저에서 접속:
```
http://127.0.0.1:5000
```

## 📸 Raspberry Pi 실행 방법

라즈베리파이에서 아래 실행:
```
python3 raspi_client/capture_and_send.py
```
