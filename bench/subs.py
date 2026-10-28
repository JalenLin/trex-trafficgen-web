"""Simulated browser tabs: N WebSocket viewers that reconnect whenever the GUI restarts.

Prints a line per minute with how many stats/error messages each viewer got,
so you can confirm the GUI was really polling during scenarios B and C.
"""
import asyncio
import json
import sys
import time

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:18080/api/hosts/local/stats"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 3
counts = [{"stats": 0, "error": 0, "disconnected": 0} for _ in range(N)]


async def viewer(i):
    while True:
        try:
            async with websockets.connect(URL) as ws:
                async for raw in ws:
                    counts[i][json.loads(raw)["type"]] += 1
        except Exception:
            await asyncio.sleep(1)


async def report():
    while True:
        await asyncio.sleep(60)
        print(time.strftime("%H:%M:%S"), json.dumps(counts), flush=True)
        for c in counts:
            for k in c:
                c[k] = 0


async def main():
    await asyncio.gather(report(), *(viewer(i) for i in range(N)))


asyncio.run(main())
