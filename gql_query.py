#!/usr/bin/env python3

from argparse import ArgumentParser
import json
from logging import getLogger
from pathlib import Path
from reprlib import repr as smart_repr
import requests
import sys
from textwrap import dedent
import yaml


logger = getLogger(__name__)


def main():
    p = ArgumentParser()
    p.add_argument('--conf', metavar='FILE', help='path to configuration file')
    args = p.parse_args()
    setup_logging()
    cfg_path = Path(args.conf or '../private/ow_telegram_notifier.yaml')
    cfg = yaml.safe_load(cfg_path.read_text())
    rs = requests.session()
    query = dedent('''
        {
          activeAlerts {
            pageInfo {
              hasNextPage
            }
            edges {
              node {
                id
                alertId
                alertType
                streamId
                itemPath
                lastItemUnit
                lastItemValueJSON
              }
            }
          }
        }
    ''')
    r = rs.post(cfg['graphql_endpoint'], headers={'Accept': 'application/json'}, json={'query': query})
    r.raise_for_status()
    rj = r.json()
    logger.debug('GQL response: %s', smart_repr(rj))
    if rj.get('error') or rj.get('errors'):
        sys.exit(f'Received error: {rj}')
    alerts = [edge['node'] for edge in rj['data']['activeAlerts']['edges']]
    for n, alert in enumerate(alerts, start=1):
        print(f'Alert {n}/{len(alerts)}: {json.dumps(alert)}')


log_format = '%(asctime)s %(name)-25s %(levelname)5s: %(message)s'


def setup_logging():
    from logging import DEBUG, getLogger, StreamHandler, Formatter
    getLogger('').setLevel(DEBUG)
    h = StreamHandler()
    h.setFormatter(Formatter(log_format))
    h.setLevel(DEBUG)
    getLogger('').addHandler(h)


if __name__ == '__main__':
    main()
