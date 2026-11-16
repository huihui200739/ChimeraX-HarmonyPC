#!/usr/bin/env python3
"""Test the real CPython 3.11 entry API on the HOST only; never a target/UI test."""
from __future__ import annotations
import argparse
import json
import platform
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]


def link_existing(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() and destination.resolve()==source.resolve(): return
        raise RuntimeError(f'Preserving conflicting existing path: {destination}')
    destination.symlink_to(source.resolve(),target_is_directory=source.is_dir())


def run(argv: list[str]) -> dict:
    result=subprocess.run(argv,capture_output=True,text=True,timeout=60,check=False)
    return {'argv':argv,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-home',required=True,type=Path,help='A local CPython 3.11 installation; never downloaded by this tool')
    day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    parser.add_argument('--report',type=Path,default=ROOT/f'reports/host-embedding-{day}.json')
    args=parser.parse_args(argv)
    report={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'real_host_python_api_only','host_system':platform.system(),
            'device_contacted':False,'upstream_app_launched':False,'target_python_validated':False,
            'target_ui_validated':False,'port_validated':False,'commands':[]}
    report_path=args.report
    try:
        home=args.python_home.resolve()
        executable=home/'bin/python3.11'
        metadata=run([str(executable),'-I','-c','import json,sys; print(json.dumps(dict(version=list(sys.version_info[:3]),implementation=sys.implementation.name)))'])
        report['commands'].append(metadata)
        if metadata['returncode']!=0: raise RuntimeError('Cannot query the supplied host interpreter')
        info=json.loads(metadata['stdout'])
        if info['version'][:2]!=[3,11] or info['implementation']!='cpython': raise RuntimeError('A real local CPython 3.11 installation is required')
        library=next((p for p in [home/'lib/libpython3.11.dylib',home/'lib/libpython3.11.so.1.0',home/'lib/libpython3.11.so'] if p.is_file()),None)
        if library is None or not (home/'lib/python3.11/encodings/__init__.py').is_file():
            raise RuntimeError('Required host shared library and standard library were not found')
        stage=ROOT/'build/host embedding 中文 space'
        (stage/'bin').mkdir(parents=True,exist_ok=True)
        (stage/'lib').mkdir(exist_ok=True)
        link_existing(home/'lib/python3.11',stage/'lib/python3.11')
        link_existing(library,stage/'lib/libpython3.11.so.1.0')
        launcher=stage/'bin/ChimeraX'
        flags=['clang','-std=c11','-Wall','-Wextra','-Werror',str(ROOT/'harmony/bootstrap.c'),'-o',str(launcher)]
        if platform.system()!='Darwin': flags+=['-ldl']
        compiled=run(flags)
        report['commands'].append(compiled)
        if compiled['returncode']!=0: raise RuntimeError('Host adapter compilation failed')
        checked=run([str(launcher),'--cx-runtime-check'])
        report['commands'].append(checked)
        if checked['returncode']!=0: raise RuntimeError('Real host interpreter entry check failed')
        observed=json.loads(checked['stdout'])
        if not (observed.get('check')=='cx_harmony_runtime' and observed.get('implementation')=='cpython'
                and observed.get('isolated') and observed.get('utf8')
                and Path(observed.get('prefix','')).resolve()==stage.resolve()
                and Path(observed.get('executable','')).resolve()==launcher.resolve()):
            raise RuntimeError('Host interpreter did not honor the private runtime or startup flags')
        report.update(status='host_embedding_passed',host_runtime_validated=True,
                      actual_runtime=observed,source_python_home=str(home))
    except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        report.update(status='blocked_host_embedding',host_runtime_validated=False,error=str(exc))
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"{report['status']}: {report_path}")
    return 0 if report.get('host_runtime_validated') else 2


if __name__=='__main__': raise SystemExit(main())
