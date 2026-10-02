import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('depth_bench',Path(__file__).with_name('bench-v41-depth-ab.py'))
bench=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

def stream(tokens=512, usage=True, done=True, thought=False):
    chunks=[{'choices':[{'delta':{'role':'assistant'}}]},
            {'choices':[{'delta':{'reasoning_content' if thought else 'content':'a'}}]},
            {'choices':[{'delta':{'content':'b'}}]},
            {'choices':[{'delta':{},'finish_reason':'length'}]}]
    if usage: chunks.append({'choices':[],'usage':{'prompt_tokens':20000,'completion_tokens':tokens}})
    data=b''.join(b'data: '+json.dumps(c).encode()+b'\n\n' for c in chunks)
    if done: data+=b'data: [DONE]\n\n'
    return io.BytesIO(data)

class ProtocolTests(unittest.TestCase):
    def call(self, response):
        with patch.object(bench.urllib.request,'urlopen',return_value=response), patch.object(bench.time,'perf_counter',side_effect=[0,1,2,3]):
            return bench.request('http://fixture',bench.body_for('test'),512)

    def test_usage_counts_not_sse_chunks(self):
        r=self.call(stream())
        self.assertEqual(r['completion_tokens'],512)
        self.assertEqual(len(r['events']),2)
        self.assertEqual(r['decode_proxy_tps'],511)
        self.assertEqual(r['ttft_s'],1)
        self.assertEqual(r['output'],'ab')

    def test_missing_usage_is_not_a_zero_speed_result(self):
        with self.assertRaisesRegex(RuntimeError,'Incomplete stream'):
            self.call(stream(usage=False))

    def test_dropped_connection_is_not_a_completed_trial(self):
        with self.assertRaisesRegex(RuntimeError,'Incomplete stream'):
            self.call(stream(done=False))

    def test_short_answer_is_not_compared_with_full_window(self):
        with self.assertRaisesRegex(RuntimeError,'Only 128'):
            self.call(stream(tokens=128))

    def test_unexpected_reasoning_is_refused(self):
        with self.assertRaisesRegex(RuntimeError,'Thinking was not disabled'):
            self.call(stream(thought=True))

    def test_sglang_plain_text_flush(self):
        with patch.object(bench.urllib.request,'urlopen',return_value=io.BytesIO(b'Cache flushed.\nPlease check backend logs.')):
            self.assertIsNone(bench.post('http://fixture','/flush_cache',{}))

    def test_unconfirmed_flush_is_refused(self):
        with patch.object(bench.urllib.request,'urlopen',return_value=io.BytesIO(b'not flushed')):
            with self.assertRaisesRegex(RuntimeError,'did not confirm'):
                bench.post('http://fixture','/flush_cache',{})

if __name__=='__main__': unittest.main()
