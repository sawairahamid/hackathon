import sys
import json
from app import trace
trace.init_db()
from app.parser import parse_request

PROMPTS = [
    "Purchase 30 desktop computers with a maximum budget of PKR 6 million. Compare at least three suppliers, evaluate their prices, delivery times, warranties, and ratings, select the best option, prepare the purchase order, and send it for approval.",
    "Purchase 20 enterprise network switches with a maximum budget of PKR 4 million. Get quotes from at least three suppliers, compare their pricing, delivery time, warranty, and rating.",
    "Procure 15 high-speed routers under PKR 2 million.",
    "Buy 5 office printers with a budget of PKR 100,000.",
    "Procure 2 database servers with a PKR 8 million ceiling.",
    "Purchase 50 4K monitors for PKR 2.5 million.",
    "Renew 100 Microsoft 365 licenses for PKR 1 million.",
    "Purchase 40 ergonomic office chairs for PKR 800,000.",
    "Purchase 10 laptops for PKR 1.5 million."
]

for i, p in enumerate(PROMPTS):
    print(f"--- TEST {i+1} ---")
    ent, tag = parse_request(p)
    print(f"Item: {ent.item}")
    print(f"Qty : {ent.quantity}")
    print(f"Budg: {ent.budget}")
    print()
