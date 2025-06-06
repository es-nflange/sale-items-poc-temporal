import asyncio

from temporalio import activity

from models import SaleItem


@activity.defn
async def move_from_open_to_ready(sale_item: SaleItem):
    await asyncio.sleep(1)  # Simulate a network call or db interaction


@activity.defn
async def move_from_ready_to_open(sale_item: SaleItem):
    await asyncio.sleep(1)


@activity.defn
async def move_from_ready_to_billed_pending(sale_item: SaleItem):

    await asyncio.sleep(1)


@activity.defn
async def move_from_billed_pending_to_billed_approved(sale_item: SaleItem):

    await asyncio.sleep(1)


@activity.defn
async def post_update_activity(sale_item: SaleItem):
    """
    This activity is called after a state transition to perform any necessary updates.
    """
    # Simulate a post-update operation, e.g., logging or notifying other systems
    await asyncio.sleep(1)
    activity.logger.info(
        f"Post-update activity completed for sale item {sale_item.sale_item_id} with status {sale_item.current_status}"
    )
