#!/usr/bin/env python3

from aiohttp import ClientSession
from aiohttp.web import Application, RouteTableDef, AppRunner, TCPSite, Response, json_response
from argparse import ArgumentParser
from asyncio import run, sleep, wait_for
import json
from logging import getLogger
from pathlib import Path
from reprlib import repr as smart_repr
import requests
import sys
from textwrap import dedent
import yaml


logger = getLogger(__name__)

routes = RouteTableDef()


def main():
    p = ArgumentParser()
    p.add_argument('--conf', metavar='FILE', help='path to configuration file')
    p.add_argument('--port', default=5000, type=int, help='bind port')
    p.add_argument('--host', default='127.0.0.1', help='bind host')
    args = p.parse_args()
    setup_logging()
    cfg_path = Path(args.conf or '../private/ow_telegram_notifier.yaml')
    logger.debug('Loading configuration from %s', cfg_path)
    cfg = yaml.safe_load(cfg_path.read_text())
    try:
        run(async_main(cfg, args.host, args.port))
    except Exception as e:
        logger.exception('Bot failed: %r', e)


async def async_main(cfg, bind_host, bind_port):
    app = Application()
    app.router.add_routes(routes)
    runner = AppRunner(app)
    await runner.setup()
    try:
        site = TCPSite(runner, bind_host, bind_port)
        await site.start()
        async with ClientSession() as session:
            alerts = await wait_for(retrieve_alerts(cfg, session), 60)
            while True:
                try:
                    new_alerts = await wait_for(retrieve_alerts(cfg, session), 60)
                except Exception as e:
                    logger.info('Failed to retrieve alerts: %s', e)
                    await sleep(60)
                    continue
                logger.debug('Retrieved %d alerts', len(new_alerts))
                alerts = new_alerts
                app['alerts'] = alerts
                await sleep(10)
    finally:
        await runner.cleanup()



@routes.get('/')
async def handle_index(request):
    return Response(text='Hello from ow-telegram-notifier!\n')


@routes.get('/ow-telegram-notifier/alerts')
async def handle_list_alerts(request):
    return json_response({'alerts': request.app['alerts']})


async def retrieve_alerts(cfg, session):
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
    headers = {
        'Accept': 'application/json',
    }
    async with session.post(cfg['graphql_endpoint'], headers=headers, json={'query': query}, timeout=30) as resp:
        resp.raise_for_status()
        rj = await resp.json()
        logger.debug('GQL response: %s', smart_repr(rj))
        if rj.get('error') or rj.get('errors'):
            raise Exception(f'Received error: {rj}')
        alerts = [edge['node'] for edge in rj['data']['activeAlerts']['edges']]
        return alerts


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
