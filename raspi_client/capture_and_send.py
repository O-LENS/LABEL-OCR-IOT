import requests
import time
import uuid
import os
from picamera2 import Picamera2
from datetime import datetime

# 서버 주소 (필요하면 IP로 바꿔라)
SERVER_URL = "http://127.0.0.1:5000/api/upload"

# 저장될 임시 파일 경로
TEMP_DIR = "/home/pi/label_temp"
os.makedirs(TEMP_DIR, exist_ok=True)


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
    return filepath


def upload_image(filepath):
    """서버로 이미지 업로드"""
    file_id = str(uuid.uuid4())

    with open(filepath, "rb") as f:
        files = {"file": (os.path.basename(filepath), f, "image/jpeg")}
        data = {"id": file_id}

        print("[…] 서버로 업로드 중…")
        response = requests.post(SERVER_URL, files=files, data=data)

    if response.status_code == 200:
        print("[✓] 업로드 성공!")
        print("서버 응답:", response.json())

        # 임시 파일 삭제
        os.remove(filepath)
        print("[✓] 로컬 파일 삭제 완료")

    else:
        print("[X] 업로드 실패! 상태코드:", response.status_code)
        print(response.text)


def main():
    while True:
        print("\n=== 📸 라벨 촬영 & OCR 업로드 ===")
        cmd = input("촬영하려면 Enter, 종료하려면 q: ")

        if cmd.lower() == "q":
            print("종료합니다.")
            break

        try:
            path = capture_image()
            upload_image(path)
        except Exception as e:
            print("[ERROR] 문제가 발생했습니다:", e)


if __name__ == "__main__":
    main()
