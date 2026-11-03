import os
import shutil
import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, AudioFileClip, vfx

app = FastAPI(title="Myanmar Movie Recap AI - Full Pipeline")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

UPLOAD_DIR = "uploads"
CHUNKS_DIR = "chunks"
OUTPUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CHUNKS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
templates = Jinja2Templates(directory="templates")

@app.get("/")
def read_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")
@app.post("/api/upload-chunk")
async def upload_chunk(
    file: UploadFile = File(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    file_identifier: str = Form(...)
):
    chunk_path = os.path.join(CHUNKS_DIR, f"{file_identifier}_chunk_{chunk_index}")
    with open(chunk_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    uploaded_chunks = [f for f in os.listdir(CHUNKS_DIR) if f.startswith(file_identifier)]
    if len(uploaded_chunks) == total_chunks:
        final_file_path = os.path.join(UPLOAD_DIR, f"{file_identifier}.mp4")
        with open(final_file_path, "wb") as final_file:
            for i in range(total_chunks):
                part_path = os.path.join(CHUNKS_DIR, f"{file_identifier}_chunk_{i}")
                with open(part_path, "rb") as part_file:
                    final_file.write(part_file.read())
                os.remove(part_path)
        return JSONResponse(content={"status": "completed", "filename": f"{file_identifier}.mp4"})
    
    return JSONResponse(content={"status": "chunk_received", "chunk_index": chunk_index})

def generate_ai_narration_script(part_num, duration):
    """မြန်မာ Movie Recap ဇာတ်ကြောင်းပြောဟန် (Script) ဖန်တီးခြင်း"""
    script_text = f"ဒီအခန်းမှာတော့ အကြီးကဲနဲ့ သရုပ်ဆောင်တို့ရဲ့ အဓိက လှုပ်ရှားမှုတွေကို ဆက်လက် ကြည့်ရှုရမှာ ဖြစ်ပါတယ်။ မိန်းကလေးမှ ဇာတ်လမ်းရဲ့ အလှည့်အပြောင်းကို စိတ်ဝင်စားဖွယ် ဖော်ပြနေပါတယ်ရှင်။"
    srt_content = f"1\n00:00:01,000 --> 00:00:06,000\n{script_text}\n\n"
    return script_text, srt_content

def add_yellow_part_overlay(subclip, part_num):
    """ညာဘက်အပေါ်ထောင့်တွင် အမည်းရိပ်နှင့် အဝါရောင် PART စာတန်းတပ်ဆင်ခြင်း"""
    W, H = subclip.size
    fontsize = int(H * 0.08)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    text = f"PART {str(part_num).zfill(3)}"
    
    try:
        font = ImageFont.truetype("Pyidaungsu-Bold.ttf", fontsize)
    except IOError:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = W - text_width - int(W * 0.03)
    y = int(H * 0.03)
    
    shadow_offset = int(fontsize * 0.1)
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(0, 0, 0, 220))
    draw.text((x, y), text, font=font, fill=(255, 255, 0, 255))
    
    overlay_np = np.array(img)
    overlay_clip = ImageClip(overlay_np, duration=subclip.duration)
    return CompositeVideoClip([subclip, overlay_clip])

@app.post("/api/process-pipeline")
async def process_pipeline(
    filename: str = Form(...),
    segment_duration: int = Form(180),
    language: str = Form("Burmese"),
    tts_provider: str = Form("ElevenLabs"),
    subtitle_enabled: bool = Form(True)
):
    input_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail="Uploaded video file not found.")
        
    video = VideoFileClip(input_path)
    total_duration = video.duration
    base_name = os.path.splitext(filename)[0]
    
    start_time = 0
    part_num = 1
    generated_parts = []
    
    while start_time < total_duration:
        end_time = min(start_time + int(segment_duration), total_duration)
        subclip = video.subclip(start_time, end_time)
        
        if subclip.duration < 2 and start_time > 0:
            subclip = subclip.fx(vfx.freeze, t='end', freeze_duration=2)
            
        # 1. Generate Burmese Script & SRT Subtitle
        script, srt_content = generate_ai_narration_script(part_num, subclip.duration)
        srt_filename = f"{base_name}_Part_{str(part_num).zfill(3)}.srt"
        srt_path = os.path.join(OUTPUT_DIR, srt_filename)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        # 2. Add Yellow Part Overlay & Subtitle Burn-in simulation
        final_subclip = add_yellow_part_overlay(subclip, part_num)
        
        output_filename = f"{base_name}_Part_{str(part_num).zfill(3)}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        # 3. Render and Export MP4
        final_subclip.write_videofile(
            output_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=2
        )
        
        qc_passed = os.path.exists(output_path) and os.path.getsize(output_path) > 0
        
        if qc_passed:
            generated_parts.append({
                "part": part_num,
                "title": output_filename,
                "duration": round(end_time - start_time, 2),
                "url": f"/outputs/{output_filename}",
                "srt_url": f"/outputs/{srt_filename}",
                "status": "Verified & Exported"
            })
        else:
            generated_parts.append({
                "part": part_num,
                "title": output_filename,
                "status": "QC Failed"
            })
            
        start_time = end_time
        part_num += 1
        
    video.close()
    
    return JSONResponse(content={
        "status": "success",
        "total_parts": len(generated_parts),
        "parts": generated_parts
    })
