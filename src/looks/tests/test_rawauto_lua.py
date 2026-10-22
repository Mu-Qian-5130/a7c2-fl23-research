"""Execute plugin profile logic under Lua5.1, independent of Lightroom/USB."""
from pathlib import Path
import struct
import tempfile
import unittest

try:from lupa.lua51 import LuaRuntime
except ImportError:LuaRuntime=None


@unittest.skipUnless(LuaRuntime,'Lua5.1 test runtime not installed')
class PluginTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.plugin=Path(__file__).resolve().parents[3]/'plugins/A7LookAuto.lrplugin'
        self.lua.execute('_PLUGIN={}; settings={CameraProfile="Adobe Standard",Exposure2012=1.25}; calls=0; saved={}; '
            'photo={getDevelopSettings=function() return settings end, '
            'applyDevelopSettings=function(self,changes) calls=calls+1; for k,v in pairs(changes) do settings[k]=v end end, '
            'setPropertyForPlugin=function(self,plugin,key,value) saved[key]=value end}; '
            'catalog={withWriteAccessDo=function(self,title,callback) callback() end}')
        self.logic=self.lua.execute((self.plugin/'Logic.lua').read_text(encoding='utf-8'))
        self.verify=self.lua.eval('function(photo) return settings.CameraProfile end')

    def test_every_plugin_file_parses_as_lua51(self):
        for path in self.plugin.glob('*.lua'):self.lua.compile(path.read_text(encoding='utf-8'))

    def test_profile_only_application_keeps_other_development_edits(self):
        status=self.logic.apply(self.lua.globals().catalog,self.lua.globals().photo,'NC version','id-one','Adobe Standard',self.verify)
        self.assertEqual(status,'applied')
        self.assertEqual(self.lua.globals().settings['Exposure2012'],1.25)
        self.assertEqual(self.lua.globals().settings['CameraProfile'],'NC version')
        self.assertEqual(self.lua.globals().saved['lookId'],'id-one')

    def test_user_profile_change_after_import_is_not_overwritten(self):
        self.lua.execute('settings.CameraProfile="User changed profile"')
        status=self.logic.apply(self.lua.globals().catalog,self.lua.globals().photo,'NC','id','Adobe Standard',self.verify)
        self.assertEqual(status,'profile_changed_since_import');self.assertEqual(self.lua.globals().calls,0)

    def test_already_correct_profile_records_version_without_reapplying(self):
        self.lua.execute('settings.CameraProfile="NC"')
        status=self.logic.apply(self.lua.globals().catalog,self.lua.globals().photo,'NC','id','NC',self.verify)
        self.assertEqual(status,'applied');self.assertEqual(self.lua.globals().calls,0)

    def test_echoed_name_with_actual_adobe_fallback_is_not_success(self):
        self.lua.execute('settings.Look={Name="Original overlay"}; settings.CameraProfileDigest="original"')
        fallback=self.lua.eval('function(photo) return "Adobe Standard" end')
        status=self.logic.apply(self.lua.globals().catalog,self.lua.globals().photo,'New NC','id','Adobe Standard',fallback)
        self.assertEqual(status,'awaiting_profile_reload')
        self.assertEqual(self.lua.globals().settings['CameraProfile'],'Adobe Standard')
        self.assertEqual(self.lua.globals().settings['CameraProfileDigest'],'original')
        self.assertEqual(self.lua.globals().settings['Look']['Name'],'Original overlay')
        self.assertIsNone(self.lua.globals().saved['lookId'])
        self.assertEqual(self.lua.globals().settings['Exposure2012'],1.25)

    def test_getter_without_render_verification_does_not_claim_applied(self):
        status=self.logic.apply(self.lua.globals().catalog,self.lua.globals().photo,'NC','id','Adobe Standard')
        self.assertEqual(status,'profile_requested_unverified');self.assertIsNone(self.lua.globals().saved['lookId'])

    def test_failed_render_restores_import_profile(self):
        failure=self.lua.eval('function(photo) return nil,"export unavailable" end')
        status=self.logic.apply(self.lua.globals().catalog,self.lua.globals().photo,'NC','id','Adobe Standard',failure)
        self.assertEqual(status,'verification_failed')
        self.assertEqual(self.lua.globals().settings['CameraProfile'],'Adobe Standard')

    def test_user_change_during_verification_is_retained(self):
        changed=self.lua.eval('function(photo) settings.CameraProfile="User chosen"; return "NC" end')
        status=self.logic.apply(self.lua.globals().catalog,self.lua.globals().photo,'NC','id','Adobe Standard',changed)
        self.assertEqual(status,'profile_changed_since_import')
        self.assertEqual(self.lua.globals().settings['CameraProfile'],'User chosen')
        self.assertIsNone(self.lua.globals().saved['lookId'])

    def test_pending_queue_retains_catalog_path_and_observed_profile(self):
        module=self.lua.execute((self.plugin/'Queue.lua').read_text(encoding='utf-8'))
        rows=self.lua.table_from([self.lua.table_from(dict(catalog='C:/目录/one.lrcat',id='123',path='P:/照片/a.ARW',profile='NC & CC'))])
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'queue.tsv');module.write(path,rows);restored=module.read(path)
        self.assertEqual(restored[1]['catalog'],rows[1]['catalog'])
        self.assertEqual(restored[1]['path'],rows[1]['path'])
        self.assertEqual(restored[1]['profile'],rows[1]['profile'])

    def test_rendition_parser_uses_xmp_not_profile_like_text_in_other_metadata(self):
        self.lua.execute('import=function(name) return {} end')
        module=self.lua.execute((self.plugin/'Verification.lua').read_text(encoding='utf-8'))
        def segment(code,payload):return b'\xff'+bytes([code])+struct.pack('>H',len(payload)+2)+payload
        decoy=segment(0xed,b'crs:CameraProfile="Wrong"')
        xmp=segment(0xe1,b'http://ns.adobe.com/xap/1.0/\0<rdf:Description crs:CameraProfile="NC &amp; CC"/>')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'export.jpg';path.write_bytes(b'\xff\xd8'+decoy+xmp+b'\xff\xd9')
            self.assertEqual(module.exportedProfile(str(path)),'NC & CC')

    def test_runtime_resumes_only_queued_import_after_profile_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'test-1').mkdir()
            (root/'test-1/result.tsv').write_text('123\tapply\t4e43\t76657273696f6e\t\n')
            queue=self.lua.execute((self.plugin/'Queue.lua').read_text())
            rows=self.lua.table_from([self.lua.table_from(dict(catalog='owned-test.lrcat',id='123',path='new.ARW',profile='Adobe Standard'))])
            queue.write(str(root/'pending-imports.tsv'),rows)
            self.lua.globals().testRoot=root.as_posix()
            self.lua.globals().testLogic=self.logic
            self.lua.globals().testQueue=queue
            self.lua.execute('''
                now=0; ticks=0; actualProfile='Adobe Standard'
                oldCalls=0
                old={localIdentifier=999, getRawMetadata=function() return 'old.ARW' end,
                    getDevelopSettings=function() return {CameraProfile='Existing user edit'} end,
                    applyDevelopSettings=function() oldCalls=oldCalls+1 end}
                photo.localIdentifier=123
                photo.getRawMetadata=function() return 'new.ARW' end
                catalog.getPath=function() return 'owned-test.lrcat' end
                catalog.getAllPhotos=function() return {old,photo} end
                modules={Config={work_root=testRoot,install_id='test',log=testRoot..'/log',
                    status=testRoot..'/status',python='python',worker='worker.py',settings='settings.json'},
                    Logic=testLogic,Queue=testQueue,Verification={render=function() return actualProfile end}}
                imports={LrApplication={activeCatalog=function() return catalog end},
                    LrFileUtils={createAllDirectories=function() end},
                    LrPathUtils={child=function(a,b) return a..'/'..b end},
                    LrTasks={pcall=pcall,execute=function() return 0 end,
                        sleep=function() ticks=ticks+1;if ticks>=2 then _G.A7LookAuto.running=false end end},
                    LrDate={currentTime=function() now=now+10;return now end}}
                import=function(name) return imports[name] end
                require=function(name) return modules[name] end
                context={addCleanupHandler=function() end}
            ''')
            runtime=self.lua.execute((self.plugin/'Runtime.lua').read_text())
            runtime.start(self.lua.globals().context)
            self.assertEqual(self.lua.globals().settings['CameraProfile'],'Adobe Standard')
            self.assertEqual(self.lua.globals().A7LookAuto['applied'],0)
            self.assertEqual(len(queue.read(str(root/'pending-imports.tsv'))),1)
            self.lua.execute('actualProfile="NC";ticks=0')
            runtime.start(self.lua.globals().context)
            self.assertEqual(self.lua.globals().settings['CameraProfile'],'NC')
            self.assertEqual(self.lua.globals().A7LookAuto['applied'],1)
            self.assertEqual(len(queue.read(str(root/'pending-imports.tsv'))),0)
            self.assertEqual(self.lua.globals().oldCalls,0)


if __name__=='__main__':unittest.main()
