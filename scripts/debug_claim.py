from genlayer_py.client.genlayer_client import GenLayerClient
from genlayer_py.chains.studionet import studionet

client = GenLayerClient(studionet)
print(client.read_contract('0xc02eFA03faFC3f4bb1b38EfE7f8B5920e0261928', 'get_claim', ['claim_1']))
