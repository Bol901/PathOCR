# Validation record

Date: 2026-10-08. Windows 11 x64 / Python 3.12.9; WSL2 Ubuntu 24.04.3 x64 / Python 3.12.3 / glibc 2.39. Requested OvisOCR2-Q4_K_S model with mmproj-F16, official llama.cpp b11511. Defaults: Auto acceleration, 999 GPU layers, DPI 160, Flash Attention disabled.

## Verified

- Automated tests cover PDF validation/rendering, streaming inference, progress, saving/download/preview, unique paths, cancellation/resume, interrupted and truncated responses, local access, settings, backend selection, legacy migration, and GPU inference fallback. All 19 tests passed on both Windows and Linux after the English conversion. JavaScript syntax and Python compilation checks passed. Application-owned interface, messages, installer text, and documentation contain no Chinese text; bilingual OCR fixtures remain unchanged.
- Model and projector SHA256 verified (approximately 505 MB and 205 MB).
- Controlled source-app test, RTX 4090, same simple two-page English/Chinese PDF and inference settings: CPU 49.83 s; CUDA 3.53 s; Auto selecting CUDA 3.53 s; Vulkan with CPU vision 41.12 s. Includes startup. Individual observations, not a general performance guarantee.
- CUDA logs confirmed 25/25 model layers offloaded and CLIP using CUDA0. Vulkan compatibility logs confirmed GPU model layers and CPU vision. Vulkan vision produced incorrect output and is disabled for this model.
- English and Chinese headings, body text, and amounts 42/128 recognized. Chinese digits sometimes contain spaces; original model output is preserved.
- Updated English Windows and Linux executables passed real-model upload, frontend delivery, Markdown/PNG/download APIs, automatic saving, and normal shutdown. Both selected CUDA automatically, offloaded 25/25 model layers, and used CUDA vision. End-to-end timings including app startup were Windows 8.52 s and Linux 36.62 s. Linux ran under WSL on a mounted Windows filesystem while archive compression was active; these timings are not a controlled OS comparison.

## Unverified

- Actual macOS builds/runs and Ubuntu 22.04 CI. Supplied Linux build requires glibc 2.39+.
- Browser visual/interaction acceptance: embedded browser blocks localhost and no external automation session is available. HTTP checks do not prove layout, drag/drop, or dialogs.
- Interactive installers, native folder chooser, automatic browser opening. Linux without Tk requires manually entering output paths.
- Large-document stress, complex tables/formulas/handwriting accuracy, other GPUs, Metal, and other Linux distributions.

Reproduce: `python -m unittest discover -s tests -v`, `python scripts/benchmark.py --mode auto`, and `python scripts/smoke_package.py` after building. Test data in .pathocr-* is excluded from source archives.

## GitHub source distribution update

Startup automatically prepares the engine in the background. Tests verify the startup trigger, default model download calls with pinned checksums, and preservation of custom local files; those tests mock network transfers rather than downloading another full model. The default CI package excludes weights. Previously built offline executables predate this startup change.
