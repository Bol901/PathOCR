# PathOCR

A local, cross-platform PDF-to-Markdown workspace powered by llama.cpp and OvisOCR2-Q4_K_S.gguf with mmproj-F16.gguf. The English web interface supports batch drag and drop, page progress, Markdown/source/PDF previews, automatic saving, cancellation, and resuming unfinished tasks. OCR preserves the original document language.

## Installation

- Windows x64: Extract the offline ZIP, double-click Install.cmd, and use the desktop shortcut. You can also run PathOCR.exe directly. No administrator access is required.
- Linux x64: Extract the ZIP and run `sh install.sh`. Launch from the application menu. The supplied build requires glibc 2.39+, such as Ubuntu 24.04.
- macOS: Build the matching architecture package, open its DMG, and drag PathOCR to Applications. Unsigned builds may require approval in Privacy & Security. Mac builds have not been validated here.

The system browser opens automatically. On startup, PathOCR automatically downloads missing models and runtimes in the background, shows progress, and starts the engine. Verified model files are cached for subsequent launches. If a download fails, use the engine button to retry. Offline packages use their bundled models. Downloads contact GitHub and Hugging Face; document processing stays on your computer. Click Quit app to stop the background service.

Default output: ~/Documents/PathOCR. Preferences accepts any writable absolute folder path. Each document is automatically saved as `<original-name>-<task-id>.md`, UTF-8, with unique names to prevent overwriting. Page boundaries use HTML comments. HTML tables and LaTeX source are preserved; formulas currently display as LaTeX source.

Files are uploaded and processed sequentially. One page is rendered at a time, with maximum dimension 2400 pixels. Each PDF may be up to 2 GB. Decrypt protected files before uploading. A page reaching the output token limit reports an error instead of marking truncated output successful.

Cancel preserves completed pages; Resume skips those pages. Interrupted tasks can be resumed after reopening. Settings affect new uploads; existing tasks retain their parameters and output location. Original PDFs, page checkpoints, and history stay in application data until manually removed.

## GPU acceleration

Default: Auto mode and 999 GPU layers (all). Windows/Linux x64 packages include CUDA dependencies, Vulkan, and CPU runtimes. Auto prefers usable CUDA, then Vulkan, then CPU. macOS uses Metal with CPU fallback. Windows/Linux ARM64 defaults include Vulkan and CPU. Software renderers are excluded; discrete GPUs are preferred. Startup logs must confirm actual GPU offloading, and the interface shows the active backend/device.

CUDA (Windows 12.4 / Linux 12.8) and Metal accelerate model and vision encoding. Vulkan accelerates the text model while using CPU vision for compatibility: this model produced incorrect OCR with Vulkan vision enabled in testing. Flash Attention stays disabled. Vulkan provides less acceleration for this workload.

GPU startup failure tries the next backend. GPU memory exhaustion, device loss, or inference transport failure triggers CPU fallback and retries the current page, retaining completed pages. Status/logs expose the reason. Input errors and token limits do not trigger fallback. Preferences can force a backend or CPU; zero GPU layers forces CPU. Legacy default CPU settings migrate to Auto; custom engines and explicitly saved CPU mode are preserved.

A compatible graphics driver is required. PathOCR bundles runtime dependencies without installing CUDA Toolkit or modifying drivers. Downloads use pinned official llama.cpp b11511 assets with SHA256 verification. Model downloads support resuming and checksum verification. Advanced preferences accept existing engine, model, and projector paths.

On RTX 4090, the same simple two-page bilingual PDF took 49.83 seconds on CPU and 3.53 seconds on CUDA, including startup (about 14.1 times faster). These observations are not a guarantee for other documents or hardware. See VALIDATION.md.

## Development

Python 3.12 is required. Windows: start.cmd. macOS/Linux: `sh start.sh`. These create an environment, install dependencies, fetch frontend libraries, and start the app. For manual use, create/activate a virtual environment, install requirements.txt, run `python scripts/fetch_assets.py`, then `python run.py`.

`python run.py --no-browser --port 8765 --home .pathocr` selects port and data folder. Open the console's session-token URL. The service binds to 127.0.0.1 and checks Host, Origin, and cookies; it is intended for local use.

Data locations: Windows %LOCALAPPDATA%/PathOCR; macOS ~/Library/Application Support/PathOCR; Linux XDG_DATA_HOME/pathocr or ~/.local/share/pathocr. PATHOCR_HOME overrides the location. Inspect llama-server.log there for engine errors.

## Build and distribution

Install requirements.txt and pyinstaller==6.21.0, then run `python scripts/build.py` on each target OS/architecture. The default distribution excludes model weights and downloads them automatically on first launch. Model files, runtime downloads, local data, and build outputs are excluded from Git. Use --offline only for a separate fully offline distribution. Outputs in dist include self-contained ZIPs and, on macOS, a DMG. Packages include corresponding PathOCR-source.zip and third-party licenses.

GitHub Actions targets Windows x64, Ubuntu 22.04 x64, and both Mac architectures; that workflow has not run here. It does not publish releases or sign/notarize binaries. Run `python -m unittest discover -s tests -v` for automated checks.

## License

AGPL-3.0; see LICENSE. PyMuPDF is included. Preserve corresponding source and licenses when distributing. See THIRD_PARTY_NOTICES.md.
