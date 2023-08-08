import os, sys, json
import traceback
import requests
import datetime
import pytz
import web3

from weaveapi.records import *
from weaveapi.options import *
from weaveapi.weaveh import *

NFT_ABI = "PoP_abi.json"
CONFIG = "config.json"
KEYS_CONFIG = "/keys/keys.json"

with open(CONFIG, "r") as f:
    config = json.load(f)
with open(KEYS_CONFIG, "r") as f:
    keys = json.load(f)

ROOT_IMG_URL = config["ROOT_IMG_URL"]
DONATIONS_WALLET = config["DONATIONS_WALLET"]
DEFAULT_RATES = config["DEFAULT_FALLBACK_RATES"] # safety fallback approximations, values are replaced with results from cryptocompare if call is successful
FROM_BLOCK = config["FROM_BLOCK"]
TOKENS = config["TOKENS"]

# Source table
data_collection = config["DATA_COLLECTION"]
items_table = config["DATA_TABLE"]

ETH_NODE = "https://rpc-mainnet.maticvigil.com"
CHAIN_ID = 137

LOG_CONTENT = False
FORCE_UPDATE_ALL = False

ALCHEMY_KEY = keys["ALCHEMY_KEY"]
CRYPTOCOMPARE_API_KEY = keys["CRYPTOCOMPARE_KEY"]

#LOCAL_CONFIG = "weave.config"
LOCAL_CONFIG = None

nodeApi, session = connect_weave_api(LOCAL_CONFIG)

output = {}


def get_rates():
    try:
        prices = requests.post("https://min-api.cryptocompare.com/data/price?fsym=USD&tsyms=" + TOKENS,
                               headers={"Authorization": "Apikey " + CRYPTOCOMPARE_API_KEY})
        rates = prices.json()
        if type(rates) is not dict:
            rates = DEFAULT_RATES
        for sym in DEFAULT_RATES.keys():
            if rates.get(sym) is None:
                rates[sym] = DEFAULT_RATES[sym]
    except:
        rates = DEFAULT_RATES
    return rates


def get_tier():
    tier = "black"
    description = "Welcome to Ouroboros, please donate $1 to upgrade"
    if total >= 0.9:
        tier = "bronze"
        description = "$1-$99 donated, nice start, keep going!"
    if total >= 99:
        tier = "silver"
        description = "$100-$999 donated, way to make a difference!"
    if total >= 990:
        tier = "gold"
        description = "$1000-$9999 donated, outstanding! Almost best of the best…"
    if total >= 9990:
        tier = "regen"
        description = "$10,000+ donated, LEGENDARY, way to support humanity's future!!!"
    return tier, description


def parse_transfer(transfer, private_data, rates, now):
    total = 0
    raw_value = int(transfer['rawContract']['value'], base=16)
    decimals = int(transfer['rawContract']['decimal'], base=16)
    blockNum = transfer['blockNum']
    value = raw_value / pow(10, decimals)
    asset = transfer['asset']
    unique_id = transfer["uniqueId"]
    existing = private_data.get(unique_id)
    if existing is None:
        rate = rates.get(asset)
        if rate is not None:
            usd_value = value / rate
            if usd_value > 0:
                total += float(usd_value)
                print("Transferred " + str(value) + " " + asset + " = " + str(usd_value) + " USD")
                private_data[unique_id] = {"usd_value": usd_value, "value": value, "token": asset, "block": blockNum,
                                           "ts": now, "from": owner}
        else:
            print("Ignored transfer for " + asset, "from", owner)
    else:
        usd_value = existing.get("usd_value")
        if usd_value is None:
            rate = rates.get(asset)
            if rate is not None:
                usd_value = value / rate
                private_data[unique_id]["usd_value"] = usd_value
        if usd_value is not None:
            total += float(usd_value)
            print("Using " + str(value) + " " + asset + " = " + str(usd_value) + " USD")
        else:
            print("Ignored transfer for " + asset, "from", owner)
    return total


def get_tokens(toQuery):
    # could be moved to config, keep in the script for now
    if toQuery == "eth-mainnet":
        MATIC_ADDRESS = '0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0'
        USDC_ADDRESS = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
        USDT_ADDRESS = '0xdAC17F958D2ee523a2206206994597C13D831ec7'
        ETH_ADDRESS = '0x0000000000000000000000000000000000000000'
        VITA_ADDRESS = '0x81f8f0bb1cB2A06649E51913A151F0E7Ef6FA321'
        tokens = [MATIC_ADDRESS, USDC_ADDRESS, USDT_ADDRESS, ETH_ADDRESS, VITA_ADDRESS]
    else:
        MATIC_ADDRESS = '0x0000000000000000000000000000000000001010'
        USDC_ADDRESS = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'
        USDT_ADDRESS = '0xc2132D05D31c914a87C6611C10748AEb04B58e8F'
        ETH_ADDRESS = '0x7ceb23fd6bc0add59e62ac25578270cff1b9f619'
        tokens = [MATIC_ADDRESS, USDC_ADDRESS, USDT_ADDRESS, ETH_ADDRESS]
    return tokens


try:
    w3 = web3.Web3(web3.HTTPProvider(ETH_NODE))
    w3.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)

    with open(NFT_ABI, "r") as f:
        item_abi = json.load(f)

    filter = Filter(None, { "id": "ASC" }, None, [ "name" ])
    reply = nodeApi.read(session, data_collection, items_table, filter, READ_DEFAULT_NO_CHAIN).get()
    #print(reply)

    rates = get_rates()
    print("Using rates", rates)

    if reply.get("data") is not None:
        now = int(datetime.datetime.now(tz=pytz.utc).timestamp() * 1000)

        print("Parsing " + str(len(reply["data"])) + " rows")
        for row in reply["data"]:
            try:
                private_data = json.loads(row["private_data"]) if row.get("private_data") is not None and len(row["private_data"]) > 0 else {}

                nft_id = row["nft_id"].split(":")
                nft_addr = nft_id[2]
                item_id = nft_id[3]

                nftContract = w3.eth.contract(abi=item_abi, address=nft_addr)
                try:
                    owner = nftContract.functions.ownerOf(int(item_id)).call()
                except:
                    break

                print(nft_id, ": checking transactions from", owner, "to", DONATIONS_WALLET)

                total = 0

                for toQuery in [ "eth-mainnet", "polygon-mainnet" ]:
                    tokens = get_tokens(toQuery)

                    categories = [ "external", "erc20" ]
                    params = {"fromBlock": FROM_BLOCK, "toBlock": "latest", "fromAddress": owner, "toAddress": DONATIONS_WALLET, "contractAddresses": tokens, "category": categories}

                    queryChain = 'https://' + toQuery + '.g.alchemy.com/v2/'

                    has_data = True
                    page_key = None
                    while has_data:
                        if page_key is not None:
                            params["pageKey"] = page_key
                        #print(params)
                        reply = requests.post(queryChain + ALCHEMY_KEY, json={"jsonrpc": "2.0", "id": 0, "method": "alchemy_getAssetTransfers", "params": [params]})
                        data = reply.json()

                        if data.get("result") is None:
                            break

                        print(data)
                        page_key = data['result'].get('pageKey')
                        has_data = page_key is not None

                        transfers = data['result']['transfers']
                        if len(transfers) > 0:
                            for i in range(len(transfers)):
                                transfer = transfers[i]
                                total = total + parse_transfer(transfer, private_data, rates, now)

                print("Total transferred for ", owner, ":", total)

                tier, description = get_tier()

                img = ROOT_IMG_URL + tier + ".jpg"

                public_data = json.loads(row["public_data"]) if row.get("public_data") is not None and len(row["public_data"]) > 0 else {}
                old_tier = private_data.get("tier") is not None and private_data.get("tier")

                if FORCE_UPDATE_ALL or tier != old_tier:
                    print("Storing new state")
                    private_data["tier"] = tier

                    public_data["name"] = "Proof of Philanthropy #" + str(item_id)
                    public_data["description"] = description
                    public_data["external_url"] = "https://pop.lifespan.io"
                    public_data["image"] = img
                    public_data["attributes"] =  [ { "tier": tier } ]

                    item = [
                        None, # id, filled server side
                        None, # timestamp, filled server side
                        None, # writer, filled server side
                        None, # signature, filled server side
                        row["roles"], #allowed readers
                        row["name"],
                        row["nft_id"],
                        json.dumps(public_data),
                        json.dumps(private_data)
                    ]
                    items = [ item ]
                    data = Records(items_table, items)
                    print("Writing new state for item " + str(row["nft_id"]))
                    res = nodeApi.write(session, data_collection, data, WRITE_DEFAULT).get()
                    print(res)

                if LOG_CONTENT:
                    uri = nftContract.functions.tokenURI(int(item_id)).call()
                    nft = requests.get(uri)
                    print(nft.json())
            except:
                print(traceback.format_exc())
                break
except:
    print(traceback.format_exc())
    output["error"] = "Error processing transactions"

weave_task_output(nodeApi, session, output)
