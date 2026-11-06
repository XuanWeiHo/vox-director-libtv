"""Offline ffmpeg tests; no cloud nodes or paid model invocations."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import shutil
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from libtv_provider import save_json
from media_utils import probe_duration
import assemble
import aroll_assemble
import aroll_clips
import host_clips
import text_overlay


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, args)], check=True, capture_output=True)


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vox-test-")
        self.root = Path(self.tmp.name) / "中文 project's files"
        self.root.mkdir()
        self.video = self.root / "source.mp4"
        self.audio = self.root / "narration.mp3"
        ff("-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=2", "-f", "lavfi", "-i",
           "sine=frequency=400:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", self.video)
        ff("-i", self.video, "-vn", "-t", "1", self.audio)

    def tearDown(self):
        self.tmp.cleanup()

    def test_broll_assembly_unicode_paths_captions_and_music(self):
        doc = {"aspect": "16:9", "output_size": [320,180], "watermark": "",
               "bgm_path": str(self.audio), "beats": [{"id":1, "narration":"纸片也能讲故事。",
               "narration_audio":str(self.audio), "narration_dur":1,
               "shots":[{"id":"a", "dur":1,"clip_path":str(self.video)},
                         {"id":"b", "dur":1,"clip_path":str(self.video)}]}]}
        save_json(self.root / "beats.json", doc)
        assemble.run(str(self.root))
        self.assertAlmostEqual(probe_duration(self.root / "final.mp4"), 2, delta=0.1)
        ff("-xerror", "-i", self.root / "final.mp4", "-f", "null", "-")

    def test_aroll_preserves_whole_audio_span(self):
        doc = {"aspect":"16:9", "output_size":[320,180], "source_video":str(self.video),
               "beats":[{"id":1,"start":0,"end":2,"dur":2,"text":"保留原始音轨。","clip_path":str(self.video)}]}
        save_json(self.root / "beats.json",doc)
        aroll_assemble.run(str(self.root))
        self.assertAlmostEqual(probe_duration(self.root / "final.mp4"),2,delta=0.1)

    def test_aroll_full_source_reuses_node_and_respects_resolution(self):
        source=self.video
        calls=[]
        class FakeProvider:
            def ref(self,reference,kind):
                calls.append(('ref',reference,kind))
            def upload(self,path):
                raise AssertionError('Full source should not create an upload node')
            def submit_video(self,model,prompt,**params):
                calls.append(('submit',params))
                return 'job'
            def get_status(self,job):
                return {'status':'completed','output':'libtv://test/result'}
            def download(self,reference,dest):
                shutil.copyfile(source,dest)
        doc={'provider':'libtv','mode':'aroll','aspect':'16:9','source_video':str(source),
             'source_node':'libtv://test/source','video_resolution':'480p',
             'beats':[{'id':1,'start':0,'end':2,'dur':2}]}
        save_json(self.root/'beats.json',doc)
        with patch('aroll_clips.get_provider',return_value=FakeProvider()):
            aroll_clips.run(str(self.root))
        params=next(c[1] for c in calls if c[0]=='submit')
        self.assertEqual(params['video'],'libtv://test/source')
        self.assertEqual(params['resolution'],'480p')

    def test_aroll_refuses_missing_clip(self):
        doc={"source_video":str(self.video),"beats":[{"id":1,"start":0,"dur":2}]}
        save_json(self.root/'beats.json',doc)
        with self.assertRaisesRegex(RuntimeError,"missing clip"):
            aroll_assemble.run(str(self.root))

    def test_aroll_refuses_silent_duration_truncation(self):
        doc={"source_video":str(self.video),"beats":[{"id":1,"start":0,"end":1,"dur":1,"clip_path":str(self.video)}]}
        save_json(self.root/'beats.json',doc)
        with self.assertRaisesRegex(RuntimeError,"differs from source"):
            aroll_assemble.run(str(self.root))

    def test_host_audio_and_green_screen_composition(self):
        green=self.root/'green.mp4'
        ff('-f','lavfi','-i','color=c=0x00B140:s=320x180:r=24:d=2','-c:v','libx264','-pix_fmt','yuv420p',green)
        own=self.root/'own.mp3'
        host_clips.adopt_model_audio(str(self.video),str(own))
        host_clips.composite(str(green),str(self.video),str(self.root/'composite.mp4'),(320,180))
        self.assertGreater(probe_duration(own),1.9)
        self.assertAlmostEqual(probe_duration(self.root/'composite.mp4'),2,delta=0.1)

    def test_chinese_caption_wraps_inside_safe_width(self):
        font=text_overlay._font(text_overlay.FONT_BOLD,30)
        draw=ImageDraw.Draw(Image.new('RGB',(320,180)))
        lines=text_overlay._wrap(draw,'这是一段没有空格但需要自动换行的中文字幕。',font,200)
        self.assertGreater(len(lines),1)
        self.assertTrue(all(draw.textlength(line,font=font)<=200 for line in lines))


if __name__=='__main__':
    unittest.main()
