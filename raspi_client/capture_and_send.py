import requests
import time
import uuid
import os
import subprocess
from picamera2 import Picamera2
from datetime import datetime

# TTS 라이브러리 (gTTS 사용)
try:
    from gtts import gTTS
    TTS_AVAILABLE = True
except ImportError:
    print("[경고] gTTS가 설치되지 않았습니다. pip install gtts 로 설치하세요.")
    TTS_AVAILABLE = False

# 서버 주소 (필요하면 IP로 바꿔라)
SERVER_URL = "http://127.0.0.1:5000/api/upload"

# 저장될 임시 파일 경로
TEMP_DIR = "/home/pi/label_temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# TTS 음성 파일 경로
TTS_FILE = "/tmp/tts_output.mp3"


def speak(text):
    """텍스트를 음성으로 읽어주기 (한국어)"""
    if not TTS_AVAILABLE:
        print(f"[TTS 미설치] {text}")
        return
    
    if not text or not text.strip():
        return
    
    try:
        print(f"[🔊 음성 출력] {text}")
        
        # gTTS로 음성 생성
        tts = gTTS(text=text, lang='ko')
        tts.save(TTS_FILE)
        
        # mpg321 또는 mpg123으로 재생 (라즈베리파이에서 사용 가능)
        # mpg321이 없으면 aplay나 다른 플레이어 사용
        players = ['mpg321', 'mpg123', 'omxplayer', 'aplay']
        
        for player in players:
            try:
                if player == 'aplay':
                    # aplay는 wav만 지원하므로 변환 필요
                    subprocess.run(['ffmpeg', '-y', '-i', TTS_FILE, '/tmp/tts_output.wav'], 
                                   capture_output=True, timeout=10)
                    subprocess.run([player, '/tmp/tts_output.wav'], 
                                   capture_output=True, timeout=30)
                else:
                    subprocess.run([player, TTS_FILE], capture_output=True, timeout=30)
                break
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                print("[경고] 음성 재생 시간 초과")
                break
        
        # 임시 파일 삭제
        if os.path.exists(TTS_FILE):
            os.remove(TTS_FILE)
            
    except Exception as e:
        print(f"[TTS 오류] {e}")


def build_speech_text(result):
    """서버 응답에서 읽을 텍스트 생성"""
    lines = []
    analysis = result.get("analysis", {})
    
    # 제품명
    label = result.get("label")
    if label:
        lines.append(f"{label} 분석 결과입니다.")
    else:
        lines.append("식품 라벨 분석 결과입니다.")
    
    # 영양 정보
    nutrition_parts = []
    
    if analysis.get("calories_value"):
        nutrition_parts.append(f"열량 {analysis['calories_value']} {analysis.get('calories_unit', 'kcal')}")
    
    if analysis.get("carbs_value"):
        nutrition_parts.append(f"탄수화물 {analysis['carbs_value']} {analysis.get('carbs_unit', 'g')}")
    
    if analysis.get("sugar_value"):
        nutrition_parts.append(f"당류 {analysis['sugar_value']} {analysis.get('sugar_unit', 'g')}")
    
    if analysis.get("protein_value"):
        nutrition_parts.append(f"단백질 {analysis['protein_value']} {analysis.get('protein_unit', 'g')}")
    
    if analysis.get("fat_value"):
        nutrition_parts.append(f"지방 {analysis['fat_value']} {analysis.get('fat_unit', 'g')}")
    
    if analysis.get("sodium_value"):
        nutrition_parts.append(f"나트륨 {analysis['sodium_value']} {analysis.get('sodium_unit', 'mg')}")
    
    if nutrition_parts:
        lines.append("영양 정보: " + ", ".join(nutrition_parts) + ".")
    else:
        lines.append("영양 정보를 찾을 수 없습니다.")
    
    # 알레르기 정보 (중요!)
    allergens = analysis.get("allergens")
    if allergens:
        lines.append(f"주의! 알레르기 유발 성분: {', '.join(allergens)}.")
    else:
        lines.append("알레르기 유발 성분이 감지되지 않았습니다.")
    
    return " ".join(lines)


def capture_image():
    """라즈베리파이 카메라로 이미지 촬영"""
    picam = Picamera2()
    picam.configure(picam.create_still_configuration())
    picam.start()
    time.sleep(1)  # 카메라 워밍업

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    filepath = os.path.join(TEMP_DIR, filename)

    picam.capture_file(filepath)
    picam.stop()

    print(f"[✓] 촬영 완료 → {filepath}")
    speak("촬영 완료. 분석 중입니다.")
    return filepath


def upload_image(filepath):
    """서버로 이미지 업로드 및 TTS 출력"""
    file_id = str(uuid.uuid4())

    with open(filepath, "rb") as f:
        files = {"file": (os.path.basename(filepath), f, "image/jpeg")}
        data = {"id": file_id}
        
        # JSON 응답을 받기 위한 헤더
        headers = {"Accept": "application/json"}

        print("[…] 서버로 업로드 중…")
        response = requests.post(SERVER_URL, files=files, data=data, headers=headers)

    if response.status_code == 200:
        print("[✓] 업로드 성공!")
        
        try:
            result = response.json()
            print("서버 응답:", result)
            
            # TTS로 결과 읽어주기
            speech_text = build_speech_text(result)
            speak(speech_text)
            
        except Exception as e:
            print(f"[경고] JSON 파싱 오류: {e}")
            speak("분석이 완료되었습니다.")

        # 임시 파일 삭제
        os.remove(filepath)
        print("[✓] 로컬 파일 삭제 완료")

    else:
        print("[X] 업로드 실패! 상태코드:", response.status_code)
        print(response.text)
        speak("업로드에 실패했습니다.")


def main():
    print("\n" + "="*50)
    print("  🏷️  라벨 OCR & 음성 안내 시스템")
    print("="*50)
    
    # 시작 안내
    speak("라벨 분석 시스템이 시작되었습니다. 촬영하려면 엔터를 누르세요.")
    
    while True:
        print("\n=== 📸 라벨 촬영 & OCR 업로드 ===")
        cmd = input("촬영하려면 Enter, 종료하려면 q: ")

        if cmd.lower() == "q":
            speak("시스템을 종료합니다.")
            print("종료합니다.")
            break

        try:
            path = capture_image()
            upload_image(path)
        except Exception as e:
            print("[ERROR] 문제가 발생했습니다:", e)
            speak("오류가 발생했습니다.")


if __name__ == "__main__":
    main()
