import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from activities import (
    move_from_open_to_ready,
    move_from_ready_to_open,
    move_from_ready_to_billed_pending,
    move_from_billed_pending_to_billed_approved,
    post_update_activity,
)
from workflows import SaleItemWorkflow

interrupt_event = asyncio.Event()


async def main():
    logging.basicConfig(level=logging.INFO)

    client = await Client.connect("localhost:7233")

    async with Worker(
        client,
        task_queue="sale_item_poc_task_queue",
        workflows=[SaleItemWorkflow],
        activities=[
            move_from_open_to_ready,
            move_from_ready_to_open,
            move_from_ready_to_billed_pending,
            move_from_billed_pending_to_billed_approved,
            post_update_activity,
        ],
    ):
        logging.info("Worker started, ctrl+c to exit")
        await interrupt_event.wait()
        logging.info("Shutting down")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        interrupt_event.set()
        loop.run_until_complete(loop.shutdown_asyncgens())
