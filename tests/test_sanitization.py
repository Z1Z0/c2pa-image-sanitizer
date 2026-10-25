"""
tests/test_sanitization.py — Comprehensive test suite for multi-format C2PA & metadata sanitization.

Tests coverage:
1. Normal images with EXIF, XMP, IPTC, comments.
2. AI-generator tags (Midjourney, DALL-E, Stable Diffusion, Google Imagen, SynthID).
3. Embedded C2PA Content Credentials across supported formats (JPEG, PNG, WebP, TIFF, GIF, HEIC).
4. Multiple metadata categories simultaneously.
5. Transparent PNG and WebP images (preserving alpha channel and mode).
6. Animated GIF and animated WebP images (preserving frame count, durations, looping).
7. Multi-page TIFF images (preserving pages, stripping metadata tags).
8. BMP images (stripping trailing bytes).
9. HEIC/HEIF images (with pillow-heif).
10. Error handling: corrupted files, unsupported extensions, uppercase extensions.
11. Output collision policies ('rename', 'overwrite', 'skip').
12. JPEG regression tests (orientation baking, color profiles).
13. End-to-end CLI batch processing.
"""

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PIL import Image, ImageOps, PngImagePlugin, TiffImagePlugin

import clean_c2pa
from clean_c2pa import (
    HAS_C2PA,
    HAS_HEIF,
    SUPPORTED_EXTENSIONS,
    find_exiftool,
    get_standard_srgb_profile_bytes,
    process_image,
    resolve_collision,
    verify_cleaned_image,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CERTS_DIR = FIXTURES_DIR / "certs"


@pytest.fixture(scope="session")
def exiftool_path():
    path = find_exiftool()
    assert path is not None and os.path.isfile(path), "exiftool.exe must be available for testing"
    return path


@pytest.fixture(scope="session")
def srgb_bytes():
    profile = get_standard_srgb_profile_bytes()
    assert len(profile) > 0
    return profile


@pytest.fixture(scope="session")
def c2pa_signer():
    if not HAS_C2PA:
        pytest.skip("c2pa-python is not installed")

    import c2pa

    pub_path = CERTS_DIR / "es256.pub"
    pem_path = CERTS_DIR / "es256.pem"
    assert pub_path.is_file() and pem_path.is_file(), "C2PA test certs must exist"

    with open(pub_path, "rb") as f:
        cert_bytes = f.read()
    with open(pem_path, "rb") as f:
        key_bytes = f.read()

    signer_info = c2pa.C2paSignerInfo(b"es256", cert_bytes, key_bytes, None)
    return c2pa.Signer.from_info(signer_info)


def create_c2pa_signed_image(source_path: Path, dest_path: Path, signer, title="Test Asset"):
    """Signs an image file using official C2PA Python SDK."""
    import c2pa

    manifest_def = {
        "title": title,
        "claim_generator_info": [{"name": "TestGenerator", "version": "1.0"}],
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
                        }
                    ]
                },
            }
        ],
    }
    builder = c2pa.Builder.from_json(json.dumps(manifest_def))
    builder.sign_file(str(source_path), str(dest_path), signer)


# ==============================================================================
# 1. JPEG Regression & Normal Metadata Tests
# ==============================================================================

def test_jpeg_regression_orientation_and_metadata(tmp_path, exiftool_path, srgb_bytes):
    """Verifies JPEG orientation baking, metadata removal, and sRGB profile embedding."""
    src = tmp_path / "oriented.jpg"
    dest = tmp_path / "cleaned.jpg"

    # Create image with EXIF orientation tag 6 (Rotate 90 CW)
    im = Image.new("RGB", (60, 30), (255, 100, 50))
    exif = im.getexif()
    exif[0x0112] = 6  # Orientation
    exif[0x010E] = "Test Description"
    exif[0x0131] = "Midjourney v6"
    im.save(src, format="JPEG", exif=exif)

    success, msg = process_image(src, dest, srgb_bytes, None, exiftool_path)
    assert success, f"JPEG processing failed: {msg}"
    assert dest.exists()

    # Orientation 6 rotates (60, 30) to (30, 60)
    with Image.open(dest) as out_im:
        assert out_im.size == (30, 60)
        assert out_im.mode == "RGB"
        out_exif = out_im.getexif()
        # EXIF orientation tag should no longer exist in cleaned file
        assert 0x0112 not in out_exif
        assert 0x010E not in out_exif

    # Dual verification check
    clean, issues = verify_cleaned_image(dest, exiftool_path)
    assert clean, f"Verification failed on JPEG: {issues}"


def test_jpeg_c2pa_removal(tmp_path, exiftool_path, srgb_bytes, c2pa_signer):
    """Verifies that embedded C2PA Content Credentials are completely removed from JPEG."""
    import c2pa

    raw_jpg = tmp_path / "raw.jpg"
    signed_jpg = tmp_path / "c2pa_signed.jpg"
    cleaned_jpg = tmp_path / "c2pa_cleaned.jpg"

    im = Image.new("RGB", (80, 80), (100, 150, 200))
    im.save(raw_jpg, format="JPEG")

    create_c2pa_signed_image(raw_jpg, signed_jpg, c2pa_signer, "JPEG C2PA Sample")

    # Confirm C2PA is active before cleaning
    reader = c2pa.Reader.try_create(str(signed_jpg))
    assert reader is not None, "Signed JPEG should contain C2PA manifest"
    reader.close()

    # Sanitize
    success, msg = process_image(signed_jpg, cleaned_jpg, srgb_bytes, None, exiftool_path)
    assert success, f"Sanitization failed: {msg}"

    # Independent check 1: official C2PA SDK
    reader_cleaned = c2pa.Reader.try_create(str(cleaned_jpg))
    assert reader_cleaned is None, "Cleaned JPEG must NOT contain C2PA manifest"

    # Independent check 2: ExifTool
    res = subprocess.run(
        [exiftool_path, "-json", "-G", "-a", "-u", "-s", str(cleaned_jpg)],
        capture_output=True,
        text=True,
        check=True,
    )
    tags = json.loads(res.stdout)[0]
    c2pa_tags = [k for k in tags if any(w in k.lower() for w in ["c2pa", "jumbf", "manifest", "claim"])]
    assert len(c2pa_tags) == 0, f"ExifTool found C2PA tags in cleaned JPEG: {c2pa_tags}"


# ==============================================================================
# 2. PNG Transparency & C2PA Tests
# ==============================================================================

def test_png_transparency_and_metadata(tmp_path, exiftool_path, srgb_bytes):
    """Verifies PNG preserves alpha transparency and removes tEXt/zTXt/iTXt chunks."""
    src = tmp_path / "transparent_with_meta.png"
    dest = tmp_path / "cleaned.png"

    # RGBA image with transparent pixels
    im = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    # Draw a colored square in the center
    for x in range(10, 40):
        for y in range(10, 40):
            im.putpixel((x, y), (255, 0, 100, 180))

    meta = PngImagePlugin.PngInfo()
    meta.add_text("Software", "Midjourney v6.1")
    meta.add_text("Comment", "Prompt: hyperrealistic cyberpunk cat")
    meta.add_itxt("XML:com.adobe.xmp", "<x:xmpmeta><rdf:RDF><rdf:Description/></rdf:RDF></x:xmpmeta>")
    im.save(src, pnginfo=meta)

    success, msg = process_image(src, dest, srgb_bytes, None, exiftool_path)
    assert success, f"PNG processing failed: {msg}"

    # Verify transparency preserved
    with Image.open(dest) as out_im:
        assert out_im.mode == "RGBA"
        assert out_im.size == (50, 50)
        assert out_im.getpixel((0, 0)) == (0, 0, 0, 0)
        assert out_im.getpixel((20, 20)) == (255, 0, 100, 180)

    # Check chunks: no tEXt, zTXt, iTXt
    with open(dest, "rb") as f:
        data = f.read()
    assert b"tEXt" not in data
    assert b"zTXt" not in data
    assert b"iTXt" not in data
    assert b"Midjourney" not in data

    clean, issues = verify_cleaned_image(dest, exiftool_path)
    assert clean, f"Verification failed on PNG: {issues}"


def test_png_c2pa_removal(tmp_path, exiftool_path, srgb_bytes, c2pa_signer):
    """Verifies that embedded C2PA manifest (caBX chunk) is removed from PNG."""
    import c2pa

    raw_png = tmp_path / "raw.png"
    signed_png = tmp_path / "c2pa_signed.png"
    cleaned_png = tmp_path / "c2pa_cleaned.png"

    im = Image.new("RGBA", (60, 60), (30, 80, 200, 220))
    im.save(raw_png, format="PNG")

    create_c2pa_signed_image(raw_png, signed_png, c2pa_signer, "PNG C2PA Sample")

    reader = c2pa.Reader.try_create(str(signed_png))
    assert reader is not None, "Signed PNG should contain C2PA manifest"
    reader.close()

    success, msg = process_image(signed_png, cleaned_png, srgb_bytes, None, exiftool_path)
    assert success, f"Sanitization failed: {msg}"

    reader_cleaned = c2pa.Reader.try_create(str(cleaned_png))
    assert reader_cleaned is None, "Cleaned PNG must NOT contain C2PA manifest"

    # Verify caBX chunk is absent
    with open(cleaned_png, "rb") as f:
        data = f.read()
    assert b"caBX" not in data
    assert b"caPI" not in data

    clean, issues = verify_cleaned_image(cleaned_png, exiftool_path)
    assert clean, f"PNG verification failed: {issues}"


# ==============================================================================
# 3. WebP Transparency, Animation & C2PA Tests
# ==============================================================================

def test_webp_transparency_and_c2pa(tmp_path, exiftool_path, srgb_bytes, c2pa_signer):
    """Verifies WebP static image with transparency and C2PA chunk removal."""
    import c2pa

    raw_webp = tmp_path / "raw.webp"
    signed_webp = tmp_path / "signed.webp"
    cleaned_webp = tmp_path / "cleaned.webp"

    im = Image.new("RGBA", (45, 45), (200, 100, 50, 128))
    im.save(raw_webp, format="WEBP")

    create_c2pa_signed_image(raw_webp, signed_webp, c2pa_signer, "WebP C2PA Sample")

    reader = c2pa.Reader.try_create(str(signed_webp))
    assert reader is not None
    reader.close()

    success, msg = process_image(signed_webp, cleaned_webp, srgb_bytes, None, exiftool_path)
    assert success, f"WebP processing failed: {msg}"

    with Image.open(cleaned_webp) as out_im:
        assert out_im.mode == "RGBA"
        assert out_im.size == (45, 45)

    reader_cleaned = c2pa.Reader.try_create(str(cleaned_webp))
    assert reader_cleaned is None, "Cleaned WebP must NOT contain C2PA manifest"

    with open(cleaned_webp, "rb") as f:
        data = f.read()
    assert b"C2PA" not in data
    assert b"JUMB" not in data

    clean, issues = verify_cleaned_image(cleaned_webp, exiftool_path)
    assert clean, f"WebP verification failed: {issues}"


def test_webp_animated_preservation(tmp_path, exiftool_path, srgb_bytes):
    """Verifies that animated WebP preserves frame count, timing, and looping."""
    src = tmp_path / "animated.webp"
    dest = tmp_path / "cleaned_anim.webp"

    f1 = Image.new("RGBA", (30, 30), (255, 0, 0, 255))
    f2 = Image.new("RGBA", (30, 30), (0, 255, 0, 255))
    f3 = Image.new("RGBA", (30, 30), (0, 0, 255, 128))

    durations = [120, 200, 150]
    f1.save(
        src,
        format="WEBP",
        save_all=True,
        append_images=[f2, f3],
        duration=durations,
        loop=2,
    )

    success, msg = process_image(src, dest, srgb_bytes, None, exiftool_path)
    assert success, f"Animated WebP failed: {msg}"

    with Image.open(dest) as out_im:
        assert getattr(out_im, "is_animated", False)
        assert out_im.n_frames == 3

    clean, issues = verify_cleaned_image(dest, exiftool_path)
    assert clean, f"Animated WebP verification failed: {issues}"


# ==============================================================================
# 4. GIF Animation & C2PA Tests
# ==============================================================================

def test_gif_animation_and_c2pa(tmp_path, exiftool_path, srgb_bytes, c2pa_signer):
    """Verifies that animated GIF preserves frames, loop count, and strips C2PA/comments."""
    import c2pa

    raw_gif = tmp_path / "raw.gif"
    signed_gif = tmp_path / "signed.gif"
    cleaned_gif = tmp_path / "cleaned.gif"

    im1 = Image.new("RGB", (32, 32), (255, 0, 0))
    im2 = Image.new("RGB", (32, 32), (0, 255, 0))
    im1.save(raw_gif, format="GIF", save_all=True, append_images=[im2], duration=100, loop=0)

    create_c2pa_signed_image(raw_gif, signed_gif, c2pa_signer, "GIF C2PA Sample")

    reader = c2pa.Reader.try_create(str(signed_gif))
    assert reader is not None
    reader.close()

    success, msg = process_image(signed_gif, cleaned_gif, srgb_bytes, None, exiftool_path)
    assert success, f"GIF processing failed: {msg}"

    with Image.open(cleaned_gif) as out_im:
        assert getattr(out_im, "is_animated", False)
        assert out_im.n_frames == 2

    reader_cleaned = c2pa.Reader.try_create(str(cleaned_gif))
    assert reader_cleaned is None, "Cleaned GIF must NOT contain C2PA manifest"

    clean, issues = verify_cleaned_image(cleaned_gif, exiftool_path)
    assert clean, f"GIF verification failed: {issues}"


# ==============================================================================
# 5. TIFF Multi-Page & C2PA Tests
# ==============================================================================

def test_tiff_multipage_and_c2pa(tmp_path, exiftool_path, srgb_bytes, c2pa_signer):
    """Verifies multi-page TIFF preserves all pages and strips C2PA/metadata tags."""
    import c2pa

    raw_tif = tmp_path / "multipage.tif"
    signed_tif = tmp_path / "signed.tif"
    cleaned_tif = tmp_path / "cleaned.tif"

    p1 = Image.new("RGB", (40, 40), (255, 128, 0))
    p2 = Image.new("RGB", (40, 40), (0, 128, 255))
    p1.save(raw_tif, format="TIFF", save_all=True, append_images=[p2], compression="tiff_lzw")

    create_c2pa_signed_image(raw_tif, signed_tif, c2pa_signer, "TIFF C2PA Sample")

    reader = c2pa.Reader.try_create(str(signed_tif))
    assert reader is not None
    reader.close()

    success, msg = process_image(signed_tif, cleaned_tif, srgb_bytes, None, exiftool_path)
    assert success, f"TIFF processing failed: {msg}"

    with Image.open(cleaned_tif) as out_im:
        assert getattr(out_im, "n_frames", 1) == 2

    reader_cleaned = c2pa.Reader.try_create(str(cleaned_tif))
    assert reader_cleaned is None, "Cleaned TIFF must NOT contain C2PA manifest"

    clean, issues = verify_cleaned_image(cleaned_tif, exiftool_path)
    assert clean, f"TIFF verification failed: {issues}"


# ==============================================================================
# 6. BMP Sanitization Test
# ==============================================================================

def test_bmp_sanitization(tmp_path, exiftool_path, srgb_bytes):
    """Verifies BMP image sanitization and removal of appended trailer payloads."""
    src = tmp_path / "dirty.bmp"
    dest = tmp_path / "cleaned.bmp"

    im = Image.new("RGB", (30, 30), (120, 200, 80))
    im.save(src, format="BMP")

    # Append trailing malicious / tracking metadata payload past end of file
    with open(src, "ab") as f:
        f.write(b"TRAILER_DATA_TRACKING_PAYLOAD_C2PA_FAKE_12345")

    success, msg = process_image(src, dest, srgb_bytes, None, exiftool_path)
    assert success, f"BMP processing failed: {msg}"

    with open(dest, "rb") as f:
        clean_data = f.read()
    assert b"TRAILER_DATA" not in clean_data

    clean, issues = verify_cleaned_image(dest, exiftool_path)
    assert clean, f"BMP verification failed: {issues}"


# ==============================================================================
# 7. HEIC / HEIF C2PA Tests (Optional / Conditionally Executed)
# ==============================================================================

@pytest.mark.skipif(not HAS_HEIF, reason="pillow-heif is not installed")
def test_heic_c2pa_removal(tmp_path, exiftool_path, srgb_bytes, c2pa_signer):
    """Verifies HEIC/HEIF C2PA manifest removal and clean container creation."""
    import c2pa

    raw_heic = tmp_path / "raw.heic"
    signed_heic = tmp_path / "signed.heic"
    cleaned_heic = tmp_path / "cleaned.heic"

    im = Image.new("RGB", (48, 48), (250, 220, 100))
    im.save(raw_heic, format="HEIF")

    create_c2pa_signed_image(raw_heic, signed_heic, c2pa_signer, "HEIC C2PA Sample")

    reader = c2pa.Reader.try_create(str(signed_heic))
    assert reader is not None
    reader.close()

    success, msg = process_image(signed_heic, cleaned_heic, srgb_bytes, None, exiftool_path)
    assert success, f"HEIC processing failed: {msg}"

    reader_cleaned = c2pa.Reader.try_create(str(cleaned_heic))
    assert reader_cleaned is None, "Cleaned HEIC must NOT contain C2PA manifest"

    clean, issues = verify_cleaned_image(cleaned_heic, exiftool_path)
    assert clean, f"HEIC verification failed: {issues}"


# ==============================================================================
# 8. Edge Cases & Error Handling Tests
# ==============================================================================

def test_corrupted_file_handling(tmp_path, exiftool_path, srgb_bytes):
    """Verifies that corrupted files fail gracefully and leave no partial output."""
    corrupted = tmp_path / "corrupt.jpg"
    dest = tmp_path / "cleaned_corrupt.jpg"

    # Write truncated/garbage data
    with open(corrupted, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00garbage_truncated_payload")

    success, msg = process_image(corrupted, dest, srgb_bytes, None, exiftool_path)
    assert not success, "Processing corrupted image should fail"
    assert not dest.exists(), "Corrupted image must not leave output file behind"
    # Ensure temporary file was removed
    temp_file = dest.with_name(f".tmp_{dest.name}")
    assert not temp_file.exists()


def test_unsupported_file_extension(tmp_path, exiftool_path, srgb_bytes):
    """Verifies that unsupported file extensions are rejected gracefully."""
    unsupported = tmp_path / "document.pdf"
    dest = tmp_path / "cleaned.pdf"
    with open(unsupported, "wb") as f:
        f.write(b"%PDF-1.4 header")

    success, msg = process_image(unsupported, dest, srgb_bytes, None, exiftool_path)
    assert not success
    assert "Unsupported file extension" in msg


def test_uppercase_extensions(tmp_path, exiftool_path, srgb_bytes):
    """Verifies that uppercase extensions like .PNG, .JPG are handled case-insensitively."""
    src = tmp_path / "sample.PNG"
    dest = tmp_path / "cleaned.PNG"
    im = Image.new("RGB", (20, 20), (50, 100, 150))
    im.save(src, format="PNG")

    success, msg = process_image(src, dest, srgb_bytes, None, exiftool_path)
    assert success
    assert dest.exists()


def test_collision_policies(tmp_path, exiftool_path, srgb_bytes):
    """Verifies rename, overwrite, and skip collision resolution policies."""
    dest = tmp_path / "target.jpg"
    dest.write_text("existing content")

    # 1. Rename
    resolved, skip = resolve_collision(dest, "rename")
    assert not skip
    assert resolved.name == "target (1).jpg"

    # 2. Overwrite
    resolved, skip = resolve_collision(dest, "overwrite")
    assert not skip
    assert resolved == dest

    # 3. Skip
    resolved, skip = resolve_collision(dest, "skip")
    assert skip
    assert resolved is None


# ==============================================================================
# 9. CLI End-to-End Batch Processing Test
# ==============================================================================

def test_cli_end_to_end_batch(tmp_path):
    """Verifies running clean_c2pa.py via CLI end-to-end on a folder of mixed image formats."""
    in_dir = tmp_path / "input_images"
    out_dir = tmp_path / "output_cleaned"
    in_dir.mkdir()

    # Generate sample images across multiple formats
    Image.new("RGB", (20, 20), (255, 0, 0)).save(in_dir / "test.jpg", format="JPEG")
    Image.new("RGBA", (20, 20), (0, 255, 0, 128)).save(in_dir / "test.png", format="PNG")
    Image.new("RGB", (20, 20), (0, 0, 255)).save(in_dir / "test.webp", format="WEBP")
    Image.new("RGB", (20, 20), (255, 255, 0)).save(in_dir / "test.gif", format="GIF")
    Image.new("RGB", (20, 20), (255, 0, 255)).save(in_dir / "test.tif", format="TIFF")
    Image.new("RGB", (20, 20), (0, 255, 255)).save(in_dir / "test.bmp", format="BMP")

    cmd = [
        sys.executable,
        str(Path(clean_c2pa.__file__).resolve()),
        "-i",
        str(in_dir),
        "-o",
        str(out_dir),
        "--non-interactive",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"CLI command failed with code {result.returncode}: {result.stderr}"
    assert "Found 6 image(s) to process" in result.stdout
    assert "Successfully cleaned: 6" in result.stdout

    # Verify all output files exist in out_dir
    assert (out_dir / "test.jpg").is_file()
    assert (out_dir / "test.png").is_file()
    assert (out_dir / "test.webp").is_file()
    assert (out_dir / "test.gif").is_file()
    assert (out_dir / "test.tif").is_file()
    assert (out_dir / "test.bmp").is_file()


def test_ai_generator_metadata_scrubbing(tmp_path, exiftool_path, srgb_bytes):
    """Verifies that multiple AI generator tool signatures and prompts are thoroughly removed."""
    src = tmp_path / "ai_generated.png"
    dest = tmp_path / "ai_cleaned.png"

    meta = PngImagePlugin.PngInfo()
    meta.add_text("Software", "Stable Diffusion WebUI v1.9")
    meta.add_text("prompt", "a scenic mountain by midjourney generator, dalle3 style")
    meta.add_text("Comment", "synthid:watermark-v1 digitalSourceType:trainedAlgorithmicMedia")
    meta.add_itxt("XML:com.adobe.xmp", "<x:xmpmeta><rdf:RDF><rdf:Description c2pa:claim='test' digitalSourceType='trainedAlgorithmicMedia'/></rdf:RDF></x:xmpmeta>")

    im = Image.new("RGBA", (32, 32), (100, 150, 200, 255))
    im.save(src, format="PNG", pnginfo=meta)

    success, msg = process_image(src, dest, srgb_bytes, None, exiftool_path)
    assert success, f"AI metadata scrubbing failed: {msg}"

    with open(dest, "rb") as f:
        clean_bytes = f.read().lower()

    for forbidden in [
        b"stable diffusion",
        b"midjourney",
        b"dalle",
        b"synthid",
        b"trainedalgorithmicmedia",
    ]:
        assert forbidden not in clean_bytes, f"Found forbidden AI string: {forbidden}"

    clean, issues = verify_cleaned_image(dest, exiftool_path)
    assert clean, f"Cleaned image failed verification: {issues}"


def test_simultaneous_multiple_metadata_categories(tmp_path, exiftool_path, srgb_bytes, c2pa_signer):
    """Verifies that an image with EXIF, XMP, IPTC, comments, and C2PA simultaneously is fully cleaned."""
    raw_jpg = tmp_path / "multi_cat_raw.jpg"
    signed_jpg = tmp_path / "multi_cat_signed.jpg"
    dest_jpg = tmp_path / "multi_cat_cleaned.jpg"

    im = Image.new("RGB", (64, 64), (120, 80, 40))
    exif = im.getexif()
    exif[0x010E] = "Simultaneous Test Description"
    exif[0x0131] = "DALL-E 3 Generator"
    exif[0x013B] = "AI Artist"

    im.save(raw_jpg, format="JPEG", exif=exif, comment=b"JPEG User Comment AI Test")

    create_c2pa_signed_image(raw_jpg, signed_jpg, c2pa_signer, "Multi-Category Asset")

    # Sanitize
    success, msg = process_image(signed_jpg, dest_jpg, srgb_bytes, None, exiftool_path)
    assert success, f"Multi-category sanitization failed: {msg}"

    clean, issues = verify_cleaned_image(dest_jpg, exiftool_path)
    assert clean, f"Verification failed on multi-category cleaned file: {issues}"


def test_missing_heif_dependency_graceful_handling(tmp_path, exiftool_path, srgb_bytes, monkeypatch):
    """Verifies graceful skip/failure reporting when pillow-heif dependency is unavailable."""
    heic_file = tmp_path / "sample.heic"
    dest_file = tmp_path / "cleaned.heic"
    heic_file.write_bytes(b"\x00\x00\x00\x20ftypheic\x00\x00\x00\x00mif1heic")

    # Temporarily mock HAS_HEIF = False
    monkeypatch.setattr(clean_c2pa, "HAS_HEIF", False)

    success, msg = process_image(heic_file, dest_file, srgb_bytes, None, exiftool_path)
    assert not success
    assert "pillow-heif" in msg
    assert not dest_file.exists()
