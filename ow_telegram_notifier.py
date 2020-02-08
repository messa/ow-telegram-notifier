#!/usr/bin/env python3

from aiohttp import ClientSession
from aiohttp.web import Application, RouteTableDef, AppRunner, TCPSite, Response, json_response, HTTPForbidden
from argparse import ArgumentParser
from asyncio import run, sleep, wait_for
try:
    import simplejson as json
except ImportError:
    import json
from logging import getLogger
import os
from pathlib import Path
import re
from reprlib import repr as smart_repr
import sys
from textwrap import dedent
from time import monotonic as monotime
import yaml


logger = getLogger(__name__)

routes = RouteTableDef()


def main():
    p = ArgumentParser()
    p.add_argument('--conf', metavar='FILE', help='path to configuration file')
    p.add_argument('--port', type=int, help='bind port')
    p.add_argument('--host', help='bind host')
    p.add_argument('--dev', action='store_true', help='enable development mode')
    p.add_argument('--verbose', '-v', action='store_true', help='enable more logging')
    args = p.parse_args()
    setup_logging(verbose=args.verbose)
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
        env = os.environ.get
        self.bind_host = args.host or env('BIND_HOST') or cfg.get('bind_host') or '127.0.0.1'
        self.bind_port = int(args.port or env('BIND_PORT') or cfg.get('bind_port') or 5000)
        self.graphql_endpoint = env('GRAPHQL_ENDPOINT') or cfg.get('graphql_endpoint')
        self.public_url = env('PUBLIC_URL') or cfg.get('public_url')
        self.telegram_api_token = env('TELEGRAM_API_TOKEN') or cfg.get('telegram_api_token')
        self.telegram_chat_id = env('TELEGRAM_CHAT_ID') or cfg.get('telegram_chat_id')
        self.development_mode_enabled = args.dev
        self.sleep_interval = float(cfg.get('sleep_interval') or 5)


async def async_main(conf):
    async with ClientSession() as session:
        current_alerts = await wait_for(retrieve_alerts(conf, session), 30)
        logger.debug('Initial alerts:\n%s', '\n'.join(json.dumps(a) for a in current_alerts))
        app = Application()
        app['conf'] = conf
        app['current_alerts'] = current_alerts
        app['client_session'] = session
        app.router.add_routes(routes)
        runner = AppRunner(app)
        await runner.setup()
        try:
            site = TCPSite(runner, conf.bind_host, conf.bind_port)
            await site.start()
            logger.info('Listening on http://%s:%s', conf.bind_host, conf.bind_port)
            await setup_telegram_webhook(conf, session)
            while True:
                await sleep(conf.sleep_interval)
                try:
                    new_alerts = await wait_for(retrieve_alerts(conf, session), 60)
                except Exception as e:
                    logger.info('Failed to retrieve alerts: %s', e)
                    await sleep(60)
                    continue
                await notify_about_alerts(conf, session, current_alerts, new_alerts)
                current_alerts[:] = new_alerts
        finally:
            await runner.cleanup()


async def notify_about_alerts(conf, session, old_alerts, new_alerts):
    if not conf.telegram_chat_id:
        logger.info('telegram_chat_id not configured')
        return
    message_texts = generate_message_texts(old_alerts, new_alerts)
    for txt in message_texts:
        await tg_request(conf, session, 'sendMessage', {
            'chat_id': conf.telegram_chat_id,
            'text': txt,
            'parse_mode': 'MarkdownV2',
        })

        
def generate_message_texts(old_alerts, new_alerts):
    old_alerts_by_id = {a['alertId']: a for a in old_alerts}
    new_alerts_by_id = {a['alertId']: a for a in new_alerts}
    assert len(old_alerts_by_id) == len(old_alerts)
    assert len(new_alerts_by_id) == len(new_alerts)
    message_texts = []
    # message with closed alerts
    text_parts = []
    for a in old_alerts:
        if a['alertId'] not in new_alerts_by_id:
            logger.debug('Alert closed: %s', json.dumps(a))
            text_parts.append('\U0001F334 ' + alert_text(a))
    if text_parts:
        message_texts.append('\n'.join(text_parts))
    # message with newly opened alerts
    text_parts = []
    for a in new_alerts:
        if a['alertId'] not in old_alerts_by_id:
            logger.debug('Alert open: %s', json.dumps(a))
            text_parts.append('\U0001F525 ' + alert_text(a))
    if text_parts:
        message_texts.append('\n'.join(text_parts))
    return message_texts


def tg_md2_escape(s):
    '''
    According to https://core.telegram.org/bots/api#markdownv2-style
    '''
    for c in '_*[]()~`>#+-=|{}.!':
        s = s.replace(c, '\\' + c)
    return s


def alert_text(alert):
    esc = tg_md2_escape
    try:
        label = json.loads(alert['stream']['labelJSON'])
        label_str = ' '.join(f"{esc(k)}{esc('=')}`{esc(v)}`" for k, v in label.items())
        path = '>'.join(alert['itemPath'])
        return f"{label_str} *{esc(alert['alertType'])}* {esc(path)} {esc(alert['lastItemValueJSON'] or '-')} {esc('(')}`{esc(alert['alertId'])}`{esc(')')}"
    except Exception as e:
        logger.exception('Failed to build alert text: %r; alert: %r', e, alert)
        return json.dumps(alert)


@routes.get('/')
async def handle_index(request):
    return Response(text='Hello from ow-telegram-notifier!\n')


@routes.get('/current-alerts')
async def handle_list_alerts(request):
    if not request.app['conf'].development_mode_enabled:
        raise HTTPForbidden(text='Available only in development mode')
    return json_response({'current_alerts': request.app['current_alerts']})


@routes.post('/telegram-webhook')
async def handle_telegram_webhook(request):
    conf = request.app['conf']
    session = request.app['client_session']
    payload = await request.json()
    logger.debug('Telegram webhook data: %r', payload)
    await process_telegram_webhook(conf, session, payload)
    return json_response({'ok': True})
                             
                             
async def process_telegram_webhook(conf, session, payload):
    if payload.get('message') and payload['message'].get('text') == '/id':
        chat = payload['message']['chat']
        chat_id = chat['id']
        await tg_request(conf, session, 'sendMessage', {
            'chat_id': chat_id,
            'text': f'Hola, the chat id is {chat_id}\nFull data: {json.dumps(chat)}',
        })


async def setup_telegram_webhook(conf, session):
    callback_url = conf.public_url.rstrip('/') + '/telegram-webhook'
    await tg_request(conf, session, 'setWebhook', {
        'url': callback_url,
        'allowed_updates': ['message'],
    })


async def tg_request(conf, session, method_name, params):
    url = f'https://api.telegram.org/bot{conf.telegram_api_token}/{method_name}'
    post_kwargs = dict(
        headers={
            'Content-Type': 'application/json',
        },
        json=params,
        timeout=30)
    logger.info('Calling Telegram API method: %s params: %r', method_name, params)
    async with session.post(url, **post_kwargs) as resp:
        text = await resp.text()
        logger.debug('Telegram API response: %s %r', resp.status, text[:1000])
        resp.raise_for_status()
        return await resp.json()


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
            stream {
              labelJSON
            }
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
    url = conf.graphql_endpoint
    logger.debug('Retrieving alerts from %s', redacted(url))
    t0 = monotime()
    async with session.post(url, **post_kwargs) as resp:
        resp.raise_for_status()
        rj = await resp.json()
        logger.debug('GQL response: %s', smart_repr(rj))
        if rj.get('error') or rj.get('errors'):
            raise Exception(f'Received error response from {redacted(url)}: {rj}')
        alerts = [edge['node'] for edge in rj['data']['activeAlerts']['edges']]
        logger.debug('Retrieved %d alerts in %.3f s', len(alerts), monotime() - t0)
        return alerts


log_format = '%(asctime)s %(name)-25s %(levelname)5s: %(message)s'


def setup_logging(verbose):
    from logging import DEBUG, WARNING, getLogger, StreamHandler, Formatter
    getLogger('').setLevel(DEBUG)
    h = StreamHandler()
    h.setFormatter(Formatter(log_format))
    h.setLevel(DEBUG if verbose else WARNING)
    getLogger('').addHandler(h)


def redacted(s):
    assert isinstance(s, str)
    s = re.sub(r'(https?://[^@/]+:)[^@/]+(@)', r'\1...\2', s)
    return s


if __name__ == '__main__':
    main()
