"""Offline tests. Mock CPython exports are clearly synthetic, never a runtime validation."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MOCK_SOURCE=r'''
/* ISOLATED SYNTHETIC API FIXTURE: not Python, not an application. */
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
static const wchar_t *home;
static const wchar_t *program;
const char *Py_GetVersion(void) {
    const char *v=getenv("CX_SYNTHETIC_VERSION"); return v?v:"3.11.SYNTHETIC-NOT-PYTHON";
}
int Py_IsInitialized(void) { return getenv("CX_SYNTHETIC_INITIALIZED")?1:0; }
void Py_SetPythonHome(const wchar_t *s) { home=s; }
void Py_SetProgramName(const wchar_t *s) { program=s; }
static void codepoints(const char *label, const wchar_t *s) {
    printf("%s=",label); for (;*s;++s) { printf("%x,",(unsigned)*s); } putchar('\n');
}
int Py_Main(int argc, wchar_t **argv) {
    puts("SYNTHETIC_API_FIXTURE_ONLY"); codepoints("HOME",home); codepoints("PROGRAM",program);
    for (int i=0;i<argc;++i) { char label[32]; snprintf(label,sizeof(label),"ARG_%d",i); codepoints(label,argv[i]); }
    const char *p=getenv("QT_PLUGIN_PATH"); printf("QT_PLUGIN=%s\n",p?p:"");
    p=getenv("QT_QPA_PLATFORM"); printf("QPA=%s\n",p?p:"");
    p=getenv("CX_SYNTHETIC_EXIT"); return p?atoi(p):0;
}
'''


def encoded(text):
    return ''.join(f'{ord(c):x},' for c in text)


@unittest.skipUnless(shutil.which('clang') and sys.platform in ('darwin','linux'), 'requires local clang on a POSIX host')
class StartupAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory(prefix='cx-local-unit-')
        cls.work=Path(cls.temporary.name)
        cls.executable=cls.work/'host-adapter'
        flags=['clang','-std=c11','-Wall','-Wextra','-Werror',str(ROOT/'harmony/bootstrap.c'),'-o',str(cls.executable)]
        if sys.platform!='darwin': flags+=['-ldl']
        subprocess.run(flags,check=True,capture_output=True,text=True)
        source=cls.work/'synthetic_api.c'
        source.write_text(MOCK_SOURCE)
        cls.library=cls.work/'synthetic_api.so'
        shared=['-dynamiclib'] if sys.platform=='darwin' else ['-shared','-fPIC']
        subprocess.run(['clang',*shared,'-Wall','-Wextra','-Werror',str(source),'-o',str(cls.library)],check=True,capture_output=True,text=True)

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cx-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.runtime=Path(self.temp.name)/'合成 runtime with spaces 🖥'
        self.runtime.mkdir()
        encodings=self.runtime/'lib/python3.11/encodings'
        encodings.mkdir(parents=True)
        (encodings/'__init__.py').write_text('# SYNTHETIC empty fixture; no modules executed\n')
        shutil.copy2(self.library,self.runtime/'lib/libpython3.11.so.1.0')

    def invoke(self,*args,env=None,executable=None):
        environment=os.environ.copy()
        for key in list(environment):
            if key.startswith('CX_SYNTHETIC_'): del environment[key]
        environment.update(env or {})
        command=[str(executable or self.executable),'--cx-runtime-root',str(self.runtime),*args]
        return subprocess.run(command,capture_output=True,text=True,env=environment,check=False,timeout=10)

    def arguments(self,result):
        return [line.split('=',1)[1] for line in result.stdout.splitlines() if line.startswith('ARG_')]

    def test_help_does_not_require_runtime(self):
        result=subprocess.run([str(self.executable),'--cx-help'],capture_output=True,text=True,check=False)
        self.assertEqual(result.returncode,0)
        self.assertIn('not a complete application',result.stdout)

    def test_private_home_and_unicode_arguments(self):
        result=self.invoke('空白界面 文本 🖥','--generic-option')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('SYNTHETIC_API_FIXTURE_ONLY',result.stdout)
        self.assertIn('HOME='+encoded(str(self.runtime.resolve())),result.stdout)
        args=self.arguments(result)
        self.assertEqual(args[-2:],[encoded('空白界面 文本 🖥'),encoded('--generic-option')])
        self.assertIn(encoded('chimerax.core'),args)
        self.assertIn(encoded('-I'),args)

    def test_debug_preserved_and_python_debug_flag_added(self):
        result=self.invoke('--debug')
        args=self.arguments(result)
        self.assertEqual(args[1:3],[encoded('-X'),encoded('dev')])
        self.assertEqual(args[-1],encoded('--debug'))

    def test_runtime_check_never_selects_application_module(self):
        result=self.invoke('--cx-runtime-check','--','synthetic-app-argument')
        args=self.arguments(result)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(encoded('-c'),args)
        self.assertNotIn(encoded('chimerax.core'),args)
        self.assertNotIn(encoded('synthetic-app-argument'),args)

    def test_double_dash_preserves_application_option(self):
        result=self.invoke('--','--cx-runtime-check')
        self.assertEqual(self.arguments(result)[-1],encoded('--cx-runtime-check'))
        self.assertIn(encoded('chimerax.core'),self.arguments(result))

    def test_missing_stdlib_blocks_before_interpreter(self):
        (self.runtime/'lib/python3.11/encodings/__init__.py').unlink()
        result=self.invoke()
        self.assertEqual(result.returncode,69)
        self.assertIn('STDLIB_MISSING',result.stderr)
        self.assertNotIn('SYNTHETIC_API_FIXTURE_ONLY',result.stdout)

    def test_no_fallback_to_host_python(self):
        (self.runtime/'lib/libpython3.11.so.1.0').unlink()
        result=self.invoke()
        self.assertEqual(result.returncode,69)
        self.assertIn('PYTHON_LOAD',result.stderr)

    def test_wrong_python_minor_is_rejected(self):
        result=self.invoke(env={'CX_SYNTHETIC_VERSION':'3.14.SYNTHETIC'})
        self.assertEqual(result.returncode,69)
        self.assertIn('PYTHON_ABI',result.stderr)

    def test_existing_interpreter_not_reconfigured(self):
        result=self.invoke(env={'CX_SYNTHETIC_INITIALIZED':'1'})
        self.assertEqual(result.returncode,69)
        self.assertIn('PYTHON_INITIALIZED',result.stderr)

    def test_private_qt_plugin_path_and_no_forced_qpa(self):
        plugins=self.runtime/'lib/python3.11/site-packages/PyQt6/Qt6/plugins/platforms'
        plugins.mkdir(parents=True)
        result=self.invoke(env={'QT_PLUGIN_PATH':'synthetic-wrong-host-path','QT_QPA_PLATFORM':'synthetic-native-qpa'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('QT_PLUGIN='+str(plugins.parent.resolve()),result.stdout)
        self.assertIn('QPA=synthetic-native-qpa',result.stdout)

    def test_application_exit_status_is_preserved(self):
        self.assertEqual(self.invoke(env={'CX_SYNTHETIC_EXIT':'17'}).returncode,17)

    def test_cpp_integration_links_the_exported_c_entry(self):
        library=Path(self.temp.name)/'host-bootstrap.so'
        shared=['-dynamiclib'] if sys.platform=='darwin' else ['-shared','-fPIC']
        command=['clang',*shared,'-DCX_BOOTSTRAP_LIBRARY','-std=c11','-Wall','-Wextra','-Werror',
                 str(ROOT/'harmony/bootstrap.c'),'-o',str(library)]
        if sys.platform!='darwin': command+=['-ldl']
        subprocess.run(command,check=True,capture_output=True,text=True)
        source=Path(self.temp.name)/'synthetic_cpp_caller.cpp'
        source.write_text('#include "bootstrap.h"\nint main(int argc,char **argv) { if (argc!=2) return 2; return cx_harmony_bootstrap(argv[1],1,argv,1); }\n')
        caller=Path(self.temp.name)/'synthetic_cpp_caller'
        command=['clang++','-std=c++11','-Wall','-Wextra','-Werror','-I',str(ROOT/'harmony'),
                 str(source),str(library),'-o',str(caller)]
        if sys.platform!='darwin': command+=['-Wl,-rpath,'+str(library.parent)]
        subprocess.run(command,check=True,capture_output=True,text=True)
        result=subprocess.run([str(caller),str(self.runtime)],capture_output=True,text=True,check=False,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('SYNTHETIC_API_FIXTURE_ONLY',result.stdout)

    def test_default_root_uses_executable_not_working_directory(self):
        binary=self.runtime/'bin/ChimeraX'
        binary.parent.mkdir()
        shutil.copy2(self.executable,binary)
        result=subprocess.run([str(binary),'--cx-runtime-check'],cwd=self.work,
                              capture_output=True,text=True,check=False,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('HOME='+encoded(str(self.runtime.resolve())),result.stdout)


@unittest.skipUnless((ROOT/'build/upstream-local-adapted/mk/config.make').is_file(),
                     'pinned generic upstream metadata cache is required for this integration check')
class PlatformPatchIntegrationTests(unittest.TestCase):
    def run_make(self,target='cx-platform-info',**variables):
        tree=ROOT/'build/upstream-local-adapted'
        makefile=f'''TOP := {tree}
include $(TOP)/mk/config.make
.PHONY: cx-platform-info
cx-platform-info:
\t@printf '%s\\n' 'OS=$(OS)' 'OSARCH=$(OSARCH)' 'APP_FILENAME=$(APP_FILENAME)' 'CHIMERAX_EXE=$(CHIMERAX_EXE)' 'CC=$(CC)' 'NO_PREBUILT=$(NO_PREBUILT)' 'OPENGL_LIBS=$(OPENGL_LIBS)'
'''
        command=['make','--no-print-directory','-f','-',target,
                 'HARMONY_NATIVE_SDK=/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native']
        command += [f'{key}={value}' for key,value in variables.items()]
        return subprocess.run(command,input=makefile,capture_output=True,text=True,check=False,timeout=15)

    def test_explicit_harmony_target_uses_sdk_and_private_paths(self):
        result=self.run_make(CX_TARGET_PLATFORM='harmonyos')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('OS=HarmonyOS',result.stdout)
        self.assertIn('OSARCH=HarmonyArm64',result.stdout)
        self.assertIn('APP_FILENAME=ChimeraX.harmony',result.stdout)
        self.assertIn('--target=aarch64-linux-ohos',result.stdout)
        self.assertIn('NO_PREBUILT=1',result.stdout)
        self.assertIn('OPENGL_LIBS=\n',result.stdout)

    def test_host_target_is_not_silently_changed(self):
        result=self.run_make(CX_TARGET_PLATFORM='host')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('OS=HarmonyOS',result.stdout)
        self.assertIn('APP_FILENAME=ChimeraX.app',result.stdout)

    def test_typo_does_not_fall_back_to_host(self):
        result=self.run_make(CX_TARGET_PLATFORM='harmony-typo')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Unsupported CX_TARGET_PLATFORM',result.stderr)

    def test_unsupported_architecture_is_explicit(self):
        result=self.run_make(CX_TARGET_PLATFORM='harmonyos',CX_HARMONY_ARCH='unsupported-test-arch')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Only the aarch64',result.stderr)

    def test_full_upstream_install_not_mistaken_for_cross_build(self):
        result=self.run_make(target='install',CX_TARGET_PLATFORM='harmonyos')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Full upstream cross-build is not enabled',result.stderr)


class PatchSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('platform_patch',ROOT/'tools/apply_platform_patch.py')
        cls.module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_changed_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'source'
            (source/'mk').mkdir(parents=True)
            changed=source/'mk/detectOS.make'
            changed.write_text('# isolated synthetic user edit, not upstream source\n')
            before=changed.read_bytes()
            status=self.module.main(['--source-root',str(source),'--apply','--report',str(Path(temporary)/'report.json')])
            self.assertEqual(status,2)
            self.assertEqual(changed.read_bytes(),before)


if __name__=='__main__': unittest.main()
