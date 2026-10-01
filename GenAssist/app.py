import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gtts import gTTS
from PIL import Image


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = STATIC_DIR / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

DREAMTALK_DIR = Path(os.getenv("DREAMTALK_DIR", BASE_DIR / "dreamtalk")).resolve()
CHECKPOINT_DIR = DREAMTALK_DIR / "checkpoints"
INFERENCE_SCRIPT = DREAMTALK_DIR / "inference_for_demo_video.py"
STYLE_PATH = (
    DREAMTALK_DIR
    / "data"
    / "style_clip"
    / "3DMM"
    / "M030_front_neutral_level1_001.mat"
)
POSE_PATH = (
    DREAMTALK_DIR
    / "data"
    / "pose"
    / "RichardShelby_front_neutral_level1_001.mat"
)
DEFAULT_PORTRAIT = Path(
    os.getenv(
        "GENASSIST_DEFAULT_PORTRAIT",
        DREAMTALK_DIR / "data" / "src_img" / "uncropped" / "male_face.png",
    )
)

app = FastAPI(title="GenAssist API")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def checkpoint_files():
    if not CHECKPOINT_DIR.exists():
        return []
    return [
        path
        for path in CHECKPOINT_DIR.rglob("*")
        if path.is_file() and path.name != ".gitkeep" and path.stat().st_size > 1024
    ]


def dreamtalk_ready():
    return all(
        path.exists()
        for path in (INFERENCE_SCRIPT, STYLE_PATH, POSE_PATH)
    ) and bool(checkpoint_files())


def create_support_response(message):
    text = message.lower()
    responses = [
        (
            ("refund", "return", "money back"),
            "I can help with your refund. Please provide your order number and the reason for the return. We will verify the purchase and explain the next steps.",
        ),
        (
            ("order", "delivery", "shipping", "track"),
            "I can help track your order. Please provide your order number. I will use it to check the latest delivery status.",
        ),
        (
            ("password", "login", "sign in", "account"),
            "I can help restore access to your account. Please use the forgot-password option first. If the reset email does not arrive, check your spam folder and confirm that you entered the registered email address.",
        ),
        (
            ("payment", "card", "charged", "billing"),
            "I am sorry about the payment issue. Please do not share your full card number. Provide the transaction date, amount, and order reference so the billing team can investigate safely.",
        ),
        (
            ("cancel", "cancellation"),
            "I can help cancel the request if it has not already been processed. Please provide the order or subscription reference.",
        ),
    ]
    for keywords, response in responses:
        if any(keyword in text for keyword in keywords):
            return response
    return (
        "Thank you for contacting GenAssist. I understand your request. "
        "Please share any relevant order or account reference, without including "
        "passwords or complete payment details, so I can guide you further."
    )


async def save_portrait(upload, destination):
    if upload is None:
        if DEFAULT_PORTRAIT.exists():
            shutil.copy2(DEFAULT_PORTRAIT, destination)
            return destination
        return None

    if upload.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=400, detail="Portrait must be PNG, JPEG, or WebP.")
    data = await upload.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Portrait must be smaller than 10 MB.")
    destination.write_bytes(data)
    try:
        image = Image.open(destination).convert("RGB")
        if min(image.size) < 256:
            raise HTTPException(
                status_code=400,
                detail="Portrait must be at least 256 x 256 pixels.",
            )
        image.save(destination, format="PNG")
        return destination
    except HTTPException:
        raise
    except Exception as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The portrait is not a valid image.") from error


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "speech_ready": True,
        "dreamtalk_ready": dreamtalk_ready(),
        "dreamtalk_dir": str(DREAMTALK_DIR),
    }


@app.post("/api/chat")
async def chat(
    message: str = Form(...),
    generate_video: bool = Form(True),
    portrait: UploadFile | None = File(None),
):
    message = message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if len(message) > 1000:
        raise HTTPException(status_code=400, detail="Message is too long.")
    run_id = uuid.uuid4().hex
    run_dir = GENERATED_DIR / run_id
    run_dir.mkdir(parents=True)
    image_path = run_dir / "portrait.png"
    audio_path = run_dir / "response.mp3"
    video_path = run_dir / "response.mp4"

    selected_portrait = await save_portrait(portrait, image_path)
    response_text = create_support_response(message)

    try:
        gTTS(text=response_text, lang="en", slow=False).save(str(audio_path))
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Speech generation failed: {error}",
        ) from error

    audio_url = f"/static/generated/{run_id}/response.mp3"
    result = {
        "response": response_text,
        "audio_url": audio_url,
        "video_url": None,
        "status": "VOICE RESPONSE READY",
    }

    if not generate_video:
        return result
    if not dreamtalk_ready():
        result["status"] = (
            "VOICE READY — ADD THE OFFICIAL DREAMTALK CHECKPOINT TO ENABLE VIDEO"
        )
        return result
    if selected_portrait is None:
        result["status"] = (
            "VOICE READY — UPLOAD A FRONT-FACING PORTRAIT TO GENERATE VIDEO"
        )
        return result

    command = [
        sys.executable,
        str(INFERENCE_SCRIPT),
        "--wav_path",
        str(audio_path),
        "--style_clip_path",
        str(STYLE_PATH),
        "--pose_path",
        str(POSE_PATH),
        "--image_path",
        str(image_path),
        "--cfg_scale",
        "1.0",
        "--max_gen_len",
        "30",
        "--output_name",
        run_id,
    ]
    completed = subprocess.run(
        command,
        cwd=DREAMTALK_DIR,
        capture_output=True,
        text=True,
        timeout=900,
    )
    dreamtalk_output = DREAMTALK_DIR / "output_video" / f"{run_id}.mp4"
    if completed.returncode != 0:
        result["status"] = "VOICE READY — DREAMTALK FAILED: " + (
            completed.stderr or completed.stdout
        )[-500:]
        return result
    if not dreamtalk_output.exists():
        result["status"] = "VOICE READY — DREAMTALK DID NOT CREATE A VIDEO"
        return result

    shutil.copy2(dreamtalk_output, video_path)
    result["video_url"] = f"/static/generated/{run_id}/response.mp4"
    result["status"] = "VOICE AND TALKING-AVATAR VIDEO READY"
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
