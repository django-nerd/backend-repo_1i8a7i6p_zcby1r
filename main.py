import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import io
import base64
from datetime import datetime

# Pillow for simple server-side image generation
from PIL import Image, ImageDraw, ImageFont, ImageFilter

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=2, max_length=280)
    width: int = Field(768, ge=256, le=1024)
    height: int = Field(768, ge=256, le=1024)
    seed: Optional[int] = None


class GenerateResponse(BaseModel):
    image_base64: str
    mime_type: str = "image/png"
    width: int
    height: int
    prompt: str
    seed: int
    generated_at: str


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response


def _get_font(size: int):
    """Attempt to get a decent font; fallback to default."""
    try:
        # Try common fonts available in many environments
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("arial.ttf", size)
        except Exception:
            return ImageFont.load_default()


def _generate_placeholder_image(prompt: str, width: int, height: int, seed: Optional[int] = None) -> Image.Image:
    import random
    rnd = random.Random(seed)

    # Create gradient background
    img = Image.new("RGB", (width, height), (10, 12, 26))
    draw = ImageDraw.Draw(img)

    # Soft radial lights
    for i in range(3):
        cx = rnd.randint(0, width)
        cy = rnd.randint(0, height)
        radius = rnd.randint(int(min(width, height) * 0.3), int(min(width, height) * 0.6))
        color = (rnd.randint(80, 180), rnd.randint(80, 180), 255)
        radial = Image.new("L", (radius * 2, radius * 2), 0)
        radial_draw = ImageDraw.Draw(radial)
        for r in range(radius, 0, -2):
            a = int(255 * (r / radius) ** 2)
            radial_draw.ellipse((radius - r, radius - r, radius + r, radius + r), fill=a)
        glow = Image.new("RGBA", (radius * 2, radius * 2), (*color, 0))
        glow.putalpha(radial)
        img.paste(glow, (cx - radius, cy - radius), glow)

    # Foreground glass card
    card_margin = int(min(width, height) * 0.08)
    card_box = (card_margin, card_margin, width - card_margin, height - card_margin)
    card = Image.new("RGBA", (card_box[2] - card_box[0], card_box[3] - card_box[1]), (20, 24, 48, 180))
    card = card.filter(ImageFilter.GaussianBlur(0.5))
    img.paste(card, (card_box[0], card_box[1]), card)

    # Render prompt text
    font_size = max(18, int(min(width, height) * 0.04))
    font = _get_font(font_size)

    # Wrap text roughly
    def wrap_text(text, max_chars):
        words = text.split()
        lines = []
        line = []
        for w in words:
            if sum(len(x) for x in line) + len(line) + len(w) > max_chars:
                lines.append(" ".join(line))
                line = [w]
            else:
                line.append(w)
        if line:
            lines.append(" ".join(line))
        return lines[:6]

    lines = wrap_text(prompt, max_chars=32)
    text = "\n".join(lines)

    text_draw = ImageDraw.Draw(img)
    tw, th = text_draw.multiline_textsize(text, font=font, spacing=8)
    tx = (width - tw) // 2
    ty = (height - th) // 2

    # Shadow
    text_draw.multiline_text((tx+2, ty+2), text, font=font, fill=(0, 0, 0, 255), spacing=8, align="center")
    # Text
    text_draw.multiline_text((tx, ty), text, font=font, fill=(230, 240, 255, 255), spacing=8, align="center")

    return img


@app.post("/api/generate", response_model=GenerateResponse)
def generate_image(req: GenerateRequest):
    try:
        seed = req.seed if req.seed is not None else int.from_bytes(os.urandom(4), 'big')
        img = _generate_placeholder_image(req.prompt, req.width, req.height, seed=seed)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return GenerateResponse(
            image_base64=b64,
            width=req.width,
            height=req.height,
            prompt=req.prompt,
            seed=seed,
            generated_at=datetime.utcnow().isoformat() + "Z",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
