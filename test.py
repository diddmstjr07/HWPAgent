import os
from PIL import Image

def get_image_info(file_path):
    """
    이미지 파일의 해상도와 주요 정보를 읽어옵니다.
    """
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            format_type = img.format
            mode = img.mode # RGB, RGBA etc.
            
            # 파일 용량 계산 (MB 단위)
            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            
            return {
                "filename": os.path.basename(file_path),
                "width": width,
                "height": height,
                "total_pixels": width * height,
                "format": format_type,
                "size_mb": round(file_size_mb, 2),
                "valid": True
            }
    except Exception as e:
        return {"filename": os.path.basename(file_path), "valid": False, "error": str(e)}

def scan_images(target_path):
    """
    폴더 혹은 단일 파일 경로를 받아 정보를 출력합니다.
    """
    target_files = []

    # 1. 대상이 폴더인지 파일인지 확인
    if os.path.isdir(target_path):
        print(f"📂 폴더 스캔 중: {target_path}")
        # 파일명 순으로 정렬하여 읽기
        files = sorted(os.listdir(target_path))
        for f in files:
            full_path = os.path.join(target_path, f)
            # 이미지 확장자만 필터링 (필요시 추가 가능)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                target_files.append(full_path)
    elif os.path.isfile(target_path):
        print(f"📄 단일 파일 분석: {target_path}")
        target_files.append(target_path)
    else:
        print("❌ 경로를 찾을 수 없습니다.")
        return

    print("-" * 70)
    print(f"{'파일명':<25} | {'해상도 (WxH)':<15} | {'총 픽셀 수':<12} | {'용량(MB)':<8}")
    print("-" * 70)

    # 2. 정보 출력
    for file_path in target_files:
        info = get_image_info(file_path)
        
        if info['valid']:
            resolution = f"{info['width']} x {info['height']}"
            # 가독성을 위해 천 단위 콤마 추가
            pixels = f"{info['total_pixels']:,}"
            print(f"{info['filename']:<25} | {resolution:<15} | {pixels:<12} | {info['size_mb']} MB")
        else:
            print(f"{info['filename']:<25} | ❌ 읽기 실패 ({info.get('error')})")

    print("-" * 70)

if __name__ == "__main__":
    # 사용 예시 1: 앞서 만든 폴더 스캔
    target_folder = "resolution_tests" 
    
    # 폴더가 없으면 현재 경로의 특정 이미지를 테스트하거나 경고 메시지 출력
    if os.path.exists(target_folder):
        scan_images(target_folder)
    else:
        print(f"'{target_folder}' 폴더가 없습니다. 경로를 확인해주세요.")
        # 사용 예시 2: 특정 파일 직접 지정 (주석 해제 후 사용)
        # scan_images("my_image.jpg")