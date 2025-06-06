import asyncio
from typing import Optional

from temporalio.client import Client

from workflows import SaleItemWorkflow, SaleItemWorkflowInput


async def main(client: Optional[Client] = None):
    client = client or await Client.connect("localhost:7233")
    wf_handle = await client.start_workflow(
        SaleItemWorkflow.run,
        SaleItemWorkflowInput(sale_item_id="1234567", quantity=10),
        id="sale-item-poc-workflow-1234567",
        task_queue="sale_item_poc_task_queue",
    )

    print(await wf_handle.result())


if __name__ == "__main__":
    asyncio.run(main())
