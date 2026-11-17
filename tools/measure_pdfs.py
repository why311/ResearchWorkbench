"""Measure the actual supplied PDFs with the production extraction worker."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]


def measure(path):
    started = time.monotonic()
    result = {'file': path.name, 'bytes': path.stat().st_size, 'pages': 0, 'characters': 0,
              'ocr_pages': 0, 'headings': 0, 'tables': 0, 'formula_candidates': 0, 'peak_rss_mb': 0}
    proc = subprocess.Popen([sys.executable, str(ROOT/'backend/pdf_worker.py'), str(path), '1', 'true'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    received, errors = queue.Queue(), []
    def read():
        for line in proc.stdout:
            received.put(line)
        received.put(None)
    def stderr():
        for line in proc.stderr:
            errors.append(line[-500:])
            del errors[:-10]
    threading.Thread(target=read, daemon=True).start()
    threading.Thread(target=stderr, daemon=True).start()
    expected, last_page = 0, time.monotonic()
    try:
        while True:
            if time.monotonic()-started > 1200 or time.monotonic()-last_page > 90:
                raise ValueError('extraction time budget exceeded')
            try:
                worker = psutil.Process(proc.pid)
                rss = sum(p.memory_info().rss for p in [worker,*worker.children(recursive=True)] if p.is_running())/1024**2
                result['peak_rss_mb'] = max(result['peak_rss_mb'], round(rss, 2))
                if rss > 1024:
                    raise ValueError('extraction memory budget exceeded')
            except psutil.NoSuchProcess:
                pass
            try:
                line = received.get(timeout=.2)
            except queue.Empty:
                continue
            if line is None:
                break
            item = json.loads(line)
            if item['type'] == 'metadata':
                expected = item['pages']
                continue
            last_page = time.monotonic()
            if item['page'] != result['pages']+1:
                raise ValueError('noncontiguous page sequence')
            result['pages'] += 1
            result['ocr_pages'] += item['method']=='ocr'
            result['characters'] += sum(len(b['text']) for b in item['blocks'])
            result['headings'] += sum(b.get('kind')=='heading' for b in item['blocks'])
            result['formula_candidates'] += sum(b.get('formula_candidate',False) for b in item['blocks'])
            result['tables'] += len(item['tables'])
            result['last_page_characters'] = sum(len(b['text']) for b in item['blocks'])
            if result['pages']==1:
                result['first_page_seconds'] = round(time.monotonic()-started, 2)
        code = proc.wait(timeout=5)
        result.update(expected_pages=expected, status='passed' if code==0 and expected==result['pages'] and result['characters'] else 'failed')
        if result['status']=='failed':
            result['error'] = ''.join(errors)[-1000:]
    except Exception as exc:
        result.update(status='failed',error=str(exc))
    finally:
        if proc.poll() is None:
            try:
                for child in psutil.Process(proc.pid).children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                pass
            proc.kill()
        proc.wait()
    result['seconds'] = round(time.monotonic()-started, 2)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    special=['UnderstandingDeepLearning_02_09_26_C.pdf','1706.03762v1_img.pdf','1706.03762v1.pdf','1706.03762v7.pdf']
    paths=[args.corpus/n for n in special]
    paths += [p for p in sorted(args.corpus.glob('*.pdf')) if p.name not in special][:20]
    report={'scope':'Actual complete extraction, not an OCR or scientific-answer accuracy score.', 'results':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(measure,p) for p in paths]
        for future in futures:
            item=future.result()
            report['results'].append(item)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(item['file'],item['status'],item['pages'],item['seconds'],flush=True)
