"""Isolated API/budget integration checks; no network or production credentials."""
import copy
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRATCH=tempfile.TemporaryDirectory(prefix='jobfind-api-test-')
TEMP=Path(SCRATCH.name)
cfg=json.loads((ROOT/'config/example.json').read_text())
cfg['data_dir']=str(TEMP/'data')
cfg['hermes']['output_dir']=str(TEMP/'output')
cfg['matching']={'required_task_terms':['UX'],'excluded_company_terms':['Fictional Finance'],'excluded_job_terms':[]}
KEY=TEMP/'test-key'
KEY.write_text('fictional-test-secret')
KEY.chmod(0o600)
cfg['api_search']={'enabled':True,'credential_file':str(KEY),'budget_file':str(TEMP/'real-budget.sqlite3'),
                   'monthly_budget_usd':5,'min_interval_hours':6,'max_candidates':6,'max_web_searches':2}
CONFIG_FILE=TEMP/'config.json'
CONFIG_FILE.write_text(json.dumps(cfg))
os.environ['JOBFIND_CONFIG']=str(CONFIG_FILE)
sys.path[:0]=[str(ROOT/'scripts/modules'),str(ROOT/'hermes')]
import config
import store
import api_search as api
import context
from import_jobs import scan_output

URL='https://example.org/jobs/ux-1'
JOB=dict(title='UX Designer',company='Fictional Public Services',original_url=URL,
         summary='UX und Bedienkonzepte für digitale Bürgerdienste gestalten.',location='Beispielstadt',score=8)

def response(value, *, search=False, usage=True):
    output=[]
    if search: output.append({'type':'web_search_call','action':{'sources':[{'url':URL}]}})
    output.append({'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]})
    result={'status':'completed','output':output}
    if usage: result['usage']={'input_tokens':100,'output_tokens':40}
    return result

def original(url):
    assert url==URL
    description='UX und Bedienkonzepte für digitale Bürgerdienste gestalten. Nutzeroberflächen entwickeln. '*5
    data={'@type':'JobPosting','title':JOB['title'],'description':description,
          'jobLocation':{'address':{'addressLocality':'Beispielstadt'}}}
    return {'http':200,'error':'','final_url':url,'body':'<html><h1>UX Designer</h1><script type="application/ld+json">'+json.dumps(data)+'</script></html>'}

class Checks(unittest.TestCase):
    def setUp(self):
        with store.connect() as db:
            for table in ('job_feedback','job_likes','company_profiles','company_logos','jobs','runs'):
                db.execute('DELETE FROM '+table)
        path=Path(config.CONFIG['api_search']['budget_file'])
        if path.exists(): path.unlink()

    def budget(self, amount=5):
        return api.Budget(TEMP/('budget-'+os.urandom(5).hex()+'.sqlite3'),amount,'Europe/Berlin')

    def test_concurrent_reservations_cannot_overspend(self):
        budget=self.budget(1)
        def reserve(_):
            try: return budget.reserve(250000)
            except api.BudgetExceeded: return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            tokens=list(pool.map(reserve,range(12)))
        self.assertEqual(sum(bool(t) for t in tokens),4)
        self.assertEqual(budget.status()['accounted_usd'],1)
        with self.assertRaises(api.BudgetExceeded): budget.reserve(1)

    def test_unknown_usage_and_timeout_keep_full_reservation(self):
        budget=self.budget()
        token=budget.reserve(100000)
        budget.settle(token,{})
        self.assertEqual(budget.status()['accounted_usd'],.1)
        def fail(*args): raise api.SearchError('openai_request_failed')
        with self.assertRaises(api.SearchError): api.request_json('JSON',budget,'fictional',searches=2,sender=fail)
        self.assertGreater(budget.status()['accounted_usd'],.2)

    def test_usage_settlement_and_month_boundary(self):
        budget=self.budget(1)
        token=budget.reserve(100000)
        budget.settle(token,response({},search=True))
        self.assertEqual(budget.status()['accounted_usd'],api.cost(100,40,1)/1000000)
        with sqlite3.connect(budget.path) as db: db.execute("UPDATE charges SET month='2000-01'")
        self.assertEqual(budget.status()['accounted_usd'],0)

    def test_unexpected_usage_stops_month(self):
        budget=self.budget(1)
        token=budget.reserve(100)
        with self.assertRaises(api.SearchError): budget.settle(token,response({}))
        with self.assertRaises(api.BudgetExceeded): budget.reserve(1)

    def test_call_bounds_and_no_keys_in_payload(self):
        budget=self.budget()
        def sender(body,key):
            self.assertEqual(key,'fictional-test-secret')
            self.assertNotIn(key,body.decode())
            request=json.loads(body)
            self.assertFalse(request['store'])
            self.assertEqual(request['max_tool_calls'],2)
            self.assertEqual(request['max_output_tokens'],api.OUTPUT_TOKENS)
            self.assertEqual(request['model'],api.MODEL)
            return response({'candidates':[]},search=True)
        result,urls=api.request_json('Return JSON',budget,'fictional-test-secret',searches=2,sender=sender)
        self.assertEqual(result,{'candidates':[]})
        self.assertIn(URL,urls)
        before=budget.status()
        with self.assertRaises(api.SearchError): api.request_json('x'*(api.MAX_BODY+1),budget,'fictional',sender=sender)
        self.assertEqual(budget.status(),before)

    def test_search_must_actually_happen(self):
        with self.assertRaises(api.SearchError):
            api.request_json('Return JSON',self.budget(),'fictional',searches=2,sender=lambda *a:response({'candidates':[]}))

    def test_original_grounding_and_profile_filters(self):
        candidate={k:JOB[k] for k in ['title','company','original_url']}
        checked,unavailable=api.checked_candidates([candidate],{URL},6,original)
        self.assertEqual(len(checked),1)
        self.assertEqual(unavailable,0)
        payload=dict(schema_version=1,run_status='ok',jobs=[dict(JOB)],company_profiles=[],error='')
        self.assertEqual(len(api.grounded_result(payload,checked)['jobs']),1)
        forged=copy.deepcopy(payload)
        forged['jobs'][0]['original_url']='https://example.org/jobs/not-fetched'
        with self.assertRaises(api.SearchError): api.grounded_result(forged,checked)
        forged=copy.deepcopy(payload)
        forged['jobs'][0]['company']='Unrelated Employer'
        with self.assertRaises(api.SearchError): api.grounded_result(forged,checked)
        annotated=copy.deepcopy(checked)
        annotated[0]['company']+=' (Portal listing)'
        self.assertEqual(len(api.grounded_result(payload,annotated)['jobs']),1)
        payload['jobs'][0]['location']='Fernstadt'
        self.assertEqual(api.grounded_result(payload,checked)['jobs'],[])
        payload['jobs'][0]['location']='Musterhausen'
        self.assertEqual(api.grounded_result(payload,checked)['jobs'],[], 'An allowed city still needs evidence in the original ad')
        self.assertEqual(api.checked_candidates([candidate],set(),6,original),([],1))

    def test_complete_run_import_spacing_and_budget(self):
        candidate={k:JOB[k] for k in ['title','company','original_url']}
        calls=[]
        def sender(body,key):
            calls.append(json.loads(body))
            return response({'candidates':[candidate]},search=True) if len(calls)==1 else response(
                dict(schema_version=1,run_status='ok',jobs=[dict(JOB)],company_profiles=[],error=''))
        result=api.run_search(force=True,sender=sender,fetcher=original)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['imported'],1)
        self.assertEqual(store.list_jobs()[0]['company'],JOB['company'])
        self.assertEqual(api.run_search(sender=sender)['status'],'skipped_interval')
        self.assertEqual(len(calls),2)
        budget=api.Budget(Path(cfg['api_search']['budget_file']),5,'Europe/Berlin')
        budget.reserve(int(budget.status()['remaining_usd']*1000000))
        self.assertEqual(api.run_search(force=True,sender=sender)['status'],'skipped_budget')
        self.assertEqual(len(calls),2,'Force cannot bypass the budget')

    def test_blocked_sources_are_error_and_no_agent_reports_skipped(self):
        candidate={k:JOB[k] for k in ['title','company','original_url']}
        result=api.run_search(force=True,sender=lambda *a:response({'candidates':[candidate]},search=True),
            fetcher=lambda url:{'http':403,'error':'blocked','body':''})
        self.assertEqual(result['status'],'error')
        self.assertEqual(store.metadata()['last_run']['status'],'error')
        folder=config.CONFIG['output_path']
        folder.mkdir(exist_ok=True)
        report=folder/'2026-01-01_00-00-00.md'
        report.write_text('Hermes no-agent execution summary')
        os.utime(report,(0,0))
        self.assertEqual(scan_output()['errors'],0)

    def test_key_permissions_and_opt_in_validation(self):
        KEY.chmod(0o644)
        try:
            with self.assertRaises(ValueError): api.run_search(force=True)
        finally: KEY.chmod(0o600)
        original_cfg=CONFIG_FILE.read_text()
        try:
            candidate=copy.deepcopy(cfg)
            candidate.pop('api_search')
            CONFIG_FILE.write_text(json.dumps(candidate))
            self.assertFalse(config.load_config(CONFIG_FILE)['api_search']['enabled'])
            for value in (0,-1,True,float('nan')):
                candidate['api_search']=dict(cfg['api_search'],monthly_budget_usd=value)
                CONFIG_FILE.write_text(json.dumps(candidate))
                with self.assertRaises(ValueError): config.load_config(CONFIG_FILE)
        finally: CONFIG_FILE.write_text(original_cfg)

    def test_rotation_advances_independent_of_six_hour_spacing(self):
        previous=config.CONFIG['research']
        config.CONFIG['research']=dict(max_search_queries=8,max_listing_checks=12,directions_per_run=2,
            directions=[dict(id=str(i),label=str(i),query_terms=['UX']) for i in range(6)])
        try:
            covered=set()
            for step in range(6):
                covered.update(d['id'] for d in context.build_research_plan(rotation_step=step)['directions'])
            self.assertEqual(covered,{str(i) for i in range(6)})
        finally: config.CONFIG['research']=previous

    def test_daily_import_limit_skips_paid_requests(self):
        previous=config.CONFIG['max_new_jobs_per_day']
        config.CONFIG['max_new_jobs_per_day']=1
        try:
            store.import_run('already-full',store.now_iso(),'ok',[JOB])
            def forbidden(*args): self.fail('No paid request after reaching daily import limit')
            self.assertEqual(api.run_search(force=True,sender=forbidden)['status'],'skipped_daily_limit')
        finally: config.CONFIG['max_new_jobs_per_day']=previous

if __name__=='__main__':
    unittest.main(verbosity=2)
