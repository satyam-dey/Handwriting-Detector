from flask import Flask, request, render_template, jsonify, send_file
import os
from PIL import Image, ImageOps
import numpy as np
import io
import cv2

# MODIFICATION: Use the /tmp directory, which is writable on Vercel
UPLOAD_DIR = "/tmp/glyphs"
PAGE_WIDTH = 2480  # px ~ A4 at 300dpi
PAGE_HEIGHT = 3508
GLYPH_HEIGHT = 120  # normalized height of glyph images
H_SPACING = 10
V_SPACING = 20
LINE_MARGIN = 80

# MODIFICATION: Create the temporary directory
os.makedirs(UPLOAD_DIR, exist_ok=True)

# MODIFICATION: Point Flask to the correct template folder location
app = Flask(__name__, template_folder='../templates')

def normalize_glyph_image(pil_img, target_h=GLYPH_HEIGHT):
    img = pil_img.convert("L")
    arr = np.array(img)
    thresh = arr.mean() * 0.9
    mask = arr < thresh
    coords = np.argwhere(mask)
    if coords.size == 0:
        return Image.new("RGBA", (int(target_h * 0.6), target_h), (255,255,255,0))
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0) + 1
    cropped = img.crop((x0, y0, x1, y1)).convert("L")
    w, h = cropped.size
    new_h = target_h
    new_w = int(w * (new_h / h))
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (new_w + 8, new_h + 8), (255,255,255,0))
    alpha = 255 - np.array(resized)
    alpha = (alpha - alpha.min()) / (alpha.ptp() + 1e-6) * 255
    glyph = Image.new("RGBA", resized.size, (0,0,0,0))
    a = Image.fromarray(alpha.astype('uint8'), mode='L')
    glyph.putalpha(a)
    black = Image.new("RGBA", resized.size, (0,0,0,255))
    glyph = Image.composite(black, glyph, a)
    canvas.paste(glyph, (4,4), glyph)
    return canvas

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload_glyph", methods=["POST"])
def upload_glyph():
    ch = request.form.get("char", "")
    f = request.files.get("file", None)
    if not ch or not f:
        return jsonify({"ok":False, "error":"char or file missing"}), 400
    safe_name = ch
    # MODIFICATION: Path points to the temporary directory
    filename = os.path.join(UPLOAD_DIR, f"{safe_name}.png")
    img = Image.open(f.stream)
    glyph = normalize_glyph_image(img)
    glyph.save(filename)
    return jsonify({"ok": True, "stored": f"Temporarily stored: {filename}"})

@app.route("/list_glyphs")
def list_glyphs():
    if not os.path.exists(UPLOAD_DIR):
        return jsonify({"chars": []})
    files = os.listdir(UPLOAD_DIR)
    chars = [os.path.splitext(x)[0] for x in files]
    return jsonify({"chars": chars})

def load_glyph(ch):
    path = os.path.join(UPLOAD_DIR, f"{ch}.png")
    if os.path.exists(path):
        return Image.open(path).convert("RGBA")
    return Image.new("RGBA", (GLYPH_HEIGHT//2, GLYPH_HEIGHT), (255,255,255,0))

@app.route("/render_pdf", methods=["POST"])
def render_pdf():
    data = request.json or {}
    text = data.get("text", "")
    font_size = data.get("font_size", GLYPH_HEIGHT)
    
    page = Image.new("RGBA", (PAGE_WIDTH, PAGE_HEIGHT), (255,255,255,255))
    x, y, max_h_in_line = LINE_MARGIN, LINE_MARGIN, 0

    for ch in text:
        if ch == "\n":
            x = LINE_MARGIN
            y += max_h_in_line + V_SPACING
            max_h_in_line = 0
            continue
        
        glyph = load_glyph(ch)
        gw, gh = glyph.size
        scale = font_size / gh if gh > 0 else 0
        new_w, new_h = max(1, int(gw * scale)), max(1, int(gh * scale))
        glyph_r = glyph.resize((new_w, new_h), Image.LANCZOS)

        if x + new_w + LINE_MARGIN > PAGE_WIDTH:
            x = LINE_MARGIN
            y += max_h_in_line + V_SPACING
            max_h_in_line = 0
        
        page.paste(glyph_r, (x, y), glyph_r)
        x += new_w + H_SPACING
        max_h_in_line = max(max_h_in_line, new_h)
        
        if y + max_h_in_line + LINE_MARGIN > PAGE_HEIGHT:
            break

    # --- MAJOR MODIFICATION: SAVE PDF TO MEMORY AND SEND DIRECTLY ---
    pdf_buffer = io.BytesIO()
    page.convert("RGB").save(pdf_buffer, "PDF", resolution=300.0)
    pdf_buffer.seek(0) # Rewind the buffer to the beginning

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name="handwritten_output.pdf",
        mimetype="application/pdf"
    )

# The /download route is no longer needed and has been removed.