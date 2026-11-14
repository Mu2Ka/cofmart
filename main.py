import asyncio

from app.bot.main import main
from app.process_lock import AlreadyRunningError


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AlreadyRunningError as exc:
        raise SystemExit(str(exc)) from None
