# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""The CPU import stub must not advertise a real TransferQueue package."""

import shlex
import subprocess
import sys
import textwrap
from pathlib import Path


def test_ci_tq_stub_supports_wholepack_without_claiming_real_metadata(tmp_path):
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
    block = workflow.split("# Create a stub for transfer_queue", 1)[1].split("- name: Run tests", 1)[0]
    command = shlex.split(block[block.index("python -c") :])
    assert command[:2] == ["python", "-c"] and len(command) == 3
    installer = textwrap.dedent(command[2]).replace("site.getsitepackages()[0]", repr(str(tmp_path)))
    subprocess.run([sys.executable, "-c", installer], check=True)
    probe = f"""
import sys
sys.path.insert(0, {str(tmp_path)!r})
import transfer_queue
from transfer_queue.sampler import BaseSampler
assert isinstance(BaseSampler, type)
assert vars(transfer_queue)['__relax_ci_stub__'] is True
assert transfer_queue.__spec__.submodule_search_locations is None
assert not hasattr(transfer_queue, '__path__')
try:
    import transfer_queue.metadata
except ModuleNotFoundError:
    pass
else:
    raise AssertionError('CI stub must not fabricate real metadata support')
"""
    subprocess.run([sys.executable, "-c", probe], check=True)
