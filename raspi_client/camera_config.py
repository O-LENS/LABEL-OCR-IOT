"""
카메라 설정 및 프리뷰 모듈
해상도, 줌, 포커스 등의 카메라 설정을 관리하고 프리뷰 기능을 제공합니다.
"""

import time
from picamera2 import Picamera2, Preview
from PIL import Image


class CameraConfig:
    """카메라 설정 클래스"""
    
    def __init__(self):
        # 기본 해상도 설정 (None이면 센서 기본값 사용)
        self.resolution = None  # (width, height) 튜플 또는 None
        
        # 줌 설정 (1.0 = 줌 없음, 0.75 = 25% 줌인, 0.5 = 50% 줌인)
        self.zoom_factor = 0.75  # 25% 줌인 기본값
        
        # 자동 포커스 활성화 여부
        self.autofocus_enabled = True
        
        # 카메라 워밍업 대기 시간 (초)
        self.warmup_time = 2.0
        
        # 이미지 품질 (JPEG 품질, 1-100)
        self.jpeg_quality = 95
        
        # 카메라 인스턴스
        self.picam = None
    
    def create_camera(self):
        """카메라 인스턴스 생성 및 설정"""
        self.picam = Picamera2()
        
        # 해상도 설정이 있으면 적용
        if self.resolution:
            width, height = self.resolution
            config = self.picam.create_still_configuration(
                main={"size": (width, height)}
            )
        else:
            config = self.picam.create_still_configuration()
        
        self.picam.configure(config)
        return self.picam
    
    def start_camera(self):
        """카메라 시작 및 설정 적용"""
        if not self.picam:
            self.create_camera()
        
        self.picam.start()
        
        # 자동 포커스 설정
        if self.autofocus_enabled:
            try:
                self.picam.set_controls({"AfMode": 2})  # 2 = Auto focus mode
                print("[카메라] 자동 포커스 모드 활성화")
            except Exception as e:
                print(f"[경고] 자동 포커스 설정 실패: {e}")
        
        # 워밍업 대기
        time.sleep(self.warmup_time)
        print(f"[카메라] 워밍업 완료 ({self.warmup_time}초)")
    
    def stop_camera(self):
        """카메라 중지"""
        if self.picam:
            self.picam.stop()
            self.picam = None
    
    def apply_zoom_to_image(self, image_path):
        """이미지에 줌 효과 적용 (후처리)"""
        try:
            img = Image.open(image_path)
            width, height = img.size
            
            # 줌인 = 중앙 영역만 사용
            crop_width = int(width * self.zoom_factor)
            crop_height = int(height * self.zoom_factor)
            left = (width - crop_width) // 2
            top = (height - crop_height) // 2
            right = left + crop_width
            bottom = top + crop_height
            
            # 중앙 영역 크롭
            cropped_img = img.crop((left, top, right, bottom))
            cropped_img.save(image_path, quality=self.jpeg_quality)
            
            print(f"[카메라] {int((1-self.zoom_factor)*100)}% 줌인 적용 "
                  f"(원본: {width}x{height} → 크롭: {crop_width}x{crop_height})")
            return True
        except Exception as e:
            print(f"[경고] 이미지 크롭 실패: {e}")
            return False
    
    def capture_image(self, filepath, apply_zoom=True):
        """이미지 촬영"""
        if not self.picam:
            raise RuntimeError("카메라가 시작되지 않았습니다. start_camera()를 먼저 호출하세요.")
        
        self.picam.capture_file(filepath)
        
        # 줌 효과 적용
        if apply_zoom and self.zoom_factor < 1.0:
            self.apply_zoom_to_image(filepath)
        
        return filepath
    
    def get_preview_config(self, preview_size=(1280, 720)):
        """프리뷰용 설정 생성"""
        if not self.picam:
            self.create_camera()
        
        # 프리뷰 설정 (더 낮은 해상도로 빠른 프리뷰)
        preview_config = self.picam.create_preview_configuration(
            main={"size": preview_size}
        )
        return preview_config


def start_preview(config: CameraConfig = None, preview_size=(1280, 720), duration=None, preview_type=None):
    """
    카메라 프리뷰 시작
    
    Args:
        config: CameraConfig 인스턴스 (None이면 기본 설정 사용)
        preview_size: 프리뷰 해상도 (width, height)
        duration: 프리뷰 지속 시간 (초, None이면 무한)
        preview_type: 프리뷰 타입 (Preview.QTGL, Preview.QT, Preview.DRM, None=자동)
    """
    if config is None:
        config = CameraConfig()
    
    picam = None
    try:
        # 카메라 생성
        picam = Picamera2()
        
        # 프리뷰 설정
        preview_config = picam.create_preview_configuration(
            main={"size": preview_size}
        )
        picam.configure(preview_config)
        
        # 프리뷰 타입 자동 선택 (None이면 자동)
        if preview_type is None:
            # 시스템에 따라 자동으로 선택
            try:
                preview_type = Preview.QTGL  # OpenGL 기반 (권장)
            except:
                try:
                    preview_type = Preview.QT  # Qt 기반
                except:
                    preview_type = Preview.DRM  # DRM 기반 (라즈베리파이 기본)
        
        # 프리뷰 시작
        picam.start_preview(preview_type)
        
        # 카메라 시작
        picam.start()
        
        # 자동 포커스 설정
        if config.autofocus_enabled:
            try:
                picam.set_controls({"AfMode": 2})
                print("[프리뷰] 자동 포커스 활성화")
            except Exception as e:
                print(f"[경고] 자동 포커스 설정 실패: {e}")
        
        print(f"[프리뷰] 시작됨 (해상도: {preview_size[0]}x{preview_size[1]})")
        print("[프리뷰] 종료하려면 Ctrl+C를 누르세요.")
        
        if duration:
            time.sleep(duration)
            picam.stop_preview()
            picam.stop()
            print("[프리뷰] 종료됨")
        else:
            # 무한 대기 (Ctrl+C로 종료)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n[프리뷰] 사용자에 의해 종료됨")
                picam.stop_preview()
                picam.stop()
    
    except Exception as e:
        print(f"[오류] 프리뷰 시작 실패: {e}")
        if picam:
            try:
                picam.stop_preview()
            except:
                pass
            try:
                picam.stop()
            except:
                pass


if __name__ == "__main__":
    # 테스트: 프리뷰 실행
    print("카메라 프리뷰 테스트")
    print("=" * 50)
    
    # 커스텀 설정 예시
    config = CameraConfig()
    config.zoom_factor = 0.75  # 25% 줌인
    config.autofocus_enabled = True
    config.warmup_time = 1.0
    
    # 프리뷰 시작 (무한 실행, Ctrl+C로 종료)
    start_preview(config, preview_size=(1280, 720))

