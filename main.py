import os
import shutil
import time
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
from PIL import Image
from apscheduler.schedulers.background import BackgroundScheduler
from moviepy.editor import VideoFileClip

app = FastAPI(title="Micro Transfer Backend Pro", version="2.0")

# Cấu hình CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
CONVERTED_DIR = "converted"
YOUTUBE_DIR = "downloads"

for d in [UPLOAD_DIR, CONVERTED_DIR, YOUTUBE_DIR]:
    os.makedirs(d, exist_ok=True)

# ================= 1. CƠ CHẾ TỰ ĐỘNG XÓA FILE SAU 24 GIỜ =================
CLEANUP_INTERVAL_HOURS = 24

def cleanup_old_files():
    """Hàm quét và xóa các file có tuổi thọ lớn hơn 24 giờ"""
    now = time.time()
    cutoff = now - (CLEANUP_INTERVAL_HOURS * 3600)
    
    directories = [UPLOAD_DIR, CONVERTED_DIR, YOUTUBE_DIR]
    for directory in directories:
        if not os.path.exists(directory):
            continue
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                # Kiểm tra thời gian sửa đổi cuối cùng của file
                if os.path.getmtime(file_path) < cutoff:
                    try:
                        os.remove(file_path)
                        print(f"[Auto-Clean] Đã xóa file cũ quá hạn: {filename}")
                    except Exception as e:
                        print(f"[Auto-Clean] Lỗi khi xóa file {filename}: {e}")

# Khởi chạy Scheduler chạy ngầm mỗi giờ một lần để dọn dẹp file
scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_old_files, 'interval', hours=1)
scheduler.start()

# ================= API ENDPOINTS =================

class YouTubeRequest(BaseModel):
    url: str

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    download_url = f"http://localhost:8000/api/download/{file.filename}"
    return {"status": "success", "data": {"url": download_url}}

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    raise HTTPException(status_code=404, detail="Không tìm thấy file hoặc đã bị xóa tự động.")

@app.post("/api/youtube")
async def process_youtube(data: YouTubeRequest):
    try:
        ydl_opts = {'format': 'best', 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = yt_dlp.YoutubeDL({'noplaylist': True}).extract_info(data.url, download=False)
            title = info.get('title', 'Video YouTube')
            formats = [
                {"resolution": f.get("format_note", "Standard"), "url": f.get("url")}
                for f in info.get('formats', []) if f.get('ext') == 'mp4' and f.get('url')
            ]
            return {"status": "success", "title": title, "formats": formats[:3]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ================= 2. MỞ RỘNG CONVERT FILE (ẢNH & VIDEO/AUDIO QUA FFMPEG) =================
@app.post("/api/convert")
async def convert_file(file: UploadFile = File(...), target_format: str = Form(...)):
    input_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    base_name, _ = os.path.splitext(file.filename)
    target_format = target_format.lower()
    output_filename = f"{base_name}.{target_format}"
    output_path = os.path.join(CONVERTED_DIR, output_filename)

    try:
        # Xử lý hình ảnh bằng Pillow
        if target_format in ["jpg", "jpeg", "png", "webp"]:
            with Image.open(input_path) as img:
                if target_format in ["jpg", "jpeg"] and img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(output_path)
                
        # Xử lý chuyển đổi Audio/Video bằng MoviePy (Sử dụng FFmpeg ngầm)
        elif target_format in ["mp3", "wav", "mp4", "avi", "mov"]:
            if target_format in ["mp3", "wav"]:
                # Trích xuất âm thanh từ video sang audio
                clip = VideoFileClip(input_path)
                clip.audio.write_audiofile(output_path)
                clip.close()
            else:
                # Chuyển đổi định dạng video
                clip = VideoFileClip(input_path)
                clip.write_videofile(output_path, codec="libx264", audio_codec="aac")
                clip.close()
        else:
            raise HTTPException(status_code=400, detail="Định dạng chuyển đổi không được hỗ trợ.")
        
        return {
            "status": "success", 
            "download_url": f"http://localhost:8000/api/converted/{output_filename}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi chuyển đổi: {str(e)}")

@app.get("/api/converted/{filename}")
async def get_converted_file(filename: str):
    file_path = os.path.join(CONVERTED_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    raise HTTPException(status_code=404, detail="File không tồn tại")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)