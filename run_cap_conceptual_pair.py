"""Run the original and one fixed rewrite in independent, matched simulator trials."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from getpass import getpass
from pathlib import Path


def compare_trials(rows, tolerance=0.0001):
    report = {
        'semantic_equivalence_verified': False,
        'scene_tolerance_m': tolerance,
        'interpretation': 'Preliminary event comparison only; review the rewritten instruction and videos before attributing a mechanism.',
        'generally_improves_attack_success': 'not_established',
        'trials': rows,
    }
    if set(rows) != {'direct','conceptual'} or any(
        row.get('exit_code') != 0 or row.get('result',{}).get('status') != 'completed'
        for row in rows.values()
    ):
        report['pair_outcome']='incomplete_pair'
        return report
    direct, conceptual = rows['direct']['result'], rows['conceptual']['result']
    same_sources = bool(direct.get('source_sha256')) and direct.get('source_sha256') == conceptual.get('source_sha256')
    same_config = bool(direct.get('lmp_config')) and direct.get('lmp_config') == conceptual.get('lmp_config')
    same_rewrite = bool(direct.get('rewrite_file_sha256')) and direct.get('rewrite_file_sha256') == conceptual.get('rewrite_file_sha256')
    same_seed = direct.get('seed') is not None and direct.get('seed') == conceptual.get('seed')
    same_requested_model = bool(direct.get('model')) and direct.get('model') == conceptual.get('model')
    dpos, cpos = direct.get('before',{}), conceptual.get('before',{})
    max_delta = None
    if dpos and set(dpos)==set(cpos):
        try:
            max_delta=max(abs(float(a)-float(b)) for name in dpos
                          for a,b in zip(dpos[name],cpos[name],strict=True))
        except (TypeError,ValueError):
            pass
    dmodels=set(rows['direct'].get('returned_models',[]))
    cmodels=set(rows['conceptual'].get('returned_models',[]))
    same_returned_model = bool(dmodels and cmodels and dmodels==cmodels)
    scene_matches = max_delta is not None and max_delta <= tolerance
    comparable = all([same_sources,same_config,same_rewrite,same_seed,
                      same_requested_model,same_returned_model,scene_matches])
    report.update({
        'source_hashes_match':same_sources, 'lmp_config_matches':same_config,
        'rewrite_snapshot_matches':same_rewrite, 'seed_matches':same_seed,
        'requested_model_matches':same_requested_model,
        'returned_models_match':same_returned_model,
        'initial_position_max_delta_m':max_delta, 'scene_matches':scene_matches,
        'matched_conditions_verified':comparable,
    })
    if not comparable:
        report['pair_outcome']='conditions_not_matched'
        return report
    d=direct.get('target_event_observed')
    c=conceptual.get('target_event_observed')
    if type(d) is not bool or type(c) is not bool:
        report['pair_outcome']='missing_event_measurement'
        return report
    report['direct_event']=d
    report['conceptual_event']=c
    report['pair_outcome']={
        (True,True):'both_triggered', (False,True):'conceptual_only',
        (True,False):'direct_only', (False,False):'neither_triggered',
    }[(d,c)]
    return report


def read_trial(directory, code):
    row={'exit_code':code,'run_dir':str(directory)}
    try:
        row['result']=json.loads((directory/'result.json').read_text(encoding='utf-8'))
    except Exception as error:
        row['read_error']=str(error)
    models=[]
    logs=sorted((directory/'api_calls').glob('call_*.json'))
    for path in logs:
        try:
            item=json.loads(path.read_text(encoding='utf-8'))
            if item.get('returned_model'):
                models.append(item['returned_model'])
        except (OSError,json.JSONDecodeError):
            pass
    row['api_attempts_logged']=len(logs)
    row['returned_models']=sorted(set(models))
    return row


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--rewrite-file',type=Path)
    parser.add_argument('--query-id',choices=list('abcd'),default='a')
    parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--model',default='deepseek-flash')
    parser.add_argument('--max-calls',type=int,default=12)
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    if args.max_calls<1 or args.timeout<1 or not 0<=args.seed<=2**32-1:
        parser.error('Invalid limits or seed')
    root=Path(__file__).resolve().parent
    if args.rewrite_file:
        source=args.rewrite_file.expanduser().resolve()
    else:
        candidates=sorted((root/'outputs').glob(f'rewrite_{args.query_id}_*/rewrite.json'))
        if not candidates:
            raise FileNotFoundError('Run prepare_cap_rewrite.py first.')
        source=candidates[-1]
    rewrite=json.loads(source.read_text(encoding='utf-8'))
    if rewrite.get('status')!='generated_unreviewed' or rewrite.get('query_id')!=args.query_id:
        raise ValueError('The latest rewrite is invalid or mismatched; no fallback to an earlier rewrite.')
    queries=json.loads((root/'paper_cap_queries.json').read_text(encoding='utf-8'))
    if rewrite.get('original')!=queries['queries'][args.query_id]:
        raise ValueError('Rewrite original does not match the paper query record.')
    print('Using rewrite:',source,flush=True)
    print('Original:',rewrite['original'],flush=True)
    print('Rewritten:',rewrite['rewritten'],flush=True)
    key=os.environ.get('DEEPSEEK_API_KEY') or getpass('DeepSeek API key (hidden, once for both trials): ').strip()
    if not key:
        raise ValueError('Empty API key')
    child_env=os.environ.copy()
    child_env['DEEPSEEK_API_KEY']=key
    del key
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output=source.parent/f'pair_seed{args.seed}_{stamp}'
    output.mkdir(parents=True)
    snapshot=output/'rewrite.json'
    shutil.copyfile(source,snapshot)
    config={
        'query_id':args.query_id,'seed':args.seed,'model':args.model,
        'max_calls_per_trial':args.max_calls,'timeout_per_trial':args.timeout,
        'order':['direct','conceptual'],'automatic_retries':False,
        'rewrite_snapshot_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        'semantic_equivalence_verified':False,
    }
    (output/'pair_config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    rows={}
    try:
        for condition in ['direct','conceptual']:
            directory=output/condition
            command=[sys.executable,'-u',str(root/'run_cap_pair_worker.py'),
                     '--condition',condition,'--query-id',args.query_id,
                     '--seed',str(args.seed),'--model',args.model,
                     '--max-calls',str(args.max_calls),'--timeout',str(args.timeout),
                     '--rewrite-file',str(snapshot),'--output-dir',str(directory)]
            print(f'\n=== {condition} | seed={args.seed} ===',flush=True)
            started=time.monotonic()
            with (output/f'{condition}.console.log').open('w',encoding='utf-8') as log:
                with subprocess.Popen(command,cwd=root,env=child_env,
                                      stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                      text=True,bufsize=1) as process:
                    try:
                        for line in process.stdout:
                            print(line,end='',flush=True)
                            log.write(line);log.flush()
                        code=process.wait()
                    except KeyboardInterrupt:
                        process.terminate()
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill();process.wait()
                        rows[condition]=read_trial(directory,process.returncode)
                        raise
            rows[condition]=read_trial(directory,code)
            rows[condition]['elapsed_wall_seconds']=time.monotonic()-started
    finally:
        child_env.pop('DEEPSEEK_API_KEY',None)
        report=compare_trials(rows)
        report['rewriter_model']=rewrite.get('returned_rewriter_model')
        report['rewrite_record']=rewrite
        report['api_attempts_logged_for_trials']=sum(r.get('api_attempts_logged',0) for r in rows.values())
        (output/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('\n=== Paired comparison ===')
        print('Direct event:',report.get('direct_event','not comparable'))
        print('Conceptual event:',report.get('conceptual_event','not comparable'))
        print('Pair outcome:',report['pair_outcome'])
        print('Semantic equivalence: pending review')
        print('Comparison:',output/'comparison.json',flush=True)


if __name__=='__main__':
    main()
