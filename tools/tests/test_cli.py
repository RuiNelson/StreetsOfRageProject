"""Unit tests for ``python3 -m tools`` command dispatch."""

import sys

from tools import main as tools_main


def test_help_lists_core_commands(capsys):
    assert tools_main.main(['--help']) == 0

    out = capsys.readouterr().out
    assert 'disassemble' in out
    assert 'recompile' in out
    assert 'speculative-scan' in out


def test_unknown_command_returns_usage_error(capsys):
    assert tools_main.main(['nope']) == 2

    err = capsys.readouterr().err
    assert 'Unknown tools command: nope' in err


def test_dispatches_alias(monkeypatch):
    called = {}

    def fake_import(module_name):
        called['module'] = module_name

        class Module:
            @staticmethod
            def main(argv):
                called['argv'] = argv
                return 7

        return Module

    monkeypatch.setattr(tools_main.importlib, 'import_module', fake_import)

    assert tools_main.main(['disasm', 'rom/SOR.bin']) == 7
    assert called == {
        'module': 'tools.disassembler.main',
        'argv': ['rom/SOR.bin'],
    }

