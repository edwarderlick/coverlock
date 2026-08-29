import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from genlayer_py.client.genlayer_client import GenLayerClient
from genlayer_py.chains.studionet import studionet
from scripts.deploy_and_verify import load_account

client = GenLayerClient(studionet)
client.local_account = load_account('coverlock-submitter')
addr = '0x19d9512004570B24040Cc65B2B659DAf62395a85'

for cid in ['claim_0', 'claim_1', 'claim_2']:
    try:
        c = client.read_contract(address=addr, function_name='get_claim', args=[cid])
        print('='*50)
        print(f'ID: {cid}')
        print(f'Claimant: {c["claimant"]}')
        print(f'State: {c["state_name"]}')
        print(f'Source: {c["source"][:60]}...')
        print(f'Brief: {c["brief"][:60]}...')
        print(f'Excerpt: "{c["source_excerpt"]}"')
        print(f'Verdict: {c["verdict"]}, Settlement: {c["settlement"]}')
    except Exception as e:
        print(f'{cid} error: {e}')
