import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from compiler.fas_writer import FasWriter
from compiler.roundtrip import _compile_to_fas
from decompiler.fas4_decompiler import Fas4Parser, detect_layout

COMPACT_SOURCE = """
(defun add (a b) (+ a b))
(defun sub (a b) (- a b))
(defun sq (x) (* x x))
"""


def _compact(path):
    from compiler.compile_cmd import cmd_compile

    source = os.path.join(os.path.dirname(path), 'src.lsp')
    with open(source, 'w', encoding='utf-8') as handle:
        handle.write(COMPACT_SOURCE)
    cmd_compile(source, path)
    return path


def test_detect_layout_compact_stub(tmp_path):
    fas = _compact(str(tmp_path / 'multi.fas'))
    assert detect_layout(Fas4Parser().parse(fas)) == 'compact'


def test_detect_layout_selfcontained(tmp_path):
    seg0, seg1, symtab = _compile_to_fas(COMPACT_SOURCE)
    fas = str(tmp_path / 'self.fas')
    FasWriter(symtab).write(fas, seg0, seg1)
    assert detect_layout(Fas4Parser().parse(fas)) == 'selfcontained'


def test_info_reports_layout(tmp_path):
    from compiler.info_cmd import cmd_info

    fas = _compact(str(tmp_path / 'multi.fas'))
    assert cmd_info(fas)['format'] == 'compact'
