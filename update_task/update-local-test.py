import os, sys, json
import traceback
import requests
import datetime, time
import pytz
import web3

from weaveapi.records import *
from weaveapi.options import *
from weaveapi.weaveh import *

NFT_ABI = "PoP_abi.json"
CONFIG = "config.json"
KEYS_CONFIG = "keys.json"

with open(CONFIG, "r") as f:
    config = json.load(f)
with open(KEYS_CONFIG, "r") as f:
    keys = json.load(f)

ROOT_IMG_URL = config["ROOT_IMG_URL"]
DONATIONS_WALLETS = config["DONATIONS_WALLETS"]
DEFAULT_RATES = config["DEFAULT_FALLBACK_RATES"] # safety fallback approximations, values are replaced with results from cryptocompare if call is successful
FROM_BLOCK = config["FROM_BLOCK"]
TOKENS = config["TOKENS"]
ADDRESSES = config["ADDRESSES"]
COIN_MAPPING = config["COIN_MAPPING"]
INDEXER_URL = "https://indexer-production.fly.dev/data/"

# Source table
data_collection = config["DATA_COLLECTION"]
items_table = config["DATA_TABLE"]

ETH_NODE = "https://rpc-mainnet.maticvigil.com"
CHAIN_ID = 137

MAX_PAGES = 1000

LOG_CONTENT = False
FORCE_UPDATE_ALL = False

ALCHEMY_KEY = keys["ALCHEMY_KEY"]
CRYPTOCOMPARE_API_KEY = keys["CRYPTOCOMPARE_KEY"]
COINGECKO_KEY = None if keys.get("COINGECKO_KEY") is None else keys["COINGECKO_KEY"]



LOCAL_CONFIG = "weave.config"
#LOCAL_CONFIG = None

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

    try:
        rates["VITA"] = DEFAULT_RATES["VITA"]
        cgecko = "https://api.coingecko.com" if COINGECKO_KEY is None else "https://pro-api.coingecko.com"
        vita = requests.get(cgecko + "/api/v3/simple/price?ids=vitadao&vs_currencies=usd")
        vprice = vita.json()
        prc = 1 / float(vprice["vitadao"]["usd"])
        rates["VITA"] = prc
    except:
        pass

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


def parse_transfer(transfer, private_data, rates, now, chain):
    total = 0
    raw_value = int(transfer['rawContract']['value'], base=16)
    decimals = int(transfer['rawContract']['decimal'], base=16)
    blockNum = transfer['blockNum']
    value = raw_value / pow(10, decimals)
    asset = transfer['asset']
    unique_id = transfer["uniqueId"]
    existing = private_data.get(unique_id)
    if existing is None:
        rate = rates.get(COIN_MAPPING[asset] if COIN_MAPPING.get(asset) is not None else asset)
        if rate is not None:
            usd_value = value / rate
            if usd_value > 0:
                total += float(usd_value)
                print("< Transferred " + str(value) + " " + asset + " = " + str(usd_value) + " USD")
                private_data[unique_id] = {"usd_value": usd_value, "value": value, "token": asset, "block": blockNum,
                                           "ts": now, "from": owner, "chain": chain}
        else:
            print("! Ignored transfer for " + asset, "from", owner, " rate = 0")
    else:
        usd_value = existing.get("usd_value")
        if usd_value is None:
            rate = rates.get(asset)
            if rate is not None:
                usd_value = value / rate
                private_data[unique_id]["usd_value"] = usd_value
        if usd_value is not None:
            total += float(usd_value)
            print(". Using " + str(value) + " " + asset + " = " + str(usd_value) + " USD")
        else:
            print("! Ignored transfer for " + asset, "from", owner, " usd_value = 0")
    return total

try:
    print("Started", time.time())
    w3 = web3.Web3(web3.HTTPProvider(ETH_NODE))
    w3.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)

    with open(NFT_ABI, "r") as f:
        item_abi = json.load(f)

    filter = Filter(None, { "id": "ASC" }, None, [ "name" ])
    reply = nodeApi.read(session, data_collection, items_table, filter, READ_DEFAULT_NO_CHAIN).get()
    #print(reply)

    rates = get_rates()
    print(". Using rates", rates)

    if reply.get("data") is not None:
        now = int(datetime.datetime.now(tz=pytz.utc).timestamp() * 1000)

        cached_rounds = None
        cached_replies = {}

        toWrite = []
        print(". Parsing " + str(len(reply["data"])) + " rows")

        owners = []
        contracts = {}
        old_private_data_map = {}
        private_data_map = {}

        for row in reply["data"]:
            nft_id = row["nft_id"].split(":")
            nft_addr = nft_id[2]
            item_id = nft_id[3]

            old_private_data = row["private_data"] if row.get("private_data") is not None and len(row["private_data"]) > 0 else "{}"
            old_private_data_map[item_id] = old_private_data
            private_data_map[item_id] = json.loads(old_private_data)

            nftContract = contracts.get(nft_addr)
            if nftContract is None:
                nftContract = w3.eth.contract(abi=item_abi, address=nft_addr)
                contracts[nft_addr] = nftContract

            try:
                owner = nftContract.functions.ownerOf(int(item_id)).call()
                row["owner"] = owner
                owners.append(owner)
            except:
                break
        print("NFT owners:", len(owners))

        totals = {}
        for toQuery, tokens in ADDRESSES.items():
            print(". Querying " + toQuery)
            if tokens is None:
                print("! ERROR! No token addresses mapped for " + toQuery)
                continue

            if toQuery == "indexer":
                rounds = tokens["rounds"]
                chains = tokens["chains"]
                projects = tokens["projects"]

                try:
                    if rounds == ["*"]:
                        if cached_rounds is not None:
                            rounds = cached_rounds
                        else:
                            rounds = set()
                            for chain in chains:
                                url = INDEXER_URL + str(chain[0]) + "/rounds"
                                print(url)
                                resp = requests.get(url)
                                items = resp.text.split('a href="/data/' + str(chain[0]) + '/rounds/')
                                for it in items:
                                    r = it[0:it.index('"')]
                                    if r[0:2] == "0x":
                                        rounds.add(r)
                            rounds = list(rounds)
                            print(". Rounds: " + str(rounds))
                            cached_rounds = rounds

                    for project in projects:
                        for chain in chains:
                            for round in rounds:
                                url = INDEXER_URL + str(chain[0]) + "/rounds/" + web3.Web3.toChecksumAddress(round) + "/projects/" + project + "/contributors.json"

                                data = cached_replies.get(url)
                                if data is None:
                                    print(url)
                                    resp = requests.get(url)
                                    print(resp)
                                    if resp.status_code == 200:
                                        data = resp.json()
                                    else:
                                        data = ""
                                    cached_replies[url] = data

                                if len(data) > 0:
                                    for it in data:
                                        for row in reply["data"]:
                                            nft_id = row["nft_id"].split(":")
                                            item_id = nft_id[3]
                                            owner = row.get("owner")
                                            private_data = private_data_map.get(item_id)

                                            if owner is not None and web3.Web3.toChecksumAddress(it.get("id")) == web3.Web3.toChecksumAddress(owner):
                                                print("< Transfer: " + str(it))
                                                unique_id = chain[0] + ":" + project + ":" + owner + ":" + round
                                                asset = "USD"
                                                usd_value = float(it.get("amountUSD"))
                                                if usd_value > 0:
                                                    totals[item_id] = usd_value + (0 if totals.get(item_id) is None else totals.get(item_id))
                                                    print("< Transferred " + str(usd_value) + " " + asset + " = " + str(
                                                        usd_value) + " USD")
                                                    prevrec = private_data.get(unique_id)
                                                    if prevrec is None or prevrec.get(
                                                            "usd_value") is not None and prevrec.get(
                                                            "usd_value") != usd_value:
                                                        private_data[unique_id] = {"usd_value": usd_value,
                                                                                   "value": usd_value,
                                                                                   "token": asset,
                                                                                   "block": 0,
                                                                                   "ts": now,
                                                                                   "from": owner,
                                                                                   "chain": chain}
                except:
                    print("! ERROR! Failed querying indexer")
                    print(traceback.format_exc())
                    break
            elif not toQuery.startswith("indexer"):
                for target in DONATIONS_WALLETS:
                    print(". Querying donations to " + toQuery + " " + target)

                    categories = ["external", "erc20"]
                    params = {"fromBlock": FROM_BLOCK[toQuery], "toBlock": "latest", "toAddress": target, "contractAddresses": [t[1] for t in tokens], "category": categories}

                    queryChain = 'https://' + toQuery + '.g.alchemy.com/v2/'

                    has_data = True
                    pages = 0
                    page_key = None
                    while has_data:
                        if page_key is not None:
                            params["pageKey"] = page_key
                        # print(params)
                        print("Query " + queryChain + " " + str(params))
                        resp = requests.post(queryChain + ALCHEMY_KEY,
                                              json={"jsonrpc": "2.0", "id": 0, "method": "alchemy_getAssetTransfers",
                                                    "params": [params]})
                        data = resp.json()

                        if data.get("result") is None:
                            break

                        print(data)
                        pages = pages + 1
                        if pages > MAX_PAGES:
                            break
                        page_key = data['result'].get('pageKey')
                        has_data = page_key is not None

                        transfers = data['result']['transfers']
                        if len(transfers) > 0:
                            #print(transfers)
                            print("< " + str(len(transfers)) + " transfer(s) to wallet " + target)
                            for i in range(len(transfers)):
                                transfer = transfers[i]

                                source = transfer["from"]
                                print("Source: " + source)
                                for row in reply["data"]:
                                    nft_id = row["nft_id"].split(":")
                                    item_id = nft_id[3]
                                    owner = row.get("owner")
                                    private_data = private_data_map.get(item_id)

                                    if owner is not None and web3.Web3.toChecksumAddress(source) == web3.Web3.toChecksumAddress(owner):
                                        print("Owner: " + owner)
                                        totals[item_id] = parse_transfer(transfer, private_data, rates, now, toQuery) + (0 if totals.get(item_id) is None else totals.get(item_id))
        print("Totals: ", totals)


        for row in reply["data"]:
            try:
                nft_id = row["nft_id"].split(":")
                nft_addr = nft_id[2]
                item_id = nft_id[3]
                old_private_data = old_private_data_map[item_id]
                private_data = private_data_map[item_id]
                owner = row.get("owner")

                if owner is None:
                    break

                print(nft_id, ": checking transactions from", owner, "to", DONATIONS_WALLETS)

                total = 0 if totals.get(item_id) is None else totals[item_id]

                print("Total transferred for ", owner, nft_id, ":", total)

                tier, description = get_tier()
                print("NFT #", item_id, " tier ", tier)

                img = ROOT_IMG_URL + tier + ".png"

                public_data = json.loads(row["public_data"]) if row.get("public_data") is not None and len(row["public_data"]) > 0 else {}
                old_tier = private_data.get("tier") is not None and private_data.get("tier")

                if FORCE_UPDATE_ALL or tier != old_tier or old_private_data != json.dumps(private_data):
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

                    print("New state for item " + str(row["nft_id"]))
                    toWrite.append(item)

                if LOG_CONTENT:
                    nftContract = w3.eth.contract(abi=item_abi, address=nft_addr)
                    uri = nftContract.functions.tokenURI(int(item_id)).call()
                    nft = requests.get(uri)
                    print(nft.json())
            except:
                print(traceback.format_exc())
                break

        if False and len(toWrite) > 0:
            print("> Writing " + str(len(toWrite)) + " records")
            data = Records(items_table, toWrite)
            res = nodeApi.write(session, data_collection, data, WriteOptions(True, 1, False, 1, 180, True, True, True)).get()
            print(res)

except:
    print(traceback.format_exc())
    output["error"] = "Error processing transactions"

print("Done", time.time())

#weave_task_output(nodeApi, session, output)
