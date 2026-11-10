#!/usr/bin/env python3
"""Run the F3 pulse with an existing credential, restoring the touched block.

Only the sanitized result is printed; endpoints, credentials, identities and
coordinates are never included. Pairing must be completed separately by the
human operator before this script is run.
"""
import argparse
import datetime
import json
import os

from mc_remote.auth import PairingRequiredError
from mc_remote.minecraft import Minecraft


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', default='localhost')
    parser.add_argument('--port', type=int, default=25575)
    parser.add_argument('--token-key')
    parser.add_argument('--paper-version', required=True,
                        help='Paper version/build verified by the local operator')
    parser.add_argument('--position', nargs=3, type=int,
                        help='An operator-approved origin-relative test block')
    args = parser.parse_args()
    # Minecraft.create gives environment overrides precedence; use the selected
    # local endpoint consistently within this one helper process.
    os.environ['MCREMOTE_API_HOST'] = args.address
    os.environ['MCREMOTE_API_PORT'] = str(args.port)
    result = {'date': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'paper_version': args.paper_version,
              'paper_version_source': 'operator verified',
              'required_mcremote_version': '2321.1.0',
              'authentication': 'existing token store; pair=False',
              'status': 'not_run'}
    mc = None
    original = None
    touched = False
    try:
        mc = Minecraft.create(args.address, args.port, token_key=args.token_key,
                              pair=False, sync_catalog=False)
        result['protocol'] = mc.protocol
        result['minecraft_version'] = mc.mc_version
        candidates = [args.position] if args.position else [(0, y, 0) for y in (3, 8, 16, 32, 64, 96)]
        for position in candidates:
            try:
                value = mc.getBlock(*position)
            except Exception:
                continue
            if value.block_id in ('minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'):
                args.position, original = position, value
                break
        if original is None:
            raise RuntimeError('No empty test position available')
        block = 'minecraft:gold_block' if original.block_id!='minecraft:gold_block' else 'minecraft:stone'
        touched = True
        mc.setBlock(*args.position, block)
        assert mc.getBlock(*args.position).block_id==block
        result['status'] = 'pass'
    except PairingRequiredError:
        result['status'] = 'pairing_required'
    except Exception as exc:
        result['status'] = 'error'
        result['exception_type'] = type(exc).__name__
    finally:
        if mc is not None:
            try:
                if touched:
                    mc.setBlock(*args.position, original.block_id, state=dict(original.state))
                    restored = mc.getBlock(*args.position)
                    assert restored==original
                result['restored'] = True
            except Exception:
                result['restored'] = False
                result['status'] = 'error'
            finally:
                try:
                    mc.close()
                except Exception as exc:
                    result['status'] = 'error'
                    result['close_exception_type'] = type(exc).__name__
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status']=='pass' else 1


if __name__=='__main__':
    raise SystemExit(main())
