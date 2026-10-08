import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock

from pathocr.runtime import Runtime,parse_devices,runtime_assets
from pathocr.storage import Store


class AccelerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.home=Path(self.tmp.name)
        self.store=Store(self.home)
        exe='llama-server.exe' if os.name=='nt' else 'llama-server'
        for backend in ('cuda','vulkan','cpu'):
            p=self.home/'runtime'/backend/exe
            p.parent.mkdir(parents=True)
            p.write_bytes(b'test executable')
        for name in ('OvisOCR2-Q4_K_S.gguf','mmproj-F16.gguf'):
            p=self.home/'models'/name
            p.parent.mkdir(exist_ok=True)
            p.write_bytes(b'test model')
        self.runtime=Runtime(self.store)
        self.platform=patch('pathocr.runtime.platform.system',return_value='Windows' if os.name=='nt' else 'Linux')
        self.platform.start()

    def tearDown(self):
        self.platform.stop()
        self.runtime.stop()
        self.store.db.close()
        self.tmp.cleanup()

    def test_default_and_upgrade_enable_auto(self):
        self.assertEqual(self.store.settings()['acceleration'],'auto')
        self.assertEqual(self.store.settings()['gpu_layers'],999)
        (self.home/'settings.json').write_text(json.dumps(dict(gpu_layers=0,server_path='')),encoding='utf-8')
        self.assertEqual(self.store.settings()['gpu_layers'],999)
        explicit=self.store.settings()
        explicit.update(acceleration='cpu',gpu_layers=0)
        self.store.save_settings(explicit)
        self.assertEqual(self.store.settings()['gpu_layers'],0)

    def test_nvidia_uses_cuda_and_reports_real_offload(self):
        with patch('pathocr.runtime.probe_devices',return_value=([dict(id='CUDA0',name='RTX 4090')],'')),patch.object(self.runtime,'_launch',return_value=25) as launch:
            self.runtime.ensure()
        self.assertEqual(launch.call_args.args[5],'cuda')
        self.assertEqual(launch.call_args.args[4],999)
        self.assertEqual(self.runtime.status()['offloaded_layers'],25)
        self.assertEqual(self.runtime.status()['backend'],'cuda')

    def test_gpu_out_of_memory_tries_vulkan_then_cpu(self):
        with patch('pathocr.runtime.probe_devices',return_value=([dict(id='CUDA0',name='GPU')],'')),patch.object(self.runtime,'_launch',side_effect=[RuntimeError('CUDA out of memory'),RuntimeError('Vulkan out of memory'),0]) as launch:
            self.runtime.ensure()
        self.assertEqual([c.args[5] for c in launch.call_args_list],['cuda','vulkan','cpu'])
        self.assertEqual(launch.call_args.args[4],0)
        self.assertEqual(self.runtime.status()['backend'],'cpu')
        self.assertIn('out of memory',self.runtime.status()['fallback_reason'])

    def test_amd_or_intel_uses_vulkan_when_cuda_has_no_device(self):
        with patch('pathocr.runtime.probe_devices',side_effect=[([], 'no CUDA device'),([dict(id='Vulkan0',name='AMD Radeon')],'')]),patch.object(self.runtime,'_launch',return_value=25) as launch:
            self.runtime.ensure()
        self.assertEqual(launch.call_args.args[5],'vulkan')
        self.assertEqual(self.runtime.status()['backend'],'vulkan')

    def test_explicit_cpu_never_probes_or_downloads_gpu(self):
        settings=self.store.settings()
        settings['acceleration']='cpu'
        self.store.save_settings(settings)
        with patch('pathocr.runtime.probe_devices') as probe,patch('pathocr.runtime.install_runtime') as install,patch.object(self.runtime,'_launch',return_value=0) as launch:
            self.runtime.ensure()
        probe.assert_not_called()
        install.assert_not_called()
        self.assertEqual(launch.call_args.args[4],0)
        self.assertEqual(self.runtime.status()['backend'],'cpu')

    def test_device_parsing_rejects_software_renderers(self):
        devices=parse_devices('Available devices:\n  CUDA0: NVIDIA RTX 4090 (24564 MiB)\n  Vulkan0: llvmpipe (4096 MiB)\n  Metal: Apple M4 (16000 MiB)')
        self.assertEqual([d['id'] for d in devices],['CUDA0','Metal'])

    def test_cuda_packages_include_required_runtime_libraries(self):
        self.assertEqual(len(runtime_assets('cuda','Windows','x64')),2)
        self.assertIn('12.8',runtime_assets('cuda','Linux','x64')[1])


if __name__=='__main__':
    unittest.main()
