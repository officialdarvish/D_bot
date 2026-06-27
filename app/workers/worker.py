
import asyncio

class Worker:
    async def run(self):
        while True:
            print("Enterprise worker running...")
            await asyncio.sleep(5)
