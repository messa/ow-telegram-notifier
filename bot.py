#!/usr/bin/env python3

from aiohttp import ClientSession
from aiohttp.web import Application, RouteTableDef, AppRunner, TCPSite, Response, json_response, HTTPForbidden
from argparse import ArgumentParser
from asyncio import run, sleep, wait_for
import json
from logging import getLogger
import os
from pathlib import Path
import re
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
    p.add_argument('--port', type=int, help='bind port')
    p.add_argument('--host', help='bind host')
    p.add_argument('--dev', action='store_true', help='enable development mode')
    args = p.parse_args()
    setup_logging()
    cfg_path = args.conf or os.environ.get('CONF_FILE')
    conf = Configuration(cfg_path, args)
    try:
        run(async_main(conf))
    except Exception as e:
        logger.exception('Bot failed: %r', e)


class Configuration:

    def __init__(self, cfg_path, args):
        if cfg_path:
            cfg_path = Path(cfg_path)
            logger.debug('Loading configuration from %s', cfg_path)
            cfg = yaml.safe_load(cfg_path.read_text())
        else:
            cfg = {}
        self.bind_host = args.host or cfg.get('bind_host') or '127.0.0.1'
        self.bind_port = args.port or cfg.get('bind_port') or 5000
        self.graphql_endpoint = os.environ.get('GRAPHQL_ENDPOINT') or cfg.get('graphql_endpoint')
        self.development_mode_enabled = args.dev


async def async_main(conf):
    async with ClientSession() as session:
        current_alerts = await wait_for(retrieve_alerts(conf, session), 30)
        app = Application()
        app['conf'] = conf
        app['current_alerts'] = current_alerts
        app.router.add_routes(routes)
        runner = AppRunner(app)
        await runner.setup()
        try:
            site = TCPSite(runner, conf.bind_host, conf.bind_port)
            await site.start()
            logger.info('Listening on http://%s:%s', conf.bind_host, conf.bind_port)
            while True:
                await sleep(10)
                try:
                    new_alerts = await wait_for(retrieve_alerts(conf, session), 60)
                except Exception as e:
                    logger.info('Failed to retrieve alerts: %s', e)
                    await sleep(60)
                    continue
                logger.debug('Retrieved %d alerts', len(new_alerts))
                current_alerts[:] = new_alerts
        finally:
            await runner.cleanup()


@routes.get('/')
@routes.get('/ow-telegram-notifier/')
async def handle_index(request):
    return Response(text='Hello from ow-telegram-notifier!\n')


@routes.get('/ow-telegram-notifier/current-alerts')
async def handle_list_alerts(request):
    if not request.app['conf'].development_mode_enabled:
        raise HTTPForbidden(text='Available only in development mode')
    return json_response({'current_alerts': request.app['current_alerts']})


alert_query = dedent('''
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


async def retrieve_alerts(conf, session):
    post_kwargs = dict(
        headers={
            'Accept': 'application/json',
        },
        json={'query': alert_query},
        timeout=30)
    logger.debug('Retrieving alerts from %s', redacted(conf.graphql_endpoint))
    async with session.post(conf.graphql_endpoint, **post_kwargs) as resp:
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


def redacted(s):
    assert isinstance(s, str)
    s = re.sub(r'(https?://[^@/]+:)[^@/]+(@)', r'\1...\2', s)
    return s


if __name__ == '__main__':
    main()
