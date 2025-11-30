#!/usr/bin/env python3
"""
카메라 프리뷰 스크립트
카메라 설정을 사용하여 실시간 프리뷰를 표시합니다.
"""

import sys
import argparse
from camera_config import CameraConfig, start_preview


def main():
    parser = argparse.ArgumentParser(description="라즈베리파이 카메라 프리뷰")
    parser.add_argument(
        "--width", type=int, default=1280,
        help="프리뷰 너비 (기본값: 1280)"
    )
    parser.add_argument(
        "--height", type=int, default=720,
        help="프리뷰 높이 (기본값: 720)"
    )
    parser.add_argument(
        "--zoom", type=float, default=0.75,
        help="줌 팩터 (1.0=줌없음, 0.75=25%% 줌인, 기본값: 0.75)"
    )
    parser.add_argument(
        "--no-autofocus", action="store_true",
        help="자동 포커스 비활성화"
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="프리뷰 지속 시간 (초, 기본값: 무한)"
    )
    parser.add_argument(
        "--warmup", type=float, default=2.0,
        help="카메라 워밍업 시간 (초, 기본값: 2.0)"
    )
    
    args = parser.parse_args()
    
    # 카메라 설정 생성
    config = CameraConfig()
    config.zoom_factor = args.zoom
    config.autofocus_enabled = not args.no_autofocus
    config.warmup_time = args.warmup
    
    print("=" * 50)
    print("  📷 카메라 프리뷰")
    print("=" * 50)
    print(f"해상도: {args.width}x{args.height}")
    print(f"줌: {int((1-args.zoom)*100)}% 줌인")
    print(f"자동 포커스: {'활성화' if config.autofocus_enabled else '비활성화'}")
    print(f"워밍업 시간: {args.warmup}초")
    if args.duration:
        print(f"지속 시간: {args.duration}초")
    else:
        print("지속 시간: 무한 (Ctrl+C로 종료)")
    print("=" * 50)
    
    # 프리뷰 시작
    try:
        start_preview(
            config=config,
            preview_size=(args.width, args.height),
            duration=args.duration
        )
    except KeyboardInterrupt:
        print("\n프리뷰가 종료되었습니다.")
        sys.exit(0)
    except Exception as e:
        print(f"\n오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

