# test_backend.py

import os
import re
import errno
import platform
import subprocess

import pytest

from graphviz.backend import (run, render, pipe, version, view,
                              ExecutableNotFound, RequiredArgumentError)


if platform.system().lower() == 'windows':
    def check_startupinfo(Popen):  # noqa: N803
        startupinfo = Popen.call_args[1]['startupinfo']
        assert isinstance(startupinfo, subprocess.STARTUPINFO)
        assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
        assert startupinfo.wShowWindow == subprocess.SW_HIDE
else:
    def check_startupinfo(Popen):  # noqa: N803
        assert Popen.call_args[1]['startupinfo'] is None


@pytest.exe
def test_run_oserror():
    with pytest.raises(OSError) as e:
        run([''])
    assert e.value.errno in (errno.EACCES, errno.EINVAL)


def test_render_engine_unknown():
    with pytest.raises(ValueError, match=r'unknown engine'):
        render('', 'pdf', 'nonfilepath')


def test_render_format_unknown():
    with pytest.raises(ValueError, match=r'unknown format'):
        render('dot', '', 'nonfilepath')


def test_render_renderer_unknown():
    with pytest.raises(ValueError, match=r'unknown renderer'):
        render('dot', 'ps', 'nonfilepath', '', None)


def test_render_renderer_missing():
    with pytest.raises(RequiredArgumentError, match=r'without renderer'):
        render('dot', 'ps', 'nonfilepath', None, 'core')


def test_render_formatter_unknown():
    with pytest.raises(ValueError, match=r'unknown formatter'):
        render('dot', 'ps', 'nonfilepath', 'ps', '')


@pytest.mark.usefixtures('empty_path')
def test_render_missing_executable():
    with pytest.raises(ExecutableNotFound, match=r'execute'):
        render('dot', 'pdf', 'nonfilepath')


@pytest.exe
def test_render_missing_file(quiet, engine='dot', format_='pdf'):
    with pytest.raises(subprocess.CalledProcessError) as e:
        render(engine, format_, '', quiet=quiet)
    assert e.value.returncode == 2


@pytest.exe
@pytest.mark.parametrize('format_, renderer, formatter, expected_suffix', [
    ('pdf', None, None, 'pdf'),
    ('plain', 'dot', 'core', 'core.dot.plain'),
])
@pytest.mark.parametrize('engine', ['dot'])
def test_render(capsys, tmpdir, engine, format_, renderer, formatter,
                expected_suffix, filename='hello.gv',
                data=b'digraph { hello -> world }'):
    lpath = tmpdir / filename
    lpath.write_binary(data)
    rendered = lpath.new(ext='%s.%s' % (lpath.ext, expected_suffix))

    assert render(engine, format_, str(lpath), renderer, formatter) == str(rendered)

    assert rendered.size()
    assert capsys.readouterr() == ('', '')


@pytest.exe
def test_render_img(capsys, tmpdir, filesdir, engine='dot', format_='pdf'):
    subdir = tmpdir / 'subdir'
    subdir.ensure(dir=True)

    img_path = subdir / 'dot_red.png'
    (filesdir / img_path.basename).copy(img_path)
    assert img_path.size()

    gv_path = subdir / 'img.gv'
    rendered = gv_path.new(ext='%s.%s' % (gv_path.ext, format_))
    gv_rel, rendered_rel = map(tmpdir.bestrelpath, (gv_path, rendered))
    assert all(s.startswith('subdir') for s in (gv_rel, rendered_rel))
    gv_path.write_text(u'graph { red_dot [image="%s"] }' % img_path.basename,
                       encoding='ascii')

    with tmpdir.as_cwd():
        assert render(engine, format_, gv_rel) == rendered_rel

    assert rendered.size()
    assert capsys.readouterr() == ('', '')


def test_render_mocked(capsys, mocker, Popen, quiet):  # noqa: N803
    proc = Popen.return_value
    proc.returncode = 0
    proc.communicate.return_value = (b'stdout', b'stderr')

    assert render('dot', 'pdf', 'nonfilepath', quiet=quiet) == 'nonfilepath.pdf'

    Popen.assert_called_once_with(['dot', '-Tpdf', '-O', 'nonfilepath'],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  cwd=None, startupinfo=mocker.ANY)
    check_startupinfo(Popen)
    proc.communicate.assert_called_once_with(None)
    assert capsys.readouterr() == ('', '' if quiet else 'stderr')


@pytest.mark.usefixtures('empty_path')
def test_pipe_missing_executable():
    with pytest.raises(ExecutableNotFound, match=r'execute'):
        pipe('dot', 'pdf', b'nongraph')


@pytest.exe
@pytest.mark.xfail('version() == (2, 36, 0)',
                   reason='https://bugs.launchpad.net/ubuntu/+source/graphviz/+bug/1694108')
def test_pipe_invalid_data(capsys, quiet, engine='dot', format_='svg'):
    with pytest.raises(subprocess.CalledProcessError) as e:
        pipe(engine, format_, b'nongraph', quiet=quiet)

    assert e.value.returncode == 1
    assert 'syntax error in line' in str(e.value)
    out, err = capsys.readouterr()
    assert out == ''
    if quiet:
        assert err == ''
    else:
        assert 'syntax error in line' in err


@pytest.exe
@pytest.mark.parametrize('format_, renderer, formatter, pattern', [
    ('svg', None, None, r'(?s)^<\?xml .+</svg>\s*$'),
    ('ps', 'ps', 'core', r'%!PS-'),
])
@pytest.mark.parametrize('engine', ['dot'])
def test_pipe(capsys, engine, format_, renderer, formatter, pattern,
              data=b'graph { spam }'):
    out = pipe(engine, format_, data, renderer, formatter).decode('ascii')

    if pattern is not None:
        assert re.match(pattern, out)
    assert capsys.readouterr() == ('', '')


def test_pipe_pipe_invalid_data_mocked(mocker, py2, Popen, quiet):  # noqa: N803
    stderr = mocker.patch('sys.stderr', autospec=True,
                          **{'flush': mocker.Mock(), 'encoding': 'nonencoding'})
    proc = Popen.return_value
    proc.returncode = mocker.sentinel.returncode
    err = mocker.create_autospec(bytes, instance=True, name='err',
                                 **{'__len__.return_value': 23})
    proc.communicate.return_value = (mocker.sentinel.out, err)

    with pytest.raises(subprocess.CalledProcessError) as e:
        pipe('dot', 'png', b'nongraph', quiet=quiet)

    assert e.value.returncode is mocker.sentinel.returncode
    assert e.value.stdout is mocker.sentinel.out
    assert e.value.stderr is err
    Popen.assert_called_once_with(['dot', '-Tpng'],
                                  stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  startupinfo=mocker.ANY)
    check_startupinfo(Popen)
    proc.communicate.assert_called_once_with(b'nongraph')
    if not quiet:
        if py2:
            stderr.write.assert_called_once_with(err)
        else:
            err.decode.assert_called_once_with(stderr.encoding)
            stderr.write.assert_called_once_with(err.decode.return_value)
        stderr.flush.assert_called_once_with()


def test_pipe_mocked(capsys, mocker, Popen, quiet):  # noqa: N803
    proc = Popen.return_value
    proc.returncode = 0
    proc.communicate.return_value = (mocker.sentinel.out, b'stderr')

    assert pipe('dot', 'png', b'nongraph', quiet=quiet) is mocker.sentinel.out

    Popen.assert_called_once_with(['dot', '-Tpng'],
                                  stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  startupinfo=mocker.ANY)
    check_startupinfo(Popen)
    proc.communicate.assert_called_once_with(b'nongraph')
    assert capsys.readouterr() == ('', '' if quiet else 'stderr')


@pytest.mark.usefixtures('empty_path')
def test_version_missing_executable():
    with pytest.raises(ExecutableNotFound, match=r'execute'):
        version()


@pytest.exe
def test_version(capsys):
    result = version()
    assert isinstance(result, tuple) and result
    assert all(isinstance(d, int) for d in result)
    assert capsys.readouterr() == ('', '')


def test_version_parsefail_mocked(mocker, Popen):  # noqa: N803
    proc = Popen.return_value
    proc.returncode = 0
    proc.communicate.return_value = (b'nonversioninfo', None)

    with pytest.raises(RuntimeError, match=r'nonversioninfo'):
        version()

    Popen.assert_called_once_with(['dot', '-V'],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,
                                  startupinfo=mocker.ANY)
    check_startupinfo(Popen)
    proc.communicate.assert_called_once_with(None)


def test_version_mocked(mocker, Popen):  # noqa: N803
    proc = Popen.return_value
    proc.returncode = 0
    proc.communicate.return_value = (b'dot - graphviz version 1.2.3 (mocked)',
                                     None)

    assert version() == (1, 2, 3)

    Popen.assert_called_once_with(['dot', '-V'],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,
                                  startupinfo=mocker.ANY)
    check_startupinfo(Popen)
    proc.communicate.assert_called_once_with(None)


def test_view_unknown_platform(unknown_platform):
    with pytest.raises(RuntimeError, match=r'platform'):
        view('nonfilepath')


def test_view(mocker, py2, platform, Popen, startfile, quiet):  # noqa: N803
    if quiet and py2:
        open_ = mocker.patch('__builtin__.open', mocker.mock_open())

    assert view('nonfilepath', quiet=quiet) is None

    if platform == 'windows':
        startfile.assert_called_once_with('nonfilepath')
        return

    if quiet and py2:
        open_.assert_called_once_with(os.devnull, 'w')
        kwargs = {'stderr': open_.return_value}
    elif quiet:
        kwargs = {'stderr': subprocess.DEVNULL}
    else:
        kwargs = {}

    if platform == 'darwin':
        Popen.assert_called_once_with(['open', 'nonfilepath'], **kwargs)
    elif platform in ('linux', 'freebsd'):
        Popen.assert_called_once_with(['xdg-open', 'nonfilepath'], **kwargs)
    else:
        raise RuntimeError
