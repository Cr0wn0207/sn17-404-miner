"""Local subscription experiments with exact cached replay; no Witness proof.

This tool never submits an output and is not imported by the miner entry point.
Request/response caches contain private experimental data and stay outside Git.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import httpx
from renderer_client import RendererClient, RenderRejected
from witness_client.request import load_credentials, serialize_body, PROVIDERS
from witness_client.response import model_result


class LocalCodexWitness:
    def __init__(self, directory, config, *, offline=False, renderer='http://127.0.0.1:18040',
                 call_slots=None, render_slots=None, notify=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config = config
        self.offline = offline
        self.responses = self
        self.trace = []
        self.calls = []
        self.request_ids = set()
        self.call_slots = call_slots or threading.BoundedSemaphore(8)
        self.render_slots = render_slots or threading.BoundedSemaphore(1)
        self.renderer = RendererClient(renderer, renderer_id='local-source-renderer-0.4.10', timeout=180)
        self.notify = notify or (lambda event, **fields: print(json.dumps({'event': event, **fields}), flush=True))

    def location(self, kind, data):
        digest = hashlib.sha256(data).hexdigest()
        self.trace.append({'kind': kind, 'sha256': digest})
        return self.directory / (kind + '-' + digest)

    async def create(self, *, request_id, session_id=None, **params):
        if request_id in self.request_ids:
            raise ValueError('Duplicate request_id in one generation')
        self.request_ids.add(request_id)
        session = session_id or 'sn17-local-improvement-v2'
        body = serialize_body({'service_tier': 'default', **params, 'stream': True}, 'codex')
        identity = str(request_id).encode() + b'\0' + session.encode() + b'\0' + body
        path = self.location('call', identity)
        response = await asyncio.to_thread(self.fetch, path, body, session, request_id, params['model'])
        self.calls.append({'request_id': request_id, 'model': params['model'],
                           'effort': params.get('reasoning', {}).get('effort'),
                           'status': response.status,
                           'usage': response.usage.model_dump() if response.usage else None,
                           'cache_key': path.name, 'witness_proof': False})
        self.notify('response', request_id=request_id, model=params['model'], status=response.status)
        return response

    def fetch(self, path, body, session, ident, model):
        metadata = path.with_suffix('.json')
        payload = path.with_suffix('.sse')
        if metadata.exists() and payload.exists():
            record = json.loads(metadata.read_text())
            raw = payload.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record['response_sha256']:
                raise ValueError('Modified response cache')
            return model_result(record['status'], raw, 'codex', stream=False)
        if self.offline:
            raise RuntimeError('Replay request mismatch: ' + path.name)
        with self.call_slots:
            token, account = load_credentials(self.config, 'codex', None)
            headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream',
                       'Authorization': 'Bearer ' + token, 'session-id': session}
            if account:
                headers['ChatGPT-Account-Id'] = account
            host, route = PROVIDERS['codex']
            self.notify('call', request_id=ident, model=model)
            with httpx.Client(timeout=httpx.Timeout(900, connect=30), follow_redirects=False) as client:
                response = client.post('https://' + host + route, content=body, headers=headers)
            # Headers and credentials are deliberately never persisted.
            path.with_suffix('.request.json').write_bytes(body)
            payload.write_bytes(response.content)
            metadata.write_text(json.dumps({'status': response.status_code,
                                            'response_sha256': hashlib.sha256(response.content).hexdigest(),
                                            'request_sha256': hashlib.sha256(body).hexdigest(),
                                            'transport': 'direct_codex_subscription_https',
                                            'witness_proof': False}, indent=2) + '\n')
            return model_result(response.status_code, response.content, 'codex', stream=False)

    async def render(self, source, options):
        key = json.dumps({'source': source, 'options': options.query()}, sort_keys=True, separators=(',', ':')).encode()
        path = self.location('render', key)
        return await asyncio.to_thread(self.render_sync, path, source, options)

    def render_sync(self, path, source, options):
        rejection = path.with_suffix('.rejection.json')
        png = path.with_suffix('.png')
        if rejection.exists():
            raise RenderRejected(rejection.read_text())
        if png.exists():
            return png.read_bytes()
        if self.offline:
            raise RuntimeError('Replay render mismatch: ' + path.name)
        with self.render_slots:
            try:
                image = self.renderer.render(source, options)
            except RenderRejected as error:
                rejection.write_text(error.detail_json)
                raise
        path.with_suffix('.source.js').write_text(source)
        path.with_suffix('.options.json').write_text(json.dumps(options.query(), indent=2) + '\n')
        png.write_bytes(image)
        return image

    def close(self):
        self.renderer.close()


async def run(args):
    from miner.pipeline import generate
    from miner.budget import Budget
    image = Path(args.image).read_bytes()
    directory = Path(args.output)
    config = json.loads(Path(args.witness_config).read_text())
    host = LocalCodexWitness(directory / 'cache', config, offline=args.replay)
    start = time.monotonic()
    try:
        source = await generate(image, args.seed, host)
        budget = Budget()
        from types import SimpleNamespace
        for call in host.calls:
            budget.consume(call['model'], SimpleNamespace(usage=SimpleNamespace(**call['usage']) if call['usage'] else None))
        if args.replay:
            expected = json.loads((directory / 'result.json').read_text())
            assert source is not None and hashlib.sha256(source.encode()).hexdigest() == expected['source_sha256']
            assert host.trace == json.loads((directory / 'trace.json').read_text())
            print('LOCAL_EXACT_REPLAY_PASSED', len(host.trace), 'observations; no Witness proof', flush=True)
        else:
            if source:
                (directory / 'selected.js').write_text(source)
            (directory / 'trace.json').write_text(json.dumps(host.trace, indent=2) + '\n')
            record = {'success': source is not None, 'source_sha256': hashlib.sha256(source.encode()).hexdigest() if source else None,
                      'image_sha256': hashlib.sha256(image).hexdigest(), 'seed': args.seed,
                      'credits': str(budget.spent), 'model_calls': budget.calls, 'calls': host.calls,
                      'elapsed_seconds': time.monotonic() - start, 'witness_proof': False,
                      'official_round3': False, 'chain_transaction_sent': False}
            (directory / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
            print(json.dumps({k: v for k, v in record.items() if k != 'calls'}), flush=True)
    finally:
        host.close()


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--witness-config', required=True)
    parser.add_argument('--replay', action='store_true')
    asyncio.run(run(parser.parse_args()))
