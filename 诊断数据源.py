#!/usr/bin/env python3
"""Run live feed checks without starting Streamlit."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from gold_intelligence.service import DataHub


def diagnose(cache_dir, wait_seconds=25):
    started = time.monotonic()
    hub = DataHub(cache_dir)
    initial = hub.snapshot()
    read_ms = round((time.monotonic()-started)*1000, 2)
    hub.refresh_due(force=True)
    first_result = None
    while time.monotonic() - started < wait_seconds:
        snap = hub.snapshot()
        if first_result is None and any(e['data'] and not initial['feeds'][k]['data'] for k,e in snap['feeds'].items()):
            first_result = round(time.monotonic()-started, 3)
        if not any(e['running'] for e in snap['feeds'].values()):
            break
        time.sleep(.05)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'cache_read_ms':read_ms,
              'first_new_data_seconds':first_result, 'elapsed_seconds':round(time.monotonic()-started,3),
              'feeds':{k:{'status':e['status'],'seconds':e['duration'],'error':e['error'],
                           'source':(e['data'] or {}).get('source'),
                           'observed_at':(e['data'] or {}).get('observed_at'),
                           'rows':len((e['data'] or {}).get('rows',[])),
                           'macro_series':list((e['data'] or {}).get('series',{})),
                           'news_items':len((e['data'] or {}).get('items',[]))}
                       for k,e in hub.snapshot()['feeds'].items()}}
    hub.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', default=str(Path(__file__).parent/'data'/'cache'))
    parser.add_argument('--output')
    args = parser.parse_args()
    report = diagnose(args.cache)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text+'\n', encoding='utf-8')
