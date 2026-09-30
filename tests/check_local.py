"""Isolated checks for the optional local installation boundary."""
import copy
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='jobfind-local-check-') as scratch:
    tmp = Path(scratch)
    cfg = json.loads((ROOT / 'config/example.json').read_text())
    cfg['data_dir'] = str(tmp / 'data')
    cfg['hermes'].update(job_id='fictional', output_dir=str(tmp / 'output'))
    assets = tmp / 'assets'
    assets.mkdir()
    (assets / 'mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    presentation = {'assets': {'/assets/logos/mark.svg': {'file':'mark.svg','public':False}},
                    'company_logos': {'fictional company': {'url':'/assets/logos/mark.svg','mode':'alpha'}},
                    'part_time_terms':['32 Std.', '80 %']}
    appearance = tmp / 'presentation.json'
    appearance.write_text(json.dumps(presentation))
    cfg['local'] = {'assets_dir':str(assets), 'presentation_file':str(appearance),
                    'session_cookie':'old_session', 'legacy_run_ids':True}
    configfile = tmp / 'config.json'
    configfile.write_text(json.dumps(cfg))
    os.environ['JOBFIND_CONFIG'] = str(configfile)
    sys.path.insert(0, str(ROOT / 'scripts/modules'))
    sys.path.insert(0, str(ROOT / 'hermes'))
    import config, local_settings, store, import_jobs
    item = {'company':'Fictional Company', 'hours':'32 Std. pro Woche'}
    local_settings.decorate_job(item)
    assert item['part_time_hint'] and item['company_logo_url'] == '/assets/logos/mark.svg'
    item['hours'] = '132 Std.'
    local_settings.decorate_job(item)
    assert not item['part_time_hint']
    assert local_settings.local_asset('/assets/logos/mark.svg')[2] is False
    assert local_settings.local_asset('/assets/logos/../../config.json') is None
    outside = tmp / 'outside.svg'
    outside.write_text('private')
    (assets / 'mark.svg').unlink()
    (assets / 'mark.svg').symlink_to(outside)
    try:
        local_settings.local_asset('/assets/logos/mark.svg')
        raise AssertionError('symlink escape accepted')
    except ValueError:
        pass
    (assets / 'mark.svg').unlink()
    (assets / 'mark.svg').write_text('<svg/>')
    importlib.reload(store)
    store.connect().close()
    output = tmp / 'output'
    output.mkdir()
    old = output / '2026-09-30_01-02-03.md'
    old.write_text('# Result\n\n## Response\n[SILENT]\n')
    assert import_jobs.import_file(old)['run_status'] == 'empty'
    assert store.has_run(old.stem)
    assert import_jobs.import_file(old)['already_imported']
    empty = output / '2026-09-30_01-02-04.md'
    empty.write_text('\n## Response\n{"schema_version":1,"run_status":"ok","jobs":[]}')
    assert import_jobs.import_file(empty)['run_status'] == 'empty'
    duplicate = output / '2026-09-30_01-02-05.md'
    duplicate.write_text('\n## Response\n{"schema_version":1,"run_status":"ok","jobs":[1],"jobs":[]}')
    try:
        import_jobs.import_file(duplicate)
        raise AssertionError('duplicate key accepted')
    except ValueError:
        pass
    bad = copy.deepcopy(cfg)
    bad['local']['session_cookie'] = 'x; insecure'
    configfile.write_text(json.dumps(bad))
    try:
        config.load_config(configfile)
        raise AssertionError('unsafe cookie name accepted')
    except ValueError:
        pass
print('Local checks passed: appearance, path boundary, symlink escape, cookie name, legacy deduplication and strict JSON.')
