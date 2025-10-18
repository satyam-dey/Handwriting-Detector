from flask import Flask, request, render_template, jsonify, send_file
import os
from PIL import Image, ImageOps
import numpy as np
import io

# Config
UPLOAD_DIR = "glyphs"      # stores glyph images named by character, e.g. glyphs/A.png
OUTPUT_DIR = "outputs"
PAGE_WIDTH = 2480  # px ~ A4 at 300dpi
PAGE_HEIGHT = 3508
GLYPH_HEIGHT = 120  # normalized height of glyph images
H_SPACING = 10
V_SPACING = 20
LINE_MARGIN = 80

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)

def normalize_glyph_image(pil_img, target_h=GLYPH_HEIGHT):
    # Convert to grayscale and trim/center, resize preserving aspect ratio
    img = pil_img.convert("L")
    # invert so handwriting black on white becomes black on white (if needed)
    bg = Image.new("L", img.size, 255)
    diff = ImageOps.invert(ImageChops := Image).difference if False else None  # placeholder to avoid lint
    # simple thresholding
    arr = np.array(img)
    thresh = arr.mean() * 0.9
    mask = arr < thresh
    # crop to content
    coords = np.argwhere(mask)
    if coords.size == 0:
        # blank image, return a blank small image
        return Image.new("RGBA", (int(target_h * 0.6), target_h), (255,255,255,0))
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0) + 1
    cropped = img.crop((x0, y0, x1, y1)).convert("L")
    # resize to target height
    w, h = cropped.size
    new_h = target_h
    new_w = int(w * (new_h / h))
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)
    # make RGBA with transparency and place centered in canvas
    canvas = Image.new("RGBA", (new_w + 8, new_h + 8), (255,255,255,0))
    # convert black strokes to black color with alpha
    # create alpha from brightness
    alpha = 255 - np.array(resized)  # darker -> larger alpha
    alpha = (alpha - alpha.min()) / (alpha.ptp() + 1e-6) * 255
    glyph = Image.new("RGBA", resized.size, (0,0,0,0))
    glyph_pixels = glyph.load()
    a = Image.fromarray(alpha.astype('uint8'), mode='L')
    glyph.putalpha(a)
    # fill black color where alpha > 0
    black = Image.new("RGBA", resized.size, (0,0,0,255))
    glyph = Image.composite(black, glyph, a)
    canvas.paste(glyph, (4,4), glyph)
    return canvas

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload_glyph", methods=["POST"])
def upload_glyph():
    # expects fields: char (string) and file (image)
    ch = request.form.get("char", "")
    f = request.files.get("file", None)
    if not ch or not f:
        return jsonify({"ok":False, "error":"char or file missing"}), 400
    # sanitize filename: use unicode codepoint representation
    safe_name = ch
    filename = os.path.join(UPLOAD_DIR, f"{safe_name}.png")
    img = Image.open(f.stream)
    glyph = normalize_glyph_image(img)
    glyph.save(filename)
    return jsonify({"ok": True, "stored": filename})

@app.route("/list_glyphs")
def list_glyphs():
    files = os.listdir(UPLOAD_DIR)
    chars = [os.path.splitext(x)[0] for x in files]
    return jsonify({"chars": chars})

def load_glyph(ch):
    path = os.path.join(UPLOAD_DIR, f"{ch}.png")
    if os.path.exists(path):
        return Image.open(path).convert("RGBA")
    # fallback: blank small image
    return Image.new("RGBA", (GLYPH_HEIGHT//2, GLYPH_HEIGHT), (255,255,255,0))

@app.route("/render_pdf", methods=["POST"])
def render_pdf():
    data = request.json or {}
    text = data.get("text", "")
    font_size = data.get("font_size", GLYPH_HEIGHT)  # glyph height
    # create a white page
    page = Image.new("RGBA", (PAGE_WIDTH, PAGE_HEIGHT), (255,255,255,255))
    x = LINE_MARGIN
    y = LINE_MARGIN
    max_h_in_line = 0
    for ch in text:
        if ch == "\n":
            x = LINE_MARGIN
            y += max_h_in_line + V_SPACING
            max_h_in_line = 0
            continue
        glyph = load_glyph(ch)
        # resize glyph to requested font_size height
        gw, gh = glyph.size
        scale = max(1e-6, font_size / gh)
        new_w = max(1, int(gw * scale))
        new_h = max(1, int(gh * scale))
        glyph_r = glyph.resize((new_w, new_h), Image.LANCZOS)
        if x + new_w + LINE_MARGIN > PAGE_WIDTH:
            # wrap
            x = LINE_MARGIN
            y += max_h_in_line + V_SPACING
            max_h_in_line = 0
        page.paste(glyph_r, (x, y), glyph_r)
        x += new_w + H_SPACING
        max_h_in_line = max(max_h_in_line, new_h)
        # if goes beyond page height, stop (or you could create a multi-page feature)
        if y + max_h_in_line + LINE_MARGIN > PAGE_HEIGHT:
            break
    # save to PDF in memory
    rgba = page.convert("RGB")
    out_path = os.path.join(OUTPUT_DIR, "handwritten_output.pdf")
    rgba.save(out_path, "PDF", resolution=300.0)
    return jsonify({"ok": True, "pdf": f"/download/{os.path.basename(out_path)}"})

@app.route("/download/<filename>")
def download(filename):
    return send_file(os.path.join(OUTPUT_DIR, filename), as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
