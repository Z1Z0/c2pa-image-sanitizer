# C2PA Image Sanitizer — Multi-Format Provenance & Generative AI Metadata Removal Tool

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#cross-platform-support)
[![Verification](https://img.shields.io/badge/verification-3--Tier%20Independent-orange.svg)](#multi-tier-verification-architecture)

A high-assurance, production-grade image sanitization utility engineered to systematically strip embedded provenance tracking, **C2PA Content Credentials** manifests, **JUMBF containers**, and **Generative AI metadata signatures** (including **ChatGPT**, **Nano Banana**, **Midjourney**, **Stable Diffusion**, **DALL-E**, **Adobe Firefly**, and **Google SynthID**).

The engine operates via **pure raster reconstruction**: decoding raw pixel arrays into memory, baking physical raster orientations, standardizing wide-gamut color profiles to IEC 61966-2.1 sRGB, and re-encoding sterile target containers from scratch. It guarantees visual parity, transparency preservation, animation retention, and atomic file safety without altering original media.

---

## Architecture & Sanitization Pipeline

Rather than attempting to black-list individual metadata chunks (which risks missing vendor-proprietary or obfuscated tags), the tool employs a **zero-trust synthetic container reconstruction pipeline**:

```
[ Input Image ]
       │
       ▼
[ 1. Ingestion & Validation ] ──► Strict format detection & corrupted byte checks
       │
       ▼
[ 2. Geometry & Raster Extraction ]
       ├─ EXIF Orientation Baked directly into pixel raster
       ├─ Transparency (Alpha channel) isolated & preserved (RGBA / LA / Palette)
       └─ Multi-Frame / Multi-Page extracted (WebP / GIF animations, TIFF layers)
       │
       ▼
[ 3. Color Management & Normalization ]
       ├─ Inspect source ICC / color profile
       ├─ Transform wide-gamut (Display P3, Adobe RGB) to sRGB
       └─ Inject self-contained, standard sRGB IEC 61966-2.1 ICC profile
       │
       ▼
[ 4. Sterile Container Synthesis ] ──► Encodes virgin container directly from raw bytes
       │
       ▼
[ 5. 3-Tier Multi-Engine Verification ]
       ├─ Tier 1: Low-level byte parser (checks APP markers, PNG chunks, RIFF, ISOBMFF)
       ├─ Tier 2: Official C2PA Python SDK (`c2pa.Reader` verification)
       └─ Tier 3: External ExifTool deep metadata audit (if installed)
       │
       ▼
[ 6. Atomic File Commit ] ──► Atomic replace (`.tmp_<file>` -> destination)
```

---

## Supported Formats & Capabilities

| Format | Extensions | Alpha / Transparency | Animation / Multi-Page | Sanitization Mechanism |
|---|---|:---:|:---:|---|
| **JPEG** | `.jpg`, `.jpeg` | Normalized to RGB | Single frame | Fresh baseline container (Q95, 4:4:4 chroma subsampling, optimized), orientation baked, APP markers purged |
| **PNG** | `.png` | Preserved (`RGBA`, `LA`) | Single frame | Lossless re-encoding; purges `caBX`, `caPI`, `eXIf`, `tEXt`, `zTXt`, `iTXt` |
| **WebP** | `.webp` | Preserved (`RGBA`) | Preserved (all frames, timing, loop count) | Strips `C2PA`, `JUMB`, `EXIF`, `XMP ` chunks |
| **TIFF** | `.tif`, `.tiff` | Preserved (`RGBA`, `LA`) | Preserved (multi-page layers retained) | Lossless LZW re-encoding; IFD metadata tags stripped (EXIF, XMP, IPTC, JUMBF) |
| **GIF** | `.gif` | Preserved (palette alpha) | Preserved (all frames, durations, loop count) | Purges comment blocks (`0xFE`) and non-Netscape application extensions (`0xFF`) |
| **BMP** | `.bmp` | Preserved (`RGBA`) | Single frame | Clean BMP header & DIB raster; removes trailing payloads |
| **HEIC / HEIF** | `.heic`, `.heif` | Preserved (`RGBA`) | Single frame | Clean ISOBMFF container via `pillow-heif`; strips `jumb`, `Exif`, `mime` items |

*File extensions are detected case-insensitively (`.JPG`, `.PNG`, etc.).*

---

## Provenance & AI Signatures Scrubbed

### 1. C2PA & Provenance Standards
* **C2PA Manifests & Claims:** Purges embedded Content Credentials, JUMBF boxes (ISO 19566-5), assertion stores, digital signatures, and claim generators.
* **APP Segments & Chunks:** Strips JPEG `APP1` (EXIF/XMP), `APP11` (JUMBF/C2PA), `APP13` (Photoshop IRB / IPTC), and PNG `caBX` / `caPI` chunks.
* **Tracking Containers:** Strips WebP `C2PA` / `JUMB` chunks, TIFF tag 700 / 51107 / 51108, and ISOBMFF `jumb` UUID boxes (`d8fec3d6-1b0e-483c-9297-5828877aae48`).

### 2. Generative AI Tracking & Prompt Watermarks
* **ChatGPT & OpenAI DALL-E:** Eliminates embedded generation prompts, synthetic media descriptors, and C2PA origin credentials injected into generated exports.
* **Nano Banana:** Scrubs embedded model identifiers, custom generator tags, and provenance tracking metadata.
* **Stable Diffusion, ComfyUI & Automatic1111:** Completely removes raw generation parameters, positive/negative prompts, seed, sampler settings, CFG scale, model hashes, and embedded workflow JSON stored in PNG `tEXt` / `iTXt` chunks.
* **Midjourney:** Purges generation parameters, job IDs, full prompt text, and seed values.
* **Adobe Firefly:** Strips embedded provenance manifests, Content Authenticity Initiative assertions, and digital source type tracking.
* **Google SynthID & Imagen:** Removes synthetic source markers, digital source tags (`c2pa.digital_source_type`), and generative metadata flags.

---

## Project Structure

```
c2pa-image-sanitizer/
├── clean_c2pa.py              # Core application & multi-tier verification engine
├── requirements.txt           # Production Python dependencies
├── README.md                  # System documentation & technical specifications
└── tests/                     # Automated regression test suite
    ├── test_sanitization.py   # Format-by-format unit & integration test coverage
    └── fixtures/
        └── certs/             # Test-only ES256 mock certs for C2PA verification tests
            ├── es256.pem      # Non-sensitive mock private key for test runner
            └── es256.pub      # Non-sensitive mock public cert for test runner
```

---

## Installation & Setup

### 1. Prerequisites
Python 3.8 or newer is required. Check your runtime:
```bash
python --version
```

### 2. Install Dependencies

Clone this repository and install the production dependencies:

```bash
pip install -r requirements.txt
```

#### Optional Acceleration & Verification Modules:
* **`pillow-heif`** *(Recommended)*: Adds support for Apple HEIC and HEIF image sanitization:
  ```bash
  pip install pillow-heif
  ```
* **`c2pa-python`** *(Recommended)*: Enables official Adobe/Coalition for Content Provenance verification:
  ```bash
  pip install c2pa-python
  ```
* **`pytest`** *(For developers running tests)*:
  ```bash
  pip install pytest
  ```

### 3. ExifTool Integration (Optional Tier-3 Verification)

The tool includes a standalone native byte-inspection engine and requires **no external binaries** to run. However, for redundant third-tier verification, ExifTool can be installed:

* **Windows:**
  ```powershell
  winget install OliverBetz.ExifTool
  ```
  *Or download from [exiftool.org](https://exiftool.org/) and place `exiftool.exe` on your system `PATH`.*
* **macOS:**
  ```bash
  brew install exiftool
  ```
* **Linux (Debian/Ubuntu):**
  ```bash
  sudo apt-get install libimage-exiftool-perl
  ```

---

## Usage Guide

### 1. Interactive Mode (Default)

Running without arguments automatically initializes the interactive workflow:

```bash
python clean_c2pa.py
```

* **GUI Folder Picker:** Opens a native directory selection dialog.
* **Console Fallback:** If running in a headless environment, prompts for interactive console input or folder drag-and-drop.
* **Safe Default Destination:** Suggests `<input_folder>/C2PA Cleaned` (press `Enter` to confirm).

### 2. Command-Line Interface (CLI Mode)

Designed for headless servers, scripts, and CI/CD pipelines:

```bash
# Basic batch execution
python clean_c2pa.py -i "/path/to/source_images"

# Custom destination and quality
python clean_c2pa.py -i "./inputs" -o "./outputs" -q 95

# Headless execution with collision handling
python clean_c2pa.py -i "./inputs" -o "./outputs" --collision overwrite --non-interactive

# Specify custom ExifTool binary
python clean_c2pa.py -i "./inputs" --exiftool "/usr/local/bin/exiftool"
```

#### CLI Flag Reference:

| Flag | Type | Default | Description |
|---|---|---|---|
| `-i`, `--input` | `str` | *Interactive Prompt* | Path to input directory containing images. |
| `-o`, `--output` | `str` | `<input>/C2PA Cleaned` | Destination directory for sanitized images. |
| `-q`, `--quality` | `int` | `95` | Compression quality for lossy formats (`JPEG`, `WebP`, `HEIC`) (1–100). |
| `--collision` | `choice` | `rename` | Policy when target file exists: `rename`, `overwrite`, or `skip`. |
| `--exiftool` | `str` | *Auto-detected* | Explicit file path to `exiftool` executable. |
| `--non-interactive`| `flag` | `False` | Disables GUI file dialogs and interactive console prompts. |

---

## Multi-Tier Verification Architecture

Every sanitized image must clear an independent multi-tier verification gauntlet before it is written to the destination. If any tier detects lingering provenance markers or structural corruption, the file is rejected and immediately removed:

1. **Tier 1 — Native Binary & Structural Inspection (Built-in):**
   * Low-level segment parser directly verifies format-specific byte streams.
   * Scans JPEG APP markers, PNG chunk names (`caBX`, `caPI`, `eXIf`), WebP RIFF headers, TIFF IFD tags, and ISOBMFF boxes.
   * Scans binary payloads for prohibited C2PA UUID signatures (`d8fec3d6-1b0e-483c-9297-5828877aae48`).
2. **Tier 2 — Official C2PA Reference Parser (Optional):**
   * Invokes `c2pa.Reader.try_create()` using the official Rust-backed `c2pa-python` engine.
   * Verifies that the official industry validator detects zero manifests, claims, or assertion stores.
3. **Tier 3 — ExifTool Deep Metadata Audit (Optional):**
   * Spawns an automated `exiftool -json -G -u` inspection pass.
   * Validates that all metadata groups (EXIF, XMP, IPTC, Photoshop IRB, Generative AI tags) are empty, allowing only mandatory layout/geometry fields.

---

## Engineering Guarantees & Edge Cases

* **Non-Destructive Guarantee:** Source images are opened exclusively in read-only mode and are never modified, renamed, or deleted. The tool explicitly blocks setting the destination directory identical to the source directory.
* **Atomic File Writes:** Output images are initially written to hidden temporary files (`.tmp_<filename>`). Only after completing full verification without error are they atomically moved into place.
* **Self-Contained Color Management:** Wide-gamut color spaces (e.g., Apple Display P3, Adobe RGB) are converted to standard sRGB. The tool embeds an internal, base64-encoded IEC 61966-2.1 sRGB ICC profile, avoiding external `.icc` disk dependencies.
* **Top-Level Directory Scope:** By default, directory scanning is flat (non-recursive) to ensure precise operational boundaries and prevent unintended processing of nested subdirectories.
* **Exit Codes:**
  * `0`: Batch finished successfully (all files processed, skipped, or handled according to policy).
  * `1`: Fatal configuration error (e.g., source directory does not exist, or input matches output directory).

---

## Running the Automated Test Suite

The test suite validates end-to-end sanitization across all 7 supported formats, verifying alpha preservation, animation timing, orientation baking, collision policies, and C2PA strip verification:

```bash
# Run all tests with verbose logging
pytest -v tests/test_sanitization.py
```

> [!NOTE]
> The test suite includes mock cryptographic certificates in `tests/fixtures/certs/` to dynamically sign test images with legitimate C2PA manifests before verifying that the engine completely strips them.

---

## License

This project is licensed under the [MIT License](LICENSE). Third-party dependencies and libraries remain under their respective licenses.
