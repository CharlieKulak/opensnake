"""Browser entry point (pygbag). Build with web-support/build.sh."""

import asyncio

# pygbag fetches pygame-ce when the entry script imports it, so this must
# come before the game is imported.
import pygame  # noqa: F401


async def main():
    from opensnake.app import App

    await App().run_async()


asyncio.run(main())
