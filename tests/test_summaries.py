import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('summaries',ROOT/'scripts/summarize_papers.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
TEMP_ROOT=ROOT/'.local'

class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): TEMP_ROOT.mkdir(exist_ok=True)
    def settings(self):
        return dict(model='test-model',prompt_version='v3',accepted_prompt_versions=['v1','v2','v3'],mode='automatic',max_per_run=100,max_output_tokens=800,max_abstract_chars=12000,workers=1,max_run_seconds=30,max_content_repairs=1,daily_budget_cny=.35,annual_budget_cny=150,pricing_cny_per_million=dict(input_miss=2,input_hit=.04,output=8))
    def paper(self,pid='new',abstract='A short abstract.'):
        return dict(id=pid,title='Imaging study '+pid,abstract=abstract,published='2026-10-23',first_seen='2026-10-23T05:00:00Z')
    def response(self,text='本研究关注语言加工的脑网络，结果显示不同任务情境下的网络联系会发生变化。'):
        return dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(dict(summary_zh=text))))],usage=dict(prompt_tokens=1000,completion_tokens=200))
    def run_batch(self,papers,cache,responses,settings=None,day='2026-10-23'):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder,patch.object(m,'ROOT',Path(folder)):
            with patch.object(m,'complete',side_effect=responses) as api:
                m.generate_all(papers,cache,settings or self.settings(),'test-key',Path(folder)/'cache.json',day)
                return api.call_count
    def test_source_hash_changes(self):
        self.assertNotEqual(m.source_hash(self.paper(abstract='one')),m.source_hash(self.paper(abstract='two')))
    def test_word_counts_are_not_acceptance_gates(self):
        for size in (20,90,149,150,200,201,320,600): self.assertEqual(m.validate_summary('文'*size,''),'文'*size)
        for value in ('','  ','English only',None):
            with self.assertRaises(ValueError):m.validate_summary(value,'')
    def test_outside_target_never_causes_paid_retry(self):
        cache=dict(entries={},ledger=[])
        calls=self.run_batch([self.paper(str(n)) for n in range(3)],cache,[self.response('文'*n) for n in (90,250,600)])
        self.assertEqual(calls,3);self.assertEqual(len(cache['ledger']),3)
        self.assertEqual(sorted(len(e['summary_zh']) for e in cache['entries'].values()),[90,250,600])
    def test_daily_and_annual_budget_limits(self):
        settings=self.settings();cache=dict(ledger=[dict(date='2026-10-23',budget_charge_cny=.34)])
        self.assertFalse(m.within_budget(cache,'2026-10-23',.02,settings))
        self.assertTrue(m.within_budget(cache,'2026-10-24',.02,settings))
        self.assertFalse(m.within_budget(dict(ledger=[dict(date='2026-01-01',budget_charge_cny=150)]),'2026-10-23',.01,settings))
    def test_backfill_separate_from_daily_but_inside_annual_budget(self):
        settings=self.settings();settings['backfill']=dict(id='initial',through_date='2026-10-23',budget_cny=20)
        cache=dict(ledger=[dict(date='2026-10-23',budget_charge_cny=.35),dict(date='2026-10-23',budget_charge_cny=19.9,budget_group='initial')])
        self.assertFalse(m.within_budget(cache,'2026-10-23',.01,settings))
        self.assertTrue(m.within_budget(cache,'2026-10-23',.05,settings,'initial'))
        self.assertFalse(m.within_budget(cache,'2026-10-23',.11,settings,'initial'))
        self.assertFalse(m.within_budget(cache,'2026-10-23',.01,settings,'unknown'))
        self.assertEqual(m.budget_group(self.paper(),settings),'initial')
        newer=self.paper();newer['first_seen']='2026-10-23T16:01:00Z';self.assertIsNone(m.budget_group(newer,settings))
        settings['annual_budget_cny']=20;self.assertFalse(m.within_budget(cache,'2026-10-23',.01,settings,'initial'))
    def test_cache_input_pricing(self):
        self.assertAlmostEqual(m.usage_cost(dict(prompt_tokens=1000,prompt_cache_hit_tokens=500,completion_tokens=200),self.settings()['pricing_cny_per_million']),.00262)
    def test_stale_summary_and_missing_abstract_have_distinct_counts(self):
        p=self.paper();p['summary_zh']='stale';data=dict(papers=[p,self.paper('blank','')])
        m.attach(data,dict(entries={'new':dict(status='success',source_hash='old')}),self.settings())
        self.assertNotIn('summary_zh',p)
        self.assertEqual(data['summary_status']['pending'],1);self.assertEqual(data['summary_status']['no_abstract'],1)
        self.assertEqual(data['summary_status']['eligible'],1)
    def test_valid_old_success_and_metadata_are_not_rewritten(self):
        p=self.paper();entry=dict(status='success',summary_zh='原'*318,source_hash=m.source_hash(p),prompt_version='v1',model='old',generated_at='then',review_status='reviewed')
        cache=dict(entries={'new':entry},ledger=[]);before=copy.deepcopy(cache)
        self.assertEqual(self.run_batch([p],cache,[]),0)
        m.attach(dict(papers=[p]),cache,self.settings());self.assertEqual(p['summary_zh'],entry['summary_zh']);self.assertEqual(cache,before)
    def test_changed_abstract_is_summarized_again(self):
        p=self.paper();entry=dict(status='success',summary_zh='原',source_hash=m.source_hash(p),prompt_version='v1');p['abstract']='Updated abstract.'
        cache=dict(entries={'new':entry},ledger=[]);self.assertEqual(self.run_batch([p],cache,[self.response()]),1)
        self.assertEqual(cache['entries']['new']['source_hash'],m.source_hash(p))
    def test_reserve_written_before_call(self):
        cache=dict(entries={},ledger=[])
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            path=Path(folder)/'cache.json'
            def provider(*args):
                saved=json.loads(path.read_text(encoding='utf-8'));self.assertEqual(saved['ledger'][0]['status'],'reserved');self.assertGreater(saved['ledger'][0]['budget_charge_cny'],0);return self.response()
            with patch.object(m,'complete',side_effect=provider):m.generate_all([self.paper()],cache,self.settings(),'test-key',path,'2026-10-23')
        self.assertEqual(cache['ledger'][0]['status'],'success')
    def test_concurrent_reservations_cannot_overspend(self):
        settings=self.settings();settings['workers']=2;settings['daily_budget_cny']=m.estimate_reservation(m.messages_for(self.paper('a')),settings)*1.5
        cache=dict(entries={},ledger=[])
        self.assertEqual(self.run_batch([self.paper('a'),self.paper('b')],cache,[self.response()],settings),1)
        self.assertLessEqual(sum(e['budget_charge_cny'] for e in cache['ledger']),settings['daily_budget_cny'])
    def test_uncertain_network_retains_reserve_no_immediate_retry(self):
        cache=dict(entries={},ledger=[]);p=self.paper()
        self.assertEqual(self.run_batch([p],cache,[URLError('connection lost')]),1)
        self.assertGreater(cache['ledger'][0]['budget_charge_cny'],0)
        self.assertEqual(self.run_batch([p],cache,[]),0)
        self.assertEqual(self.run_batch([p],cache,[self.response()],day='2026-10-24'),1)
    def test_missing_usage_keeps_reserve(self):
        cache=dict(entries={},ledger=[]);response=self.response();response.pop('usage')
        self.run_batch([self.paper()],cache,[response]);self.assertGreater(cache['ledger'][0]['budget_charge_cny'],.01)
    def test_content_error_is_repaired_once(self):
        with self.assertRaisesRegex(ValueError,'unsupported number'):m.validate_summary('本研究纳入999名参与者。','10 participants')
        cache=dict(entries={},ledger=[])
        self.assertEqual(self.run_batch([self.paper()],cache,[self.response('本研究纳入999名参与者。'),self.response()]),2)
        self.assertEqual(cache['entries']['new']['status'],'success');self.assertEqual([e['content_repair'] for e in cache['ledger']],[0,1])
    def test_spelled_out_numbers(self):
        self.assertTrue({'17','97','7'}<=m.numeric_evidence('Seventeen patients and ninety-seven controls, in seven regions.'))
        self.assertNotIn('3',m.numeric_evidence('one and two'))
    def test_publisher_decimal_spacing_and_spelled_ordinals(self):
        source='Ambient PM2 .5 and PM10. Diagnostic Manual, Fifth Edition; scale Fourth Edition.'
        self.assertTrue({'2.5','10','5','4'}<=m.numeric_evidence(source))
        self.assertEqual(m.validate_summary('本研究考察PM2.5和PM10，并依据DSM-5分类。',source),'本研究考察PM2.5和PM10，并依据DSM-5分类。')
    def test_no_abstract_means_no_provider_call(self):
        self.assertEqual(self.run_batch([self.paper(abstract='')],dict(entries={},ledger=[]),[]),0)
    def test_resumed_content_review_includes_corrective_context(self):
        p=self.paper();cache=dict(entries={'new':dict(status='pending',source_hash=m.source_hash(p),prompt_version='v3',reason='Summary introduced an unsupported number')},ledger=[])
        def provider(messages,*args):
            self.assertEqual(messages[-1]['content'],m.CONTENT_CORRECTION)
            return self.response()
        self.assertEqual(self.run_batch([p],cache,provider),1)
        self.assertEqual(cache['entries']['new']['status'],'success')

if __name__=='__main__':unittest.main()
