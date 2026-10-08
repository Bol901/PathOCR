# Third party components

PathOCR uses llama.cpp (MIT), OvisOCR2 GGUF and its projector (Apache-2.0), FastAPI (MIT), Uvicorn (BSD-3-Clause), HTTPX (BSD-3-Clause), python-multipart (Apache-2.0), Marked (MIT), and DOMPurify (Apache-2.0 or MPL-2.0). Browser library licenses are bundled beside their files. llama.cpp LICENSE and the model license are included when bundling those assets. See the installed Python package metadata for their license notices.

**PyMuPDF is distributed under AGPL-3.0 or a commercial license.** This project is distributed under AGPL-3.0 to match the open-source dependency. Anyone distributing a modified application must satisfy applicable AGPL source disclosure obligations, or obtain an appropriate commercial license and review all dependency terms. This is not a proprietary distribution template.

Upstream sources:
- https://github.com/ggml-org/llama.cpp
- https://huggingface.co/Abiray/OvisOCR2-GGUF
- https://github.com/pymupdf/PyMuPDF
- https://github.com/markedjs/marked
- https://github.com/cure53/DOMPurify

GPU-enabled Windows/Linux packages also include the CUDA redistributables provided with the pinned official llama.cpp release. CUDA libraries remain subject to NVIDIA's applicable redistribution license; notices and licenses shipped in those runtime archives are retained under vendor/runtime/cuda. GPU drivers are not distributed or installed by PathOCR. Vulkan uses the system's existing Vulkan driver.
